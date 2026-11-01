import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'dictionary_repository.dart';

/// Offline-first dictionary backed by the bundled snapshot.
final dictionaryRepositoryProvider =
    Provider<DictionaryRepository>((ref) => DictionaryRepository(rootBundle));
