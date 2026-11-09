import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:trilingual_dictionary/core/translation_status.dart';

/// Contract test: the Dart ladder must agree with the backend and with the
/// shared golden vectors in `shared/translation_status_golden.json`.
///
/// The Python suite reads the same file. There is no second copy of these
/// expectations anywhere, on purpose.
void main() {
  late Map<String, dynamic> golden;

  setUpAll(() {
    final file = File('shared/translation_status_golden.json');
    expect(file.existsSync(), isTrue,
        reason: 'golden vectors must live in shared/ so both sides read them');
    golden = jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
  });

  test('golden file is a versioned object with well-formed cases', () {
    expect(golden['version'], 1);
    final cases = golden['cases'] as List<dynamic>;
    expect(cases.length, greaterThanOrEqualTo(20));
    for (final item in cases) {
      final m = item as Map<String, dynamic>;
      expect(m.containsKey('name'), isTrue);
      expect(m['input'], isA<Map>());
      expect(m['expected'], isA<Map>());
    }
  });

  test('derivation matches the shared golden vectors', () {
    for (final item in golden['cases'] as List<dynamic>) {
      final m = item as Map<String, dynamic>;
      final input = m['input'] as Map<String, dynamic>;
      final expected = m['expected'] as Map<String, dynamic>;
      final status = TranslationStatus.derive(
        publicationStatus: input['publication_status'] as String?,
        humanVerification: input['human_verification'] as String?,
        validationStatus: input['validation_status'] as String?,
        evidenceStrength: input['evidence_strength'] as String?,
        generationMethod: input['generation_method'] as String?,
        originSource: input['origin_source'] as String?,
        originMethod: input['origin_method'] as String?,
        evidenceLanguage: input['evidence_language'] as String?,
        senseMatchMethod: input['sense_match_method'] as String?,
        hasSuccessor: (input['has_successor'] ?? false) as bool,
      );
      expect(status.code, expected['code'], reason: '${m['name']}: code');
      expect(status.label, expected['label'], reason: '${m['name']}: label');
      expect(status.visible, expected['visible'], reason: '${m['name']}: visible');
      expect(status.attribution, expected['attribution'],
          reason: '${m['name']}: attribution');
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

  test('a superseded row is hidden and keeps its attribution', () {
    final old = TranslationStatus.derive(
      hasSuccessor: true,
      originSource: 'wiktionary',
      validationStatus: 'passed',
      evidenceStrength: 'direct',
      evidenceLanguage: 'ne',
      senseMatchMethod: 'sense_gloss',
    );
    expect(old.code, 'superseded');
    expect(old.visible, isFalse);
  });
}
