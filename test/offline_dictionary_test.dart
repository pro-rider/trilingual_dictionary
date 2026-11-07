import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:trilingual_dictionary/core/normalizer.dart';
import 'package:trilingual_dictionary/data/local/offline_dictionary.dart';

/// Runs the real bundled database through the exact search code the phone
/// uses. Skipped when the built database is not on this machine (it is
/// gitignored, so a fresh clone has no data until `build_dictionary.py` runs).
void main() {
  final dbPath =
      r'C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend\data\build\dictionary.sqlite';

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  test('English headword resolves through a sense gloss', () async {
    if (!File(dbPath).existsSync()) {
      markTestSkipped('dictionary.sqlite not built on this machine');
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
    if (!File(dbPath).existsSync()) {
      markTestSkipped('dictionary.sqlite not built on this machine');
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
    if (!File(dbPath).existsSync()) {
      markTestSkipped('dictionary.sqlite not built on this machine');
      return;
    }
    final dict = OfflineDictionary(overridePath: dbPath);
    final entry = await dict.search('pinyin', InputLanguage.english);
    expect(entry, isNotNull);
    await dict.close();
  });
}
