/// Input language. Nepali is output-only by design (never a search input).
enum InputLanguage { english, chinese }

/// UI language for the app's interface (buttons, labels).
enum AppLanguage { english, chinese, nepali }

extension InputLanguageX on InputLanguage {
  String get label => switch (this) {
        InputLanguage.english => 'English',
        InputLanguage.chinese => '中文',
      };

  String get short => switch (this) {
        InputLanguage.english => 'EN',
        InputLanguage.chinese => '中文',
      };
}

/// Text normalization + language detection.
///
/// Rules locked in the v2 spec:
///  - lowercase for English
///  - strip tone marks / diacritics from pinyin
///  - CJK detection decides English vs 中文 input
abstract final class Normalizer {
  static final RegExp _cjk = RegExp(r'[\u3400-\u4dbf\u4e00-\u9fff]');
  static final RegExp _diacritics = RegExp(r'[\u0300-\u036f]');

  /// Detect the input language from the raw text.
  static InputLanguage detectLanguage(String text) =>
      _cjk.hasMatch(text) ? InputLanguage.chinese : InputLanguage.english;

  /// Basic normalize: trim + lowercase.
  static String normalize(String text) => text.trim().toLowerCase();

  /// Remove tone marks so a user may type "guang" for "guāng".
  /// Uses a fixed pinyin→base mapping table (deterministic, no external
  /// dependency), then strips any remaining combining marks.
  static String pinyinKey(String pinyin) {
    final sb = StringBuffer();
    for (final ch in pinyin.split('')) {
      sb.write(_pinyinBase[ch] ?? ch);
    }
    return sb.toString().replaceAll(_diacritics, '').toLowerCase();
  }

  static const Map<String, String> _pinyinBase = {
    'ā': 'a', 'á': 'a', 'ǎ': 'a', 'à': 'a',
    'ē': 'e', 'é': 'e', 'ě': 'e', 'è': 'e',
    'ī': 'i', 'í': 'i', 'ǐ': 'i', 'ì': 'i',
    'ō': 'o', 'ó': 'o', 'ǒ': 'o', 'ò': 'o',
    'ū': 'u', 'ú': 'u', 'ǔ': 'u', 'ù': 'u',
    'ǖ': 'ü', 'ǘ': 'ü', 'ǚ': 'ü', 'ǜ': 'ü',
    'ń': 'n', 'ǹ': 'n', 'ḿ': 'm',
    'ɡ': 'g', 'ɑ': 'a', 'ɐ': 'a',
  };

  /// True if [text] starts with [key].
  static bool prefixMatch(String text, String key) {
    final a = normalize(text);
    final b = normalize(key);
    return a.startsWith(b) || b.startsWith(a);
  }
}
