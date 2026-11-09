import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

/// One AI-filled Nepali gloss (or Chinese gloss) held in the user database.
class AiGloss {
  const AiGloss({
    required this.senseKey,
    required this.ne,
    required this.zh,
    required this.status,
    required this.model,
    required this.createdAt,
  });

  final String senseKey;
  final String ne;
  final String zh;
  final String status;
  final String model;
  final int createdAt;

  bool get isEmpty => ne.isEmpty && zh.isEmpty;
}

/// One AI-written example sentence.
class AiExample {
  const AiExample({
    required this.senseKey,
    required this.en,
    required this.zh,
    required this.ne,
    required this.status,
    required this.createdAt,
  });

  final String senseKey;
  final String en;
  final String zh;
  final String ne;
  final String status;
  final int createdAt;
}

/// Everything the user owns, kept in a database the dictionary never touches.
///
/// The dictionary database (`dictionary.sqlite`) is *replaced* on every
/// `assetVersion` bump — anything written into it dies with the old file. That
/// used to include AI-translated Nepali glosses and AI example sentences fetched
/// with the user's own API quota. This store is a sibling file (`user.db`) that
/// survives every dictionary update, and every row is keyed by a **stable key**
/// built from the headword, pinyin and English gloss — never by a row id that a
/// rebuild can renumber.
///
/// Schema (versioned, migrations are always preceded by a file backup):
///
/// * `ai_glosses(sense_key PK, gloss_ne, gloss_zh, status, model, created_at)`
/// * `ai_examples(sense_key PK, en, zh, ne, status, created_at)`
/// * `favorites(key PK, entry_id, word_zh, gloss_en, created_at)`
/// * `prefs(key PK, value)`
/// * `id_remap(old_id PK, new_key, reason, created_at)`
/// * `migrations(id PK, applied_at)`
class UserStore {
  UserStore({this.overridePath});

  static const String fileName = 'user.db';
  static const int schemaVersion = 1;

  /// Separator that cannot occur in a headword or gloss.
  static const String keySeparator = '\u001f';

  /// Test/desktop hook: use this path instead of the app support directory.
  final String? overridePath;

  Database? _db;
  Future<Database?>? _opening;

  /// The stable identity of a sense. Independent of entry ids, so a rebuilt
  /// dictionary that renumbers rows cannot break a saved favourite or an AI
  /// gloss.
  static String senseKey({
    required String wordZh,
    required String pinyin,
    required String glossEn,
  }) {
    final zh = wordZh.trim();
    final py = pinyin.trim().toLowerCase();
    final en = glossEn.trim().toLowerCase();
    return '$zh$keySeparator$py$keySeparator$en';
  }

  Future<Database?> open() => _opening ??= _openInner();

  Future<Database?> _openInner() async {
    try {
      final file = await _file();
      await file.parent.create(recursive: true);
      final existed = file.existsSync();
      final db = await openDatabase(file.path);
      final version = Sqflite.firstIntValue(
            await db.rawQuery('PRAGMA user_version'),
          ) ??
          0;
      if (!existed) {
        await _createSchema(db);
        await db.execute('PRAGMA user_version = $schemaVersion');
      } else if (version < schemaVersion) {
        // An older install (including a legacy file that never had a version
        // stamp): copy it first, so a failed migration is always reversible.
        await backup();
        await _migrate(db, from: version);
        await db.execute('PRAGMA user_version = $schemaVersion');
      }
      _db = db;
      return db;
    } catch (_) {
      _opening = null;
      return null;
    }
  }

  Future<File> _file() async {
    final override = overridePath;
    if (override != null) return File(override);
    final dir = await getApplicationSupportDirectory();
    return File(p.join(dir.path, fileName));
  }

  Future<void> _createSchema(Database db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS ai_glosses (
        sense_key TEXT PRIMARY KEY,
        gloss_ne TEXT NOT NULL DEFAULT '',
        gloss_zh TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'ai_translated',
        model TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL
      )
    ''');
    await db.execute('''
      CREATE TABLE IF NOT EXISTS ai_examples (
        sense_key TEXT PRIMARY KEY,
        en TEXT NOT NULL,
        zh TEXT NOT NULL DEFAULT '',
        ne TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'ai_generated',
        created_at INTEGER NOT NULL
      )
    ''');
    await db.execute('''
      CREATE TABLE IF NOT EXISTS favorites (
        key TEXT PRIMARY KEY,
        entry_id TEXT NOT NULL DEFAULT '',
        word_zh TEXT NOT NULL DEFAULT '',
        gloss_en TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL
      )
    ''');
    await db.execute('''
      CREATE TABLE IF NOT EXISTS prefs (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      )
    ''');
    await db.execute('''
      CREATE TABLE IF NOT EXISTS id_remap (
        old_id TEXT PRIMARY KEY,
        new_key TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL
      )
    ''');
    await db.execute('''
      CREATE TABLE IF NOT EXISTS migrations (
        id TEXT PRIMARY KEY,
        applied_at INTEGER NOT NULL
      )
    ''');
  }

  Future<void> _migrate(Database db, {required int from}) async {
    // v1 is the baseline. Future versions add their steps here, each recorded
    // in `migrations` so a re-run is a no-op.
    if (from < 1) {
      await _createSchema(db);
    }
  }

  /// Copy the database beside itself. Returns the backup path, or null when
  /// there was nothing to copy.
  Future<String?> backup() async {
    final file = await _file();
    if (!file.existsSync()) return null;
    final stamp = DateTime.now().toUtc().toIso8601String().replaceAll(':', '-');
    final target = File('${file.path}.bak-$stamp');
    await file.copy(target.path);
    return target.path;
  }

  // ---------------------------------------------------------------- AI glosses

  Future<AiGloss?> aiGloss(String senseKey) async {
    final db = await open();
    if (db == null) return null;
    final rows = await db.query('ai_glosses',
        where: 'sense_key = ?', whereArgs: [senseKey], limit: 1);
    if (rows.isEmpty) return null;
    final r = rows.first;
    return AiGloss(
      senseKey: senseKey,
      ne: (r['gloss_ne'] as String?) ?? '',
      zh: (r['gloss_zh'] as String?) ?? '',
      status: (r['status'] as String?) ?? 'ai_translated',
      model: (r['model'] as String?) ?? '',
      createdAt: (r['created_at'] as int?) ?? 0,
    );
  }

  /// Batch read — one query for a whole entry instead of one per sense.
  Future<Map<String, AiGloss>> aiGlosses(Iterable<String> keys) async {
    if (keys.isEmpty) return const {};
    final db = await open();
    if (db == null) return const {};
    final placeholders = List.filled(keys.length, '?').join(',');
    final rows = await db.query('ai_glosses',
        where: 'sense_key IN ($placeholders)', whereArgs: keys.toList());
    return {
      for (final r in rows)
        (r['sense_key'] as String): AiGloss(
          senseKey: r['sense_key'] as String,
          ne: (r['gloss_ne'] as String?) ?? '',
          zh: (r['gloss_zh'] as String?) ?? '',
          status: (r['status'] as String?) ?? 'ai_translated',
          model: (r['model'] as String?) ?? '',
          createdAt: (r['created_at'] as int?) ?? 0,
        ),
    };
  }

  Future<void> putAiGloss(
    String senseKey, {
    String ne = '',
    String zh = '',
    String status = 'ai_translated',
    String model = '',
  }) async {
    final db = await open();
    if (db == null) return;
    await db.insert(
      'ai_glosses',
      {
        'sense_key': senseKey,
        'gloss_ne': ne,
        'gloss_zh': zh,
        'status': status,
        'model': model,
        'created_at': DateTime.now().toUtc().millisecondsSinceEpoch,
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  // --------------------------------------------------------------- AI examples

  Future<Map<String, AiExample>> aiExamples(Iterable<String> keys) async {
    if (keys.isEmpty) return const {};
    final db = await open();
    if (db == null) return const {};
    final placeholders = List.filled(keys.length, '?').join(',');
    final rows = await db.query('ai_examples',
        where: 'sense_key IN ($placeholders)', whereArgs: keys.toList());
    return {
      for (final r in rows)
        (r['sense_key'] as String): AiExample(
          senseKey: r['sense_key'] as String,
          en: (r['en'] as String?) ?? '',
          zh: (r['zh'] as String?) ?? '',
          ne: (r['ne'] as String?) ?? '',
          status: (r['status'] as String?) ?? 'ai_generated',
          createdAt: (r['created_at'] as int?) ?? 0,
        ),
    };
  }

  Future<void> putAiExample(
    String senseKey, {
    required String en,
    String zh = '',
    String ne = '',
    String status = 'ai_generated',
  }) async {
    if (en.trim().isEmpty) return;
    final db = await open();
    if (db == null) return;
    await db.insert(
      'ai_examples',
      {
        'sense_key': senseKey,
        'en': en,
        'zh': zh,
        'ne': ne,
        'status': status,
        'created_at': DateTime.now().toUtc().millisecondsSinceEpoch,
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  // ------------------------------------------------------------ export / import

  /// Everything the user owns, as JSON a person could keep or move to another
  /// phone. Never includes dictionary content.
  Future<Map<String, Object?>> exportData() async {
    final db = await open();
    if (db == null) return {'version': schemaVersion, 'tables': {}};
    final tables = <String, Object?>{};
    for (final t in _ownedTables) {
      tables[t] = await db.query(t);
    }
    return {
      'version': schemaVersion,
      'exported_at': DateTime.now().toUtc().toIso8601String(),
      'tables': tables,
    };
  }

  Future<String> exportJson() async => const JsonEncoder.withIndent('  ')
      .convert(await exportData());

  static const List<String> _ownedTables = [
    'ai_glosses',
    'ai_examples',
    'favorites',
    'prefs',
    'id_remap',
  ];

  /// Merge an export back in. Rows already on the device win when they are
  /// newer, so importing an old file cannot roll back fresher AI results.
  Future<int> importJson(String json) async {
    final Map<String, Object?> data;
    try {
      data = jsonDecode(json) as Map<String, Object?>;
    } catch (_) {
      return 0;
    }
    final db = await open();
    if (db == null) return 0;
    final tables = data['tables'];
    if (tables is! Map) return 0;

    var count = 0;
    for (final entry in tables.entries) {
      final name = entry.key.toString();
      if (!_ownedTables.contains(name)) continue;
      final rows = entry.value;
      if (rows is! List) continue;
      for (final raw in rows) {
        if (raw is! Map) continue;
        final row = raw.map((k, v) => MapEntry(k.toString(), v));
        final incoming = (row['created_at'] as int?) ?? 0;
        if (name == 'ai_glosses' || name == 'ai_examples') {
          final existing = await db.query(name,
              where: 'sense_key = ?',
              whereArgs: [row['sense_key']],
              limit: 1);
          final mine = existing.isEmpty
              ? -1
              : ((existing.first['created_at'] as int?) ?? 0);
          if (existing.isNotEmpty && mine >= incoming) continue;
        }
        await db.insert(
          name,
          row,
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
        count++;
      }
    }
    return count;
  }

  Future<void> close() async {
    await _db?.close();
    _db = null;
    _opening = null;
  }
}
