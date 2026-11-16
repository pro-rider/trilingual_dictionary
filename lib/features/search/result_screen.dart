import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/theme/app_tokens.dart';
import '../../core/normalizer.dart';
import '../../core/tts_service.dart';
import '../../data/api_client.dart';
import '../../data/models/dictionary_entry.dart';
import '../../data/models/sense.dart';
import '../favorites/favorites_repository.dart';
import 'search_provider.dart';
import 'widgets/result_card.dart';
import 'widgets/sense_selector.dart';
import 'widgets/word_image_card.dart';

/// Shows the 3-language result for a search.
class ResultScreen extends ConsumerStatefulWidget {
  final String query;
  final InputLanguage lang;

  const ResultScreen({super.key, required this.query, required this.lang});

  @override
  ConsumerState<ResultScreen> createState() => _ResultScreenState();
}

class _ResultScreenState extends ConsumerState<ResultScreen> {
  int _senseIndex = 0;

  /// The sense currently on screen, read straight from the provider so the
  /// toolbar no longer needs a data-dependent closure.
  Sense? _currentSense() {
    final entry =
        ref.read(resultProvider(SearchArgs(widget.query, widget.lang))).value;
    if (entry == null || entry.senses.isEmpty) return null;
    final i = _senseIndex < entry.senses.length ? _senseIndex : 0;
    return entry.senses[i];
  }

  void _speak() {
    final sense = _currentSense();
    if (sense == null) return;
    // Speak the headword in the language the user typed in.
    final service = ref.read(ttsServiceProvider);
    if (widget.lang == InputLanguage.chinese) {
      service.speak(sense.wordZh, lang: SpeechLang.chinese);
    } else {
      service.speak(sense.wordEn, lang: SpeechLang.english);
    }
  }

  /// Re-run the lookup so the repository gets another chance to fill the empty
  /// 中文 / नेपाली boxes from the backend, then refresh the screen.
  void _retryEnrich() {
    final args = SearchArgs(widget.query, widget.lang);
    ref.invalidate(backendReachableProvider);
    ref.invalidate(resultProvider(args));
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Reaching the server for the missing languages…')),
      );
    }
  }

  Future<void> _copy(Sense sense) async {    final buffer = StringBuffer()
      ..writeln(sense.wordEn)
      ..writeln('${sense.wordZh}  ${sense.pinyin}'.trim());
    if (sense.meaningEn.isNotEmpty) buffer.writeln('EN: ${sense.meaningEn}');
    if (sense.meaningZh.isNotEmpty) buffer.writeln('中文: ${sense.meaningZh}');
    if (sense.meaningNe.isNotEmpty) buffer.writeln('नेपाली: ${sense.meaningNe}');
    final example = sense.reviewedExample;
    if (example != null) buffer.writeln('例: ${example.zh} / ${example.en}');
    await Clipboard.setData(ClipboardData(text: buffer.toString().trim()));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Copied to clipboard')),
    );
  }

  @override
  Widget build(BuildContext context) {
    final result =
        ref.watch(resultProvider(SearchArgs(widget.query, widget.lang)));

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          tooltip: 'Back',
          icon: const Icon(Icons.arrow_back),
          onPressed: () {
            if (context.canPop()) {
              context.pop();
            } else {
              context.go('/home');
            }
          },
        ),
        title: Text('“${widget.query}”'),
        actions: [
          IconButton(
            tooltip: 'Pronounce',
            onPressed: _speak,
            icon: const Icon(Icons.volume_up, size: 20),
          ),
          IconButton(
            tooltip: 'Copy result',
            onPressed: () {
              final sense = _currentSense();
              if (sense != null) _copy(sense);
            },
            icon: const Icon(Icons.copy, size: 20),
          ),
        ],
      ),
      body: result.when(
        data: (entry) => entry == null ? _empty() : _entry(entry),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => _error('$e'),
      ),
    );
  }

  Widget _entry(DictionaryEntry entry) {
    final senses = entry.senses;
    if (_senseIndex >= senses.length) _senseIndex = 0;
    final sense = senses[_senseIndex];
    final favorites = ref.watch(favoritesProvider).value ?? const [];
    final isFav = favorites.contains(entry.entryId);
    final tokens = context.tokens;

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
      children: [
        // Word header
        Row(
          children: [
            Expanded(
              child: Text(
                entry.wordEn,
                style: const TextStyle(
                    fontSize: 26, fontWeight: FontWeight.w800),
              ),
            ),
            IconButton(
              tooltip: isFav ? 'Remove from favorites' : 'Save to favorites',
              onPressed: () =>
                  ref.read(favoritesProvider.notifier).toggle(entry.entryId),
              icon: Icon(
                isFav ? Icons.star : Icons.star_border,
                color: isFav ? tokens.ne : null,
              ),
            ),
            TextButton.icon(
              onPressed: () =>
                  context.push('/detail/${entry.entryId}?sense=$_senseIndex'),
              icon: const Icon(Icons.open_in_full, size: 18),
              label: const Text('Detail'),
            ),
          ],
        ),
        const SizedBox(height: 6),
        if (entry.isAiGenerated) ...[
          _aiBanner(entry.cached),
          const SizedBox(height: 8),
        ],
        SenseSelector(
          senses: senses,
          selectedIndex: _senseIndex,
          onSelect: (i) => setState(() => _senseIndex = i),
        ),
        const SizedBox(height: 4),
        ResultCard(sense: sense, onRetryEmpty: _retryEnrich),
        const SizedBox(height: 14),
        // Picture for this entry, loaded separately so the meaning never waits
        // on the network (stage 44 of the image plan).
        WordImageCard(entryId: entry.entryId, wordZh: entry.wordZh),
      ],
    );
  }

  /// Honest label for an online AI answer: this word is not in the dictionary,
  /// so the meaning is machine-generated and must not read as verified data.
  Widget _aiBanner(bool cached) {
    final tokens = context.tokens;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: tokens.warningSoft,
        border: Border.all(color: tokens.warning),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          Icon(Icons.auto_awesome, size: 18, color: tokens.ne),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              'AI-generated · unverified'
              '${cached ? ' · cached' : ''}\n'
              'This word is not in the dictionary yet. The meaning and example '
              'come from an AI model — check them before relying on them.',
              style: TextStyle(fontSize: 12, color: tokens.warningInk),
            ),
          ),
        ],
      ),
    );
  }

  Widget _empty() {
    final tokens = context.tokens;
    final reachable = ref.watch(backendReachableProvider);
    final args = SearchArgs(widget.query, widget.lang);
    final online = reachable.valueOrNull;
    final message = online == null
        ? 'Checking whether the server is reachable…'
        : online
            ? '“${widget.query}” is not in the dictionary and the AI could not '
                'answer right now (provider error or limit). Try again in a moment.'
            : 'Not in the offline dictionary either — the bundled database is '
                'still being filled in for this word. Adding the AI lookup back '
                'needs a connection.';
    final buttonLabel = online == true ? 'Try again' : 'Reconnect and retry';

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(online == false ? Icons.wifi_off : Icons.search_off,
                size: 56, color: tokens.textMuted),
            const SizedBox(height: 12),
            const Text('No entry found',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            const SizedBox(height: 6),
            Text(
              message,
              textAlign: TextAlign.center,
              style: TextStyle(color: tokens.textMuted),
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: () {
                ref.invalidate(backendReachableProvider);
                ref.invalidate(resultProvider(args));
              },
              icon: const Icon(Icons.refresh),
              label: Text(buttonLabel),
            ),
            const SizedBox(height: 8),
            TextButton.icon(
              onPressed: () => context.go('/home'),
              icon: const Icon(Icons.arrow_back),
              label: const Text('Back to search'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _error(String message) {
    final tokens = context.tokens;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, size: 56, color: tokens.zh),
            const SizedBox(height: 12),
            const Text('Something went wrong',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            const SizedBox(height: 6),
            Text(message, style: TextStyle(color: tokens.textMuted)),
          ],
        ),
      ),
    );
  }
}
