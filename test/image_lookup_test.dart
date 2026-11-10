import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:trilingual_dictionary/core/normalizer.dart';
import 'package:trilingual_dictionary/data/local/offline_dictionary.dart';

import 'support/real_db.dart';

void main() {
  final dbPath = realDictionaryPath();
  final noDb = missingRealDictionary();

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  test('imageForEntry returns the bundled thumbnail for 玩具', () async {
    final dict = OfflineDictionary(overridePath: dbPath);
    final image = await dict.imageForEntry(72148);
    // ignore: avoid_print
    print('imageForEntry(72148) -> '
        '${image?.assetPath} conf=${image?.confidence} '
        'w=${image?.width} h=${image?.height} lic=${image?.license}');
    expect(image, isNotNull);
    expect(image!.assetPath, endsWith('.webp'));
    await dict.close();
  }, skip: noDb ? kMissingDictionarySkip : null);

  test('entry ids from search are usable as image keys', () async {
    final dict = OfflineDictionary(overridePath: dbPath);
    for (final word in ['toy', 'sound', 'water', 'mountain']) {
      final entry = await dict.search(word, InputLanguage.english);
      // ignore: avoid_print
      print('search($word) entryId=${entry?.entryId} wordZh=${entry?.wordZh}');
      if (entry == null) continue;
      final pk = int.tryParse(entry.entryId.replaceFirst('zh', ''));
      final image = await dict.imageForEntry(pk ?? -1);
      // ignore: avoid_print
      print('  image -> ${image?.assetPath}');
      expect(image, isNotNull, reason: '$word should carry a thumbnail');
    }
    await dict.close();
  }, skip: noDb ? kMissingDictionarySkip : null);

  test('quarantined examples never reach the reader', () async {
    final dict = OfflineDictionary(overridePath: dbPath);
    // The one quarantined row in the live database belongs to 11区.
    for (final word in ['Area 11', '11区']) {
      final entry = await dict.search(word, InputLanguage.english);
      if (entry == null) continue;
      final all = entry.senses.expand((s) => s.examples).toList();
      // ignore: avoid_print
      print('examples shown for $word: ${all.length}');
      for (final ex in all) {
        expect(ex.en, isNot(contains('Code Geass')),
            reason: 'quarantined sentence leaked into the reader');
      }
    }
    await dict.close();
  }, skip: noDb ? kMissingDictionarySkip : null);

  test('headword lookup covers entries whose id is not a local row', () async {
    final dict = OfflineDictionary(overridePath: dbPath);
    // 'book' as the UI shows it: a seed/AI entry carrying an id the local
    // database cannot resolve. The headword still has to find the photo.
    for (final word in ['书', '山', '声音', '玩具']) {
      final image = await dict.imageForWord(word);
      // ignore: avoid_print
      print('imageForWord($word) -> ${image?.assetPath}');
      expect(image, isNotNull, reason: '$word has a bundled thumbnail');
    }
    expect(await dict.imageForWord('册'), isNotNull);
    await dict.close();
  }, skip: noDb ? kMissingDictionarySkip : null);
}
