/// One linked example set: en / 中文 / नेपाली express the same sense.
///
/// Stored as a single record (not three separate fields) so the three
/// languages can never drift out of alignment.
class ExampleSentence {
  final String en;
  final String zh;
  final String ne;
  final String source; // reviewed | ai_draft | generated
  final String reviewStatus; // approved | unreviewed

  const ExampleSentence({
    required this.en,
    required this.zh,
    required this.ne,
    this.source = 'reviewed',
    this.reviewStatus = 'approved',
  });

  factory ExampleSentence.fromJson(Map<String, dynamic> json) => ExampleSentence(
        en: json['en'] as String? ?? '',
        zh: json['zh'] as String? ?? '',
        ne: json['ne'] as String? ?? '',
        source: json['source'] as String? ?? 'reviewed',
        reviewStatus: json['review_status'] as String? ?? 'approved',
      );

  /// Only reviewed examples are shown by default (v2 spec).
  bool get isPublished => reviewStatus == 'approved';
}
