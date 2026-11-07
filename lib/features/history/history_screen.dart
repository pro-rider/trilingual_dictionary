import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'history_provider.dart';

/// Search history with clear-all (persisted in shared_preferences).
class HistoryScreen extends ConsumerWidget {
  const HistoryScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final history = ref.watch(historyProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('History'),
        actions: [
          if (history.isNotEmpty)
            IconButton(
              tooltip: 'Clear all',
              onPressed: () => ref.read(historyProvider.notifier).clear(),
              icon: const Icon(Icons.delete_sweep_outlined),
            ),
        ],
      ),
      body: history.isEmpty
          ? const Center(
              child: Text('No searches yet',
                  style: TextStyle(color: Color(0xFF64748B))),
            )
          : ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: history.length,
              separatorBuilder: (_, _) => const Divider(height: 1),
              itemBuilder: (context, i) {
                final h = history[i];
                return ListTile(
                  leading: const Icon(Icons.history, color: Color(0xFF0EA5E9)),
                  title: Text(h),
                  trailing: const Icon(Icons.chevron_right, size: 20),
                  onTap: () => context.go(
                    '/result?q=${Uri.encodeComponent(h)}&lang=${_detect(h)}',
                  ),
                );
              },
            ),
    );
  }

  String _detect(String q) {
    // Reuse the CJK detection without importing the normalizer here.
    final cjk = RegExp(r'[\u3400-\u4dbf\u4e00-\u9fff]');
    return cjk.hasMatch(q) ? 'chinese' : 'english';
  }
}
