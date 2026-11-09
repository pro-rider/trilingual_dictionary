import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:trilingual_dictionary/core/normalizer.dart';
import 'package:trilingual_dictionary/data/local/offline_dictionary.dart';

/// Pasting a long paragraph used to land on `/analyze`, which only the backend
/// can answer — offline the user saw "Analysis needs the server", an error
/// screen with nothing in it. These tests run the offline analyser against the
/// real 96 MB database, i.e. exactly the data the phone carries.
void main() {
  const dbPath =
      r'C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary'
      r'\backend\data\build\dictionary.sqlite';

  late OfflineDictionary dict;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
    dict = OfflineDictionary(overridePath: dbPath);
  });

  test('a pasted paragraph resolves word by word with no server', () async {
    const text = 'word detail screen without sending data to any server. '
        'First, implement query-aware sense selection and show the best sense.';
    final result = await dict.analyzeOffline(text, InputLanguage.english);

    expect(result.segments, isNotEmpty,
        reason: 'the analyse screen must not be empty offline');
    expect(result.degraded, isFalse,
        reason: 'a 20-word sentence is well under the 300-unit budget');

    final resolved = result.segments
        .where((s) => s.hasMeaning)
        .map((s) => s.surface.toLowerCase())
        .toList();
    // These are all in the bundled dictionary; if any of them stops resolving
    // the offline fallback has broken.
    expect(resolved, containsAll(['word', 'screen', 'data', 'server', 'first']));

    final word = result.segments.firstWhere((s) => s.surface == 'word');
    expect(word.wordZh, isNotEmpty, reason: 'word → 词/单词');
    expect(word.pinyin, isNotEmpty, reason: 'the analysis shows pinyin');
    expect(word.source, 'dataset');
  });

  test('function words do not become dictionary cards', () async {
    const text = 'The dog is in the house and it has a book.';
    final result = await dict.analyzeOffline(text, InputLanguage.english);

    final functions = result.segments.where((s) => s.isFunction).toList();
    expect(functions.map((s) => s.surface.toLowerCase()),
        containsAll(['the', 'is', 'in', 'and', 'a']));
    expect(result.words.any((s) => s.surface == 'dog'), isTrue);
    expect(result.words.any((s) => s.surface == 'book'), isTrue);
  });

  test('Chinese text is segmented by longest match', () async {
    const text = '我们爬了那座山。';
    final result = await dict.analyzeOffline(text, InputLanguage.chinese);

    expect(result.segments, isNotEmpty);
    final meanings = result.segments.where((s) => s.hasMeaning).toList();
    expect(meanings, isNotEmpty, reason: '山 and 我们 must resolve');
    expect(result.segments.any((s) => s.surface == '山'), isTrue,
        reason: '山 is a single-character entry');
  });

  test('very long pastes are cut, and say so, instead of erroring', () async {
    final text = List.filled(400, 'water').join(' ');
    final result = await dict.analyzeOffline(text, InputLanguage.english);

    expect(result.degraded, isTrue);
    expect(result.segments.length, lessThanOrEqualTo(300));
    expect(result.error, contains('300'),
        reason: 'the banner must explain the cut, not just drop text');
    expect(result.segments.any((s) => s.hasMeaning), isTrue,
        reason: 'the first 300 units still get their meanings');
  }, timeout: const Timeout(Duration(minutes: 3)));
}
