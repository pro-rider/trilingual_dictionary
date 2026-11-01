import 'package:flutter/foundation.dart';

/// One unit of the analyzed text, with its own trilingual meaning.
class AnalyzedSegment {
  final String surface;
  final String kind; // word | compound | phrase | idiom | punctuation | other
  final String wordEn;
  final String wordZh;
  final String pinyin;
  final String pos;
  final String meaningEn;
  final String meaningZh;
  final String meaningNe;
  final String source; // dataset | phrase | ai | unresolved
  final String note;

  const AnalyzedSegment({
    this.surface = '',
    this.kind = 'word',
    this.wordEn = '',
    this.wordZh = '',
    this.pinyin = '',
    this.pos = '',
    this.meaningEn = '',
    this.meaningZh = '',
    this.meaningNe = '',
    this.source = 'unresolved',
    this.note = '',
  });

  bool get isPunctuation => kind == 'punctuation';
  bool get isIdiom => kind == 'idiom';
  bool get isPhrase => kind == 'phrase';
  bool get isCompound => kind == 'compound';
  bool get isUnresolved => source == 'unresolved';
  bool get hasMeaning =>
      meaningEn.isNotEmpty || meaningZh.isNotEmpty || meaningNe.isNotEmpty;

  factory AnalyzedSegment.fromJson(Map<String, dynamic> json) {
    String str(String k) => (json[k] as String?) ?? '';
    return AnalyzedSegment(
      surface: str('surface'),
      kind: str('kind'),
      wordEn: str('word_en'),
      wordZh: str('word_zh'),
      pinyin: str('pinyin'),
      pos: str('part_of_speech'),
      meaningEn: str('meaning_en'),
      meaningZh: str('meaning_zh'),
      meaningNe: str('meaning_ne'),
      source: str('source'),
      note: str('note'),
    );
  }
}

/// Natural whole-text translation (en / 中文 / नेपाली).
class WholeTranslation {
  final String en;
  final String zh;
  final String ne;

  const WholeTranslation({this.en = '', this.zh = '', this.ne = ''});

  bool get isEmpty => en.isEmpty && zh.isEmpty && ne.isEmpty;

  factory WholeTranslation.fromJson(Map<String, dynamic> json) {
    String str(String k) => (json[k] as String?) ?? '';
    return WholeTranslation(en: str('en'), zh: str('zh'), ne: str('ne'));
  }
}

/// Result of analyzing a word / phrase / sentence / paragraph.
@immutable
class AnalyzedText {
  final String text;
  final String mode; // word | compound | phrase | idiom | paragraph
  final String language; // en | zh
  final List<AnalyzedSegment> segments;
  final WholeTranslation? whole;
  final bool degraded;
  final String error;

  const AnalyzedText({
    this.text = '',
    this.mode = 'paragraph',
    this.language = 'en',
    this.segments = const [],
    this.whole,
    this.degraded = false,
    this.error = '',
  });

  List<AnalyzedSegment> get idioms =>
      segments.where((s) => s.isIdiom || s.isPhrase).toList();

  List<AnalyzedSegment> get words => segments
      .where((s) => !s.isPunctuation && !s.isIdiom && !s.isPhrase)
      .toList();

  factory AnalyzedText.fromJson(Map<String, dynamic> json) {
    final segs = (json['segments'] as List<dynamic>? ?? [])
        .whereType<Map<String, dynamic>>()
        .map(AnalyzedSegment.fromJson)
        .toList();
    final w = json['whole'];
    return AnalyzedText(
      text: (json['text'] as String?) ?? '',
      mode: (json['mode'] as String?) ?? 'paragraph',
      language: (json['language'] as String?) ?? 'en',
      segments: segs,
      whole: w is Map<String, dynamic> ? WholeTranslation.fromJson(w) : null,
      degraded: (json['degraded'] as bool?) ?? false,
      error: (json['error'] as String?) ?? '',
    );
  }
}
