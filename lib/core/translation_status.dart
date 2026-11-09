/// Dart twin of `backend/app/translations/status.py`.
///
/// The database stores dimensions, never labels. This turns the stored
/// dimensions into one display state, with the same ladder as the backend so a
/// badge in the app and a line in a report never disagree.
///
/// Ladder (first match wins):
/// 1. quarantined                     -> hidden
/// 2. human verified                  -> "Verified"
/// 3. validation failed               -> "Flagged — failed checks"
/// 4. direct evidence + validated + named source -> "Source-supported · <source>"
/// 5. llm + direct/strong evidence + validated   -> "AI-translated, checked"
/// 6. llm                             -> "AI-translated, unverified"
/// 7. source_import + direct/strong + validated  -> "Source-recorded, sense unconfirmed"
/// 8. legacy_unknown or incomplete validation    -> "Unverified — source unknown"
/// 9. otherwise                        -> "Source-recorded, sense unconfirmed"
///
/// Consequences: a valid Devanagari string never becomes "Verified";
/// `validationStatus == 'passed'` only ever yields "checked"; a legacy
/// "reviewed" status renders as unverified.
library;

import 'package:flutter/foundation.dart';

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

  final String code;
  final String label;

  /// Whether this row may appear in normal dictionary results.
  final bool visible;

  /// Source name when the label must carry attribution, else null.
  final String? attribution;

  /// The shared ladder. Missing dimensions fall back to the database defaults
  /// (`not_verified`, `incomplete`, `labeled`), so an old row cannot read as
  /// verified by accident.
  ///
  /// "Source-supported" is deliberately narrow: a source URL alone is not
  /// enough, the evidence must be lexical Nepali and the sense match defensible
  /// (see [defensibleSenseMatches]).
  factory TranslationStatus.derive({
    String? publicationStatus,
    String? humanVerification,
    String? validationStatus,
    String? evidenceStrength,
    String? generationMethod,
    String? originSource,
    String? evidenceLanguage,
    String? senseMatchMethod,
  }) {
    final publication = publicationStatus ?? 'labeled';
    final verification = humanVerification ?? 'not_verified';
    final validation = validationStatus ?? 'incomplete';
    final strength = evidenceStrength ?? 'none';
    final method = generationMethod ?? 'legacy_unknown';
    final source = (originSource != null && originSource.trim().isNotEmpty) ? originSource : null;
    final directAndDefensible = strength == 'direct' &&
        validation == 'passed' &&
        source != null &&
        evidenceLanguage == 'ne' &&
        senseMatchMethod != null &&
        defensibleSenseMatches.contains(senseMatchMethod);

    String code;
    if (publication == 'quarantined') {
      code = 'quarantined';
    } else if (verification == 'verified') {
      code = 'verified';
    } else if (validation == 'failed') {
      code = 'flagged';
    } else if (directAndDefensible) {
      code = 'source_supported';
    } else if (method == 'llm' &&
        (strength == 'direct' || strength == 'strong') &&
        validation == 'passed') {
      code = 'ai_checked';
    } else if (method == 'llm') {
      code = 'ai_unverified';
    } else if (method == 'source_import' &&
        (strength == 'direct' || strength == 'strong') &&
        validation == 'passed') {
      code = 'source_sense_unconfirmed';
    } else if (method == 'legacy_unknown' || validation == 'incomplete') {
      code = 'unverified_legacy';
    } else {
      code = 'source_sense_unconfirmed';
    }

    final String baseLabel;
    final bool visible;
    final bool needsAttribution;
    switch (code) {
      case 'quarantined':
        baseLabel = 'Hidden from results';
        visible = false;
        needsAttribution = false;
        break;
      case 'verified':
        baseLabel = 'Verified';
        visible = true;
        needsAttribution = false;
        break;
      case 'flagged':
        baseLabel = 'Flagged — failed checks';
        visible = true;
        needsAttribution = false;
        break;
      case 'source_supported':
        baseLabel = 'Source-supported';
        visible = true;
        needsAttribution = true;
        break;
      case 'ai_checked':
        baseLabel = 'AI-translated, checked';
        visible = true;
        needsAttribution = false;
        break;
      case 'ai_unverified':
        baseLabel = 'AI-translated, unverified';
        visible = true;
        needsAttribution = false;
        break;
      case 'source_sense_unconfirmed':
        baseLabel = 'Source-recorded, sense unconfirmed';
        visible = true;
        needsAttribution = true;
        break;
      default:
        baseLabel = 'Unverified — source unknown';
        visible = true;
        needsAttribution = false;
    }

    final attribution = needsAttribution ? source : null;
    return TranslationStatus(
      code: code,
      label: attribution == null ? baseLabel : '$baseLabel · $attribution',
      visible: visible,
      attribution: attribution,
    );
  }
}
