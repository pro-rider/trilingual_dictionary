import 'dart:convert';

import 'package:flutter/services.dart';

import '../core/constants.dart';
import '../core/errors/failures.dart';
import '../core/normalizer.dart';
import 'models/dictionary_entry.dart';

/// Offline dictionary backed by the bundled JSON snapshot.
///
/// Matching order (v2 spec): exact → prefix → pinyin.
/// Nepali is never a search input.
class DictionaryRepository {
  final AssetBundle _bundle;
  List<DictionaryEntry> _entries = const [];
  bool _loaded = false;

  DictionaryRepository(this._bundle);

  Future<List<DictionaryEntry>> load() async {
    if (_loaded) return _entries;
    try {
      final raw = await _bundle.loadString(AppConstants.offlineDatasetAsset);
      final data = jsonDecode(raw) as Map<String, dynamic>;
      final list = data['entries'] as List? ?? const [];
      _entries = list
          .map((e) => DictionaryEntry.fromJson(e as Map<String, dynamic>))
          .toList();
      _loaded = true;
      return _entries;
    } on Failure {
      rethrow;
    } catch (_) {
      throw const DatasetLoadFailure();
    }
  }

  /// Search by English or 中文 input. Returns the first matching entry.
  Future<DictionaryEntry?> search(String query, InputLanguage lang) async {
    await load();
    final q = Normalizer.normalize(query);
    if (q.isEmpty) return null;

    if (lang == InputLanguage.chinese) {
      // exact on word_zh
      for (final e in _entries) {
        if (Normalizer.normalize(e.wordZh) == q) return e;
      }
      // prefix on word_zh
      for (final e in _entries) {
        if (Normalizer.prefixMatch(e.wordZh, q)) return e;
      }
      // pinyin
      for (final e in _entries) {
        for (final s in e.senses) {
          if (Normalizer.pinyinKey(s.pinyin) == q) return e;
        }
      }
      return null;
    }

    // English: exact
    for (final e in _entries) {
      if (Normalizer.normalize(e.wordEn) == q) return e;
    }
    // prefix
    for (final e in _entries) {
      if (Normalizer.prefixMatch(e.wordEn, q)) return e;
    }
    return null;
  }

  Future<DictionaryEntry?> findById(String entryId) async {
    await load();
    for (final e in _entries) {
      if (e.entryId == entryId) return e;
    }
    return null;
  }

  Future<List<DictionaryEntry>> popular(int limit) async {
    await load();
    return _entries.take(limit).toList();
  }

  List<DictionaryEntry> get entries => _entries;
}
