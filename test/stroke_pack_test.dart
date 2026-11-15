import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trilingual_dictionary/features/character/stroke_pack.dart';

/// Guards the stroke pack: what it contains, that it parses, and that the
/// payload matches the checksum in the index. Any failure here means the asset
/// bundle and the index disagree, which would ship broken glyphs.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(StrokePack.resetForTests);

  test('index and payload agree, and the subset is the top-3000 build',
      () async {
    final pack = await StrokePack.load();
    expect(pack.topWords, 3000);
    expect(pack.characterCount, greaterThan(1800),
        reason: 'top-3000 words need ~1921 distinct characters');
    expect(pack.has('我'), isTrue);
    expect(pack.has('學'), isTrue, reason: 'traditional forms must be included');
    expect(pack.has('医'), isTrue);
  });

  test('the payload checksum in the index matches the shipped file', () async {
    final index = jsonDecode(
      utf8.decode((await rootBundle.load(StrokePack.indexAsset))
          .buffer
          .asUint8List()),
    ) as Map<String, dynamic>;
    expect(index['payloadSha256'], isA<String>());
    expect(index['licence'], 'ARPHICPL.TXT');
    expect((index['chars'] as int), greaterThan(1800));
  });

  test('a known character parses into strokes, medians and metrics', () async {
    final pack = await StrokePack.load();
    final glyph = pack.glyph('我')!;
    expect(glyph.strokeCount, 7, reason: 'Unihan kTotalStrokes for 我 is 7');
    expect(glyph.medians.length, 7);
    expect(glyph.medianMetrics.every((metric) => metric.length > 0), isTrue);
  });

  test('characters outside the subset are reported missing, not invented',
      () async {
    final pack = await StrokePack.load();
    // 昰 exists in CC-CEDICT as a variant of 是 but has no stroke data.
    expect(pack.has('昰'), isFalse);
    expect(pack.glyph('昰'), isNull);
    // A character from outside the top-3000 range.
    expect(pack.glyph('龘'), isNull);
  });

  test('radicals come from Unihan and Unicode, with no hand-written names',
      () async {
    final pack = await StrokePack.load();
    expect(pack.radicalNumber('我'), 62);
    expect(pack.radicalGlyph('我'), '戈');
    expect(pack.radicalName('我'), 'halberd');
    expect(pack.radicalNumber('好'), 38);
    expect(pack.radicalName('好'), 'woman');
  });

  test('every packed character keeps the stroke count the source gave it',
      () async {
    // strokes.source_counts.json is written from the raw hanzi-writer-data files
    // BEFORE packing, so a conversion that adds or merges a stroke fails here.
    final pack = await StrokePack.load();
    final counts = jsonDecode(utf8.decode((await rootBundle
            .load('assets/strokes/strokes.source_counts.json'))
        .buffer
        .asUint8List())) as Map<String, dynamic>;

    expect(counts.length, pack.characterCount,
        reason: 'one source-count record per packed character');
    final problems = <String>[];
    for (final entry in counts.entries) {
      final glyph = pack.glyph(entry.key);
      final source = (entry.value as List).cast<int>();
      if (glyph == null) {
        problems.add('${entry.key}: packed but unreadable');
        continue;
      }
      if (glyph.strokeCount != source[0]) {
        problems.add('${entry.key}: source ${source[0]} strokes, pack ${glyph.strokeCount}');
      }
      if (glyph.medians.length != source[1]) {
        problems.add('${entry.key}: source ${source[1]} medians, pack ${glyph.medians.length}');
      }
    }
    expect(problems, isEmpty, reason: problems.take(10).join('; '));
  });

  test('characters whose count disagrees with Unihan are flagged disputed',
      () async {
    final pack = await StrokePack.load();
    // 都 packages 10 strokes; Unihan says 12. The panel must not print an
    // adjudicated-looking number until a human decides.
    expect(pack.isDisputed('都'), isTrue);
    expect(pack.glyph('都')!.strokeCount, 10);
    // A character that agrees is not disputed.
    expect(pack.isDisputed('我'), isFalse);
    expect(pack.isDisputed('昰'), isFalse);
    // The index carries the whole list, so the flag is data, not a code list.
    final index = jsonDecode(utf8.decode(
            (await rootBundle.load(StrokePack.indexAsset)).buffer.asUint8List()))
        as Map<String, dynamic>;
    expect((index['disputed'] as List).length, greaterThan(40));
  });

  group('SVG path parsing', () {
    test('handles the commands the data uses', () {
      final path = parseSvgPath('M 48 24 L 97 73 Q 146 122 195 171 C 243 220 243 318 195 367 Z');
      expect(path.getBounds().isEmpty, isFalse);
      expect(path.getBounds().left, closeTo(48, 0.01));
    });

    test('reads relative coordinates and implicit repeated pairs', () {
      final relative = parseSvgPath('m 10 20 l 5 5 l 5 5');
      expect(relative.getBounds().width, closeTo(10, 0.01));
      final repeated = parseSvgPath('M 0 0 L 10 10 20 20');
      expect(repeated.getBounds().bottomRight, const Offset(20, 20));
    });

    test('reads a minus sign as the start of the next number', () {
      // "M 10-5" is 10 and -5, not 10 and 5.
      final tokens = tokensOf('M 10-5');
      expect(tokens, ['M', 10.0, -5.0]);
    });

    test('fails loudly on an unsupported command instead of guessing', () {
      expect(() => parseSvgPath('A 5 5 0 0 1 10 10'), throwsFormatException);
    });
  });
}
