import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:trilingual_dictionary/app/theme/app_theme.dart';
import 'package:trilingual_dictionary/app/theme/app_tokens.dart';
import 'package:trilingual_dictionary/data/dictionary_repository.dart';
import 'package:trilingual_dictionary/data/models/analyzed_text.dart';
import 'package:trilingual_dictionary/data/models/dictionary_entry.dart';
import 'package:trilingual_dictionary/data/providers.dart';
import 'package:trilingual_dictionary/features/analyze/analyze_provider.dart';
import 'package:trilingual_dictionary/features/analyze/analyze_screen.dart';
import 'package:trilingual_dictionary/features/favorites/favorites_repository.dart';
import 'package:trilingual_dictionary/features/favorites/favorites_screen.dart';
import 'package:trilingual_dictionary/features/history/history_screen.dart';
import 'package:trilingual_dictionary/features/onboarding/onboarding_screen.dart';
import 'package:trilingual_dictionary/features/settings/settings_screen.dart';
import 'package:trilingual_dictionary/features/splash/splash_screen.dart';

/// Renders each screen that can be mounted without a real 96 MB database, in
/// BOTH themes. A white box on dark, a crash, or a widget that falls back to a
/// hard-coded colour shows up here instead of only on the phone.
class _FakeFavorites extends FavoritesRepository {
  @override
  Future<List<String>> build() async => ['light'];
}

class _FakeDictionary extends DictionaryRepository {
  _FakeDictionary() : super(rootBundle);

  @override
  Future<DictionaryEntry?> findById(String entryId) async {
    if (entryId != 'light') return null;
    return const DictionaryEntry(
      entryId: 'light',
      wordEn: 'light',
      wordZh: '光',
      senses: [],
    );
  }
}

AnalyzedText _sampleAnalyzed() => const AnalyzedText(
      text: '你好',
      language: 'zh',
      segments: [
        AnalyzedSegment(
          surface: '你好',
          kind: 'word',
          meaningEn: 'hello',
          meaningZh: '你好',
          meaningNe: 'नमस्ते',
          pinyin: 'nǐ hǎo',
          pos: 'interj',
          source: 'dataset',
        ),
      ],
      whole: WholeTranslation(en: 'Hello', zh: '你好', ne: 'नमस्ते'),
    );

Widget _wrap(Widget home, ThemeMode mode, {List<Override> overrides = const []}) {
  return ProviderScope(
    overrides: overrides,
    child: MaterialApp(
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: mode,
      home: home,
    ),
  );
}

void _checkThemeIsApplied(WidgetTester tester, ThemeMode mode, String anchor) {
  final ctx = tester.element(find.text(anchor).first);
  final expected =
      mode == ThemeMode.dark ? Brightness.dark : Brightness.light;
  expect(Theme.of(ctx).brightness, expected, reason: 'anchor "$anchor"');
  final tokens = ctx.tokens;
  expect(tokens, isNotNull);
  // A screen that forgot the tokens would paint a near-white page on dark.
  if (mode == ThemeMode.dark) {
    expect(tokens.page.computeLuminance(), lessThan(0.1));
  } else {
    expect(tokens.page.computeLuminance(), greaterThan(0.5));
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  final screens = <String, Widget Function()>{
    'settings': () => const SettingsScreen(),
    'favorites': () => const FavoritesScreen(),
    'history': () => const HistoryScreen(),
    'analyze': () => const AnalyzeScreen(query: '你好', langText: 'chinese'),
    'onboarding': () => const OnboardingScreen(),
  };

  final anchors = <String, String>{
    'settings': 'Settings',
    'favorites': 'light',
    'history': 'History',
    'analyze': '你好',
    'onboarding': 'Next',
  };

  for (final mode in [ThemeMode.light, ThemeMode.dark]) {
    for (final entry in screens.entries) {
      testWidgets('${entry.key} renders — ${mode.name}', (tester) async {
        SharedPreferences.setMockInitialValues({});
        await tester.pumpWidget(
          _wrap(
            entry.value(),
            mode,
            overrides: [
              favoritesProvider.overrideWith(_FakeFavorites.new),
              dictionaryRepositoryProvider
                  .overrideWithValue(_FakeDictionary()),
              analyzeProvider.overrideWith(
                (ref, args) async => _sampleAnalyzed(),
              ),
            ],
          ),
        );
        await tester.pumpAndSettle(const Duration(milliseconds: 200));

        expect(tester.takeException(), isNull);
        expect(find.text(anchors[entry.key]!), findsWidgets);
        _checkThemeIsApplied(tester, mode, anchors[entry.key]!);
      });
    }
  }

  for (final mode in [ThemeMode.light, ThemeMode.dark]) {
    testWidgets('splash renders — ${mode.name}', (tester) async {
      final router = GoRouter(
        initialLocation: '/',
        routes: [
          GoRoute(path: '/', builder: (_, _) => const SplashScreen()),
          GoRoute(path: '/home', builder: (_, _) => const Scaffold()),
        ],
      );
      await tester.pumpWidget(
        ProviderScope(
          child: MaterialApp.router(
            theme: AppTheme.light,
            darkTheme: AppTheme.dark,
            themeMode: mode,
            routerConfig: router,
          ),
        ),
      );
      await tester.pump(const Duration(milliseconds: 100));

      expect(tester.takeException(), isNull);
      _checkThemeIsApplied(tester, mode, 'Trilingual Dictionary');
      // Let the splash timer fire so no timer leaks into the next test.
      await tester.pump(const Duration(seconds: 2));
      await tester.pumpAndSettle();
    });
  }
}
