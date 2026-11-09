import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:trilingual_dictionary/core/translation_status.dart';

/// Contract test: the Dart ladder must agree with the backend and with the
/// shared golden vectors in `shared/translation_status_golden.json`.
void main() {
  late List<dynamic> golden;

  setUpAll(() {
    final file = File('shared/translation_status_golden.json');
    expect(file.existsSync(), isTrue,
        reason: 'golden vectors must live in shared/ so both sides read them');
    golden = jsonDecode(file.readAsStringSync()) as List<dynamic>;
  });

  test('derivation matches the shared golden vectors', () {
    for (final item in golden) {
      final input = (item as Map)['input'] as Map<String, dynamic>;
      final expected = item['expected'] as Map<String, dynamic>;
      final status = TranslationStatus.derive(
        publicationStatus: input['publication_status'] as String?,
        humanVerification: input['human_verification'] as String?,
        validationStatus: input['validation_status'] as String?,
        evidenceStrength: input['evidence_strength'] as String?,
        generationMethod: input['generation_method'] as String?,
        originSource: input['origin_source'] as String?,
      );
      expect(status.code, expected['code'], reason: '${item['name']}: code');
      expect(status.label, expected['label'], reason: '${item['name']}: label');
      expect(status.visible, expected['visible'], reason: '${item['name']}: visible');
      expect(status.attribution, expected['attribution'],
          reason: '${item['name']}: attribution');
    }
  });

  test('legacy reviewed/verified statuses never render as Verified', () {
    final reviewed = TranslationStatus.derive(validationStatus: 'incomplete');
    expect(reviewed.code, isNot('verified'));
    expect(reviewed.label, isNot(contains('Verified')));
  });

  test('a passed validation alone is never labelled Verified', () {
    final passed = TranslationStatus.derive(
      validationStatus: 'passed',
      evidenceStrength: 'strong',
      generationMethod: 'llm',
    );
    expect(passed.code, 'ai_checked');
    expect(passed.label, 'AI-translated, checked');
  });

  test('quarantined rows are hidden', () {
    final hidden = TranslationStatus.derive(publicationStatus: 'quarantined');
    expect(hidden.visible, isFalse);
  });
}
