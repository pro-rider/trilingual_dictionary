import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:trilingual_dictionary/core/normalizer.dart';
import 'package:trilingual_dictionary/data/api_client.dart';
import 'package:trilingual_dictionary/data/local/offline_dictionary.dart';

import 'support/real_db.dart';

/// Runs the real bundled database through the exact search code the phone
/// uses. Skipped when the built database is not on this machine (it is
/// gitignored, so a fresh clone has no data until `build_dictionary.py` runs).
void main() {
  final dbPath = testDictionaryPath();

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  test('English headword resolves through a sense gloss', () async {
    if (missingTestDictionary()) {
      markTestSkipped(kMissingDictionarySkip);
      return;
    }
    final dict = OfflineDictionary(overridePath: dbPath);
    final entry = await dict.search('raisin', InputLanguage.english);
    expect(entry, isNotNull);
    expect(entry!.wordZh, '葡萄干');
    expect(entry.senses.first.meaningNe, 'किशमिश');
    expect(entry.source, 'offline-db');
    await dict.close();
  });

  test('Chinese lookup returns pinyin and the HSK5-tagged word', () async {
    if (missingTestDictionary()) {
      markTestSkipped(kMissingDictionarySkip);
      return;
    }
    final dict = OfflineDictionary(overridePath: dbPath);
    final entry = await dict.search('安排', InputLanguage.chinese);
    expect(entry, isNotNull);
    expect(entry!.wordZh, '安排');
    expect(entry.senses, isNotEmpty);
    expect(entry.senses.first.meaningNe, isNotEmpty);
    await dict.close();
  });

  test('pinyin without tones finds the entry', () async {
    if (missingTestDictionary()) {
      markTestSkipped(kMissingDictionarySkip);
      return;
    }
    final dict = OfflineDictionary(overridePath: dbPath);
    final entry = await dict.search('pinyin', InputLanguage.english);
    expect(entry, isNotNull);
    await dict.close();
  });

  test('country names resolve to the country, not to a species', () async {
    if (missingTestDictionary()) {
      markTestSkipped(kMissingDictionarySkip);
      return;
    }
    final dict = OfflineDictionary(overridePath: dbPath);
    // Regression: "Nepal" used to return the bird 白眶雀鹛 "Nepal fulvetta".
    final nepal = await dict.search('Nepal', InputLanguage.english);
    expect(nepal?.wordZh, '尼泊尔');
    // Regression: "China" used to return 东土 ("the East; China").
    final china = await dict.search('China', InputLanguage.english);
    expect(china?.wordZh, '中国');
    await dict.close();
  });

  test('plural query falls back to the singular headword', () async {
    if (missingTestDictionary()) {
      markTestSkipped(kMissingDictionarySkip);
      return;
    }
    final dict = OfflineDictionary(overridePath: dbPath);
    // Regression: "behaviors" used to match 潜规则 only because the word sat
    // inside a long parenthetical. Several entries legitimately gloss
    // "behavior" (行为 / 品行 / 做派); frequency ranking now puts the word a
    // learner means (行为) first.
    final entry = await dict.search('behaviors', InputLanguage.english);
    expect(entry, isNotNull);
    expect(entry!.wordZh, '行为');
    expect(
      entry.senses.any((s) => s.meaningEn.toLowerCase().contains('behavior')),
      isTrue,
    );
    await dict.close();
  });

  test('enrichment is a no-op when the backend is unreachable', () async {
    if (missingTestDictionary()) {
      markTestSkipped(kMissingDictionarySkip);
      return;
    }
    final dict = OfflineDictionary(overridePath: dbPath);
    final entry = await dict.search('Nepal', InputLanguage.english);
    expect(entry, isNotNull);
    // A Dio pointed at a dead port stands in for "phone has no network".
    final deadApi = ApiClient(Dio(BaseOptions(
      baseUrl: 'http://127.0.0.1:9',
      connectTimeout: const Duration(seconds: 1),
    )));
    final enriched = await dict.enrich(entry!, deadApi);
    // No answer, no writes: the entry comes back intact instead of crashing.
    expect(enriched.wordZh, '尼泊尔');
    expect(enriched.senses, isNotEmpty);
    await dict.close();
  });
}
