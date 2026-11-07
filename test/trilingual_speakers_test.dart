import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trilingual_dictionary/core/tts_service.dart';
import 'package:trilingual_dictionary/features/search/widgets/trilingual_block.dart';

/// Records what the block asked the engine to say, without touching the
/// platform TTS channel (which does not exist in a widget test).
class _RecordingTts implements TtsService {
  final List<(String, SpeechLang)> spoken = [];

  @override
  Future<void> speak(String text, {SpeechLang lang = SpeechLang.english}) async {
    spoken.add((text, lang));
  }

  @override
  Future<void> stop() async {}
}

Future<void> _pump(WidgetTester tester, _RecordingTts tts,
    {String zh = '山', String ne = 'पहाड', VoidCallback? onRetry}) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [ttsServiceProvider.overrideWithValue(tts)],
    child: MaterialApp(
      home: Scaffold(
        body: TrilingualBlock(
          en: 'mountain',
          zh: zh,
          ne: ne,
          pinyin: 'shān',
          onRetryEmpty: onRetry,
        ),
      ),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('every language row has its own speaker and speaks its own text',
      (tester) async {
    final tts = _RecordingTts();
    await _pump(tester, tts);

    expect(find.byIcon(Icons.volume_up), findsNWidgets(3));

    await tester.tap(find.byTooltip('Pronounce English'));
    await tester.tap(find.byTooltip('Pronounce 中文'));
    await tester.tap(find.byTooltip('Pronounce नेपाली'));
    await tester.pumpAndSettle();

    expect(tts.spoken, [
      ('mountain', SpeechLang.english),
      ('山', SpeechLang.chinese),
      ('पहाड', SpeechLang.nepali),
    ]);
  });

  testWidgets('an empty row offers Translate instead of a blank box',
      (tester) async {
    var tapped = 0;
    final tts = _RecordingTts();
    await _pump(tester, tts, ne: '', onRetry: () => tapped++);

    expect(find.text('Translate now'), findsOneWidget);
    expect(find.byIcon(Icons.volume_up), findsNWidgets(2));

    await tester.tap(find.text('Translate now'));
    expect(tapped, 1);
  });
}
