import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:trilingual_dictionary/app/theme/app_theme.dart';
import 'package:trilingual_dictionary/app/theme/app_tokens.dart';
import 'package:trilingual_dictionary/core/normalizer.dart';
import 'package:trilingual_dictionary/data/api_client.dart';
import 'package:trilingual_dictionary/data/dictionary_repository.dart';
import 'package:trilingual_dictionary/data/local/offline_dictionary.dart';
import 'package:trilingual_dictionary/data/models/dictionary_entry.dart';
import 'package:trilingual_dictionary/data/models/example_sentence.dart';
import 'package:trilingual_dictionary/data/models/sense.dart';
import 'package:trilingual_dictionary/data/providers.dart';
import 'package:trilingual_dictionary/features/search/home_screen.dart';
import 'package:trilingual_dictionary/features/search/result_screen.dart';
import 'package:trilingual_dictionary/features/search/search_provider.dart';

/// A small fixture so the two data-driven screens (home, result) can be
/// rendered in widget tests in BOTH themes, without opening the 96 MB asset.
const _fixtureEntry = DictionaryEntry(
  entryId: 'zh1001',
  wordEn: 'light',
  wordZh: '光',
  senses: [
    Sense(
      id: 'zh1001:1',
      wordEn: 'light',
      wordZh: '光',
      pinyin: 'guāng',
      ipaEn: 'laɪt',
      pos: 'noun',
      meaningEn: 'light; brightness',
      meaningZh: '光线；明亮',
      meaningNe: 'प्रकाश',
      examples: [
        ExampleSentence(
          en: 'The room is full of light.',
          zh: '房间里满是光。',
          ne: 'कोठा प्रकाशले भरिएको छ।',
          reviewStatus: 'approved',
        ),
      ],
    ),
    Sense(
      id: 'zh1001:2',
      wordEn: 'light',
      wordZh: '光',
      pinyin: 'guāng',
      ipaEn: 'laɪt',
      pos: 'adj',
      meaningEn: 'not heavy',
      meaningZh: '轻的',
      meaningNe: 'हल्का',
    ),
  ],
);

class _FixtureDictionary extends DictionaryRepository {
  _FixtureDictionary() : super(rootBundle);

  @override
  Future<DictionaryEntry?> search(String query, InputLanguage lang) async =>
      _fixtureEntry;

  @override
  Future<List<DictionaryEntry>> popular([int limit = 6]) async =>
      const [_fixtureEntry];

  @override
  Future<DictionaryEntry?> findById(String entryId) async => _fixtureEntry;
}

/// No database, no images: the card must fall back to its placeholder.
class _NoImagesOffline extends OfflineDictionary {
  _NoImagesOffline() : super(overridePath: 'fixture-none');

  @override
  Future<EntryImage?> imageForEntry(int entryPk) async => null;

  @override
  Future<EntryImage?> imageForWord(String wordZh) async => null;
}

List<Override> _overrides() => [
      dictionaryRepositoryProvider.overrideWithValue(_FixtureDictionary()),
      offlineDictionaryProvider.overrideWithValue(_NoImagesOffline()),
      backendReachableProvider.overrideWith((ref) async => false),
      popularProvider.overrideWith((ref) async => const [_fixtureEntry]),
      resultProvider.overrideWith((ref, args) async => _fixtureEntry),
    ];

Widget _app(Widget home, ThemeMode mode) => ProviderScope(
      overrides: _overrides(),
      child: MaterialApp(
        theme: AppTheme.light,
        darkTheme: AppTheme.dark,
        themeMode: mode,
        home: home,
      ),
    );

void _expectsTheme(WidgetTester tester, ThemeMode mode, String anchor) {
  final ctx = tester.element(find.textContaining(anchor).first);
  expect(Theme.of(ctx).brightness,
      mode == ThemeMode.dark ? Brightness.dark : Brightness.light);
  expect(ctx.tokens.page.computeLuminance(),
      mode == ThemeMode.dark ? lessThan(0.1) : greaterThan(0.5));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  for (final mode in [ThemeMode.light, ThemeMode.dark]) {
    testWidgets('home screen renders with a fixture — ${mode.name}',
        (tester) async {
      SharedPreferences.setMockInitialValues({});
      await tester.pumpWidget(_app(const HomeScreen(), mode));
      await tester.pumpAndSettle(const Duration(milliseconds: 200));

      expect(tester.takeException(), isNull);
      expect(find.text('Trilingual Dictionary'), findsOneWidget);
      expect(find.text('Popular words'), findsOneWidget);
      _expectsTheme(tester, mode, 'Trilingual Dictionary');
    });

    testWidgets('result screen renders with a fixture — ${mode.name}',
        (tester) async {
      SharedPreferences.setMockInitialValues({});
      await tester.pumpWidget(
        _app(
            const ResultScreen(query: 'light', lang: InputLanguage.english), mode),
      );
      await tester.pumpAndSettle(const Duration(milliseconds: 200));

      expect(tester.takeException(), isNull);
      // The card renders "light · 光" as one string, so match on the substring.
      expect(find.textContaining('光'), findsWidgets);
      expect(find.textContaining('light'), findsWidgets);
      _expectsTheme(tester, mode, 'light · 光');
    });
  }
}
