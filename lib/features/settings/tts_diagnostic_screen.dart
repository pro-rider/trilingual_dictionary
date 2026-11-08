import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:path_provider/path_provider.dart';

/// Temporary TTS diagnostic screen (prompt V1). Shows the engine, the installed
/// engines, the available languages/voices, and measures tap→sound latency for
/// English / 中文 / नेपाली on first tap and on five repeat taps.
///
/// Nothing here changes app behaviour: it only reads engine state and speaks
/// sample words. Delete the route once the problem is fixed.
class TtsDiagnosticScreen extends StatefulWidget {
  const TtsDiagnosticScreen({super.key});

  @override
  State<TtsDiagnosticScreen> createState() => _TtsDiagnosticScreenState();
}

class _TtsDiagnosticScreenState extends State<TtsDiagnosticScreen> {
  final FlutterTts _tts = FlutterTts();

  static const List<String> _probeLocales = [
    'en-US',
    'zh-CN',
    'zh-TW',
    'ne-NP',
    'hi-IN',
  ];

  static const Map<String, (String, String)> _samples = {
    'en-US': ('English', 'mountain'),
    'zh-CN': ('中文', '山'),
    'ne-NP': ('Nepali', 'पहाड'),
  };

  bool _running = false;
  String _report = 'Press “Run diagnosis” to start.';

  @override
  void initState() {
    super.initState();
    _configure();
  }

  Future<void> _configure() async {
    try {
      await _tts.awaitSpeakCompletion(false);
      await _tts.setQueueMode(0); // QUEUE_FLUSH: a new utterance cancels the old
      await _tts.setSpeechRate(0.45);
    } catch (_) {
      // engine may not support every setter
    }
  }

  @override
  void dispose() {
    _tts.stop();
    super.dispose();
  }

  // ---------------------------------------------------------------- diagnosis

  Future<void> _run() async {
    setState(() {
      _running = true;
      _report = 'Running… (this takes about a minute)';
    });

    final b = StringBuffer();
    b.writeln('TTS DIAGNOSTIC REPORT');
    b.writeln('generated: ${DateTime.now().toIso8601String()}');
    b.writeln('platform: ${Platform.operatingSystem} ${Platform.operatingSystemVersion}');
    b.writeln();

    // 1. engine
    String engine = '(unavailable)';
    try {
      engine = '${await _tts.getDefaultEngine}';
    } catch (e) {
      engine = 'error: $e';
    }
    b.writeln('ACTIVE ENGINE: $engine');

    b.writeln('INSTALLED ENGINES:');
    try {
      final list = await _tts.getEngines as List? ?? const [];
      for (final e in list) {
        b.writeln('  - ${e is Map ? '${e['name']} (${e['label']})' : e}');
      }
    } catch (e) {
      b.writeln('  error: $e');
    }
    b.writeln();

    // 2. languages
    List<String> languages = const [];
    try {
      languages = List<String>.from(
          (await _tts.getLanguages as List? ?? const []).map((e) => '$e'));
    } catch (e) {
      b.writeln('getLanguages error: $e');
    }
    b.writeln('getLanguages: ${languages.length} locales');
    b.writeln('  all: ${languages.join(', ')}');
    b.writeln();

    // 3. availability
    b.writeln('isLanguageAvailable:');
    final availability = <String, bool>{};
    for (final tag in _probeLocales) {
      bool ok;
      try {
        final raw = await _tts.isLanguageAvailable(tag);
        ok = raw == true || raw == 1 || raw == 'true';
      } catch (_) {
        ok = false;
      }
      availability[tag] = ok;
      b.writeln('  $tag → $ok');
    }
    b.writeln();

    // 4. voices
    b.writeln('VOICES (name | locale | network_required | quality | features):');
    final voices = <Map>[];
    try {
      final raw = await _tts.getVoices as List? ?? const [];
      for (final v in raw) {
        if (v is Map) voices.add(v);
      }
    } catch (e) {
      b.writeln('  getVoices error: $e');
    }
    b.writeln('  total voices: ${voices.length}');
    final interesting = voices.where((v) {
      final loc = '${v['locale'] ?? ''}'.toLowerCase();
      return loc.startsWith('zh') ||
          loc.startsWith('ne') ||
          loc.startsWith('hi') ||
          loc.startsWith('en');
    }).toList();
    for (final v in interesting) {
      b.writeln('  - ${v['name']} | ${v['locale']} | '
          'net=${v['network_required']} | q=${v['quality']} | ${v['features']}');
    }
    b.writeln();

    // Which locale strings actually have a voice, and whether it is offline.
    String voiceSummary(String prefix) {
      final hits = voices.where(
          (v) => '${v['locale'] ?? ''}'.toLowerCase().startsWith(prefix));
      if (hits.isEmpty) return 'none';
      final offline = hits.where((v) => '${v['network_required']}' == '0').length;
      return '${hits.length} voice(s), $offline offline';
    }

    b.writeln('VOICE SUMMARY BY LANGUAGE:');
    b.writeln('  zh*: ${voiceSummary('zh')}');
    b.writeln('  ne*: ${voiceSummary('ne')}');
    b.writeln('  hi*: ${voiceSummary('hi')}');
    b.writeln();

    // 5. timing
    b.writeln('LATENCY  (ms from speak() call → start handler)');
    b.writeln('lang    tap1  tap2  tap3  tap4  tap5  tap6   setLanguage(ms)  result');
    final timings = <String, List<int?>>{};
    final setLangMs = <String, List<int>>{};

    for (final entry in _samples.entries) {
      final tag = entry.key;
      final label = entry.value.$1;
      final text = entry.value.$2;
      final times = <int?>[];
      final setTimes = <int>[];

      for (var i = 0; i < 6; i++) {
        // Measure setLanguage separately: the app switches language on every
        // tap today, and that call is synchronous work on the engine's thread.
        final swSet = Stopwatch()..start();
        try {
          await _tts.setLanguage(tag);
        } catch (_) {
          // recorded as 0; availability already reported above
        }
        swSet.stop();
        setTimes.add(swSet.elapsedMilliseconds);

        final result = await _measureOne(text);
        times.add(result.ms);
        if (result.note != null) b.writeln('  #$i $tag: ${result.note}');
        // Let the utterance finish so the next tap is not just flushing it.
        await _waitForCompletion();
      }

      timings[tag] = times;
      setLangMs[tag] = setTimes;

      final vals = times.map((t) => t == null ? 'TIMEOUT' : '$t').toList();
      b.writeln('${label.padRight(8)}${vals.map((v) => v.padRight(6)).join()}'
          '  ${setTimes.join('/')}   ${_verdict(tag, times, availability[tag] ?? false, voices)}');
    }
    b.writeln();

    // 6. findings
    b.writeln('FINDINGS');
    for (final entry in _samples.entries) {
      final tag = entry.key;
      final times = timings[tag] ?? const [];
      final first = times.isEmpty ? null : times.first;
      final rest = times.length > 1 ? times.sublist(1) : const <int?>[];
      final restAvg = rest.isEmpty
          ? null
          : rest.whereType<int>().fold<int>(0, (a, b) => a + b) /
              (rest.whereType<int>().isEmpty ? 1 : rest.whereType<int>().length);
      final avail = availability[tag] ?? false;
      final hasVoice = voiceSummary(tag.substring(0, 2)).startsWith('none') == false;
      final reasons = <String>[];
      if (!avail || !hasVoice) reasons.add('missing voice');
      if (hasVoice && !_hasOfflineVoice(voices, tag)) {
        reasons.add('online-only voice');
      }
      if (first != null && restAvg != null && first > restAvg * 2 && first > 800) {
        reasons.add('cold start');
      }
      final setAvg = setLangMs[tag]!.isEmpty
          ? 0
          : setLangMs[tag]!.reduce((a, b) => a + b) ~/ setLangMs[tag]!.length;
      if (setAvg > 60) reasons.add('language switch costs ${setAvg}ms/tap');
      if (rest.whereType<int>().isNotEmpty) {
        final maxRest = rest.whereType<int>().reduce((a, b) => a > b ? a : b);
        if (maxRest > 600) reasons.add('slow start (${maxRest}ms)');
      }
      if (times.any((t) => t == null)) reasons.add('no start callback (silent failure)');
      b.writeln('  ${entry.value.$1}: ${reasons.isEmpty ? 'no problem detected' : reasons.join(' + ')}');
    }
    b.writeln();
    b.writeln('NOTE: start-handler latency measures when the engine begins producing '
        'audio, not when sound leaves the speaker. On-device voices are usually '
        '100–300 ms; network voices add 400–1500 ms and fail in airplane mode.');

    final text = b.toString();
    debugPrint('TTSREPORT-START\n$text\nTTSREPORT-END');

    try {
      final dir = await getApplicationDocumentsDirectory();
      final file = File('${dir.path}/tts_report.txt');
      await file.writeAsString(text);
      debugPrint('TTSREPORT-FILE ${file.path}');
    } catch (e) {
      debugPrint('TTSREPORT-FILE-ERROR $e');
    }

    if (!mounted) return;
    setState(() {
      _report = text;
      _running = false;
    });
  }

  bool _hasOfflineVoice(List<Map> voices, String tag) {
    final lang = tag.split('-').first.toLowerCase();
    return voices.any((v) =>
        '${v['locale'] ?? ''}'.toLowerCase().startsWith(lang) &&
        '${v['network_required']}' == '0');
  }

  String _verdict(String tag, List<int?> times, bool available, List<Map> voices) {
    if (!available) return 'VOICE MISSING';
    if (times.any((t) => t == null)) return 'NO START (silent)';
    final ok = times.whereType<int>().toList();
    if (ok.isEmpty) return 'NO START (silent)';
    final avg = ok.reduce((a, b) => a + b) ~/ ok.length;
    if (avg < 300) return 'OK ($avg ms avg)';
    if (avg < 700) return 'SLOW ($avg ms avg)';
    return 'VERY SLOW ($avg ms avg)';
  }

  /// Speak and wait for the start callback (or 6 s).
  Future<({int? ms, String? note})> _measureOne(String text) async {
    final completer = Completer<int?>();
    final sw = Stopwatch()..start();
    _tts.setStartHandler(() {
      if (!completer.isCompleted) completer.complete(sw.elapsedMilliseconds);
    });
    _tts.setErrorHandler((msg) {
      if (!completer.isCompleted) {
        completer.complete(null);
      }
      debugPrint('TTS ERROR during probe: $msg');
    });
    try {
      _tts.speak(text, focus: true);
    } catch (e) {
      if (!completer.isCompleted) completer.complete(null);
      return (ms: null, note: 'speak threw: $e');
    }
    final ms = await completer.future.timeout(const Duration(seconds: 6),
        onTimeout: () => null);
    return (
      ms: ms,
      note: ms == null ? 'no start callback within 6 s for "$text"' : null,
    );
  }

  Future<void> _waitForCompletion() async {
    final done = Completer<void>();
    _tts.setCompletionHandler(() {
      if (!done.isCompleted) done.complete();
    });
    try {
      await done.future.timeout(const Duration(seconds: 8));
    } catch (_) {
      // proceed; the next speak() flushes anyway
    }
  }

  Future<void> _copy() async {
    await Clipboard.setData(ClipboardData(text: _report));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Report copied')),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('TTS diagnosis'),
        actions: [
          IconButton(
            tooltip: 'Copy report',
            onPressed: _copy,
            icon: const Icon(Icons.copy, size: 20),
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
            child: Row(
              children: [
                Expanded(
                  child: FilledButton.icon(
                    onPressed: _running ? null : _run,
                    icon: _running
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.play_arrow),
                    label: Text(_running ? 'Running…' : 'Run diagnosis'),
                  ),
                ),
                const SizedBox(width: 8),
                OutlinedButton(
                  onPressed: () async {
                    await _tts.stop();
                    await _tts.speak('नमस्ते');
                  },
                  child: const Text('Test ne'),
                ),
              ],
            ),
          ),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 16),
            child: Text(
              'Temporary screen. Reads engine state only; does not change playback.',
              style: TextStyle(fontSize: 12, color: Color(0xFF64748B)),
            ),
          ),
          const Divider(height: 24),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
              child: SelectableText(
                _report,
                style: const TextStyle(
                    fontFamily: 'monospace', fontSize: 12, height: 1.35),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
