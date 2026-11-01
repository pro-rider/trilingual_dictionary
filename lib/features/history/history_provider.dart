import 'package:flutter_riverpod/flutter_riverpod.dart';

/// In-memory search history for v1 (SQLite persistence is a later phase).
class HistoryNotifier extends Notifier<List<String>> {
  static const int _max = 20;

  @override
  List<String> build() => const [];

  void add(String query) {
    final q = query.trim();
    if (q.isEmpty) return;
    final updated = <String>[q, ...state.where((e) => e != q)];
    state = updated.take(_max).toList();
  }

  void clear() => state = const [];
}

final historyProvider =
    NotifierProvider<HistoryNotifier, List<String>>(HistoryNotifier.new);
