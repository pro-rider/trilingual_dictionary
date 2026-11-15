// Stage 2 device measurement — runs on the phone, profile mode.
//
// This is test code, not a feature: it mounts the panel widget directly, so it
// measures the shipping decode path (background isolate) and the real frame cost
// of the animation without wiring the panel into any product screen yet.
//
// Run:
//   flutter drive --profile -d <device> \
//     --driver=test_driver/integration_test.dart \
//     --target=integration_test/stroke_device_test.dart
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:trilingual_dictionary/features/character/character_panel.dart';
import 'package:trilingual_dictionary/features/character/stroke_pack.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('pack load and animation cost on this device', (tester) async {
    StrokePack.resetForTests();
    // Force the shipping path: gunzip + index parse inside compute().
    StrokePack.debugDecodeInline = false;

    final rssBefore = ProcessInfo.currentRss;
    final watch = Stopwatch()..start();
    final pack = await StrokePack.load();
    watch.stop();
    final rssAfter = ProcessInfo.currentRss;

    // One glyph, timed cold (parse + path build for the character being shown).
    final glyphWatch = Stopwatch()..start();
    final glyph = pack.glyph('我');
    glyphWatch.stop();
    final pathsWatch = Stopwatch()..start();
    final pathCount = pack.glyph('學')!.outlines.length;
    pathsWatch.stop();

    final lines = <String>[
      'DEVICE pack load        ${watch.elapsedMilliseconds} ms '
          '(${pack.characterCount} chars, top ${pack.topWords} words)',
      'DEVICE rss before/after ${(rssBefore / 1024 / 1024).toStringAsFixed(1)} MB / '
          '${(rssAfter / 1024 / 1024).toStringAsFixed(1)} MB '
          '(delta ${((rssAfter - rssBefore) / 1024 / 1024).toStringAsFixed(1)} MB)',
      'DEVICE first glyph 我    ${glyphWatch.elapsedMicroseconds} µs '
          '(${glyph?.strokeCount} strokes)',
      'DEVICE 學 paths         ${pathsWatch.elapsedMicroseconds} µs for $pathCount paths',
    ];

    final frames = <FrameTiming>[];
    void onTiming(List<FrameTiming> t) => frames.addAll(t);
    SchedulerBinding.instance.addTimingsCallback(onTiming);

    await tester.pumpWidget(
      MaterialApp(
        debugShowCheckedModeBanner: false,
        home: Scaffold(
          body: Center(
            child: SizedBox(
              width: 320,
              child: CharacterPanel(characters: const ['我']),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    // The panel's FutureBuilder resolves in real async, and a pending future
    // schedules no frames — so pumpAndSettle returns before the pack is ready.
    // Poll instead of assuming, so a slow decode shows up as a real wait.
    final play = find.text('Play');
    final reducedNote = find.textContaining('reduced motion');
    final readyWatch = Stopwatch()..start();
    for (var i = 0; i < 200 && play.evaluate().isEmpty && reducedNote.evaluate().isEmpty; i++) {
      await tester.pump(const Duration(milliseconds: 20));
    }
    readyWatch.stop();
    lines.add('DEVICE panel ready       ${readyWatch.elapsedMilliseconds} ms '
        'after mount (pack already warm)');

    // With "remove animations" on, the panel deliberately hides Play and draws
    // the finished character, so there is nothing to time. Report that instead
    // of failing: it is the correct behaviour, not a missing feature.
    final staticFrame = find.text('Stroke order');
    if (play.evaluate().isEmpty && reducedNote.evaluate().isNotEmpty) {
      lines.add('DEVICE reduced motion   ON — panel shows the finished character, '
          'no Play button, so no animation to time');
      for (final line in lines) {
        debugPrint(line);
      }
      SchedulerBinding.instance.removeTimingsCallback(onTiming);
      return;
    }

    expect(play, findsOneWidget, reason: 'the panel must be idle before playing');
    expect(staticFrame, findsOneWidget);
    await tester.tap(play);
    for (var i = 0; i < 90; i++) {
      await tester.pump(const Duration(milliseconds: 16));
    }
    await tester.pumpAndSettle();
    SchedulerBinding.instance.removeTimingsCallback(onTiming);

    if (frames.isEmpty) {
      lines.add('DEVICE frames           no FrameTiming reported (build/raster '
          'timings unavailable on this device)');
    } else {
      int totalSpan = 0;
      int worstBuild = 0;
      int worstRaster = 0;
      for (final f in frames) {
        totalSpan += f.totalSpan.inMicroseconds;
        if (f.buildDuration.inMicroseconds > worstBuild) {
          worstBuild = f.buildDuration.inMicroseconds;
        }
        if (f.rasterDuration.inMicroseconds > worstRaster) {
          worstRaster = f.rasterDuration.inMicroseconds;
        }
      }
      final avg = totalSpan ~/ frames.length;
      lines.add('DEVICE frames           ${frames.length} frames, '
          'avg interval ${(avg / 1000).toStringAsFixed(2)} ms '
          '(${(1000000 / avg).toStringAsFixed(1)} fps), '
          'worst build ${(worstBuild / 1000).toStringAsFixed(2)} ms, '
          'worst raster ${(worstRaster / 1000).toStringAsFixed(2)} ms');
      final over =
          frames.where((f) => f.totalSpan.inMicroseconds > 16667).length;
      lines.add('DEVICE janky frames     $over of ${frames.length} over 16.67 ms');
    }

    for (final line in lines) {
      debugPrint(line);
    }
  });
}
