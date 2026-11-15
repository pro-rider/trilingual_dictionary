import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trilingual_dictionary/app/theme/app_theme.dart';
import 'package:trilingual_dictionary/features/character/character_panel.dart';
import 'package:trilingual_dictionary/features/character/stroke_pack.dart';

/// Task D, second half: the radical row and the missing-data fallback with NO
/// font override at all.
///
/// Why the text is boxes here: `flutter_test` installs the Ahem placeholder
/// font as the default family and ships no CJK font, so any string — English or
/// Chinese — is drawn as a solid rectangle. There is no way to render real text
/// in the harness without registering a font; that is a property of the test
/// environment, not of the app. These two captures are kept precisely to show
/// what the engine does on its own, while 01/02/03 (in
/// character_panel_screenshots_test.dart) show the same widgets with a
/// registered system font.
///
/// What is NOT boxed even here: every stroke of the character, because the
/// strokes are paths from the pack, not glyphs from a font. That is the point of
/// the comparison.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  final outDir = Directory('docs/screenshots/character-panel');

  setUp(StrokePack.resetForTests);

  Future<void> shoot(WidgetTester tester, {required String name, required Widget child}) async {
    tester.view.physicalSize = const Size(360, 480);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);

    final key = GlobalKey();
    await tester.pumpWidget(
      RepaintBoundary(
        key: key,
        child: MaterialApp(
          debugShowCheckedModeBanner: false,
          theme: AppTheme.light,
          home: Scaffold(
            body: SafeArea(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(12),
                child: child,
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final boundary = key.currentContext!.findRenderObject() as RenderRepaintBoundary;
    final bytes = await tester.runAsync(() async {
      final image = await boundary.toImage(pixelRatio: 2.0);
      final data = await image.toByteData(format: ui.ImageByteFormat.png);
      image.dispose();
      return data!;
    });
    if (!outDir.existsSync()) outDir.createSync(recursive: true);
    File('${outDir.path}/$name.png').writeAsBytesSync(bytes!.buffer.asUint8List());
    expect(tester.takeException(), isNull);
  }

  testWidgets('radical row and stroke count, no font registered', (tester) async {
    await shoot(tester, name: '08_radical_no_font',
        child: const CharacterPanel(characters: ['我']));
  });

  testWidgets('missing-data fallback, no font registered', (tester) async {
    await shoot(tester, name: '09_missing_no_font',
        child: const CharacterPanel(characters: ['昰']));
  });
}
