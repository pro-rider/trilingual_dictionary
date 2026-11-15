import 'package:flutter/material.dart';

import 'stroke_pack.dart';

/// Draws one character's strokes at [progress] (0.0 .. 1.0).
///
/// How the animation works: every stroke outline is a [Path] built once when
/// the character is loaded, so a frame only fills already-built paths and, for
/// the stroke in flight, cuts the precomputed median with its [PathMetric].
/// Nothing is parsed or rebuilt per frame.
class StrokePainter extends CustomPainter {
  StrokePainter({
    required this.glyph,
    required this.progress,
    required this.color,
    required this.penColor,
    required this.guideColor,
    this.guide = true,
  }) : super(repaint: null);

  final StrokeGlyph glyph;

  /// 0 = nothing drawn, 1 = the whole character.
  final double progress;

  /// Colour of finished strokes.
  final Color color;

  /// Colour of the stroke being written.
  final Color penColor;

  /// Colour of the faint cross guides behind the character.
  final Color guideColor;

  final bool guide;

  @override
  void paint(Canvas canvas, Size size) {
    final scale = size.shortestSide / StrokePack.emUnits;
    canvas.save();
    canvas.translate(0, StrokePack.baseline * scale);
    canvas.scale(scale, -scale); // the source data has y growing upwards

    if (guide) {
      final paint = Paint()
        ..color = guideColor
        ..strokeWidth = 1 / scale;
      final mid = StrokePack.emUnits / 2;
      canvas.drawLine(Offset(mid, 1200), Offset(mid, -400), paint);
      canvas.drawLine(Offset(-40, 450), Offset(1100, 450), paint);
    }

    final total = glyph.strokeCount;
    if (total == 0) {
      canvas.restore();
      return;
    }

    final scaled = progress.clamp(0.0, 1.0) * total;
    final completed = scaled.floor();
    final fraction = scaled - completed;

    final fill = Paint()..color = color;
    for (var i = 0; i < completed && i < total; i++) {
      canvas.drawPath(glyph.outlines[i], fill);
    }

    if (completed < total && fraction > 0) {
      final metric = glyph.medianMetrics[completed];
      final length = metric.length * fraction;
      final trail = metric.extractPath(0, length);
      // Width in GLYPH units, so the canvas scale applies to it: 74/1024 em is
      // the pen Hanzi Writer draws with. Dividing by `scale` here (as an earlier
      // version did) cancels the transform and paints a 74 DEVICE-pixel blob on
      // every canvas size, which swallowed the character mid-animation.
      final pen = Paint()
        ..color = penColor
        ..strokeWidth = 74
        ..strokeCap = StrokeCap.round
        ..style = PaintingStyle.stroke;
      canvas.drawPath(trail, pen);
    }

    canvas.restore();
  }

  @override
  bool shouldRepaint(StrokePainter old) =>
      old.progress != progress ||
      old.glyph != glyph ||
      old.color != color ||
      old.penColor != penColor ||
      old.guideColor != guideColor ||
      old.guide != guide;
}
