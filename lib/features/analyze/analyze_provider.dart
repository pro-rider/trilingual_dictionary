import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/normalizer.dart';
import '../../data/api_client.dart';
import '../../data/models/analyzed_text.dart';
import '../../data/providers.dart';

/// Arguments for an analysis — the text plus its detected input language.
/// Implements equality so Riverpod's `family` reuses the same provider for the
/// same input (avoids the loading-state-stuck pitfall from the search flow).
class AnalyzeArgs {
  final String query;
  final InputLanguage lang;

  const AnalyzeArgs(this.query, this.lang);

  @override
  bool operator ==(Object other) =>
      other is AnalyzeArgs && other.query == query && other.lang == lang;

  @override
  int get hashCode => Object.hash(query, lang);
}

/// Analyze text into per-unit trilingual meanings.
///
/// The server does the good version (whole-sentence translation, idioms, an AI
/// assist for words the dictionary lacks). When it cannot be reached, the
/// bundled 96 MB database answers instead of leaving the user on an error
/// screen: every unit still gets its meanings, and only the extras are missing.
final analyzeProvider =
    FutureProvider.family<AnalyzedText?, AnalyzeArgs>((ref, args) async {
  final client = ref.watch(apiClientProvider);
  final online = await client.analyzeText(args.query, args.lang);
  if (online != null && (online.segments.isNotEmpty || online.whole != null)) {
    return online;
  }
  final local = ref.watch(offlineDictionaryProvider);
  return local.analyzeOffline(args.query, args.lang);
});
