import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/constants.dart';
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
            return _message(context,
                'Backend not reachable. Analysis needs the server. '
                'Make sure the FastAPI backend is running.');
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
            style: const TextStyle(color: Color(0xFF64748B), fontSize: 15)),
      ),
    );
  }

  Widget _body(BuildContext context, AnalyzedText data) {
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
            color: const Color(0xFFF1F5F9),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Text(data.text,
              style: const TextStyle(
                  fontSize: 15.5, fontWeight: FontWeight.w600, height: 1.4)),
        ),
        if (data.degraded) ...[
          const SizedBox(height: 10),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: const Color(0xFFFFFBEB),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: const Color(0xFFF59E0B)),
            ),
            child: const Text(
              'Some words could not be resolved offline (AI offline). '
              'Their meanings are left blank.',
              style: TextStyle(fontSize: 12.5, color: Color(0xFF92400E)),
            ),
          ),
        ],

        if (idioms.isNotEmpty) ...[
          const SizedBox(height: 18),
          const Text('Idioms & Phrases',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          for (final s in idioms) _IdiomCard(segment: s),
        ],

        if (words.isNotEmpty) ...[
          const SizedBox(height: 18),
          const Text('Words & Meanings',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
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
                  labelStyle: const TextStyle(
                      fontSize: 12.5, color: Color(0xFF64748B)),
                  backgroundColor: const Color(0xFFF1F5F9),
                ),
            ],
          ),
        ],

        if (data.whole != null && !data.whole!.isEmpty) ...[
          const SizedBox(height: 22),
          const Text('Whole translation',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
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
    final tag = segment.isIdiom ? 'Idiom' : 'Phrase';
    return Card(
      elevation: 0,
      margin: const EdgeInsets.symmetric(vertical: 6),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: const BorderSide(color: Color(0xFFF59E0B)),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(segment.surface,
                    style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                        color: Color(0xFF0F172A))),
                const SizedBox(width: 8),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: const Color(0xFFF59E0B),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(tag,
                      style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                          color: Colors.white)),
                ),
              ],
            ),
            if (segment.note.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(segment.note,
                  style:
                      const TextStyle(fontSize: 12, color: Color(0xFFB45309))),
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
    final kindTag = segment.isCompound
        ? 'compound'
        : (segment.source == 'ai' ? 'ai' : null);
    return Card(
      elevation: 0,
      margin: const EdgeInsets.symmetric(vertical: 6),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: const BorderSide(color: Color(0xFFE2E8F0)),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(segment.surface,
                    style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                        color: Color(0xFF0F172A))),
                if (segment.pos.isNotEmpty) ...[
                  const SizedBox(width: 8),
                  Text(segment.pos,
                      style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: Color(0xFF0369A1))),
                ],
                if (kindTag != null) ...[
                  const SizedBox(width: 8),
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 8, vertical: 2),
                    decoration: BoxDecoration(
                      color: LanguageColors.brandSoft,
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Text(kindTag,
                        style: const TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w700,
                            color: Color(0xFF0369A1))),
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
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFF0FDF4),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF16A34A)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (whole.en.isNotEmpty)
            _line(const Color(0xFF0EA5E9), 'English', whole.en),
          if (whole.zh.isNotEmpty)
            _line(const Color(0xFFE11D48), '中文', whole.zh),
          if (whole.ne.isNotEmpty)
            _line(const Color(0xFFD97706), 'नेपाली', whole.ne),
        ],
      ),
    );
  }

  Widget _line(Color color, String label, String text) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label,
              style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: color)),
          const SizedBox(height: 2),
          Text(text,
              style: const TextStyle(
                  fontSize: 14.5, fontWeight: FontWeight.w500, height: 1.35)),
        ],
      ),
    );
  }
}
