import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:trilingual_dictionary/core/translation_resolution.dart';
import 'package:trilingual_dictionary/core/translation_status.dart';

Map<String, Object?>? _statusInput(Map<String, Object?> g) {
  if (g.isEmpty) return null;
  return g;
}

TranslationStatus? _governanceStatus(Map<String, Object?> g) {
  if (g.isEmpty) return null;
  return TranslationStatus.derive(
    publicationStatus: g['publication_status'] as String?,
    humanVerification: g['human_verification'] as String?,
    validationStatus: g['validation_status'] as String?,
    evidenceStrength: g['evidence_strength'] as String?,
    generationMethod: g['generation_method'] as String?,
    originSource: g['origin_source'] as String?,
    evidenceLanguage: g['evidence_language'] as String?,
    senseMatchMethod: g['sense_match_method'] as String?,
    hasSuccessor: (g['has_successor'] as bool?) ?? false,
  );
}

void main() {
  final golden = jsonDecode(
    File('shared/translation_resolution_golden.json').readAsStringSync(),
  ) as List<dynamic>;

  test('resolution matches the shared golden vectors', () {
    for (final raw in golden) {
      final c = raw as Map<String, dynamic>;
      final g = (c['governance'] as Map<String, dynamic>?) ?? <String, dynamic>{};
      final expected = c['expected'] as Map<String, dynamic>;
      final status = _governanceStatus(_statusInput(g) ?? <String, Object?>{});
      final resolved = resolveNepali(
        dictionaryText: c['dictionary'] as String?,
        governanceStatus: status,
        governanceText: g['text'] as String?,
        governancePublicationStatus: g['publication_status'] as String?,
        hasSuccessor: (g['has_successor'] as bool?) ?? false,
      );
      expect(resolved.text, expected['text'], reason: c['name']);
      expect(
        resolved.source.name,
        expected['source'],
        reason: c['name'],
      );
      expect(resolved.status.code, expected['status'], reason: c['name']);
      expect(resolved.visible, expected['visible'], reason: c['name']);
    }
  });

  test('a sense never renders two Nepali meanings', () {
    // The import copies the dictionary value; an identical copy must not append
    // a second line.
    final resolved = resolveNepali(
      dictionaryText: 'पानी',
      governanceStatus: TranslationStatus.derive(generationMethod: 'llm'),
      governanceText: 'पानी',
      governancePublicationStatus: 'labeled',
    );
    expect(resolved.source, NepaliSource.dictionary);
    expect(resolved.text, 'पानी');
  });

  test('losing the governance row keeps the original Nepali visible', () {
    final resolved = resolveNepali(dictionaryText: 'पानी');
    expect(resolved.text, 'पानी');
    expect(resolved.visible, isTrue);
    expect(resolved.status.code, 'unverified_legacy');
  });
}
