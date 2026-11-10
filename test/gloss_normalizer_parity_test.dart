// Parity test for the shared gloss normalizer.
//
// The same rule lives in `backend/app/services/gloss.py::normalize_gloss`.
// The bug it replaces (`gloss.split("(").first`) was implemented twice and the
// copies drifted, so every fixture below must produce the SAME output as the
// Python test `backend/tests/test_gloss_normalizer.py` (PARITY_FIXTURES).
//
// If you add a fixture here, add it there too.

import 'package:flutter_test/flutter_test.dart';
import 'package:trilingual_dictionary/data/local/offline_dictionary.dart';

const List<List<String>> parityFixtures = [
  ['(computing) database', 'database'],
  ['(lit. and fig.) to pollute; to contaminate', 'to pollute; to contaminate'],
  ['(bird species of China) Nepal fulvetta', 'Nepal fulvetta'],
  ['front (of a building)', 'front'],
  ['a (b (c)) d', 'a d'],
  ['（口语）你好', '你好'],
  ['[slang] money', 'money'],
  ['(idiom) 三心二意', '三心二意'],
  ['salary', 'salary'],
  ['', ''],
  ['()', ''],
  ['((nested)) (twice)', ''],
  ['  spaced   out  ', 'spaced out'],
];

void main() {
  group('normalizeGloss parity with the backend', () {
    for (final fixture in parityFixtures) {
      final input = fixture[0];
      final expected = fixture[1].toLowerCase();
      test('"$input" -> "$expected"', () {
        expect(OfflineDictionary.normalizeGloss(input), expected);
      });
    }
  });

  test('a domain tag no longer hides the definition', () {
    expect(OfflineDictionary.normalizeGloss('(computing) database'), 'database');
    // The behaviour that made 17,908 senses unreachable.
    expect('(computing) database'.split('(').first.trim(), '');
  });

  test('a word inside a tag never becomes the definition', () {
    final definition = OfflineDictionary.normalizeGloss('(in order to) so as to');
    expect(definition.contains('order'), isFalse);
  });
}
