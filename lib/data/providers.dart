import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'dictionary_repository.dart';
import 'local/offline_dictionary.dart';

/// Offline dictionary: curated snapshot → bundled 123k-entry SQLite database.
final offlineDictionaryProvider =
    Provider<OfflineDictionary>((ref) => OfflineDictionary());

final dictionaryRepositoryProvider = Provider<DictionaryRepository>(
  (ref) => DictionaryRepository(
    rootBundle,
    offline: ref.watch(offlineDictionaryProvider),
  ),
);
