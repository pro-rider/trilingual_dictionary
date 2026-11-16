import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:trilingual_dictionary/core/normalizer.dart';
import 'package:trilingual_dictionary/features/history/history_provider.dart';
import 'package:trilingual_dictionary/features/settings/settings_provider.dart';

Future<void> _settle() async {
  for (var i = 0; i < 4; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
  });

  group('settings persistence', () {
    test('writes each field under its stable key', () async {
      final c = ProviderContainer();
      addTearDown(c.dispose);
      final n = c.read(settingsProvider.notifier);
      await n.ready;

      n.setThemeMode(ThemeMode.dark);
      n.setTextScale(1.3);
      n.setUiLanguage(AppLanguage.nepali);
      n.setDefaultInputLang(InputLanguage.chinese);
      n.toggleOfflineFirst();
      n.toggleSound();
      await _settle();

      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString(SettingsKeys.themeMode), 'dark');
      expect(prefs.getDouble(SettingsKeys.textScale), 1.3);
      expect(prefs.getString(SettingsKeys.uiLanguage), 'nepali');
      expect(prefs.getString(SettingsKeys.defaultInputLang), 'chinese');
      expect(prefs.getBool(SettingsKeys.offlineFirst), isFalse);
      expect(prefs.getBool(SettingsKeys.soundEnabled), isTrue);
    });

    test('reloads persisted values into a fresh container', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{
        SettingsKeys.themeMode: 'dark',
        SettingsKeys.textScale: 1.2,
        SettingsKeys.uiLanguage: 'chinese',
        SettingsKeys.defaultInputLang: 'chinese',
        SettingsKeys.offlineFirst: false,
        SettingsKeys.soundEnabled: true,
      });

      final c = ProviderContainer();
      addTearDown(c.dispose);
      await c.read(settingsProvider.notifier).ready;

      final s = c.read(settingsProvider);
      expect(s.themeMode, ThemeMode.dark);
      expect(s.textScale, 1.2);
      expect(s.uiLanguage, AppLanguage.chinese);
      expect(s.defaultInputLang, InputLanguage.chinese);
      expect(s.offlineFirst, isFalse);
      expect(s.soundEnabled, isTrue);
    });

    test('clamps and sanitises corrupt stored values', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{
        SettingsKeys.textScale: 3.0,
        SettingsKeys.themeMode: 'not-a-theme',
        SettingsKeys.uiLanguage: 'klingon',
      });

      final c = ProviderContainer();
      addTearDown(c.dispose);
      await c.read(settingsProvider.notifier).ready;

      final s = c.read(settingsProvider);
      expect(s.textScale, kMaxTextScale);
      // Phase 1 changed the fallback from Light to "follow the system", so a
      // corrupt/absent value no longer pins anyone to a light screen.
      expect(s.themeMode, ThemeMode.system);
      expect(s.uiLanguage, AppLanguage.english);
    });
  });

  group('history persistence', () {
    test('keeps newest first, de-duplicates, caps at maxEntries', () async {
      final c = ProviderContainer();
      addTearDown(c.dispose);
      final n = c.read(historyProvider.notifier);
      await n.ready;

      n.add('light');
      n.add('  light  '); // duplicate after trim
      await _settle();
      expect(c.read(historyProvider), ['light']);

      for (var i = 1; i <= 25; i++) {
        n.add('word-$i');
      }
      await _settle();

      final list = c.read(historyProvider);
      expect(list.length, HistoryNotifier.maxEntries);
      expect(list.first, 'word-25');
      expect(list.contains('light'), isFalse);

      final prefs = await SharedPreferences.getInstance();
      expect(
        prefs.getStringList(HistoryNotifier.storageKey)!.length,
        HistoryNotifier.maxEntries,
      );
    });

    test('reloads and clears', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{
        HistoryNotifier.storageKey: <String>['光', 'light'],
      });

      final c = ProviderContainer();
      addTearDown(c.dispose);
      await c.read(historyProvider.notifier).ready;
      expect(c.read(historyProvider), ['光', 'light']);

      c.read(historyProvider.notifier).clear();
      await _settle();

      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getStringList(HistoryNotifier.storageKey), isNull);
      expect(c.read(historyProvider), isEmpty);
    });
  });
}

