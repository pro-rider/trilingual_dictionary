import 'example_sentence.dart';

/// One meaning of a word. Each meaning is a separate [Sense] carrying its
/// own translations, pronunciation and example set (v2 spec).
class Sense {
  final String id;
  final String wordEn;
  final String wordZh;
  final String pinyin;
  final String ipaEn;
  final String pos;

  final String meaningEn;
  final String meaningZh;
  final String meaningNe;

  /// ai_draft | machine_checked | human_reviewed | published | flagged
  final String meaningNeStatus;
  final String meaningNeSource;

  final List<ExampleSentence> examples;

  const Sense({
    required this.id,
    required this.wordEn,
    required this.wordZh,
    required this.pinyin,
    required this.ipaEn,
    required this.pos,
    required this.meaningEn,
    required this.meaningZh,
    required this.meaningNe,
    this.meaningNeStatus = 'published',
    this.meaningNeSource = 'dictionary',
    this.examples = const [],
  });

  factory Sense.fromJson(Map<String, dynamic> json) {
    final examplesRaw = json['examples'] as List? ?? const [];
    return Sense(
      id: json['sense_id'] as String? ?? '',
      wordEn: json['word_en'] as String? ?? '',
      wordZh: json['word_zh'] as String? ?? '',
      pinyin: json['pinyin'] as String? ?? '',
      ipaEn: json['ipa_en'] as String? ?? '',
      pos: json['part_of_speech'] as String? ?? '',
      meaningEn: json['meaning_en'] as String? ?? '',
      meaningZh: json['meaning_zh'] as String? ?? '',
      meaningNe: json['meaning_ne'] as String? ?? '',
      meaningNeStatus: json['meaning_ne_status'] as String? ?? 'published',
      meaningNeSource: json['meaning_ne_source'] as String? ?? 'dictionary',
      examples: examplesRaw
          .map((e) => ExampleSentence.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }

  /// First reviewed example, if any.
  ExampleSentence? get reviewedExample {
    for (final e in examples) {
      if (e.isPublished) return e;
    }
    return examples.isEmpty ? null : examples.first;
  }
}
