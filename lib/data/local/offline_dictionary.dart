import 'dart:async';
import 'dart:io';
import 'dart:isolate';

import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

import '../../core/normalizer.dart';
import '../api_client.dart';
import '../models/analyzed_text.dart';
import '../models/dictionary_entry.dart';
import '../models/example_sentence.dart';
import '../models/sense.dart';
import 'user_store.dart';

/// One approved image for an entry, as stored inside the bundled database.
///
/// `assetPath` points at a WebP thumbnail shipped in the APK (≤15 KB), so the
/// picture renders with no network at all. `remoteUrl` is the high-resolution
/// original, used only when the user asks for it (Issue 12: offline first).
class EntryImage {
  const EntryImage({
    required this.imageId,
    required this.assetPath,
    required this.remoteUrl,
    required this.attribution,
    required this.license,
    required this.matchMethod,
    required this.confidence,
    required this.width,
    required this.height,
  });

  final int imageId;
  final String assetPath;
  final String remoteUrl;
  final String attribution;
  final String license;
  final String matchMethod;
  final double confidence;
  final int width;
  final int height;
}

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
  /// phone keeps its own copy of the database, so a plain "file exists" check
  /// would silently keep serving the old words forever.
  ///
  /// Nothing the user owns is written into this file: AI glosses and AI example
  /// sentences live in [UserStore] (`user.db`), which this replacement never
  /// touches.
  static const String assetVersion = '2026-11-09.3';

  /// Test/desktop hook: open an existing database file instead of unpacking
  /// the bundled asset through path_provider.
  final String? overridePath;

  /// Where AI results and other user-owned rows go. Created on first use.
  UserStore? _store;
  final UserStore? _storeOverride;

  Database? _db;
  Future<Database?>? _opening;
  Object? _lastError;

  OfflineDictionary({this.overridePath, UserStore? userStore})
      : _storeOverride = userStore;

  UserStore get userStore => _store ??= (_storeOverride ?? UserStore());

  /// Stable key for a sense, so saved data survives a rebuilt dictionary.
  static String senseKey({
    required String wordZh,
    required String pinyin,
    required String glossEn,
  }) =>
      UserStore.senseKey(wordZh: wordZh, pinyin: pinyin, glossEn: glossEn);

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
        // APK. AI glosses and examples are in `user.db` (see [UserStore]) and
        // are applied on top of this file, so a swap loses nothing the user
        // paid for.
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

    // AI results live in `user.db`, keyed by the stable sense key, and are
    // overlaid here. They survive every dictionary rebuild.
    final senseKeys = <int, String>{
      for (final s in rows)
        (s['sense_id'] as int? ?? -1): senseKey(
          wordZh: simplified,
          pinyin: pinyin,
          glossEn: (s['gloss_en'] as String?) ?? '',
        ),
    };
    final overlayGlosses = await userStore.aiGlosses(senseKeys.values);
    final overlayExamples = await userStore.aiExamples(senseKeys.values);

    final examplesBySense = <int, List<ExampleSentence>>{};
    for (final ex in exampleRows) {
      final en = (ex['en'] as String?) ?? '';
      final zh = (ex['zh'] as String?) ?? '';
      final ne = (ex['ne'] as String?) ?? '';
      if (en.isEmpty) continue;
      // Never show a sentence we know is wrong: a Korean/Cyrillic fragment in
      // the Chinese line means an import defect, and a Nepali line without
      // Devanagari means the translation never happened. Quarantined rows are
      // dropped outright (Issue: "some sentences should not be shown").
      final status = (ex['review_status'] as String?) ?? '';
      if (status == 'quarantined') continue;
      if (_hasForeignScript(zh) || (ne.isNotEmpty && !_isDevanagari(ne))) {
        continue;
      }
      final trusted = status == 'reviewed' || status == 'imported';
      examplesBySense
          .putIfAbsent((ex['sense_id'] as int?) ?? -1, () => [])
          .add(ExampleSentence(
            en: en,
            zh: zh,
            ne: ne,
            source: trusted ? 'curated' : 'ai_draft',
            reviewStatus: trusted ? 'approved' : 'draft',
          ));
    }

    // A sense with no sentence of its own falls back to the AI one the user
    // already fetched (stored in user.db), labelled honestly.
    for (final e in senseKeys.entries) {
      if (examplesBySense[e.key]?.isNotEmpty ?? false) continue;
      final ai = overlayExamples[e.value];
      if (ai == null || ai.en.trim().isEmpty) continue;
      if (_hasForeignScript(ai.zh) ||
          (ai.ne.isNotEmpty && !_isDevanagari(ai.ne))) {
        continue;
      }
      examplesBySense[e.key] = [
        ExampleSentence(
          en: ai.en,
          zh: ai.zh,
          ne: ai.ne,
          source: 'ai_generated',
          reviewStatus: 'ai_generated',
        ),
      ];
    }

    final senseModels = rows.map((s) {
      final gloss = (s['gloss_en'] as String?) ?? '';
      // CC-CEDICT ships no Chinese gloss; the pink 中文 box used to render
      // empty. The headword itself is what a Chinese reader wants there.
      final dictZh = ((s['gloss_zh'] as String?) ?? '').trim();
      final key = senseKeys[(s['sense_id'] as int?) ?? -1];
      final ai = key == null ? null : overlayGlosses[key];
      final dictNe = ((s['gloss_ne'] as String?) ?? '').trim();
      final effectiveNe = dictNe.isNotEmpty ? dictNe : (ai?.ne ?? '');
      final effectiveZh = dictZh.isNotEmpty ? dictZh : (ai?.zh ?? '');
      final reviewed = (s['ne_status'] as String?) == 'reviewed';
      return Sense(
        id: '$entryId:${s['sense_order']}',
        wordEn: _shortGloss(gloss),
        wordZh: simplified,
        pinyin: pinyin,
        ipaEn: '',
        pos: '',
        meaningEn: gloss,
        meaningZh: effectiveZh.isEmpty ? simplified : effectiveZh,
        meaningNe: effectiveNe,
        meaningNeStatus:
            reviewed ? 'published' : (effectiveNe.isEmpty ? 'missing' : 'pending'),
        meaningNeSource: dictNe.isNotEmpty
            ? 'dictionary'
            : (ai != null && ai.ne.isNotEmpty ? 'ai_translated' : 'none'),
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

  /// Analyse text with the bundled dictionary alone.
  ///
  /// Pasting a paragraph used to open the `Analyze` route, which only the
  /// backend can answer — offline the user got a dead end saying "Analysis
  /// needs the server". The words of that paragraph are all in the 96 MB
  /// database already on the phone, so this walks the text and returns one
  /// segment per unit: a real meaning where the dictionary has it, an honest
  /// "not in the offline dictionary" where it does not.
  ///
  /// `maxUnits` bounds the work a long paste can cause (~0.5 ms per lookup);
  /// anything past it is reported through [AnalyzedText.degraded] instead of
  /// silently dropped.
  Future<AnalyzedText> analyzeOffline(
    String text,
    InputLanguage lang, {
    int maxUnits = 300,
  }) async {
    final db = await _open();
    if (db == null) {
      return AnalyzedText(text: text, error: 'Offline dictionary unavailable');
    }
    final trimmed = text.trim();
    if (trimmed.isEmpty) {
      return const AnalyzedText(error: 'Nothing to analyse');
    }
    final segments = <AnalyzedSegment>[];
    var truncated = false;
    // One paragraph repeats the same handful of words; resolving each one again
    // costs a query. On a 300-unit paste this is the difference between well
    // under a second and half a minute.
    final memo = <String, AnalyzedSegment?>{};
    final started = DateTime.now();

    if (lang == InputLanguage.chinese) {
      // Greedy longest match: Chinese has no spaces, so 中国人 must beat 中 + 国.
      var i = 0;
      while (i < trimmed.length) {
        if (segments.length >= maxUnits) {
          truncated = true;
          break;
        }
        final char = trimmed[i];
        if (_isCjk(char)) {
          var matched = '';
          for (var len = 4; len >= 1; len--) {
            if (i + len > trimmed.length) continue;
            final chunk = trimmed.substring(i, i + len);
            if (!_isAllCjk(chunk)) continue;
            final row = await _exactRow(db, chunk);
            if (row != null) {
              matched = chunk;
              segments.add(await _segmentFor(row, chunk, isChinese: true));
              break;
            }
          }
          if (matched.isNotEmpty) {
            i += matched.length;
            continue;
          }
          segments.add(AnalyzedSegment(surface: char, source: 'unresolved'));
          i += 1;
          continue;
        }
        if (_isPunctuation(char)) {
          segments.add(AnalyzedSegment(
              surface: char, kind: 'punctuation', source: 'dataset'));
        } else if (char.trim().isNotEmpty) {
          segments.add(AnalyzedSegment(surface: char, source: 'unresolved'));
        }
        i += 1;
      }
    } else {
      final tokens = RegExp(r"[A-Za-z][A-Za-z'-]*|[\u4e00-\u9fff]|[^\sA-Za-z\u4e00-\u9fff]")
          .allMatches(trimmed)
          .map((m) => m.group(0)!)
          .toList();
      for (final token in tokens) {
        if (segments.length >= maxUnits) {
          truncated = true;
          break;
        }
        if (_isPunctuation(token)) {
          segments.add(AnalyzedSegment(
              surface: token, kind: 'punctuation', source: 'dataset'));
          continue;
        }
        final lower = token.toLowerCase();
        if (_isCjk(token) || _stopWords.contains(lower)) {
          segments.add(AnalyzedSegment(
              surface: token,
              kind: _isCjk(token) ? 'word' : 'function',
              source: 'stopword'));
          continue;
        }
        if (memo.containsKey(lower)) {
          final hit = memo[lower];
          segments.add(hit == null
              ? AnalyzedSegment(surface: token, source: 'unresolved')
              : AnalyzedSegment(
                  surface: token,
                  kind: hit.kind,
                  wordEn: hit.wordEn,
                  wordZh: hit.wordZh,
                  pinyin: hit.pinyin,
                  pos: hit.pos,
                  meaningEn: hit.meaningEn,
                  meaningZh: hit.meaningZh,
                  meaningNe: hit.meaningNe,
                  source: hit.source,
                ));
          continue;
        }
        var resolved = await _resolveToken(db, token, lower);
        memo[lower] = resolved;
        segments.add(resolved ?? AnalyzedSegment(surface: token, source: 'unresolved'));
        if (segments.length >= 40 &&
            DateTime.now().difference(started).inMilliseconds > 2500) {
          truncated = true;
          break;
        }
      }
    }

    return AnalyzedText(
      text: trimmed,
      mode: 'paragraph',
      language: lang == InputLanguage.chinese ? 'zh' : 'en',
      segments: segments,
      degraded: truncated,
      error: truncated
          ? 'Showing the first $maxUnits units only — the offline analyser has '
              'a length limit. Use the server analyser for the full text.'
          : '',
    );
  }

  /// Resolve one English token: exact gloss first, then the normal search path.
  Future<AnalyzedSegment?> _resolveToken(
      Database db, String token, String lower) async {
    final row = await _exactRow(db, lower);
    if (row != null) return _segmentFor(row, token, isChinese: false);
    if (lower.length < 3) return null;
    final entry = await search(token, InputLanguage.english);
    final id = entry?.entryId;
    if (id == null || !id.startsWith('zh')) return null;
    final pk = int.tryParse(id.replaceFirst('zh', ''));
    if (pk == null) return null;
    final found = await _exactIdRow(db, pk);
    if (found == null) return null;
    return _segmentFor(found, token, isChinese: false);
  }

  Future<Map<String, Object?>?> _exactRow(Database db, String word) async {
    Map<String, Object?>? row = await _first(db,
        'SELECT * FROM entries WHERE simplified = ? '
        'ORDER BY is_proper, LENGTH(simplified) LIMIT 1', [word]);
    row ??= await _first(db,
        'SELECT * FROM entries WHERE traditional = ? '
        'ORDER BY is_proper, LENGTH(simplified) LIMIT 1', [word]);
    if (row == null) {
      // English side: a sense whose gloss is exactly this word.
      final hits = await _first(db,
          'SELECT e.*, s.gloss_en FROM senses s JOIN entries e '
          'ON e.entry_id = s.entry_id '
          "WHERE LOWER(TRIM(s.gloss_en)) = ? "
          'ORDER BY e.freq_rank IS NULL, e.freq_rank, LENGTH(e.simplified) '
          'LIMIT 1', [word]);
      row = hits;
    }
    return row;
  }

  Future<Map<String, Object?>?> _exactIdRow(Database db, int entryId) {
    return _first(db, 'SELECT * FROM entries WHERE entry_id = ? LIMIT 1', [entryId]);
  }

  /// One analysed unit: the entry plus its first sense, in the three languages.
  Future<AnalyzedSegment> _segmentFor(
    Map<String, Object?> row,
    String surface, {
    required bool isChinese,
  }) async {
    final db = await _open();
    final sense = db == null
        ? null
        : await _first(
            db,
            'SELECT * FROM senses WHERE entry_id = ? '
            'ORDER BY sense_order LIMIT 1',
            [row['entry_id']],
          );
    final zh = ((row['simplified'] as String?) ?? '').trim();
    final gloss = ((sense?['gloss_en'] as String?) ??
            (row['gloss_en'] as String?) ??
            '')
        .trim();
    // A Nepali/Chinese gloss fetched earlier from the server lives in user.db,
    // not in the dictionary file, so it must be overlaid here too.
    final ai = await _aiGlossFor(zh, row, sense);
    final dictNe = ((sense?['gloss_ne'] as String?) ?? '').trim();
    final dictZh = ((sense?['gloss_zh'] as String?) ?? '').trim();
    return AnalyzedSegment(
      surface: surface,
      kind: 'word',
      wordEn: isChinese ? gloss.split(';').first.trim() : surface,
      wordZh: zh,
      pinyin: ((row['pinyin_marked'] as String?) ??
          (row['pinyin_plain'] as String?) ??
          ''),
      pos: ((row['pos_primary'] as String?) ?? ''),
      meaningEn: gloss,
      meaningZh: dictZh.isNotEmpty ? dictZh : (ai?.zh ?? zh),
      meaningNe: dictNe.isNotEmpty ? dictNe : (ai?.ne ?? ''),
      source: 'dataset',
    );
  }

  /// The AI gloss this device already fetched for the sense, if any.
  Future<AiGloss?> _aiGlossFor(
    String wordZh,
    Map<String, Object?> entryRow,
    Map<String, Object?>? senseRow,
  ) async {
    if (senseRow == null) return null;
    final key = senseKey(
      wordZh: wordZh,
      pinyin: ((entryRow['pinyin_marked'] as String?) ??
          (entryRow['pinyin_plain'] as String?) ??
          ''),
      glossEn: ((senseRow['gloss_en'] as String?) ?? ''),
    );
    return userStore.aiGloss(key);
  }

  static final Set<String> _stopWords = {
    'the', 'a', 'an', 'and', 'or', 'but', 'if', 'then', 'than', 'as', 'at',
    'in', 'on', 'of', 'for', 'with', 'from', 'by', 'to', 'is', 'are', 'was',
    'were', 'be', 'been', 'being', 'am', 'do', 'does', 'did', 'have', 'has',
    'had', 'will', 'would', 'can', 'could', 'may', 'might', 'must', 'shall',
    'should', 'not', 'no', 'yes', 'so', 'this', 'that', 'these', 'those',
    'i', 'you', 'he', 'she', 'it', 'we', 'they', 'them', 'his', 'her', 'its',
    'their', 'our', 'your', 'my', 'me', 'us', 'which', 'who', 'whom', 'whose',
    'what', 'when', 'where', 'why', 'how', 'there', 'here', 'also', 'very',
  };

  static bool _isCjk(String c) =>
      RegExp(r'[\u3400-\u4dbf\u4e00-\u9fff]').hasMatch(c);

  static bool _isAllCjk(String s) =>
      s.isNotEmpty && s.split('').every(_isCjk);

  static bool _isPunctuation(String c) =>
      RegExp(r'''[.,;:!?()\[\]{}"'“”‘’—–…·、。，；：！？（）【】]''').hasMatch(c);

  /// The approved image for this entry, if the bundled database has one.
  ///
  /// Returns null rather than throwing: a word without a verified picture must
  /// keep its meanings readable (Issue 7 — "unavailable" is a normal state).
  Future<EntryImage?> imageForEntry(int entryPk) async {
    final db = await _open();
    if (db == null) return null;
    final rows = await db.rawQuery(
      'SELECT i.image_id, i.thumb_asset, i.detail_url, i.attribution_text, '
      '       i.license, i.width, i.height, ei.match_method, '
      '       COALESCE(ei.match_confidence, ei.confidence) AS conf '
      'FROM entry_images ei JOIN images i ON i.image_id = ei.image_id '
      "WHERE ei.entry_id = ? AND i.status = 'approved' "
      "  AND COALESCE(i.asset_status, 'approved') = 'approved' "
      "  AND i.thumb_asset IS NOT NULL AND i.thumb_asset != '' "
      'ORDER BY ei.rank LIMIT 1',
      [entryPk],
    );
    return rows.isEmpty ? null : _imageFromRow(rows.first);
  }

  /// The approved image for a headword, ignoring which row it was indexed on.
  ///
  /// Not every entry the UI shows comes from this database — the bundled seed
  /// words and AI answers carry ids like `seed:book`, so keying the picture on
  /// the id alone left them permanently on the placeholder even though 书 had a
  /// thumbnail in the very same APK. Chinese has several headwords for one
  /// concept anyway (玩具/玩意, 书/册), so the headword is the honest second key.
  Future<EntryImage?> imageForWord(String wordZh) async {
    final db = await _open();
    if (db == null) return null;
    final word = wordZh.trim();
    if (word.isEmpty) return null;
    final rows = await db.rawQuery(
      'SELECT i.image_id, i.thumb_asset, i.detail_url, i.attribution_text, '
      '       i.license, i.width, i.height, ei.match_method, '
      '       COALESCE(ei.match_confidence, ei.confidence) AS conf '
      'FROM entry_images ei JOIN images i ON i.image_id = ei.image_id '
      'JOIN entries e ON e.entry_id = ei.entry_id '
      "WHERE (e.simplified = ? OR e.traditional = ?) "
      "  AND i.status = 'approved' "
      "  AND COALESCE(i.asset_status, 'approved') = 'approved' "
      "  AND i.thumb_asset IS NOT NULL AND i.thumb_asset != '' "
      'ORDER BY ei.rank, conf DESC LIMIT 1',
      [word, word],
    );
    return rows.isEmpty ? null : _imageFromRow(rows.first);
  }

  EntryImage _imageFromRow(Map<String, Object?> row) {
    final asset = ((row['thumb_asset'] as String?) ?? '').trim();
    return EntryImage(
      imageId: (row['image_id'] as int?) ?? -1,
      assetPath: asset,
      remoteUrl: (row['detail_url'] as String?) ?? '',
      attribution: (row['attribution_text'] as String?) ?? '',
      license: (row['license'] as String?) ?? '',
      matchMethod: (row['match_method'] as String?) ?? '',
      confidence: ((row['conf'] as num?) ?? 0).toDouble(),
      width: (row['width'] as int?) ?? 0,
      height: (row['height'] as int?) ?? 0,
    );
  }

  /// Hangul or Cyrillic inside the Chinese line = an import defect, not  /// Chinese. A few imported rows carry exactly that (《 코드盖斯》).
  static bool _hasForeignScript(String text) {
    for (final rune in text.runes) {
      if ((rune >= 0x1100 && rune <= 0x11FF) ||
          (rune >= 0x3130 && rune <= 0x318F) ||
          (rune >= 0xAC00 && rune <= 0xD7AF) ||
          (rune >= 0x0400 && rune <= 0x04FF)) {
        return true;
      }
    }
    return false;
  }

  /// Devanagari block — the script Nepali is written in.
  static bool _isDevanagari(String text) {
    var seen = false;
    for (final rune in text.runes) {
      if (rune >= 0x0900 && rune <= 0x097F) {
        seen = true;
      } else if (rune >= 0x0041 && rune <= 0x007A) {
        // Latin inside Nepali is legitimate only for acronyms/scientific names;
        // for a full sentence it means the translation was copied, not done.
        if (text.runes.length > 6) return false;
      }
    }
    return seen;
  }

  static String _shortGloss(String gloss) {    final cut = gloss.split(RegExp(r'[;,(]')).first.trim();
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
  /// backend and persist them in the **user database** (see [UserStore]).
  ///
  /// These rows used to be written into `dictionary.sqlite`, which is replaced
  /// wholesale on every `assetVersion` bump — so a user's paid AI translations
  /// silently disappeared on update. They now live in `user.db`, keyed by the
  /// stable sense key, and are overlaid on the dictionary when a word is read.
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
      final zh = ((row['gloss_zh'] as String?) ?? '').trim();
      final needs = ne.isEmpty || zh.isEmpty || !withExample.contains(sid);
      if (!needs) continue;
      items.add(MapEntry('s$sid',
          '${entry.wordZh}\u0001${(row['gloss_en'] as String?) ?? ''}'));
    }
    if (items.isEmpty) return entry;

    final payload = await api.enrich(items);
    if (payload.isEmpty) return entry;

    final pinyin = entry.senses.isEmpty ? '' : entry.senses.first.pinyin;
    for (final item in items) {
      final sid = int.tryParse(item.key.substring(1));
      final data = payload[item.key];
      if (sid == null || data == null) continue;
      final row = rows.firstWhere((r) => r['sense_id'] == sid,
          orElse: () => const <String, Object?>{});
      final key = senseKey(
        wordZh: entry.wordZh,
        pinyin: pinyin,
        glossEn: (row['gloss_en'] as String?) ?? '',
      );
      final ne = (data['ne'] ?? '').trim();
      final zh = (data['zh'] ?? '').trim();
      if (ne.isNotEmpty || zh.isNotEmpty) {
        await userStore.putAiGloss(
          key,
          ne: ne,
          zh: zh,
          status: 'ai_translated',
          model: (data['model'] ?? '').toString(),
        );
      }
      final exampleEn = (data['example_en'] ?? '').trim();
      if (exampleEn.isNotEmpty && !withExample.contains(sid)) {
        await userStore.putAiExample(
          key,
          en: exampleEn,
          zh: (data['example_zh'] ?? '').toString(),
          ne: (data['example_ne'] ?? '').toString(),
        );
        withExample.add(sid);
      }
    }
    return _toEntry(db, {
      'entry_id': pk,
      'simplified': entry.wordZh,
      'pinyin_marked': pinyin,
    });
  }

  Future<void> close() async {
    await _db?.close();
    _db = null;
    _opening = null;
  }
}
