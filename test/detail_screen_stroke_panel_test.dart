import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:trilingual_dictionary/data/dictionary_repository.dart';
import 'package:trilingual_dictionary/data/models/dictionary_entry.dart';
import 'package:trilingual_dictionary/data/models/sense.dart';
import 'package:trilingual_dictionary/data/providers.dart';
import 'package:trilingual_dictionary/features/character/character_panel.dart';
import 'package:trilingual_dictionary/features/detail/detail_screen.dart';

/// The panel existed for a whole stage without being mounted on any screen, so
/// it could not be opened on a device. This test is the guard against that
/// happening again: the word-detail page must build a [CharacterPanel] for an
/// entry that has Chinese text, and must not build one when it does not.
class _FakeDictionary extends DictionaryRepository {
  _FakeDictionary(this._entry) : super(rootBundle);

  final DictionaryEntry? _entry;

  @override
  Future<DictionaryEntry?> findById(String entryId) async => _entry;
}

const _light = DictionaryEntry(
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
    ),
  ],
);

const _emptyChinese = DictionaryEntry(
  entryId: 'en0001',
  wordEn: 'hello',
  wordZh: '   ',
  senses: [
    Sense(
      id: 'en0001:1',
      wordEn: 'hello',
      wordZh: '   ',
      pinyin: '   ',
      ipaEn: '   ',
      pos: 'interjection',
      meaningEn: 'a greeting',
      meaningZh: '问候语',
      meaningNe: 'अभिवादन',
    ),
  ],
);

Future<void> _pump(
  WidgetTester tester,
  DictionaryEntry? entry,
) async {
  // The panel loads the real stroke pack from the asset bundle; the default
  // test window is too small for the card plus the image placeholder.
  tester.view.physicalSize = const Size(1000, 1400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);

  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        dictionaryRepositoryProvider.overrideWithValue(_FakeDictionary(entry)),
      ],
      child: MaterialApp(
        home: DetailScreen(entryId: entry?.entryId ?? 'missing'),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('the word detail page mounts the stroke panel', (tester) async {
    await _pump(tester, _light);

    expect(find.byType(CharacterPanel), findsOneWidget);
    expect(find.text('Stroke order'), findsOneWidget);

    // The pack really loads through the app path in this widget test.
    await tester.pumpAndSettle();
    expect(find.textContaining('Stroke order not reviewed'), findsNothing,
        reason: '光 has no known stroke-count disagreement');
  });

  testWidgets('a word with no Chinese text gets no panel', (tester) async {
    await _pump(tester, _emptyChinese);
    expect(find.byType(CharacterPanel), findsNothing);
  });
}
