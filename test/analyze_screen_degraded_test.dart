import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trilingual_dictionary/core/normalizer.dart';
import 'package:trilingual_dictionary/data/models/analyzed_text.dart';
import 'package:trilingual_dictionary/features/analyze/analyze_provider.dart';
import 'package:trilingual_dictionary/features/analyze/analyze_screen.dart';

/// The analyse screen must never leave the user looking at their own text with
/// no explanation. Two shapes reach it from the offline dictionary:
///
///  * nothing at all (dictionary missing or unreadable) — a centred message
///    carrying the reason;
///  * some units resolved and the rest not — the amber degraded banner above
///    the still-useful cards.
void main() {
  const args = AnalyzeArgs('The dog is in the house.', InputLanguage.english);

  Widget harness(AnalyzedText result) => ProviderScope(
        overrides: [analyzeProvider(args).overrideWith((ref) async => result)],
        child: const MaterialApp(
          home: AnalyzeScreen(
              query: 'The dog is in the house.', langText: 'english'),
        ),
      );

  testWidgets('an empty degraded result shows the reason, not a blank screen',
      (tester) async {
    await tester.pumpWidget(harness(const AnalyzedText(
      text: 'The dog is in the house.',
      degraded: true,
      error:
          'Offline dictionary could not be read — the bundled database is '
          'missing or damaged. Reinstall the app to restore it.',
    )));
    await tester.pumpAndSettle();

    expect(find.textContaining('could not be read'), findsOneWidget);
    expect(find.byType(ListView), findsNothing,
        reason: 'an empty analysis must not render the empty card list');
  });

  testWidgets('partial degradation keeps the words and shows the banner',
      (tester) async {
    await tester.pumpWidget(harness(const AnalyzedText(
      text: 'The dog is in the house.',
      degraded: true,
      error: 'Showing the first 300 units only — the offline analyser has a '
          'length limit.',
      segments: [
        AnalyzedSegment(
          surface: 'dog',
          wordEn: 'dog',
          wordZh: '狗',
          pinyin: 'gou',
          meaningNe: 'कुकुर',
          source: 'dataset',
        ),
      ],
    )));
    await tester.pumpAndSettle();

    expect(find.textContaining('first 300 units'), findsOneWidget,
        reason: 'the cut must be explained rather than silent');
    expect(find.text('Words & Meanings'), findsOneWidget,
        reason: 'the units that were resolved are still rendered as cards');
  });
}
