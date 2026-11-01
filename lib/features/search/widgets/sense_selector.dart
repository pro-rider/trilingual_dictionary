import 'package:flutter/material.dart';

import '../../../core/constants.dart';
import '../../../data/models/sense.dart';

/// Lets the user pick which meaning of a word to view (v2 spec).
class SenseSelector extends StatelessWidget {
  final List<Sense> senses;
  final int selectedIndex;
  final ValueChanged<int> onSelect;

  const SenseSelector({
    super.key,
    required this.senses,
    required this.selectedIndex,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    if (senses.length <= 1) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Padding(
          padding: EdgeInsets.only(bottom: 6),
          child: Text(
            'Choose a meaning',
            style: TextStyle(
                fontSize: 12.5,
                fontWeight: FontWeight.w700,
                color: Color(0xFF475569)),
          ),
        ),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            children: [
              for (var i = 0; i < senses.length; i++)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    selected: i == selectedIndex,
                    onSelected: (_) => onSelect(i),
                    label: Text(_label(senses[i])),
                    labelStyle: TextStyle(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w600,
                      color: i == selectedIndex
                          ? LanguageColors.brand
                          : const Color(0xFF475569),
                    ),
                    selectedColor: LanguageColors.brandSoft,
                    backgroundColor: Colors.white,
                    side: BorderSide(
                      color: i == selectedIndex
                          ? LanguageColors.brand
                          : const Color(0xFFE2E8F0),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }

  String _label(Sense s) {
    final pos = s.pos.isEmpty ? 'word' : s.pos;
    final meaning = s.meaningEn.isNotEmpty ? s.meaningEn : s.wordEn;
    return '$pos · ${_shorten(meaning)}';
  }

  String _shorten(String text, [int max = 26]) =>
      text.length <= max ? text : '${text.substring(0, max - 1)}…';
}
