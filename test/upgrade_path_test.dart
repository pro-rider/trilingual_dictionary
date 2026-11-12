import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:trilingual_dictionary/core/normalizer.dart';
import 'package:trilingual_dictionary/data/local/offline_dictionary.dart';
import 'package:trilingual_dictionary/data/local/user_store.dart';

/// Upgrade path: a user on the old bundled asset, with favorites, history and
/// paid AI results, upgrades to a new asset. Nothing the user owns may be lost.
///
/// The old dictionary is a small synthetic file (same schema, different row
/// ids), so this runs without the real 96 MB database — the point is the swap
/// contract, not the fixture size.
Future<String> _makeDictionary(String dir, String name,
    {required int entryId, required String wordZh, required String pinyin,
    required String glossEn, String glossNe = ''}) async {
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
    'ne_status': glossNe.isEmpty ? 'none' : 'reviewed',
  });
  await db.close();
  return path;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;

  late Directory tmp;

  setUp(() async {
    tmp = await Directory.systemTemp.createTemp('tridict_upgrade_');
    SharedPreferences.setMockInitialValues({
      'favorites': ['zh1', 'zh2'],
      'history': ['玩具', 'water'],
    });
  });

  tearDown(() async {
    try {
      await tmp.delete(recursive: true);
    } catch (_) {}
  });

  test('upgrading the asset keeps favorites, history and paid AI results',
      () async {
    final store = UserStore(overridePath: p.join(tmp.path, 'user.db'));
    final key = UserStore.senseKey(
        wordZh: '玩具', pinyin: 'wán jù', glossEn: 'toy');
    await store.putAiGloss(key, ne: 'खेलौना', model: 'test-model');

    // --- before the upgrade: the old bundled build -------------------------
    final oldPath = await _makeDictionary(tmp.path, 'dict_old.sqlite',
        entryId: 1, wordZh: '玩具', pinyin: 'wán jù', glossEn: 'toy');
    final oldDict = OfflineDictionary(overridePath: oldPath, userStore: store);
    final before = await oldDict.search('玩具', InputLanguage.chinese);
    expect(before, isNotNull);
    expect(before!.senses.first.meaningNeSource, 'ai_translated');

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getStringList('favorites'), ['zh1', 'zh2']);
    await oldDict.close();

    // --- the upgrade: a new asset arrives with a different row id ----------
    final newPath = await _makeDictionary(tmp.path, 'dict_new.sqlite',
        entryId: 900, wordZh: '玩具', pinyin: 'wán jù', glossEn: 'toy');
    final newDict = OfflineDictionary(overridePath: newPath, userStore: store);
    final after = await newDict.search('玩具', InputLanguage.chinese);
    expect(after, isNotNull);
    expect(after!.entryId, 'zh900', reason: 'the dictionary did change');
    expect(after.senses.first.meaningNe, 'खेलौना',
        reason: 'the paid AI Nepali gloss must survive the swap');
    expect(after.senses.first.meaningNeSource, 'ai_translated');

    final prefsAfter = await SharedPreferences.getInstance();
    expect(prefsAfter.getStringList('favorites'), ['zh1', 'zh2'],
        reason: 'favorites live in prefs, not in the replaced dictionary');
    expect(prefsAfter.getStringList('history'), ['玩具', 'water']);

    await newDict.close();
    await store.close();
  });

  test('a partial unpack is discarded, and the failure says why', () async {
    final target = File(p.join(tmp.path, 'dictionary.sqlite'));
    File('${target.path}.part').writeAsStringSync('half-written');
    File('${target.path}.stamp').writeAsStringSync('db-old');

    final dict = OfflineDictionary(overridePath: target.path);
    // The retry path must not leave the staged file behind for the next launch
    // to mistake for a usable database.
    await dict.discardPartialForTest(target);

    expect(File('${target.path}.part').existsSync(), isFalse);
    expect(File('${target.path}.stamp').existsSync(), isFalse);
    dict.dispose();
  });

  test('storage failures are turned into a message a person can act on', () {
    expect(
      OfflineDictionary.storageFailure(
          const FileSystemException('write failed', 'x', OSError('ENOSPC', 28))),
      contains('Not enough free space'),
    );
    expect(
      OfflineDictionary.storageFailure(
          const FileSystemException('write failed', 'x', OSError('EACCES', 13))),
      contains('permission'),
    );
    expect(
      OfflineDictionary.storageFailure(StateError('gzip corrupt')),
      contains('could not be unpacked'),
    );
  });
}
