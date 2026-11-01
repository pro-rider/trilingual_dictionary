import 'package:flutter/material.dart';

import '../../../core/constants.dart';

/// The reusable 3-language display widget.
/// English = sky, 中文 = rose, नेपाली = amber (v2 spec).
///
/// Pinyin is rendered as a small, clearly-separated pronunciation badge on the
/// 中文 label line — never blended into the meaning text. (Fixed per user:
/// "pinyin was showing inside the word meaning".)
class TrilingualBlock extends StatelessWidget {
  final String en;
  final String zh;
  final String ne;
  final String? pinyin;
  final bool highlightNepali;

  const TrilingualBlock({
    super.key,
    required this.en,
    required this.zh,
    required this.ne,
    this.pinyin,
    this.highlightNepali = false,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _row(context, LanguageColors.en, 'English', en),
        _row(
          context,
          LanguageColors.zh,
          '中文',
          zh,
          pinyin: pinyin,
          soft: LanguageColors.zhSoft,
        ),
        _row(
          context,
          LanguageColors.ne,
          'नेपाली',
          ne,
          soft: LanguageColors.neSoft,
          emphasized: highlightNepali,
        ),
      ],
    );
  }

  Widget _row(
    BuildContext context,
    Color color,
    String label,
    String text, {
    String? pinyin,
    Color? soft,
    bool emphasized = false,
  }) {
    final scheme = Theme.of(context).colorScheme;
    final hasPinyin = pinyin != null && pinyin.trim().isNotEmpty;
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 3),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        color: soft ?? Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 8,
            height: 8,
            margin: const EdgeInsets.only(top: 5, right: 8),
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Label line: language name + pinyin pronunciation badge.
                Row(
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    Text(
                      label,
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        color: color,
                        letterSpacing: .3,
                      ),
                    ),
                    if (hasPinyin)
                      Container(
                        margin: const EdgeInsets.only(left: 8),
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 1),
                        decoration: BoxDecoration(
                          color: color.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(999),
                        ),
                        child: Text(
                          '拼音 $pinyin',
                          style: TextStyle(
                            fontSize: 11.5,
                            fontWeight: FontWeight.w600,
                            fontStyle: FontStyle.italic,
                            color: color,
                          ),
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 3),
                Text(
                  text,
                  style: TextStyle(
                    fontSize: emphasized ? 15.5 : 14.5,
                    fontWeight: emphasized ? FontWeight.w600 : FontWeight.w500,
                    color: scheme.onSurface,
                    height: 1.35,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
