import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/normalizer.dart';
import '../../data/api_client.dart';
import '../../data/models/analyzed_text.dart';

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

/// Analyze text into per-unit trilingual meanings (backend-driven).
final analyzeProvider =
    FutureProvider.family<AnalyzedText?, AnalyzeArgs>((ref, args) {
  return ref.watch(apiClientProvider).analyzeText(args.query, args.lang);
});
