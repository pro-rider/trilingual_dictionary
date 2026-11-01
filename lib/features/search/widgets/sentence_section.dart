import 'package:flutter/material.dart';

import '../../../data/models/example_sentence.dart';
import 'trilingual_block.dart';

/// Shows one aligned example sentence set in all three languages.
class SentenceSection extends StatelessWidget {
  final ExampleSentence example;

  const SentenceSection({super.key, required this.example});

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
                example.reviewStatus == 'approved' ? '✓ reviewed' : 'draft',
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  color: example.reviewStatus == 'approved'
                      ? const Color(0xFF166534)
                      : const Color(0xFFB45309),
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
          ),
        ],
      ),
    );
  }
}
