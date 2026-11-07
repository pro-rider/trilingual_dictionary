import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_tts/flutter_tts.dart';

/// Which language a string should be spoken in.
enum SpeechLang { english, chinese, nepali }

/// Thin wrapper over `flutter_tts`.
///
/// Behaviour that matters for a dictionary:
///  * one utterance at a time — starting a new one stops the previous;
///  * a missing voice pack (Nepali is rare on desktop) degrades to the English
///    voice instead of throwing or silently doing nothing;
///  * failures are swallowed so a dead TTS engine never breaks the screen.
class TtsService {
  TtsService({FlutterTts? engine}) : _tts = engine ?? FlutterTts();

  final FlutterTts _tts;
  bool _configured = false;

  static String languageCode(SpeechLang lang) => switch (lang) {
        SpeechLang.english => 'en-US',
        SpeechLang.chinese => 'zh-CN',
        SpeechLang.nepali => 'ne-NP',
      };

  /// Nepali voice packs are rare. Devanagari is also read correctly by a Hindi
  /// voice, so the fallback chain is: Nepali → Hindi → English. This matters on
  /// Android, where `setLanguage('ne-NP')` throws when no pack is installed and
  /// the old code then silently read Devanagari with an English voice.
  static const Map<SpeechLang, List<String>> _fallbackChain = {
    SpeechLang.english: ['en-US', 'en-GB'],
    SpeechLang.chinese: ['zh-CN', 'zh-TW'],
    SpeechLang.nepali: ['ne-NP', 'ne', 'hi-IN'],
  };

  Future<void> _configure() async {
    if (_configured) return;
    try {
      await _tts.setSpeechRate(0.45);
      await _tts.setVolume(1.0);
      await _tts.setPitch(1.0);
      // Completes the future when speech ends, so `await speak()` is usable in
      // tests and for sequential playback.
      await _tts.awaitSpeakCompletion(true);
    } catch (_) {
      // Older engines may not implement every setter; keep going.
    }
    _configured = true;
  }

  Future<void> speak(String text, {SpeechLang lang = SpeechLang.english}) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return;
    await _configure();
    // One utterance at a time: starting a new one must cut the previous.
    try {
      await _tts.stop();
    } catch (_) {
      // ignore — stop() is not implemented by every engine
    }
    for (final code in _fallbackChain[lang] ?? const ['en-US']) {
      try {
        final ok = await _tts.setLanguage(code);
        if (ok == 0 && code != 'en-US') continue; // 0 = not available
        await _tts.speak(trimmed);
        return;
      } catch (_) {
        // Voice pack missing for this code; try the next one.
      }
    }
    // Last resort: the engine's default voice. Better than silence.
    try {
      await _tts.speak(trimmed);
    } catch (_) {
      // Engine unavailable entirely (e.g. headless CI) — ignore.
    }
  }

  Future<void> stop() async {
    try {
      await _tts.stop();
    } catch (_) {
      // ignore
    }
  }
}

final ttsServiceProvider = Provider<TtsService>((ref) => TtsService());
