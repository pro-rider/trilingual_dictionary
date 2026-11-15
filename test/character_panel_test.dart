import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trilingual_dictionary/app/theme/app_theme.dart';
import 'package:trilingual_dictionary/features/character/character_panel.dart';
import 'package:trilingual_dictionary/features/character/stroke_pack.dart';

/// The panel's contract: renders in both themes, falls back honestly, exposes
/// one semantic label per character, respects reduced motion and 2.0x text, and
/// never leaks Nepali when it is switched off.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(StrokePack.resetForTests);

  Widget host(Widget child,
      {ThemeMode mode = ThemeMode.light,
      double textScale = 1.0,
      bool disableAnimations = false}) {
    return MaterialApp(
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
            // Screens that show this panel are scrollable pages, so the harness
            // is too: that is what keeps 2.0x text from overflowing.
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(12),
              child: child,
            ),
          ),
        ),
      ),
    );
  }

  Future<void> pumpPanel(WidgetTester tester, Widget child,
      {ThemeMode mode = ThemeMode.light,
      double textScale = 1.0,
      bool disableAnimations = false}) async {
    await tester.pumpWidget(
      host(child, mode: mode, textScale: textScale, disableAnimations: disableAnimations),
    );
    // The pack loads from the asset bundle, so let the future finish.
    await tester.pumpAndSettle();
  }

  testWidgets('renders a character with its stroke count in both themes',
      (tester) async {
    for (final mode in [ThemeMode.light, ThemeMode.dark]) {
      StrokePack.resetForTests();
      await pumpPanel(tester, const CharacterPanel(characters: ['我']), mode: mode);
      expect(tester.takeException(), isNull, reason: 'theme $mode must not throw');
      expect(find.text('Stroke order'), findsOneWidget);
      expect(find.text('Play'), findsOneWidget);
      expect(find.byType(Slider), findsOneWidget);
    }
  });

  testWidgets('shows the radical row in English and Chinese', (tester) async {
    await pumpPanel(tester, const CharacterPanel(characters: ['我']));
    expect(find.textContaining('Radical 戈 · halberd'), findsOneWidget);
    expect(find.textContaining('(62)'), findsOneWidget);
  });

  testWidgets('an undisputed character prints its stroke count', (tester) async {
    await pumpPanel(tester, const CharacterPanel(characters: ['我']));
    expect(find.text('7 strokes'), findsOneWidget);
  });

  testWidgets('a disputed character keeps the animation but hides the count',
      (tester) async {
    // 都 packs 10 strokes while Unihan says 12; the decision is still open, so
    // the number is withheld and the note is shown instead.
    await pumpPanel(tester, const CharacterPanel(characters: ['都']));
    expect(tester.takeException(), isNull);
    expect(find.text('Stroke order not reviewed'), findsOneWidget);
    expect(find.textContaining('strokes'), findsNothing);
    // The animation itself is still offered: it comes from the data, not a guess.
    expect(find.text('Play'), findsOneWidget);
    // The radical row is unaffected by the dispute. Kangxi radical 163 is 邑,
    // which is the unified ideograph the app shows for the 阝 shape.
    expect(find.textContaining('Radical 邑'), findsOneWidget);
  });

  testWidgets('a character without stroke data falls back, no error screen',
      (tester) async {
    await pumpPanel(tester, const CharacterPanel(characters: ['昰']));
    expect(tester.takeException(), isNull);
    expect(find.text('Stroke order not available'), findsOneWidget);
    expect(find.text('昰'), findsOneWidget);
    // No play control: there is nothing to animate.
    expect(find.text('Play'), findsNothing);
  });

  testWidgets('a multi-character word gets tabs and can be switched',
      (tester) async {
    await pumpPanel(tester, const CharacterPanel(characters: ['学', '生']));
    expect(find.byType(ChoiceChip), findsNWidgets(2));
    await tester.tap(find.byType(ChoiceChip).last);
    await tester.pumpAndSettle();
    expect(find.textContaining('Radical 生'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('each character carries one combined semantic label',
      (tester) async {
    final handle = tester.ensureSemantics();
    await pumpPanel(tester, const CharacterPanel(characters: ['我']));
    expect(
      find.bySemanticsLabel(RegExp(r'^我, 7 strokes, Radical 戈 · halberd \(62\)$')),
      findsOneWidget,
    );
    handle.dispose();
  });

  testWidgets('reduced motion shows the finished character and hides Play',
      (tester) async {
    final handle = tester.ensureSemantics();
    await pumpPanel(tester, const CharacterPanel(characters: ['我']),
        disableAnimations: true);
    expect(find.text('Play'), findsNothing);
    expect(
      find.textContaining('reduced motion'),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
    handle.dispose();
  });

  testWidgets('2.0x text scale does not overflow', (tester) async {
    tester.view.physicalSize = const Size(360, 720);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await pumpPanel(
      tester,
      const CharacterPanel(characters: ['学', '生'], speed: 1.0),
      textScale: 2.0,
    );
    expect(tester.takeException(), isNull);
    // The character canvas is still on screen, not clipped away.
    expect(find.byType(CustomPaint), findsWidgets);
  });

  testWidgets('the speed slider reports changes upward', (tester) async {
    double? reported;
    await pumpPanel(
      tester,
      CharacterPanel(
        characters: const ['我'],
        onSpeedChanged: (value) => reported = value,
      ),
    );
    final slider = tester.widget<Slider>(find.byType(Slider));
    slider.onChanged!(1.5);
    expect(reported, 1.5);
  });

  testWidgets('the panel exposes no Nepali when Nepali is off', (tester) async {
    await pumpPanel(
      tester,
      const CharacterPanel(characters: ['我'], nepaliEnabled: false),
    );
    // No Nepali script (Devanagari) anywhere in the panel.
    final devanagari = RegExp(r'[\u0900-\u097F]');
    for (final text in tester.widgetList<Text>(find.byType(Text))) {
      expect(devanagari.hasMatch(text.data ?? ''), isFalse,
          reason: 'unexpected Nepali text: ${text.data}');
    }
  });

  testWidgets('touch targets are at least 48 dp', (tester) async {
    await pumpPanel(tester, const CharacterPanel(characters: ['学', '生']));
    final button = tester.getSize(find.byType(FilledButton));
    expect(button.height, greaterThanOrEqualTo(48));
    final chip = tester.getSize(find.byType(ChoiceChip).first);
    expect(chip.height, greaterThanOrEqualTo(48));
  });
}
