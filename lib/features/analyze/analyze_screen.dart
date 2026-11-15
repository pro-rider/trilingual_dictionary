import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/theme/app_tokens.dart';
import '../../core/normalizer.dart';
import '../../data/models/analyzed_text.dart';
import '../search/widgets/trilingual_block.dart';
import 'analyze_provider.dart';

/// Shows a word / phrase / sentence / paragraph broken into its units, each
/// with its own trilingual meaning. Idioms & phrases get highlighted cards;
/// unknown offline units degrade gracefully.
class AnalyzeScreen extends ConsumerWidget {
  final String query;
  final String langText;

  const AnalyzeScreen({super.key, required this.query, required this.langText});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final lang = langText == 'chinese'
        ? InputLanguage.chinese
        : InputLanguage.english;
    final result = ref.watch(analyzeProvider(AnalyzeArgs(query, lang)));

    return Scaffold(
      appBar: AppBar(title: const Text('Analyze')),
      body: result.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => _message(context,
            'Could not analyze. Please check your connection.'),
        data: (data) {
          if (data == null) {
            // analyzeProvider already falls back to the bundled database; null
            // here means even that failed, so point at the real remedy.
            return _message(context,
                'This text could not be analysed. Open a word from the search '
                'box — the offline dictionary is still available.');
          }
          if (data.error.isNotEmpty && data.segments.isEmpty) {
            return _message(context, data.error);
          }
          return _body(context, data);
        },
      ),
    );
  }

  Widget _message(BuildContext context, String text) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Text(text,
            textAlign: TextAlign.center,
            style: TextStyle(color: context.tokens.textMuted, fontSize: 15)),
      ),
    );
  }

  Widget _body(BuildContext context, AnalyzedText data) {
    final tokens = context.tokens;
    final idioms = data.idioms;
    final words = data.words.where((s) => s.hasMeaning).toList();
    final unresolved = data.words.where((s) => !s.hasMeaning).toList();

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
      children: [
        // Original text
        Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: tokens.surfaceMuted,
            borderRadius: BorderRadius.circular(12),
          ),
          child: Text(data.text,
              style: TextStyle(
                  fontSize: 15.5,
                  fontWeight: FontWeight.w600,
                  height: 1.4,
                  color: tokens.textPrimary)),
        ),
        if (data.degraded) ...[
          const SizedBox(height: 10),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: tokens.warningSoft,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: tokens.warning),
            ),
            child: Text(
              data.error.isNotEmpty
                  ? data.error
                  : 'Some words could not be resolved offline (AI offline). '
                      'Their meanings are left blank.',
              style: TextStyle(fontSize: 12.5, color: tokens.warningInk),
            ),
          ),
        ],

        if (idioms.isNotEmpty) ...[
          const SizedBox(height: 18),
          Text('Idioms & Phrases',
              style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w800,
                  color: tokens.textPrimary)),
          const SizedBox(height: 6),
          for (final s in idioms) _IdiomCard(segment: s),
        ],

        if (words.isNotEmpty) ...[
          const SizedBox(height: 18),
          Text('Words & Meanings',
              style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w800,
                  color: tokens.textPrimary)),
          const SizedBox(height: 6),
          for (final s in words) _WordCard(segment: s),
        ],

        if (unresolved.isNotEmpty) ...[
          const SizedBox(height: 14),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final s in unresolved)
                Chip(
                  label: Text('${s.surface} — ?'),
                  labelStyle:
                      TextStyle(fontSize: 12.5, color: tokens.textMuted),
                  backgroundColor: tokens.surfaceMuted,
                ),
            ],
          ),
        ],

        if (data.whole != null && !data.whole!.isEmpty) ...[
          const SizedBox(height: 22),
          Text('Whole translation',
              style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w800,
                  color: tokens.textPrimary)),
          const SizedBox(height: 6),
          _WholeCard(whole: data.whole!),
        ],
      ],
    );
  }
}

class _IdiomCard extends StatelessWidget {
  final AnalyzedSegment segment;
  const _IdiomCard({required this.segment});

  @override
  Widget build(BuildContext context) {
    final tokens = context.tokens;
    final tag = segment.isIdiom ? 'Idiom' : 'Phrase';
    return Card(
      elevation: 0,
      margin: const EdgeInsets.symmetric(vertical: 6),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: tokens.warning),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(segment.surface,
                    style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                        color: tokens.textPrimary)),
                const SizedBox(width: 8),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: tokens.neFill,
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(tag,
                      style: TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                          color: tokens.onNeFill)),
                ),
              ],
            ),
            if (segment.note.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(segment.note,
                  style: TextStyle(fontSize: 12, color: tokens.neInk)),
            ],
            const SizedBox(height: 8),
            TrilingualBlock(
              en: segment.meaningEn,
              zh: segment.meaningZh,
              ne: segment.meaningNe,
              highlightNepali: true,
            ),
          ],
        ),
      ),
    );
  }
}

class _WordCard extends StatelessWidget {
  final AnalyzedSegment segment;
  const _WordCard({required this.segment});

  @override
  Widget build(BuildContext context) {
    final tokens = context.tokens;
    final kindTag = segment.isCompound
        ? 'compound'
        : (segment.source == 'ai' ? 'ai' : null);
    return Card(
      elevation: 0,
      margin: const EdgeInsets.symmetric(vertical: 6),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: tokens.border),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(segment.surface,
                    style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                        color: tokens.textPrimary)),
                if (segment.pos.isNotEmpty) ...[
                  const SizedBox(width: 8),
                  Text(segment.pos,
                      style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: tokens.brandInk)),
                ],
                if (kindTag != null) ...[
                  const SizedBox(width: 8),
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 8, vertical: 2),
                    decoration: BoxDecoration(
                      color: tokens.brandSoft,
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Text(kindTag,
                        style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w700,
                            color: tokens.brandInk)),
                  ),
                ],
              ],
            ),
            const SizedBox(height: 8),
            TrilingualBlock(
              en: segment.meaningEn,
              zh: segment.meaningZh,
              ne: segment.meaningNe,
              pinyin: segment.pinyin,
            ),
          ],
        ),
      ),
    );
  }
}

class _WholeCard extends StatelessWidget {
  final WholeTranslation whole;
  const _WholeCard({required this.whole});

  @override
  Widget build(BuildContext context) {
    final tokens = context.tokens;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: tokens.successSoft,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: tokens.success),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (whole.en.isNotEmpty)
            _line(context, tokens.brand, 'English', whole.en),
          if (whole.zh.isNotEmpty)
            _line(context, tokens.zh, '中文', whole.zh),
          if (whole.ne.isNotEmpty)
            _line(context, tokens.ne, 'नेपाली', whole.ne),
        ],
      ),
    );
  }

  Widget _line(BuildContext context, Color color, String label, String text) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label,
              style: TextStyle(
                  fontSize: 11, fontWeight: FontWeight.w700, color: color)),
          const SizedBox(height: 2),
          Text(text,
              style: TextStyle(
                  fontSize: 14.5,
                  fontWeight: FontWeight.w500,
                  height: 1.35,
                  color: context.tokens.textPrimary)),
        ],
      ),
    );
  }
}
