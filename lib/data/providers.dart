import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_client.dart';
import 'dictionary_repository.dart';
import 'local/offline_dictionary.dart';

/// Offline dictionary: curated snapshot → bundled 123k-entry SQLite database.
final offlineDictionaryProvider =
    Provider<OfflineDictionary>((ref) => OfflineDictionary());

final dictionaryRepositoryProvider = Provider<DictionaryRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  return DictionaryRepository(
    rootBundle,
    offline: ref.watch(offlineDictionaryProvider),
    api: api,
    // Read (not watch) inside the closure: the repository asks at search time,
    // so a status flip does not rebuild the provider graph.
    isOnline: () => ref.read(backendReachableProvider).value ?? false,
  );
});
