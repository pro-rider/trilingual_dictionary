import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/normalizer.dart';

/// User-facing settings (v1).
class AppSettings {
  final ThemeMode themeMode;
  final double textScale;
  final AppLanguage uiLanguage;
  final InputLanguage defaultInputLang;
  final bool offlineFirst;
  final bool soundEnabled;

  const AppSettings({
    this.themeMode = ThemeMode.light,
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

class SettingsNotifier extends Notifier<AppSettings> {
  @override
  AppSettings build() => const AppSettings();

  void setThemeMode(ThemeMode mode) =>
      state = state.copyWith(themeMode: mode);

  void setTextScale(double value) =>
      state = state.copyWith(textScale: value);

  void setUiLanguage(AppLanguage lang) =>
      state = state.copyWith(uiLanguage: lang);

  void setDefaultInputLang(InputLanguage lang) =>
      state = state.copyWith(defaultInputLang: lang);

  void toggleOfflineFirst() =>
      state = state.copyWith(offlineFirst: !state.offlineFirst);

  void toggleSound() => state = state.copyWith(soundEnabled: !state.soundEnabled);
}

final settingsProvider =
    NotifierProvider<SettingsNotifier, AppSettings>(SettingsNotifier.new);
