import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/tts_service.dart';
import '../../data/providers.dart';
import '../search/widgets/result_card.dart';
import '../search/widgets/sense_selector.dart';
import '../search/widgets/word_image_card.dart';

/// Full detail for an entry — all senses stacked.
class DetailScreen extends ConsumerStatefulWidget {
  final String entryId;

  const DetailScreen({super.key, required this.entryId});

  @override
  ConsumerState<DetailScreen> createState() => _DetailScreenState();
}

class _DetailScreenState extends ConsumerState<DetailScreen> {
  int _senseIndex = 0;

  @override
  Widget build(BuildContext context) {
    final repo = ref.watch(dictionaryRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Word detail')),
      body: FutureBuilder(
        future: repo.findById(widget.entryId),
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          final entry = snap.data;
          if (entry == null) {
            return const Center(child: Text('Entry not found'));
          }
          final senses = entry.senses;
          if (senses.isEmpty) {
            return const Center(child: Text('No senses for this entry'));
          }
          if (_senseIndex >= senses.length) _senseIndex = 0;
          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '${entry.wordEn} · ${entry.wordZh}',
                      style: const TextStyle(
                          fontSize: 26, fontWeight: FontWeight.w800),
                    ),
                  ),
                  IconButton(
                    tooltip: 'Pronounce (Chinese)',
                    onPressed: () => ref
                        .read(ttsServiceProvider)
                        .speak(senses[_senseIndex].wordZh,
                            lang: SpeechLang.chinese),
                    icon: const Icon(Icons.volume_up),
                  ),
                  IconButton(
                    tooltip: 'Pronounce (English)',
                    onPressed: () => ref
                        .read(ttsServiceProvider)
                        .speak(senses[_senseIndex].wordEn,
                            lang: SpeechLang.english),
                    icon: const Icon(Icons.record_voice_over_outlined),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              if (senses.length > 1) ...[
                SenseSelector(
                  senses: senses,
                  selectedIndex: _senseIndex,
                  onSelect: (i) => setState(() => _senseIndex = i),
                ),
                const SizedBox(height: 4),
              ],
              for (var i = 0; i < senses.length; i++)
                if (i == _senseIndex)
                  ResultCard(sense: senses[i]),
              const SizedBox(height: 14),
              WordImageCard(entryId: entry.entryId, wordZh: entry.wordZh),
            ],
          );
        },
      ),
    );
  }
}
