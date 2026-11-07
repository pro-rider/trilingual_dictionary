import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Search history: newest first, de-duplicated, capped at [maxEntries].
/// Persisted in `shared_preferences` so it survives app restarts.
class HistoryNotifier extends Notifier<List<String>> {
  static const int maxEntries = 20;
  static const String storageKey = 'history';

  bool _dirty = false;
  Future<void> _ready = Future<void>.value();

  /// Completes after stored history has been applied (or left empty).
  Future<void> get ready => _ready;

  @override
  List<String> build() {
    _ready = _hydrate();
    return const [];
  }

  Future<void> _hydrate() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      if (_dirty) return;
      final stored = prefs.getStringList(storageKey) ?? const <String>[];
      state = _sanitize(stored);
    } catch (_) {
      // Preferences unavailable: keep an empty in-memory history.
    }
  }

  void add(String query) {
    final q = query.trim();
    if (q.isEmpty) return;
    state = _sanitize([q, ...state]);
    _dirty = true;
    _save(state);
  }

  void clear() {
    _dirty = true;
    state = const [];
    _remove();
  }

  static List<String> _sanitize(Iterable<String> input) {
    final seen = <String>{};
    final out = <String>[];
    for (final raw in input) {
      final q = raw.trim();
      if (q.isEmpty) continue;
      if (!seen.add(q)) continue;
      out.add(q);
      if (out.length == maxEntries) break;
    }
    return out;
  }

  Future<void> _save(List<String> value) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setStringList(storageKey, value);
    } catch (_) {
      // Non-fatal: history stays in memory for this session.
    }
  }

  Future<void> _remove() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(storageKey);
    } catch (_) {
      // Non-fatal.
    }
  }
}

final historyProvider =
    NotifierProvider<HistoryNotifier, List<String>>(HistoryNotifier.new);
