import 'package:flutter/foundation.dart';

/// The derived display state of one Nepali meaning.
///
/// The database stores dimensions, never labels; this is the only place a label
/// is produced. Mirrors `backend/app/translations/status.py`, and both are
/// checked against `shared/translation_status_golden.json`.
@immutable
class TranslationStatus {
  const TranslationStatus({
    required this.code,
    required this.label,
    required this.visible,
    required this.attribution,
  });

  /// How the source record was tied to this sense. Only these are defensible;
  /// `headword`, `heuristic` and a missing method are not.
  static const List<String> defensibleSenseMatches = <String>[
    'sense_gloss',
    'sense_id',
    'qid',
    'article',
  ];

  static const String quarantined = 'quarantined';
  static const String superseded = 'superseded';
  static const String verified = 'verified';
  static const String flagged = 'flagged';
  static const String userCorrection = 'user_correction';
  static const String sourceSupported = 'source_supported';
  static const String aiChecked = 'ai_checked';
  static const String aiUnverified = 'ai_unverified';
  static const String sourceSenseUnconfirmed = 'source_sense_unconfirmed';
  static const String unverifiedLegacy = 'unverified_legacy';

  final String code;
  final String label;
  final bool visible;
  final String? attribution;

  /// The ladder, first match wins — the order is part of the contract.
  ///
  /// 1. quarantined -> hidden
  /// 2. has a successor -> superseded, hidden but keeps attribution
  /// 3. human verified -> verified
  /// 4. validation failed -> flagged
  /// 5. origin_method user_correction -> user correction, awaiting verification
  /// 6. imported from a source + direct Nepali lexical evidence + defensible
  ///    sense match + named source + passed -> source-supported
  /// 7. llm + direct/strong + passed -> AI-translated, checked
  /// 8. llm -> AI-translated, unverified
  /// 9. source import + direct/strong + passed -> source recorded, sense unconfirmed
  /// 10. legacy unknown or incomplete validation -> unverified (source unknown)
  /// 11. otherwise -> source recorded, sense unconfirmed
  ///
  /// Rule 6 requires `generation_method == 'source_import'`: an LLM-written value
  /// becomes *checked*, never *source-supported*, however good the evidence for
  /// the sense is. A source URL alone is never enough.
  factory TranslationStatus.derive({
    String? publicationStatus,
    String? humanVerification,
    String? validationStatus,
    String? evidenceStrength,
    String? generationMethod,
    String? originSource,
    String? originMethod,
    String? evidenceLanguage,
    String? senseMatchMethod,
    bool hasSuccessor = false,
  }) {
    final publication = publicationStatus ?? 'labeled';
    final verification = humanVerification ?? 'not_verified';
    final validation = validationStatus ?? 'incomplete';
    final strength = evidenceStrength ?? 'none';
    final method = generationMethod ?? 'legacy_unknown';
    final source = (originSource != null && originSource.trim().isNotEmpty) ? originSource : null;
    final directAndDefensible = method == 'source_import' &&
        strength == 'direct' &&
        validation == 'passed' &&
        source != null &&
        evidenceLanguage == 'ne' &&
        senseMatchMethod != null &&
        defensibleSenseMatches.contains(senseMatchMethod);

    String code;
    if (publication == 'quarantined') {
      code = quarantined;
    } else if (hasSuccessor) {
      code = superseded;
    } else if (verification == 'verified') {
      code = TranslationStatus.verified;
    } else if (validation == 'failed') {
      code = flagged;
    } else if (originMethod == 'user_correction') {
      code = userCorrection;
    } else if (directAndDefensible) {
      code = sourceSupported;
    } else if (method == 'llm' &&
        (strength == 'direct' || strength == 'strong') &&
        validation == 'passed') {
      code = aiChecked;
    } else if (method == 'llm') {
      code = aiUnverified;
    } else if (method == 'source_import' &&
        (strength == 'direct' || strength == 'strong') &&
        validation == 'passed') {
      code = sourceSenseUnconfirmed;
    } else if (method == 'legacy_unknown' || validation == 'incomplete') {
      code = unverifiedLegacy;
    } else {
      code = sourceSenseUnconfirmed;
    }

    final rule = _rules[code]!;
    final needsAttribution = rule.$3;
    final attribution = needsAttribution ? source : null;
    final label = attribution == null ? rule.$1 : '${rule.$1} · $attribution';
    return TranslationStatus(
      code: code,
      label: label,
      visible: rule.$2,
      attribution: attribution,
    );
  }

  /// code -> (label, visible, needs attribution)
  static const Map<String, (String, bool, bool)> _rules = <String, (String, bool, bool)>{
    'quarantined': ('Hidden from results', false, false),
    'superseded': ('Superseded', false, true),
    'verified': ('Verified', true, false),
    'flagged': ('Flagged — failed checks', true, false),
    'user_correction': ('User correction — awaiting verification', true, false),
    'source_supported': ('Source-supported', true, true),
    'ai_checked': ('AI-translated, checked', true, false),
    'ai_unverified': ('AI-translated, unverified', true, false),
    'source_sense_unconfirmed': ('Source-recorded, sense unconfirmed', true, true),
    'unverified_legacy': ('Unverified — source unknown', true, false),
  };

  @override
  String toString() => 'TranslationStatus($code, $label)';
}
