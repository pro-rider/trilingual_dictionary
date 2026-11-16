import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:trilingual_dictionary/features/character/stroke_build_info.dart';

/// The stroke assets are someone else's licensed work. This audit fails if the
/// licence, the conversion statement or the checksum record goes missing.
void main() {
  const dir = 'assets/strokes';

  test('the stroke asset folder ships the licence and a record', () {
    final folder = Directory(dir);
    expect(folder.existsSync(), isTrue, reason: '$dir must exist');

    final names = folder.listSync().map((e) => e.path.split(Platform.pathSeparator).last).toSet();
    for (final required in [
      'strokes.bin.gz',
      'strokes.index.json',
      'ARPHICPL.TXT',
      'README.md',
    ]) {
      expect(names, contains(required), reason: '$dir must contain $required');
    }
  });

  test('ARPHICPL.TXT is the real Arphic Public License text', () {
    final text = File('$dir/ARPHICPL.TXT').readAsStringSync();
    expect(text, contains('ARPHIC PUBLIC LICENSE'));
    expect(text, contains('Arphic Technology'));
    expect(text.length, greaterThan(3000),
        reason: 'a truncated licence would not be a licence');
  });

  test('README records the source, version, checksum and the conversion', () {
    final text = File('$dir/README.md').readAsStringSync();
    expect(text.toLowerCase(), contains('arphic'));
    expect(text, contains('hanzi-writer-data'));
    expect(text, contains('sha256'));
    expect(text.toLowerCase(), contains('conversion'),
        reason: 'the licence requires stating how the format was changed');
  });

  test('the licence notice reaches the in-app Credits screen', () {
    final credits =
        File('lib/features/about/credits_screen.dart').readAsStringSync();
    expect(credits, contains('Arphic'));
    expect(credits, contains('ARPHICPL.TXT'));
    expect(credits, contains('Make Me a Hanzi'));
  });

  test('the licence notes exist and are not legal advice', () {
    final doc = File('docs/LICENSE-ARPHIC.md').readAsStringSync();
    expect(doc, contains('ARPHICPL.TXT'));
    expect(doc.toLowerCase(), contains('not legal advice'));
    expect(doc, contains('CC BY-SA'));
  });

  test('the build date is generated, and Credits agrees with it', () {
    // The date used to be typed into the Credits string. A rebuild changes it,
    // so the value comes from build_info.json via a generated constant, and this
    // test fails the moment the two drift apart.
    final info = jsonDecode(File('$dir/build_info.json').readAsStringSync())
        as Map<String, dynamic>;
    expect(info['built'], matches(RegExp(r'^\d{4}-\d{2}-\d{2}$')));
    expect(kStrokePackBuilt, info['built'],
        reason: 'stroke_build_info.dart must be regenerated with the pack');
    expect(kStrokePackTopWords, info['topWords']);
    expect(kStrokePackChars, info['chars']);
    expect(kStrokePackSha256, info['payloadSha256']);
    expect(kStrokePackSource, 'hanzi-writer-data@2.0.1');

    // No hand-typed date anywhere in the Credits source.
    final credits =
        File('lib/features/about/credits_screen.dart').readAsStringSync();
    expect(RegExp(r'\d{4}-\d{2}-\d{2}').hasMatch(credits), isFalse,
        reason: 'a hard-coded date would drift on every rebuild');

    // The generated README states the same date.
    expect(File('$dir/README.md').readAsStringSync(), contains(info['built'] as String));
  });

  test('the source-count record exists and covers every packed character', () {
    final counts = jsonDecode(File('$dir/strokes.source_counts.json').readAsStringSync())
        as Map<String, dynamic>;
    final index = jsonDecode(File('$dir/strokes.index.json').readAsStringSync())
        as Map<String, dynamic>;
    expect(counts.length, index['chars'],
        reason: 'one record per packed character');
  });
}
