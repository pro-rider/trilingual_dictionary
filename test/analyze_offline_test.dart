import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:trilingual_dictionary/core/normalizer.dart';
import 'package:trilingual_dictionary/data/local/offline_dictionary.dart';

import 'support/real_db.dart';

/// Pasting a long paragraph used to land on `/analyze`, which only the backend
/// can answer — offline the user saw "Analysis needs the server", an error
/// screen with nothing in it. These tests run the offline analyser against the
/// real database, i.e. exactly the data the phone carries, and skip when it has
/// not been built on this machine (it is gitignored, so CI never has it).
void main() {
  final dbPath = testDictionaryPath();
  final noDb = missingTestDictionary();

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
  }, skip: noDb ? kMissingDictionarySkip : null);

  test('function words do not become dictionary cards', () async {
    const text = 'The dog is in the house and it has a book.';
    final result = await dict.analyzeOffline(text, InputLanguage.english);

    final functions = result.segments.where((s) => s.isFunction).toList();
    expect(functions.map((s) => s.surface.toLowerCase()),
        containsAll(['the', 'is', 'in', 'and', 'a']));
    expect(result.words.any((s) => s.surface == 'dog'), isTrue);
    expect(result.words.any((s) => s.surface == 'book'), isTrue);
  }, skip: noDb ? kMissingDictionarySkip : null);

  test('Chinese text is segmented by longest match', () async {
    const text = '我们爬了那座山。';
    final result = await dict.analyzeOffline(text, InputLanguage.chinese);

    expect(result.segments, isNotEmpty);
    final meanings = result.segments.where((s) => s.hasMeaning).toList();
    expect(meanings, isNotEmpty, reason: '山 and 我们 must resolve');
    expect(result.segments.any((s) => s.surface == '山'), isTrue,
        reason: '山 is a single-character entry');
  }, skip: noDb ? kMissingDictionarySkip : null);

  test('very long pastes are cut, and say so, instead of erroring', () async {
    final text = List.filled(400, 'water').join(' ');
    final result = await dict.analyzeOffline(text, InputLanguage.english);

    expect(result.degraded, isTrue);
    expect(result.segments.length, lessThanOrEqualTo(300));
    expect(result.error, contains('300'),
        reason: 'the banner must explain the cut, not just drop text');
    expect(result.segments.any((s) => s.hasMeaning), isTrue,
        reason: 'the first 300 units still get their meanings');
  },
      skip: noDb ? kMissingDictionarySkip : null,
      timeout: const Timeout(Duration(minutes: 3)));

  // Runs everywhere, including a clone with no built dictionary: it only needs
  // a file that cannot be opened as SQLite. This is the branch that used to
  // return an empty result with degraded=false, which rendered the source text
  // and nothing else — no words, no explanation.
  test('an unopenable dictionary degrades with an explanation, not a blank screen',
      () async {
    final tmp = await Directory.systemTemp.createTemp('dict-unavailable');
    final bogus = File('${tmp.path}/not-a-database.sqlite');
    bogus.writeAsStringSync('this is not a sqlite file');
    final broken = OfflineDictionary(overridePath: bogus.path);
    final result =
        await broken.analyzeOffline('The dog is in the house.', InputLanguage.english);

    expect(result.segments, isEmpty);
    expect(result.degraded, isTrue,
        reason: 'the screen renders its banner only when degraded is true');
    expect(result.error, contains('dictionary'),
        reason: 'the banner text must name the cause the user can act on');
    await broken.close();
    await tmp.delete(recursive: true);
  });
}
