import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/normalizer.dart';

/// User-facing settings. Persisted in `shared_preferences` (see
/// `_SettingsKeys`); defaults below apply when nothing has been saved yet.
class AppSettings {
  final ThemeMode themeMode;
  final double textScale;
  final AppLanguage uiLanguage;
  final InputLanguage defaultInputLang;
  final bool offlineFirst;
  final bool soundEnabled;

  const AppSettings({
    this.themeMode = ThemeMode.system,
    this.textScale = 1.0,
    this.uiLanguage = AppLanguage.english,
    this.defaultInputLang = InputLanguage.english,
    this.offlineFirst = true,
    this.soundEnabled = false,
  });

  AppSettings copyWith({
    ThemeMode? themeMode,
    double? textScale,
    AppLanguage? uiLanguage,
    InputLanguage? defaultInputLang,
    bool? offlineFirst,
    bool? soundEnabled,
  }) =>
      AppSettings(
        themeMode: themeMode ?? this.themeMode,
        textScale: textScale ?? this.textScale,
        uiLanguage: uiLanguage ?? this.uiLanguage,
        defaultInputLang: defaultInputLang ?? this.defaultInputLang,
        offlineFirst: offlineFirst ?? this.offlineFirst,
        soundEnabled: soundEnabled ?? this.soundEnabled,
      );
}

/// Storage keys — stable strings; renaming one silently resets a user's setting.
abstract final class SettingsKeys {
  static const themeMode = 'settings.themeMode';
  static const textScale = 'settings.textScale';
  static const uiLanguage = 'settings.uiLanguage';
  static const defaultInputLang = 'settings.defaultInputLang';
  static const offlineFirst = 'settings.offlineFirst';
  static const soundEnabled = 'settings.soundEnabled';
}

/// Allowed text-scale range; mirrors the slider in SettingsScreen.
const double kMinTextScale = 0.8;
const double kMaxTextScale = 1.4;

class SettingsNotifier extends Notifier<AppSettings> {
  /// True once the local user has changed something (prevents a slow disk read
  /// from overwriting a fresh user choice).
  bool _dirty = false;
  Future<void> _ready = Future<void>.value();

  /// Completes after persisted values have been applied (or defaults kept).
  /// UI does not need it; tests and startup sequencing do.
  Future<void> get ready => _ready;

  @override
  AppSettings build() {
    _ready = _hydrate();
    return const AppSettings();
  }

  Future<void> _hydrate() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      if (_dirty) return;
      state = AppSettings(
        themeMode: _themeByName(prefs.getString(SettingsKeys.themeMode)),
        textScale: _clampScale(prefs.getDouble(SettingsKeys.textScale)),
        uiLanguage: _appLanguageByName(
          prefs.getString(SettingsKeys.uiLanguage),
        ),
        defaultInputLang:
            prefs.getString(SettingsKeys.defaultInputLang) == 'chinese'
                ? InputLanguage.chinese
                : InputLanguage.english,
        offlineFirst: prefs.getBool(SettingsKeys.offlineFirst) ?? true,
        soundEnabled: prefs.getBool(SettingsKeys.soundEnabled) ?? false,
      );
    } catch (_) {
      // Preferences unavailable (e.g. platform channel missing): keep defaults.
    }
  }

  void setThemeMode(ThemeMode mode) => _update(state.copyWith(themeMode: mode));

  void setTextScale(double value) =>
      _update(state.copyWith(textScale: _clampScale(value)));

  void setUiLanguage(AppLanguage lang) =>
      _update(state.copyWith(uiLanguage: lang));

  void setDefaultInputLang(InputLanguage lang) =>
      _update(state.copyWith(defaultInputLang: lang));

  void toggleOfflineFirst() =>
      _update(state.copyWith(offlineFirst: !state.offlineFirst));

  void toggleSound() =>
      _update(state.copyWith(soundEnabled: !state.soundEnabled));

  void _update(AppSettings next) {
    _dirty = true;
    state = next;
    _save(next);
  }

  Future<void> _save(AppSettings s) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(SettingsKeys.themeMode, s.themeMode.name);
      await prefs.setDouble(SettingsKeys.textScale, s.textScale);
      await prefs.setString(SettingsKeys.uiLanguage, s.uiLanguage.name);
      await prefs.setString(
        SettingsKeys.defaultInputLang,
        s.defaultInputLang.name,
      );
      await prefs.setBool(SettingsKeys.offlineFirst, s.offlineFirst);
      await prefs.setBool(SettingsKeys.soundEnabled, s.soundEnabled);
    } catch (_) {
      // Persistence failed: the in-memory value still applies this session.
    }
  }

  static double _clampScale(double? raw) {
    if (raw == null) return 1.0;
    if (raw.isNaN || raw.isInfinite) return 1.0;
    return raw.clamp(kMinTextScale, kMaxTextScale).toDouble();
  }

  /// Absent/unknown now means "follow the system" (Phase 1 default). A value
  /// the user already saved keeps winning, so an existing Light/Dark choice
  /// is never reset by this change.
  static ThemeMode _themeByName(String? name) => themeModeFromName(name);

  static AppLanguage _appLanguageByName(String? name) => switch (name) {
        'chinese' => AppLanguage.chinese,
        'nepali' => AppLanguage.nepali,
        _ => AppLanguage.english,
      };
}

final settingsProvider =
    NotifierProvider<SettingsNotifier, AppSettings>(SettingsNotifier.new);

/// Maps a stored string to a [ThemeMode]. Anything absent or unrecognised
/// falls back to "follow the system".
ThemeMode themeModeFromName(String? name) => switch (name) {
      'dark' => ThemeMode.dark,
      'light' => ThemeMode.light,
      _ => ThemeMode.system,
    };

