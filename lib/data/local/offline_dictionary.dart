import 'dart:async';
import 'dart:io';
import 'dart:isolate';

import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

import '../../core/normalizer.dart';
import '../api_client.dart';
import '../models/dictionary_entry.dart';
import '../models/example_sentence.dart';
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

  /// Bump this whenever `assets/data/dictionary.sqlite.gz` is rebuilt. The
  /// phone keeps its own copy of the database (it writes Nepali glosses and
  /// example sentences into it), so a plain "file exists" check would silently
  /// keep serving the old words forever.
  static const String assetVersion = '2026-11-08.3';

  /// Test/desktop hook: open an existing database file instead of unpacking
  /// the bundled asset through path_provider.
  final String? overridePath;

  Database? _db;
  Future<Database?>? _opening;
  Object? _lastError;

  OfflineDictionary({this.overridePath});

  /// Whether the on-disk database is present and current (no import needed).
  Future<bool> get isInstalled async {
    final f = await _dbFile();
    return _isCurrentVersion(f);
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
      if (!(await _isCurrentVersion(file))) {
        // Stale or missing copy: replace it with the version shipped in the
        // APK. Any enrichment done against the old file is re-fetched on the
        // next online lookup.
        if (file.existsSync()) {
          try {
            file.deleteSync();
          } catch (_) {}
        }
        await _install(file);
      }
      _db = await openDatabase(file.path);
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
    await _stamp(target).writeAsString(assetVersion, flush: true);
  }

  /// Sidecar file recording which asset build this database came from.
  File _stamp(File dbFile) => File('${dbFile.path}.stamp');

  /// True when the on-disk database exists and matches the packaged build.
  Future<bool> _isCurrentVersion(File file) async {
    if (overridePath != null) return file.existsSync();
    if (!file.existsSync()) return false;
    final stamp = _stamp(file);
    if (!stamp.existsSync()) return false;
    try {
      return stamp.readAsStringSync().trim() == assetVersion;
    } catch (_) {
      return false;
    }
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
      // English gloss: score every candidate in Dart. A plain "shortest match
      // wins" rule (and excluding proper nouns) is what made "Nepal" return the
      // bird "Nepal fulvetta" instead of 尼泊尔 and "China" return 东土 instead
      // of 中国. Same rules as backend/app/services/sqlite_dataset.py.
      row ??= await _bestEnglishRow(db, qLower);
    }

    if (row == null) return null;
    return _toEntry(db, row);
  }

  Future<Map<String, Object?>?> _bestEnglishRow(Database db, String qLower) async {
    final queries = _englishQueries(qLower);
    Map<String, Object?>? best;
    List<int>? bestKey;
    for (final query in queries) {
      // Order by frequency *before* the LIMIT: with an unordered LIMIT the
      // commonest headword (水 for "water") could be cut off entirely and a
      // rare entry answered instead.
      final rows = await db.rawQuery(
        'SELECT e.*, s.gloss_en, s.sense_order '
        'FROM senses s JOIN entries e ON e.entry_id = s.entry_id '
        "WHERE LOWER(s.gloss_en) LIKE '%' || ? || '%' "
        'ORDER BY e.freq_rank IS NULL, e.freq_rank, LENGTH(s.gloss_en) LIMIT 400',
        [query],
      );
      for (final row in rows) {
        final gloss = (row['gloss_en'] as String?) ?? '';
        final score = _glossScore(gloss, queries);
        if (score < 40) continue;
        // Rank the way a learner expects. Score first, but banded so usage can
        // decide between "the definition IS this word" (100) and "this word is
        // one of its definitions" (85). Then the sense number — surname and
        // abbreviation senses were demoted to the end of each entry
        // (backend/tools/reorder_senses.py), so sense 0 is the real meaning.
        // Then how often the word is really used (wordfreq: 水 #653 beats 四大
        // #4,622; 书 #539 beats 册 #4,264; 行为 #476 beats 品行 #35,279).
        // `is_proper` is deliberately NOT used: the build flags a whole entry
        // when any sense is a name (水 carries a surname sense).
        final freq = row['freq_rank'] as int?;
        final key = <int>[
          _scoreTier(score),
          (row['sense_order'] as int?) ?? 0,
          freq == null ? 1 : 0,
          freq ?? 0,
          gloss.length,
          ((row['simplified'] as String?) ?? '').length,
          (row['entry_id'] as int?) ?? 0,
        ];
        if (best == null || _compareKeys(key, bestKey!) < 0) {
          best = row;
          bestKey = key;
        }
      }
    }
    return best;
  }

  /// Collapse the raw score into a band so frequency can decide between
  /// "the definition IS this word" (100) and "this word is one of the
  /// definitions" (85). Without this, "behaviors" picks 品行 (glossed exactly
  /// "behavior") over the word people actually mean, 行为.
  static int _scoreTier(int score) {
    if (score >= 85) return 0;
    if (score >= 75) return 1;
    if (score >= 60) return 2;
    return 3;
  }

  static int _compareKeys(List<int> a, List<int> b) {
    for (var i = 0; i < a.length; i++) {
      final diff = a[i] - b[i];
      if (diff != 0) return diff;
    }
    return 0;
  }

  /// Typed forms to try: the word itself plus its singular / plural.
  static List<String> _englishQueries(String raw) {
    final q = raw.trim().toLowerCase();
    final out = <String>[q];
    if (q.endsWith('es') && q.length > 4) out.add(q.substring(0, q.length - 2));
    if (q.endsWith('s') && q.length > 3) {
      out.add(q.substring(0, q.length - 1));
    } else if (q.length >= 3) {
      out.add('${q}s');
    }
    return out.where((v) => v.isNotEmpty).toSet().toList();
  }

  static const List<String> _articles = ['to ', 'a ', 'an ', 'the '];

  static String _stripArticle(String piece) {
    var p = piece.trim().toLowerCase();
    for (final art in _articles) {
      if (p.startsWith(art)) return p.substring(art.length).trim();
    }
    return p;
  }

  /// How well an English gloss defines the typed word.
  ///
  /// Only the definition part (before the first bracket) counts, so
  /// "(bird species of China) Nepal fulvetta" cannot answer "Nepal":
  ///  100 a segment IS the word   90 a segment starts with it
  ///   60 the word ends a segment  40 whole word somewhere in the definition
  ///    0 no defensible match → return nothing, never a guess
  static int _glossScore(String gloss, List<String> queries) {
    final text = gloss.trim().toLowerCase();
    final definition = text.split('(').first;
    final segments = definition
        .split(RegExp(r'[;,/]'))
        .where((s) => s.trim().isNotEmpty)
        .toList();
    var best = 0;
    for (var idx = 0; idx < segments.length; idx++) {
      final piece = _stripArticle(segments[idx]);
      for (final q in queries) {
        if (piece == q) return idx == 0 ? 100 : 85;
        // A longer phrase that merely starts with the query is only a weak
        // hit: "middle age" is not a definition of "middle".
        if (piece.startsWith('$q ') || piece.startsWith("$q's")) {
          if (best < 60) best = 60;
        } else if (piece.endsWith(' $q')) {
          if (best < 60) best = 60;
        }
      }
    }
    if (best > 0) return best;
    for (final q in queries) {
      if (RegExp('[^a-z]${RegExp.escape(q)}[^a-z]').hasMatch(' $definition ')) {
        return 40;
      }
    }
    return 0;
  }

  Future<Map<String, Object?>?> _first(Database db, String sql, List<Object?> args) async {
    final rows = await db.rawQuery(sql, args);
    return rows.isEmpty ? null : rows.first;
  }

  Future<DictionaryEntry> _toEntry(
      Database db, Map<String, Object?> row) async {
    final entryId = 'zh${row['entry_id']}';
    final entryPk = row['entry_id'] as int;
    final simplified = (row['simplified'] as String?) ?? '';
    final pinyin = (row['pinyin_marked'] as String?) ?? '';
    final rows = await db.query('senses',
        where: 'entry_id = ?', whereArgs: [entryPk], orderBy: 'sense_order');
    final senseIds = rows
        .map((s) => (s['sense_id'] as int?) ?? -1)
        .where((id) => id >= 0)
        .toList();
    final exampleRows = senseIds.isEmpty
        ? const <Map<String, Object?>>[]
        : await db.query('examples',
            where: 'sense_id IN (${List.filled(senseIds.length, '?').join(',')})',
            whereArgs: senseIds);

    final examplesBySense = <int, List<ExampleSentence>>{};
    for (final ex in exampleRows) {
      final en = (ex['en'] as String?) ?? '';
      if (en.isEmpty) continue;
      examplesBySense
          .putIfAbsent((ex['sense_id'] as int?) ?? -1, () => [])
          .add(ExampleSentence(
            en: en,
            zh: (ex['zh'] as String?) ?? '',
            ne: (ex['ne'] as String?) ?? '',
            source: 'ai_draft',
            reviewStatus: 'approved',
          ));
    }

    final senseModels = rows.map((s) {
      final gloss = (s['gloss_en'] as String?) ?? '';
      // CC-CEDICT ships no Chinese gloss; the pink 中文 box used to render
      // empty. The headword itself is what a Chinese reader wants there.
      final zh = ((s['gloss_zh'] as String?) ?? '').trim();
      return Sense(
        id: '$entryId:${s['sense_order']}',
        wordEn: _shortGloss(gloss),
        wordZh: simplified,
        pinyin: pinyin,
        ipaEn: '',
        pos: '',
        meaningEn: gloss,
        meaningZh: zh.isEmpty ? simplified : zh,
        meaningNe: (s['gloss_ne'] as String?) ?? '',
        meaningNeStatus:
            (s['ne_status'] as String?) == 'reviewed' ? 'published' : 'pending',
        examples: examplesBySense[(s['sense_id'] as int?) ?? -1] ?? const [],
      );
    }).toList();

    final first = senseModels.isEmpty ? null : senseModels.first;
    // For an English lookup, show the sense that actually matched first: "apple"
    // used to open on 苹果's sense 0 "Apple (American tech company)".
    final matchedOrder = row['sense_order'];
    if (matchedOrder != null && senseModels.length > 1) {
      final at = rows.indexWhere((s) => s['sense_order'] == matchedOrder);
      if (at > 0) {
        final moved = senseModels.removeAt(at);
        senseModels.insert(0, moved);
      }
    }
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

  /// Fill this entry's missing Nepali glosses and example sentences from the
  /// backend and persist them in the on-device database.
  ///
  /// Only the senses that are actually empty are sent, so a repeat lookup
  /// costs nothing and works offline afterwards.
  Future<DictionaryEntry> enrich(DictionaryEntry entry, ApiClient api) async {
    final db = await _open();
    if (db == null) return entry;
    final pk = int.tryParse(entry.entryId.replaceFirst('zh', ''));
    if (pk == null) return entry;

    final rows = await db.query('senses',
        where: 'entry_id = ?', whereArgs: [pk], orderBy: 'sense_order');
    if (rows.isEmpty) return entry;

    final senseIds = rows.map((r) => r['sense_id'] as int).toList();
    final exampleRows = await db.query('examples',
        where: 'sense_id IN (${List.filled(senseIds.length, '?').join(',')})',
        whereArgs: senseIds);
    final withExample = exampleRows.map((r) => r['sense_id'] as int).toSet();

    final items = <MapEntry<String, String>>[];
    for (final row in rows) {
      final sid = row['sense_id'] as int;
      final ne = ((row['gloss_ne'] as String?) ?? '').trim();
      final needs = ne.isEmpty || !withExample.contains(sid);
      if (!needs) continue;
      items.add(MapEntry('s$sid',
          '${entry.wordZh}\u0001${(row['gloss_en'] as String?) ?? ''}'));
    }
    if (items.isEmpty) return entry;

    final payload = await api.enrich(items);
    if (payload.isEmpty) return entry;

    for (final item in items) {
      final sid = int.tryParse(item.key.substring(1));
      final data = payload[item.key];
      if (sid == null || data == null) continue;
      final ne = (data['ne'] ?? '').trim();
      if (ne.isNotEmpty) {
        await db.update('senses', {'gloss_ne': ne, 'ne_status': 'ai_translated'},
            where: 'sense_id = ?', whereArgs: [sid]);
      }
      final exampleEn = (data['example_en'] ?? '').trim();
      if (exampleEn.isNotEmpty && !withExample.contains(sid)) {
        await db.insert('examples', {
          'sense_id': sid,
          'en': exampleEn,
          'zh': data['example_zh'] ?? '',
          'ne': data['example_ne'] ?? '',
        });
        withExample.add(sid);
      }
    }
    return _toEntry(db, {
      'entry_id': pk,
      'simplified': entry.wordZh,
      'pinyin_marked': entry.senses.isEmpty ? '' : entry.senses.first.pinyin,
    });
  }

  Future<void> close() async {
    await _db?.close();
    _db = null;
    _opening = null;
  }
}
