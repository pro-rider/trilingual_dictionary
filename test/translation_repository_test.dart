import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:trilingual_dictionary/core/translation_resolution.dart';
import 'package:trilingual_dictionary/core/translation_status.dart';
import 'package:trilingual_dictionary/data/local/translation_repository.dart';
import 'package:trilingual_dictionary/data/local/user_store.dart';

/// Integration tests for the one place the app decides which Nepali meaning to
/// show. Half run on the in-memory store (every branch), half on the two real
/// database files so "the store holds the values" becomes "the app can read
/// them".
void main() {
  final root = Directory.current.path;
  final dictPath = '$root\\backend\\data\\build\\dictionary.sqlite';
  final storePath = '$root\\backend\\data\\build\\translations.db';

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  TranslationCandidate row(
    int id,
    String text, {
    String? senseKey = 'k',
    int? supersedes,
    String? publication = 'labeled',
    String? verification = 'not_verified',
    String? validation = 'incomplete',
    String? strength = 'none',
    String? method = 'llm',
    String? source,
    String? originMethod,
    String? evidenceLanguage,
    String? senseMatch,
  }) =>
      TranslationCandidate(
        translationId: id,
        senseKey: senseKey,
        text: text,
        supersedesId: supersedes,
        publicationStatus: publication,
        humanVerification: verification,
        validationStatus: validation,
        evidenceStrength: strength,
        generationMethod: method,
        originSource: source,
        originMethod: originMethod,
        evidenceLanguage: evidenceLanguage,
        senseMatchMethod: senseMatch,
      );

  Future<SenseTranslation> resolveWith(
    List<TranslationCandidate> rows, {
    String? legacy,
    String key = 'k',
    StoreHealth health = StoreHealth.ok,
  }) {
    final repo = LocalTranslationRepository(
      InMemoryTranslationStore(rows: {key: rows}, healthy: health, legacy: {key: legacy ?? ''}),
    );
    return repo.resolve(key, legacyText: legacy);
  }

  test('legacy value and its governance copy render as one meaning', () async {
    final r = await resolveWith(
      [row(1, 'पानी', source: 'dictionary.sqlite:senses.ne')],
      legacy: 'पानी',
    );
    expect(r.resolved.text, 'पानी');
    expect(r.resolved.source, NepaliSource.dictionary);
    expect(r.resolved.status.code, TranslationStatus.aiUnverified);
    expect(r.translationId, 1);
  });

  test('a missing governance row keeps the original Nepali visible', () async {
    final r = await resolveWith(const [], legacy: 'पानी');
    expect(r.resolved.text, 'पानी');
    expect(r.resolved.source, NepaliSource.dictionary);
    expect(r.resolved.visible, isTrue);
    expect(r.resolved.status.code, TranslationStatus.unverifiedLegacy);
    expect(r.resolved.status.label, isNot(contains('Verified')));
  });

    test('a governance-only value is shown when the dictionary has none', () async {
    final r = await resolveWith(
      [row(1, 'पानी', validation: 'passed', strength: 'strong', source: 'tatoeba')],
      legacy: '',
    );
    expect(r.resolved.text, 'पानी');
    expect(r.resolved.source, NepaliSource.governance);
    expect(r.resolved.status.code, TranslationStatus.aiChecked);
    expect(r.resolved.visible, isTrue);
  });

  test('a quarantined row hides the sense instead of exposing the original', () async {
    final r = await resolveWith(
      [row(1, 'बatti', publication: 'quarantined', validation: 'failed', method: 'legacy_unknown')],
      legacy: 'बatti',
    );
    expect(r.resolved.text, isEmpty);
    expect(r.resolved.source, NepaliSource.none);
    expect(r.resolved.visible, isFalse);
    expect(r.resolved.status.code, TranslationStatus.quarantined);
  });

  test('a user correction is shown but never labelled verified', () async {
    final r = await resolveWith(
      [row(1, 'पानी', method: 'llm'), row(2, 'जल', supersedes: 1, originMethod: 'user_correction')],
      legacy: 'पानी',
    );
    expect(r.resolved.text, 'जल');
    expect(r.resolved.source, NepaliSource.governance);
    expect(r.resolved.status.code, TranslationStatus.userCorrection);
    expect(r.resolved.status.label, isNot(contains('Verified')));
    expect(r.translationId, 2);
  });

  test('two senses sharing one Nepali value stay separate senses', () async {
    final rowsA = [row(1, 'पानी', senseKey: 'a')];
    final rowsB = [row(2, 'पानी', senseKey: 'b')];
    final repoA = LocalTranslationRepository(
        InMemoryTranslationStore(rows: {'a': rowsA}, legacy: {'a': ''}));
    final repoB = LocalTranslationRepository(
        InMemoryTranslationStore(rows: {'b': rowsB}, legacy: {'b': ''}));
    final a = await repoA.resolve('a');
    final b = await repoB.resolve('b');
    expect(a.resolved.text, 'पानी');
    expect(b.resolved.text, 'पानी');
    expect(a.translationId, isNot(b.translationId));
  });

  test('a missing governance database falls back with a reported reason', () async {
    final repo = LocalTranslationRepository(SqliteTranslationStore('$root\\no-such-store.db'));
    final r = await repo.resolve('k', legacyText: 'पानी');
    expect(r.health, StoreHealth.missing);
    expect(r.resolved.text, 'पानी');
    expect(r.resolved.visible, isTrue);
    expect(r.resolved.problem, 'store_missing');
  });

  test('a schema mismatch is refused, not guessed at', () async {
    final dir = Directory.systemTemp.createTempSync('tr_schema');
    final dbPath = '${dir.path}\\translations.db';
    final db = await databaseFactory.openDatabase(dbPath);
    await db.execute('CREATE TABLE translations(translation_id INTEGER PRIMARY KEY, text TEXT)');
    await db.execute('PRAGMA user_version = 2');
    await db.close();
    final repo = LocalTranslationRepository(SqliteTranslationStore(dbPath));
    final r = await repo.resolve('k', legacyText: 'पानी');
    expect(r.health, StoreHealth.schemaMismatch);
    expect(r.resolved.source, NepaliSource.dictionary);
    expect(r.resolved.problem, 'store_schemaMismatch');
    expect(r.resolved.status.label, isNot(contains('Source-supported')));
  });

  test('a corrupted governance file is unreadable and never fatal', () async {
    final dir = Directory.systemTemp.createTempSync('tr_corrupt');
    final dbPath = '${dir.path}\\translations.db';
    File(dbPath).writeAsBytesSync(List<int>.generate(4096, (i) => i % 251));
    final repo = LocalTranslationRepository(SqliteTranslationStore(dbPath));
    final r = await repo.resolve('k', legacyText: 'पानी');
    expect(r.health, StoreHealth.unreadable);
    expect(r.resolved.text, 'पानी');
    expect(r.resolved.problem, 'store_unreadable');
  });

  test('branched supersession resolves to nothing, not to a guess', () async {
    final r = await resolveWith(
      [row(1, 'एक'), row(2, 'दुई', supersedes: 1), row(3, 'तीन', supersedes: 1)],
      legacy: 'एक',
    );
    expect(r.integrityOk, isFalse);
    expect(r.resolved.visible, isFalse);
    expect(r.resolved.problem, 'broken_supersession');
  });

  test('a supersession cycle resolves to nothing', () async {
    final r = await resolveWith(
      [row(1, 'एक', supersedes: 2), row(2, 'दुई', supersedes: 1)],
      legacy: 'एक',
    );
    expect(r.integrityOk, isFalse);
    expect(r.resolved.visible, isFalse);
  });

  test('cross-sense supersession is refused', () async {
    final r = await resolveWith(
      [row(1, 'एक', senseKey: 'a'), row(2, 'दुई', senseKey: 'b', supersedes: 1)],
      legacy: 'एक',
      key: 'b',
    );
    expect(r.integrityOk, isFalse);
    expect(r.resolved.problem, 'broken_supersession');
  });

  test('the real store resolves an imported legacy sense without duplicates', () async {
    if (!File(storePath).existsSync() || !File(dictPath).existsSync()) {
      markTestSkipped('built databases are not on this machine');
      return;
    }
    final dict = await databaseFactory.openDatabase(
      dictPath,
      options: OpenDatabaseOptions(readOnly: true, singleInstance: false),
    );
    final rows = await dict.rawQuery('''
      SELECT e.simplified, e.pinyin_plain, s.gloss_en, s.gloss_ne
      FROM senses s JOIN entries e ON e.entry_id = s.entry_id
      WHERE s.ne_status = 'ai_translated' AND TRIM(COALESCE(s.gloss_ne,'')) <> ''
      ORDER BY s.sense_id LIMIT 1
    ''');
    await dict.close();
    final first = rows.first;
    final key = UserStore.senseKey(
      wordZh: first['simplified'] as String,
      pinyin: first['pinyin_plain'] as String,
      glossEn: first['gloss_en'] as String,
    );
    final legacy = first['gloss_ne'] as String;

    final store = SqliteTranslationStore(storePath);
    expect(await store.health(), StoreHealth.ok, reason: 'real store must open at schema 3');
    final repo = LocalTranslationRepository(store);
    final resolved = await repo.resolve(key, legacyText: legacy);
    await store.close();

    expect(resolved.resolved.text, legacy, reason: 'one meaning, the original text');
    expect(resolved.resolved.source, NepaliSource.dictionary);
    expect(resolved.resolved.status.code, TranslationStatus.aiUnverified);
    expect(resolved.resolved.status.label, 'AI-translated, unverified');
    expect(resolved.health, StoreHealth.ok);
  });
}
