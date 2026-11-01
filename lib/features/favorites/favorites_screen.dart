import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/constants.dart';
import '../../data/dictionary_repository.dart';
import '../../data/providers.dart';
import 'favorites_repository.dart';

/// Saved words. Tapping one jumps straight to its detail page.
class FavoritesScreen extends ConsumerWidget {
  const FavoritesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final favoritesAsync = ref.watch(favoritesProvider);
    final dict = ref.watch(dictionaryRepositoryProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Favorites')),
      body: favoritesAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => const Center(child: Text('Could not load favorites')),
        data: (ids) {
          if (ids.isEmpty) {
            return const Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: Text(
                  'No favorites yet.\nTap the star on a result to save it here.',
                  textAlign: TextAlign.center,
                ),
              ),
            );
          }
          return FutureBuilder<List<_Fav>>(
            future: _resolve(dict, ids),
            builder: (context, snap) {
              if (!snap.hasData) {
                return const Center(child: CircularProgressIndicator());
              }
              final entries = snap.data!;
              if (entries.isEmpty) {
                return const Center(child: Text('Saved words not in dataset.'));
              }
              return ListView.separated(
                padding: const EdgeInsets.all(16),
                itemCount: entries.length,
                separatorBuilder: (_, _) => const SizedBox(height: 8),
                itemBuilder: (_, i) {
                  final e = entries[i];
                  return ListTile(
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                    tileColor: const Color(0xFFF0F9FF),
                    leading: const Icon(Icons.star, color: LanguageColors.brand),
                    title: Text(e.en),
                    subtitle: Text(e.zh),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () =>
                        Navigator.of(context).pushNamed('/detail/${e.id}'),
                  );
                },
              );
            },
          );
        },
      ),
    );
  }

  Future<List<_Fav>> _resolve(
      DictionaryRepository dict, List<String> ids) async {
    final out = <_Fav>[];
    for (final id in ids) {
      final e = await dict.findById(id);
      if (e != null) out.add(_Fav(id: e.entryId, en: e.wordEn, zh: e.wordZh));
    }
    return out;
  }
}

class _Fav {
  const _Fav({required this.id, required this.en, required this.zh});
  final String id;
  final String en;
  final String zh;
}
