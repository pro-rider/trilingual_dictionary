import 'package:flutter/material.dart';

import '../../../app/theme/app_tokens.dart';
import '../../../data/models/example_sentence.dart';
import 'trilingual_block.dart';

/// Shows one aligned example sentence set in all three languages.
class SentenceSection extends StatelessWidget {
  final ExampleSentence example;

  /// Ask for one more enrichment pass when a language row is still empty.
  final VoidCallback? onRetryEmpty;

  const SentenceSection({super.key, required this.example, this.onRetryEmpty});

  @override
  Widget build(BuildContext context) {
    final tokens = context.tokens;
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      decoration: BoxDecoration(
        color: tokens.brandSoft,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: tokens.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                'Example sentence',
                style: TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w700,
                    color: tokens.brandInk),
              ),
              const Spacer(),
              Text(
                switch (example.reviewStatus) {
                  'approved' => '✓ reviewed',
                  'ai_generated' => 'AI · unverified',
                  _ => 'draft',
                },
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  color: switch (example.reviewStatus) {
                    'approved' => tokens.successInk,
                    _ => tokens.neInk,
                  },
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          TrilingualBlock(
            en: example.en,
            zh: example.zh,
            ne: example.ne,
            highlightNepali: true,
            onRetryEmpty: onRetryEmpty,
          ),
        ],
      ),
    );
  }
}
