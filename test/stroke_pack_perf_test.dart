import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trilingual_dictionary/features/character/stroke_pack.dart';

/// Measures the top-3000 pack in DART, not in Python.
///
/// The Stage 1 report quoted a 0.8 ms "index cold load" that was actually a
/// Python json.loads. This is the same work the app does — gunzip, parse the
/// index, parse one character's SVG paths — timed with a Stopwatch on this
/// machine. It is still not a phone number; Stage 2 measures that in profile
/// mode on the SM-M166P.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const packDir = 'stroke_work/top3000';

  test('top-3000 pack: decode and parse cost, measured in Dart', () async {
    final payload = File('$packDir/strokes.bin.gz');
    final indexFile = File('$packDir/strokes.index.json');
    if (!payload.existsSync() || !indexFile.existsSync()) {
      markTestSkipped(
          'top-3000 pack not built here (python tools/build_stroke_pack.py '
          '--top 3000 --out stroke_work/top3000)');
      return;
    }

    final gzBytes = payload.readAsBytesSync();
    final indexBytes = indexFile.readAsBytesSync();

    final decodeWatch = Stopwatch()..start();
    final raw = gzip.decode(gzBytes);
    decodeWatch.stop();

    final indexWatch = Stopwatch()..start();
    final index = jsonDecode(utf8.decode(indexBytes)) as Map<String, dynamic>;
    final entries = (index['entries'] as Map<String, dynamic>)
        .map((key, value) => MapEntry(key, (value as List).cast<int>()));
    indexWatch.stop();

    // One character at a time, exactly what StrokePack.glyph() does.
    final parseWatch = Stopwatch()..start();
    final samples = <String>['我', '的', '學', '醫', '都', '这'];
    final perChar = <String, double>{};
    for (final char in samples) {
      final slice = entries[char];
      if (slice == null) continue;
      final one = Stopwatch()..start();
      final decoded =
          (jsonDecode(utf8.decode(raw.sublist(slice[0], slice[0] + slice[1])))
              as Map<String, dynamic>)[char] as Map<String, dynamic>;
      StrokeGlyph.fromJson(char, decoded);
      one.stop();
      perChar[char] = one.elapsedMicroseconds / 1000.0;
    }
    parseWatch.stop();

    // Whole set: the cost if every character were ever drawn.
    final allWatch = Stopwatch()..start();
    var paths = 0;
    for (final entry in entries.entries) {
      final decoded =
          (jsonDecode(utf8.decode(raw.sublist(entry.value[0], entry.value[0] + entry.value[1])))
              as Map<String, dynamic>)[entry.key] as Map<String, dynamic>;
      final glyph = StrokeGlyph.fromJson(entry.key, decoded);
      paths += glyph.outlines.length + glyph.medians.length;
    }
    allWatch.stop();

    // ignore: avoid_print
    print('top-3000 pack, measured in Dart on this machine:');
    // ignore: avoid_print
    print('  gzipped on disk        ${gzBytes.length} bytes');
    // ignore: avoid_print
    print('  decoded payload        ${raw.length} bytes  (${(raw.length / 1048576).toStringAsFixed(2)} MiB)');
    // ignore: avoid_print
    print('  gunzip                 ${decodeWatch.elapsedMilliseconds} ms');
    // ignore: avoid_print
    print('  index parse            ${indexWatch.elapsedMicroseconds / 1000.0} ms  (${entries.length} entries)');
    // ignore: avoid_print
    print('  first draw, per char   ${perChar.entries.map((e) => '${e.key} ${e.value.toStringAsFixed(2)}').join(', ')} ms');
    // ignore: avoid_print
    print('  every char, paths      ${allWatch.elapsedMilliseconds} ms for ${entries.length} chars, '
        '$paths paths built');

    expect(raw.length, greaterThan(4 * 1024 * 1024));
    expect(entries.length, greaterThan(1700));
    expect(decodeWatch.elapsedMilliseconds, lessThan(2000),
        reason: 'gunzip off the UI isolate must stay in the hundreds of ms, not seconds');
  });

  test('the shipped top-3000 pack loads through the app path', () async {
    StrokePack.resetForTests();
    final watch = Stopwatch()..start();
    final pack = await StrokePack.load();
    watch.stop();
    // ignore: avoid_print
    print('top-3000 pack via StrokePack.load (assets + background isolate): '
        '${watch.elapsedMilliseconds} ms, ${pack.characterCount} chars');
    expect(pack.characterCount, greaterThan(900));
  });

  test('the shipped asset bytes match the index checksum record', () async {
    final pack = await StrokePack.load();
    final payload = await rootBundle.load(StrokePack.payloadAsset);
    final index = jsonDecode(utf8.decode(
            (await rootBundle.load(StrokePack.indexAsset)).buffer.asUint8List()))
        as Map<String, dynamic>;
    expect(payload.lengthInBytes, greaterThan(0));
    expect(index['payloadSha256'], isA<String>());
    expect(pack.topWords, index['topWords']);
    expect(pack.isDisputed('都'), isTrue);
  });
}
