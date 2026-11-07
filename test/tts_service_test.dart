import 'package:flutter_test/flutter_test.dart';
import 'package:trilingual_dictionary/core/tts_service.dart';

void main() {
  group('TtsService language mapping', () {
    test('maps each speech language to its BCP-47 code', () {
      expect(TtsService.languageCode(SpeechLang.english), 'en-US');
      expect(TtsService.languageCode(SpeechLang.chinese), 'zh-CN');
      expect(TtsService.languageCode(SpeechLang.nepali), 'ne-NP');
    });

    test('codes stay distinct so a missing voice pack cannot masquerade', () {
      final codes = [
        TtsService.languageCode(SpeechLang.english),
        TtsService.languageCode(SpeechLang.chinese),
        TtsService.languageCode(SpeechLang.nepali),
      ];
      expect(codes.toSet().length, 3);
      expect(codes.every((c) => c.contains('-')), isTrue);
    });
  });
}
