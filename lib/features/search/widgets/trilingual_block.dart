import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/theme/app_tokens.dart';
import '../../../core/tts_service.dart';

/// The reusable 3-language display widget.
/// English = sky, 中文 = rose, नेपाली = amber (v2 spec).
///
/// Pinyin is rendered as a small, clearly-separated pronunciation badge on the
/// 中文 label line — never blended into the meaning text. (Fixed per user:
/// "pinyin was showing inside the word meaning".)
///
/// Every language row carries its own speaker button: the user marks the 中文
/// and नेपाली rows as the ones they want read aloud, not just the headword.
class TrilingualBlock extends ConsumerWidget {
  final String en;
  final String zh;
  final String ne;
  final String? pinyin;
  final bool highlightNepali;

  /// Called when a language row has no text yet, so the screen can ask the
  /// backend for one more enrichment pass instead of showing a dead box.
  final VoidCallback? onRetryEmpty;

  const TrilingualBlock({
    super.key,
    required this.en,
    required this.zh,
    required this.ne,
    this.pinyin,
    this.highlightNepali = false,
    this.onRetryEmpty,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tokens = context.tokens;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _row(context, ref, tokens.brand, 'English', en, SpeechLang.english,
            soft: tokens.surface),
        _row(
          context,
          ref,
          tokens.zh,
          '中文',
          zh,
          SpeechLang.chinese,
          pinyin: pinyin,
          soft: tokens.zhSoft,
        ),
        _row(
          context,
          ref,
          tokens.ne,
          'नेपाली',
          ne,
          SpeechLang.nepali,
          soft: tokens.neSoft,
          emphasized: highlightNepali,
        ),
      ],
    );
  }

  Widget _row(
    BuildContext context,
    WidgetRef ref,
    Color color,
    String label,
    String text,
    SpeechLang lang, {
    String? pinyin,
    Color? soft,
    bool emphasized = false,
  }) {
    final tokens = context.tokens;
    final hasPinyin = pinyin != null && pinyin.trim().isNotEmpty;
    final body = text.trim();
    final hasBody = body.isNotEmpty;

    return Container(
      margin: const EdgeInsets.symmetric(vertical: 3),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        color: soft ?? tokens.surface,
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
                if (hasBody)
                  Text(
                    body,
                    style: TextStyle(
                      fontSize: emphasized ? 15.5 : 14.5,
                      fontWeight:
                          emphasized ? FontWeight.w600 : FontWeight.w500,
                      color: tokens.textPrimary,
                      height: 1.35,
                    ),
                  )
                else
                  _missingBody(context, color),
              ],
            ),
          ),
          if (hasBody)
            IconButton(
              tooltip: 'Pronounce $label',
              visualDensity: VisualDensity.compact,
              padding: const EdgeInsets.only(left: 6),
              constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
              onPressed: () => ref
                  .read(ttsServiceProvider)
                  .speak(body, lang: lang),
              icon: Icon(Icons.volume_up, size: 18, color: color),
            ),
        ],
      ),
    );
  }

  /// Empty row: say so plainly and offer the one action that can fix it, rather
  /// than leaving a blank coloured box that looks like a rendering bug.
  Widget _missingBody(BuildContext context, Color color) {
    if (onRetryEmpty == null) {
      return Text(
        '—',
        style: TextStyle(fontSize: 14, color: color.withValues(alpha: 0.6)),
      );
    }
    return InkWell(
      onTap: onRetryEmpty,
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.translate, size: 15, color: color),
            const SizedBox(width: 6),
            Text(
              'Translate now',
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: color,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
