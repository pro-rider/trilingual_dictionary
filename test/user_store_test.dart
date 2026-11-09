import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:trilingual_dictionary/core/normalizer.dart';
import 'package:trilingual_dictionary/data/local/offline_dictionary.dart';
import 'package:trilingual_dictionary/data/local/user_store.dart';

/// Builds a throwaway dictionary with the columns the app reads, so the swap
/// from one dictionary build to the next can be simulated without shipping the
/// real 96 MB file into a unit test.
Future<String> makeDictionary(
  String dir,
  String name, {
  required int entryId,
  required String wordZh,
  required String pinyin,
  required String glossEn,
  String glossNe = '',
  String? exampleEn,
}) async {
  final path = p.join(dir, name);
  final db = await databaseFactoryFfi.openDatabase(path);
  await db.execute(
    'CREATE TABLE entries (entry_id INTEGER PRIMARY KEY, simplified TEXT, '
    'traditional TEXT, pinyin_num TEXT, pinyin_marked TEXT, pinyin_plain TEXT, '
    'pinyin_search TEXT, category TEXT, pos_primary TEXT, is_proper INTEGER, '
    'is_chengyu INTEGER, is_classifier INTEGER, rarity TEXT, freq_rank INTEGER, '
    'hsk_level INTEGER, status TEXT)',
  );
  await db.execute(
    'CREATE TABLE senses (sense_id INTEGER PRIMARY KEY, entry_id INTEGER, '
    'sense_order INTEGER, gloss_en TEXT, gloss_zh TEXT, gloss_ne TEXT, '
    'ne_status TEXT, source_id TEXT)',
  );
  await db.execute(
    'CREATE TABLE examples (example_id INTEGER PRIMARY KEY, sense_id INTEGER, '
    'en TEXT, zh TEXT, ne TEXT, source_id TEXT, review_status TEXT, '
    'quarantine_reason TEXT)',
  );
  await db.insert('entries', {
    'entry_id': entryId,
    'simplified': wordZh,
    'traditional': wordZh,
    'pinyin_marked': pinyin,
    'pinyin_plain': pinyin.replaceAll(' ', ''),
    'is_proper': 0,
    'freq_rank': 100,
  });
  await db.insert('senses', {
    'sense_id': entryId * 10,
    'entry_id': entryId,
    'sense_order': 0,
    'gloss_en': glossEn,
    'gloss_zh': '',
    'gloss_ne': glossNe,
    'ne_status': glossNe.isEmpty ? null : 'reviewed',
  });
  if (exampleEn != null) {
    await db.insert('examples', {
      'example_id': entryId * 100,
      'sense_id': entryId * 10,
      'en': exampleEn,
      'zh': '这是$wordZh。',
      'ne': '',
      'review_status': 'imported',
    });
  }
  await db.close();
  return path;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;

  late Directory tmp;

  setUp(() async {
    tmp = await Directory.systemTemp.createTemp('tridict_userstore_');
  });

  tearDown(() async {
    try {
      await tmp.delete(recursive: true);
    } catch (_) {}
  });

  test('a sense key depends on the word, not on a row id', () {
    final a = UserStore.senseKey(
        wordZh: '玩具', pinyin: 'wán jù', glossEn: 'toy');
    final b = UserStore.senseKey(
        wordZh: ' 玩具 ', pinyin: 'Wán Jù', glossEn: 'TOY ');
    expect(a, b, reason: 'normalisation must make the key stable');

    final other = UserStore.senseKey(
        wordZh: '玩具', pinyin: 'wán jù', glossEn: 'plaything');
    expect(a, isNot(other), reason: 'each sense keeps its own identity');
  });

  test('AI Nepali gloss survives a dictionary rebuild', () async {
    final store = UserStore(overridePath: p.join(tmp.path, 'user.db'));
    final key = UserStore.senseKey(
        wordZh: '玩具', pinyin: 'wán jù', glossEn: 'toy');
    await store.putAiGloss(key, ne: 'खेलौना', model: 'test-model');

    // First build: entry 1.
    final first = await makeDictionary(tmp.path, 'dict_v1.sqlite',
        entryId: 1, wordZh: '玩具', pinyin: 'wán jù', glossEn: 'toy');
    final dictA = OfflineDictionary(overridePath: first, userStore: store);
    final entryA = await dictA.search('toy', InputLanguage.english);
    expect(entryA, isNotNull);
    expect(entryA!.senses.first.meaningNe, 'खेलौना');
    expect(entryA.senses.first.meaningNeSource, 'ai_translated');

    // Second build: same word, different row id — a rebuild renumbers entries.
    final second = await makeDictionary(tmp.path, 'dict_v2.sqlite',
        entryId: 900, wordZh: '玩具', pinyin: 'wán jù', glossEn: 'toy');
    final dictB = OfflineDictionary(overridePath: second, userStore: store);
    final entryB = await dictB.search('toy', InputLanguage.english);
    expect(entryB, isNotNull);
    expect(entryB!.entryId, 'zh900', reason: 'the dictionary did change');
    expect(entryB.senses.first.meaningNe, 'खेलौना',
        reason: 'the AI gloss is keyed by the sense, so it must survive');

    await dictA.close();
    await dictB.close();
    await store.close();
  });

  test('AI example is used only when the sense has none of its own', () async {
    final store = UserStore(overridePath: p.join(tmp.path, 'user.db'));
    final key = UserStore.senseKey(
        wordZh: '玩具', pinyin: 'wán jù', glossEn: 'toy');
    await store.putAiExample(key, en: 'The child plays with a toy.');

    final path = await makeDictionary(tmp.path, 'dict.sqlite',
        entryId: 5, wordZh: '玩具', pinyin: 'wán jù', glossEn: 'toy');
    final dict = OfflineDictionary(overridePath: path, userStore: store);
    final entry = await dict.search('玩具', InputLanguage.chinese);
    expect(entry, isNotNull);
    expect(entry!.senses.first.examples.first.en, 'The child plays with a toy.');
    expect(entry.senses.first.examples.first.reviewStatus, 'ai_generated');

    // A dictionary sentence outranks the AI one.
    final withOwn = await makeDictionary(tmp.path, 'dict2.sqlite',
        entryId: 5,
        wordZh: '玩具',
        pinyin: 'wán jù',
        glossEn: 'toy',
        exampleEn: 'She bought a toy.');
    final dict2 = OfflineDictionary(overridePath: withOwn, userStore: store);
    final entry2 = await dict2.search('玩具', InputLanguage.chinese);
    expect(entry2!.senses.first.examples.first.en, 'She bought a toy.');
    expect(entry2.senses.first.examples.first.reviewStatus, 'approved');

    await dict.close();
    await dict2.close();
    await store.close();
  });

  test('export and import keep AI rows, and an older file cannot win', () async {
    final store = UserStore(overridePath: p.join(tmp.path, 'a.db'));
    final key = UserStore.senseKey(
        wordZh: '玩具', pinyin: 'wán jù', glossEn: 'toy');
    await store.putAiGloss(key, ne: 'खेलौना');
    final exported = await store.exportJson();
    expect(exported, contains('खेलौना'));

    final other = UserStore(overridePath: p.join(tmp.path, 'b.db'));
    final imported = await other.importJson(exported);
    expect(imported, greaterThan(0));
    final gloss = await other.aiGloss(key);
    expect(gloss?.ne, 'खेलौना');

    await store.close();
    await other.close();
  });

  test('opening an existing file migrates it and keeps a backup', () async {
    final path = p.join(tmp.path, 'legacy.db');
    // An old install: a user database with a table but no version stamp.
    final legacy = await databaseFactoryFfi.openDatabase(path);
    await legacy.execute(
        'CREATE TABLE favorites (key TEXT PRIMARY KEY, entry_id TEXT)');
    await legacy.close();

    final store = UserStore(overridePath: path);
    await store.open();

    final backups = tmp
        .listSync()
        .whereType<File>()
        .where((f) => p.basename(f.path).startsWith('legacy.db.bak-'))
        .toList();
    expect(backups, isNotEmpty, reason: 'a migration must be reversible');

    // The schema is up to date after opening.
    final db = await databaseFactoryFfi.openDatabase(path);
    final version =
        (await db.rawQuery('PRAGMA user_version')).first.values.first as int;
    expect(version, UserStore.schemaVersion);
    final tables = await db.rawQuery(
        "SELECT name FROM sqlite_master WHERE type = 'table'");
    final names = tables.map((r) => r['name']).toSet();
    expect(names, containsAll(['ai_glosses', 'ai_examples', 'id_remap']));
    await db.close();
    await store.close();
  });
}
