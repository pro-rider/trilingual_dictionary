import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trilingual_dictionary/features/character/stroke_pack.dart';
import 'package:trilingual_dictionary/features/character/stroke_painter.dart';

/// Renders the painter at three progress values and counts inked pixels.
/// The painter is the risky part: if progress does not actually change the
/// drawing, the animation would look frozen and the tests would still pass on a
/// blank canvas.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late StrokeGlyph glyph;

  setUpAll(() async {
    StrokePack.resetForTests();
    glyph = (await StrokePack.load()).glyph('水')!;
  });

  Future<int> inkPixels(WidgetTester tester, double progress,
      {bool guide = false}) async {
    final key = GlobalKey();
    await tester.pumpWidget(
      Directionality(
        textDirection: TextDirection.ltr,
        child: Center(
          child: RepaintBoundary(
            key: key,
            child: SizedBox(
              width: 200,
              height: 200,
              child: CustomPaint(
                painter: StrokePainter(
                  glyph: glyph,
                  progress: progress,
                  color: const Color(0xFF000000),
                  penColor: const Color(0xFF000000),
                  guideColor: const Color(0xFF000000),
                  guide: guide,
                ),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pump();

    final boundary = key.currentContext!.findRenderObject() as RenderRepaintBoundary;
    final bytes = await tester.runAsync(() async {
      final image = await boundary.toImage();
      final data = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
      image.dispose();
      return data!;
    });

    var inked = 0;
    final values = bytes!.buffer.asUint8List();
    for (var i = 3; i < values.length; i += 4) {
      if (values[i] != 0) inked++;
    }
    return inked;
  }

  testWidgets('0 percent draws nothing', (tester) async {
    expect(await inkPixels(tester, 0.0), 0);
  });

  testWidgets('50 percent draws part of the character', (tester) async {
    final half = await inkPixels(tester, 0.5);
    expect(half, greaterThan(0));
  });

  testWidgets('100 percent draws more than 50 percent', (tester) async {
    final half = await inkPixels(tester, 0.5);
    final full = await inkPixels(tester, 1.0);
    expect(full, greaterThan(half));
    expect(full, greaterThan(100), reason: '水 should cover a real area');
  });

  testWidgets('the guides are optional and drawn only when asked',
      (tester) async {
    expect(await inkPixels(tester, 0.0, guide: true), greaterThan(0));
    expect(await inkPixels(tester, 0.0), 0);
  });

  test('shouldRepaint is honest about what changed', () {
    final painter = StrokePainter(
      glyph: glyph,
      progress: 0.5,
      color: const Color(0xFF000000),
      penColor: const Color(0xFF000000),
      guideColor: const Color(0xFF000000),
    );
    final same = StrokePainter(
      glyph: glyph,
      progress: 0.5,
      color: const Color(0xFF000000),
      penColor: const Color(0xFF000000),
      guideColor: const Color(0xFF000000),
    );
    final moved = StrokePainter(
      glyph: glyph,
      progress: 0.6,
      color: const Color(0xFF000000),
      penColor: const Color(0xFF000000),
      guideColor: const Color(0xFF000000),
    );
    expect(painter.shouldRepaint(same), isFalse);
    expect(painter.shouldRepaint(moved), isTrue);
  });
}
