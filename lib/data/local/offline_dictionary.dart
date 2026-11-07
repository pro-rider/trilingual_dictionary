import 'dart:async';
import 'dart:io';
import 'dart:isolate';

import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

import '../../core/normalizer.dart';
import '../models/dictionary_entry.dart';
import '../models/sense.dart';

/// The full 123,672-entry dictionary, shipped inside the APK as a gzipped
/// SQLite file and unpacked once into the app's support directory.
///
/// First launch: 42.5 MB asset → 96 MB database on disk (a few seconds, run in
/// a background isolate). After that, every word in the merged CC-CEDICT
/// dictionary — including the 2,477 HSK5-tagged entries and their Nepali
/// glosses — is searchable with no network and no backend.
class OfflineDictionary {
  static const String assetPath = 'assets/data/dictionary.sqlite.gz';
  static const String fileName = 'dictionary.sqlite';

  /// Test/desktop hook: open an existing database file instead of unpacking
  /// the bundled asset through path_provider.
  final String? overridePath;

  Database? _db;
  Future<Database?>? _opening;
  Object? _lastError;

  OfflineDictionary({this.overridePath});

  /// Whether the on-disk database already exists (no import needed).
  Future<bool> get isInstalled async {
    final f = await _dbFile();
    return f.existsSync();
  }

  Object? get lastError => _lastError;

  Future<void> installIfNeeded() async {
    await _open();
  }

  Future<Database?> _open() {
    return _opening ??= _openInner();
  }

  Future<Database?> _openInner() async {
    try {
      final file = await _dbFile();
      if (!file.existsSync()) {
        await _install(file);
      }
      _db = await openDatabase(file.path, readOnly: true);
      return _db;
    } catch (e) {
      _lastError = e;
      _opening = null;
      return null;
    }
  }

  Future<File> _dbFile() async {
    final override = overridePath;
    if (override != null) return File(override);
    final dir = await getApplicationSupportDirectory();
    await dir.create(recursive: true);
    return File(p.join(dir.path, fileName));
  }

  /// Decompress the bundled asset into the app directory.
  Future<void> _install(File target) async {
    final data = await rootBundle.load(assetPath);
    final bytes = data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes);

    // Decompression of 96 MB is CPU-bound: keep it off the UI isolate.
    final unpacked = await Isolate.run(() => _gunzip(bytes));

    final tmp = File('${target.path}.part');
    await tmp.writeAsBytes(unpacked, flush: true);
    await tmp.rename(target.path);
  }

  static Uint8List _gunzip(Uint8List bytes) {
    // dart:io's codec is available on Android/iOS/desktop; the web build never
    // reaches this class because sqflite is unavailable there.
    return Uint8List.fromList(gzip.decode(bytes));
  }

  Future<DictionaryEntry?> search(String query, InputLanguage lang) async {
    final db = await _open();
    if (db == null) return null;
    final q = query.trim();
    if (q.isEmpty) return null;
    final qLower = q.toLowerCase();

    Map<String, Object?>? row;
    if (lang == InputLanguage.chinese) {
      row = await _first(db,
          'SELECT * FROM entries WHERE simplified = ? '
          'ORDER BY LENGTH(simplified) LIMIT 1', [q]);
      row ??= await _first(db,
          'SELECT * FROM entries WHERE traditional = ? '
          'ORDER BY LENGTH(simplified) LIMIT 1', [q]);
      row ??= await _first(db,
          'SELECT * FROM entries WHERE simplified LIKE ? '
          'ORDER BY LENGTH(simplified) LIMIT 1', ['$q%']);
    } else {
      for (final candidate in _pinyinVariants(qLower).take(2)) {
        row = await _first(db,
            'SELECT * FROM entries WHERE pinyin_plain = ? '
            'ORDER BY is_proper, LENGTH(simplified) LIMIT 1', [candidate]);
        if (row != null) break;
      }
      row ??= await _first(
        db,
        "SELECT e.*, "
        " CASE WHEN LOWER(TRIM(s.gloss_en)) IN (?, ?, ?, ?) THEN 3 "
        "      WHEN LOWER(s.gloss_en) LIKE ? || ' %' "
        "        OR LOWER(s.gloss_en) LIKE 'to ' || ? || '%' "
        "        OR LOWER(s.gloss_en) LIKE ? || ',%' THEN 2 "
        "      WHEN LOWER(s.gloss_en) LIKE '% ' || ? || ' %' "
        "        OR LOWER(s.gloss_en) LIKE '% ' || ? THEN 1 "
        "      ELSE 0 END AS match_score "
        "FROM senses s JOIN entries e ON e.entry_id = s.entry_id "
        "WHERE LOWER(s.gloss_en) LIKE '%' || ? || '%' AND e.is_proper = 0 "
        "ORDER BY match_score DESC, s.sense_order, "
        "         (e.hsk_level IS NOT NULL) DESC, LENGTH(s.gloss_en), e.entry_id "
        "LIMIT 1",
        [qLower, 'to $qLower', 'a $qLower', 'the $qLower',
         qLower, qLower, qLower, qLower, qLower, qLower],
      );
    }

    if (row == null) return null;
    final entryId = row['entry_id'] as int;
    final senses = await db.query(
      'senses',
      where: 'entry_id = ?',
      whereArgs: [entryId],
      orderBy: 'sense_order',
    );
    return _toEntry(row, senses);
  }

  Future<Map<String, Object?>?> _first(Database db, String sql, List<Object?> args) async {
    final rows = await db.rawQuery(sql, args);
    return rows.isEmpty ? null : rows.first;
  }

  DictionaryEntry _toEntry(
      Map<String, Object?> row, List<Map<String, Object?>> senses) {
    final entryId = 'zh${row['entry_id']}';
    final simplified = (row['simplified'] as String?) ?? '';
    final pinyin = (row['pinyin_marked'] as String?) ?? '';
    final senseModels = senses.map((s) {
      final gloss = (s['gloss_en'] as String?) ?? '';
      return Sense(
        id: '$entryId:${s['sense_order']}',
        wordEn: _shortGloss(gloss),
        wordZh: simplified,
        pinyin: pinyin,
        ipaEn: '',
        pos: '',
        meaningEn: gloss,
        meaningZh: (s['gloss_zh'] as String?) ?? '',
        meaningNe: (s['gloss_ne'] as String?) ?? '',
        meaningNeStatus:
            (s['ne_status'] as String?) == 'reviewed' ? 'published' : 'pending',
        examples: const [],
      );
    }).toList();

    final first = senseModels.isEmpty ? null : senseModels.first;
    return DictionaryEntry(
      entryId: entryId,
      wordEn: first?.wordEn ?? '',
      wordZh: simplified,
      source: 'offline-db',
      senses: senseModels,
    );
  }

  static String _shortGloss(String gloss) {
    final cut = gloss.split(RegExp(r'[;,(]')).first.trim();
    return cut.isEmpty ? gloss : cut;
  }

  /// Same tone-less pinyin forms the backend accepts: "ni hao" → "nihao",
  /// ü written as v.
  static Iterable<String> _pinyinVariants(String q) sync* {
    final flat = q.replaceAll(RegExp(r"[\s'\-]"), '');
    if (flat.isNotEmpty) yield flat;
    final underscored = q.replaceAll(' ', '_');
    if (underscored != flat) yield underscored;
  }

  Future<void> close() async {
    await _db?.close();
    _db = null;
    _opening = null;
  }
}
