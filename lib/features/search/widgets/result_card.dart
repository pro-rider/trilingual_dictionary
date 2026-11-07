import 'package:flutter/material.dart';

import '../../../core/constants.dart';
import '../../../data/models/sense.dart';
import 'sentence_section.dart';
import 'trilingual_block.dart';

/// A result card for one sense: 3-language meanings + aligned example.
class ResultCard extends StatelessWidget {
  final Sense sense;
  final VoidCallback? onOpen;

  /// Ask for one more enrichment pass when a language row is still empty.
  final VoidCallback? onRetryEmpty;

  const ResultCard(
      {super.key, required this.sense, this.onOpen, this.onRetryEmpty});

  @override
  Widget build(BuildContext context) {
    final example = sense.reviewedExample;
    return Card(
      elevation: 0,
      margin: const EdgeInsets.symmetric(vertical: 8),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: const BorderSide(color: Color(0xFFE2E8F0)),
      ),
      child: InkWell(
        onTap: onOpen,
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _header(),
              const SizedBox(height: 12),
              TrilingualBlock(
                en: sense.meaningEn,
                zh: sense.meaningZh,
                ne: sense.meaningNe,
                pinyin: sense.pinyin,
                highlightNepali: true,
                onRetryEmpty: onRetryEmpty,
              ),
              if (example != null) ...[
                const SizedBox(height: 12),
                SentenceSection(example: example, onRetryEmpty: onRetryEmpty),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _header() {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Expanded(
          child: Text(
            '${sense.wordEn} · ${sense.wordZh}',
            style: const TextStyle(
                fontSize: 19, fontWeight: FontWeight.w700, color: Color(0xFF0F172A)),
          ),
        ),
        if (sense.pos.isNotEmpty)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(
              color: LanguageColors.brandSoft,
              borderRadius: BorderRadius.circular(999),
            ),
            child: Text(
              sense.pos,
              style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  color: Color(0xFF0369A1)),
            ),
          ),
      ],
    );
  }
}
