import 'dart:io';

import 'package:sqflite/sqflite.dart';

import '../../core/translation_resolution.dart';
import '../../core/translation_status.dart';

/// What the governance store looked like when we opened it. Resolution never
/// throws on a bad store: it reports the reason and the app falls back to the
/// original dictionary value.
enum StoreHealth { ok, missing, unreadable, schemaMismatch }

/// Where translation candidates come from. Read-only from the app's point of
/// view: the shipped dictionary is never written and the governance store is
/// only ever read.
abstract class TranslationStore {
  /// Rows of `translations` for this sense, any order.
  Future<List<TranslationCandidate>> rowsFor(String senseKey);

  /// The original value shipped in `dictionary.sqlite.senses.gloss_ne`, when the
  /// store is the one answering that question. The dictionary normally supplies
  /// it; this exists so a store can be self-contained in tests.
  Future<String?> legacyTextFor(String senseKey);

  Future<StoreHealth> health();
}

/// Reads `translations.db` with an explicit schema check.
///
/// Fail-closed rules: a missing file is `missing`, a schema other than the
/// supported one is `schemaMismatch`, and anything the SQLite layer refuses is
/// `unreadable`. In all three cases the repository shows the dictionary value
/// and never invents a label.
class SqliteTranslationStore implements TranslationStore {
  SqliteTranslationStore(this.path, {this.expectedSchema = 4});

  final String path;
  final int expectedSchema;

  Database? _db;
  StoreHealth _health = StoreHealth.missing;

  @override
  Future<StoreHealth> health() async {
    await _open();
    return _health;
  }

  Future<void> _open() async {
    if (_db != null) return;
    if (!File(path).existsSync()) {
      _health = StoreHealth.missing;
      return;
    }
    try {
      _db = await databaseFactory.openDatabase(
        path,
        options: OpenDatabaseOptions(readOnly: true, singleInstance: false),
      );
      final version = (await _db!.rawQuery('PRAGMA user_version')).first.values.first as int?;
      if (version != expectedSchema) {
        _health = StoreHealth.schemaMismatch;
        await _db!.close();
        _db = null;
        return;
      }
      // A truncated or encrypted file opens lazily in SQLite; force a read.
      await _db!.rawQuery('SELECT count(*) FROM translations LIMIT 1');
      _health = StoreHealth.ok;
    } catch (_) {
      _health = StoreHealth.unreadable;
      try {
        await _db?.close();
      } catch (_) {}
      _db = null;
    }
  }

  @override
  Future<List<TranslationCandidate>> rowsFor(String senseKey) async {
    await _open();
    if (_health != StoreHealth.ok || _db == null) return const [];
    final rows = await _db!.query(
      'translations',
      where: 'sense_key = ? AND language = ?',
      whereArgs: [senseKey, 'ne'],
      orderBy: 'translation_id',
    );
    return rows.map((m) => TranslationCandidate.fromMap(Map<String, dynamic>.from(m))).toList();
  }

  @override
  Future<String?> legacyTextFor(String senseKey) async => null;

  Future<void> close() async {
    await _db?.close();
    _db = null;
  }
}

/// In-memory store used by tests and by the offline fallback.
class InMemoryTranslationStore implements TranslationStore {
  InMemoryTranslationStore({
    Map<String, List<TranslationCandidate>>? rows,
    Map<String, String>? legacy,
    StoreHealth healthy = StoreHealth.ok,
  })  : _rows = rows ?? <String, List<TranslationCandidate>>{},
        _legacy = legacy ?? <String, String>{},
        _health = healthy;

  final Map<String, List<TranslationCandidate>> _rows;
  final Map<String, String> _legacy;
  final StoreHealth _health;

  @override
  Future<List<TranslationCandidate>> rowsFor(String senseKey) async =>
      List<TranslationCandidate>.from(_rows[senseKey] ?? const []);

  @override
  Future<String?> legacyTextFor(String senseKey) async => _legacy[senseKey];

  @override
  Future<StoreHealth> health() async => _health;
}

/// The one Nepali meaning a sense renders, plus why it was chosen.
class SenseTranslation {
  const SenseTranslation({
    required this.resolved,
    required this.health,
    this.translationId,
    this.integrityOk = true,
  });

  final ResolvedNepali resolved;
  final StoreHealth health;
  final int? translationId;
  final bool integrityOk;
}

/// The only place the app decides which Nepali meaning to show.
///
/// Widgets call this and render the result; they must not compare the
/// dictionary value with the governance store themselves. Mirrors
/// `backend/app/translations/resolve.py`.
class LocalTranslationRepository {
  LocalTranslationRepository(this.store);

  final TranslationStore store;

  /// Resolve one sense. `legacyText` is the value the dictionary shipped for
  /// this sense; pass it in so the repository never reaches across files.
  Future<SenseTranslation> resolve(String senseKey, {String? legacyText}) async {
    final health = await store.health();
    if (health != StoreHealth.ok) {
      return SenseTranslation(
        health: health,
        resolved: ResolvedNepali(
          text: (legacyText ?? '').trim(),
          source: NepaliSource.dictionary,
          status: TranslationStatus.derive(),
          visible: (legacyText ?? '').trim().isNotEmpty,
          problem: 'store_${health.name}',
        ),
      );
    }

    final rows = await store.rowsFor(senseKey);
    final integrity = ChainIntegrity.analyze(rows);
    if (!integrity.ok) {
      // Broken supersession data: show nothing rather than pick a meaning.
      return SenseTranslation(
        health: health,
        integrityOk: false,
        resolved: ResolvedNepali(
          text: '',
          source: NepaliSource.none,
          status: TranslationStatus.derive(publicationStatus: 'quarantined'),
          visible: false,
          problem: 'broken_supersession',
        ),
      );
    }

    final superseded = <int>{};
    for (final r in rows) {
      if (r.supersedesId != null) superseded.add(r.supersedesId!);
    }
    final active = rows
        .where((r) => r.translationId == null || !superseded.contains(r.translationId))
        .toList();

    if (active.isEmpty) {
      final legacy = (legacyText ?? await store.legacyTextFor(senseKey) ?? '').trim();
      return SenseTranslation(
        health: health,
        resolved: ResolvedNepali(
          text: legacy,
          source: NepaliSource.dictionary,
          status: TranslationStatus.derive(),
          visible: legacy.isNotEmpty,
        ),
      );
    }

    final chosen = active.length == 1
        ? active.first
        : active.reduce((a, b) => (a.translationId ?? -1) >= (b.translationId ?? -1) ? a : b);
    final status = TranslationStatus.derive(
      publicationStatus: chosen.publicationStatus,
      humanVerification: chosen.humanVerification,
      validationStatus: chosen.validationStatus,
      evidenceStrength: chosen.evidenceStrength,
      generationMethod: chosen.generationMethod,
      originSource: chosen.originSource,
      originMethod: chosen.originMethod,
      evidenceLanguage: chosen.evidenceLanguage,
      senseMatchMethod: chosen.senseMatchMethod,
    );

    return SenseTranslation(
      health: health,
      translationId: chosen.translationId,
      resolved: resolveNepali(
        dictionaryText: legacyText ?? await store.legacyTextFor(senseKey),
        governanceStatus: status,
        governanceText: chosen.text,
        governancePublicationStatus: chosen.publicationStatus,
      ),
    );
  }
}
