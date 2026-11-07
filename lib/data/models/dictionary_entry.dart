import 'sense.dart';

/// One canonical record per word. English and 中文 search hit the same
/// entry; each meaning is a separate [Sense] (v2 spec).
class DictionaryEntry {
  final String entryId;
  final String wordEn;
  final String wordZh;
  final List<Sense> senses;

  /// `"dictionary"` = curated fixture / merged SQLite dictionary.
  /// `"ai"` = generated online because nothing matched; must be shown as
  /// unverified, never as a dictionary fact.
  final String source;
  final bool unverified;
  final bool cached;

  const DictionaryEntry({
    required this.entryId,
    required this.wordEn,
    required this.wordZh,
    required this.senses,
    this.source = 'dictionary',
    this.unverified = false,
    this.cached = false,
  });

  bool get isAiGenerated => source == 'ai';

  factory DictionaryEntry.fromJson(Map<String, dynamic> json) {
    final sensesRaw = json['senses'] as List? ?? const [];
    return DictionaryEntry(
      entryId: json['entry_id'] as String? ?? '',
      wordEn: json['word_en'] as String? ?? '',
      wordZh: json['word_zh'] as String? ?? '',
      source: json['source'] as String? ?? 'dictionary',
      unverified: json['unverified'] as bool? ?? false,
      cached: json['cached'] as bool? ?? false,
      senses: sensesRaw
          .map((s) => Sense.fromJson(s as Map<String, dynamic>))
          .toList(),
    );
  }

  Sense? senseById(String id) {
    for (final s in senses) {
      if (s.id == id) return s;
    }
    return senses.isEmpty ? null : senses.first;
  }
}
