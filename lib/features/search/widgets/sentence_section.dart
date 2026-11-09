import 'package:flutter/material.dart';

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
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      decoration: BoxDecoration(
        color: const Color(0xFFF0F9FF),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFBAE6FD)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text(
                'Example sentence',
                style: TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w700,
                    color: Color(0xFF0369A1)),
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
                    'approved' => const Color(0xFF166534),
                    'ai_generated' => const Color(0xFFB45309),
                    _ => const Color(0xFFB45309),
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
