import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/normalizer.dart';
import '../../data/api_client.dart';
import '../../data/models/dictionary_entry.dart';
import '../../data/providers.dart';
import '../settings/settings_provider.dart';

/// Arguments for a search — query text plus the detected input language.
/// Implements equality so Riverpod's `family` reuses the same provider for the
/// same search (without this, every rebuild created a new key and the result
/// stayed stuck in a loading state).
class SearchArgs {
  final String query;
  final InputLanguage lang;

  const SearchArgs(this.query, this.lang);

  @override
  bool operator ==(Object other) =>
      other is SearchArgs && other.query == query && other.lang == lang;

  @override
  int get hashCode => Object.hash(query, lang);
}

/// Offline-first lookup: try the bundled dictionary, then fall back to the
/// backend API when the word isn't in the local snapshot (v2 spec).
final resultProvider =
    FutureProvider.family<DictionaryEntry?, SearchArgs>((ref, args) async {
  final repo = ref.watch(dictionaryRepositoryProvider);
  final offlineFirst = ref.watch(settingsProvider.select((s) => s.offlineFirst));

  if (offlineFirst) {
    final local = await repo.search(args.query, args.lang);
    if (local != null) return local;
    return ref.watch(apiClientProvider).search(args.query, args.lang);
  }

  // Online-first: hit the API, fall back to local on failure.
  final remote = await ref.watch(apiClientProvider).search(args.query, args.lang);
  if (remote != null) return remote;
  return repo.search(args.query, args.lang);
});

/// Entries available for "popular words" on the home screen.
final popularProvider = FutureProvider<List<DictionaryEntry>>((ref) {
  return ref.watch(dictionaryRepositoryProvider).popular(6);
});
