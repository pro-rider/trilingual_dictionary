import 'package:flutter_test/flutter_test.dart';

import 'package:trilingual_dictionary/core/normalizer.dart';

void main() {
  group('Normalizer', () {
    test('detects Chinese input', () {
      expect(Normalizer.detectLanguage('光'), InputLanguage.chinese);
      expect(Normalizer.detectLanguage('老师'), InputLanguage.chinese);
    });

    test('detects English input', () {
      expect(Normalizer.detectLanguage('light'), InputLanguage.english);
      expect(Normalizer.detectLanguage('mountain 山'), InputLanguage.chinese);
    });

    test('normalizes to lowercase and trims', () {
      expect(Normalizer.normalize('  Light '), 'light');
    });

    test('pinyin key strips tone marks', () {
      expect(Normalizer.pinyinKey('guāng'), 'guang');
      expect(Normalizer.pinyinKey('màoyì'), 'maoyi');
    });

    test('prefix match works both directions', () {
      expect(Normalizer.prefixMatch('light', 'lig'), isTrue);
      expect(Normalizer.prefixMatch('lights', 'light'), isTrue);
      expect(Normalizer.prefixMatch('mountain', 'light'), isFalse);
    });
  });
}
