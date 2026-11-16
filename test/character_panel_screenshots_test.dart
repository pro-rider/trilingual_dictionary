import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/services.dart';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trilingual_dictionary/app/theme/app_theme.dart';
import 'package:trilingual_dictionary/features/character/character_panel.dart';
import 'package:trilingual_dictionary/features/character/stroke_pack.dart';

/// Renders the panel through the real engine and writes the PNGs used as
/// evidence for this stage. Device measurement is Stage 2; these images are
/// engine output, not phone screenshots, and are labelled as such.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  final outDir = Directory('docs/screenshots/character-panel');

  setUpAll(() async {
    // flutter_test draws every string with the placeholder Ahem font, which
    // shows as solid boxes. Registering a system font under the Material
    // default family makes the captures readable; it does not change what the
    // app ships.
    final fontFile = File(r'C:\Windows\Fonts\simhei.ttf');
    if (!fontFile.existsSync()) return;
    final bytes = fontFile.readAsBytesSync();
    final loader = FontLoader('Roboto')
      ..addFont(Future<ByteData>.value(ByteData.view(bytes.buffer)));
    await loader.load();

    // The Material icon font is not registered in the test harness either, so
    // the Play icon would come out as a box.
    final icons = File(
        r'C:\flutter\bin\cache\artifacts\material_fonts\materialicons-regular.otf');
    if (icons.existsSync()) {
      final iconLoader = FontLoader('MaterialIcons')
        ..addFont(
            Future<ByteData>.value(ByteData.view(icons.readAsBytesSync().buffer)));
      await iconLoader.load();
    }
  });

  setUp(() {
    StrokePack.resetForTests();
  });

  Future<void> shoot(
    WidgetTester tester, {
    required String name,
    required CharacterPanel panel,
    required ThemeMode mode,
    double textScale = 1.0,
    bool disableAnimations = false,
  }) async {
    tester.view.physicalSize = const Size(360, 720);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);

    final key = GlobalKey();
    await tester.pumpWidget(
      RepaintBoundary(
        key: key,
        child: MaterialApp(
          debugShowCheckedModeBanner: false,
          theme: AppTheme.light,
          darkTheme: AppTheme.dark,
          themeMode: mode,
          home: MediaQuery(
            data: MediaQueryData(
              textScaler: TextScaler.linear(textScale),
              disableAnimations: disableAnimations,
              size: const Size(360, 720),
            ),
            child: Scaffold(
              body: SafeArea(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(12),
                  child: panel,
                ),
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

  testWidgets('capture: light theme', (tester) async {
    await shoot(tester,
        name: '01_light',
        panel: const CharacterPanel(characters: ['我']),
        mode: ThemeMode.light);
  });

  testWidgets('capture: dark theme', (tester) async {
    await shoot(tester,
        name: '02_dark',
        panel: const CharacterPanel(characters: ['我']),
        mode: ThemeMode.dark);
  });

  testWidgets('capture: character with no stroke data', (tester) async {
    await shoot(tester,
        name: '03_missing_data_light',
        panel: const CharacterPanel(characters: ['昰']),
        mode: ThemeMode.light);
  });

  testWidgets('capture: multi-character word', (tester) async {
    await shoot(tester,
        name: '04_multi_char_dark',
        panel: const CharacterPanel(characters: ['学', '生']),
        mode: ThemeMode.dark);
  });

  testWidgets('capture: 2.0x text scale and reduced motion', (tester) async {
    await shoot(tester,
        name: '05_text_200_dark',
        panel: const CharacterPanel(characters: ['学', '生']),
        mode: ThemeMode.dark,
        textScale: 2.0,
        disableAnimations: true);
  });
}


