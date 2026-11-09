import 'dart:convert';

import 'translation_status.dart';

/// One stored translation candidate (a row of `translations`).
class TranslationCandidate {
  const TranslationCandidate({
    this.translationId,
    this.senseKey,
    required this.text,
    this.supersedesId,
    this.publicationStatus,
    this.humanVerification,
    this.validationStatus,
    this.evidenceStrength,
    this.generationMethod,
    this.originSource,
    this.originMethod,
    this.evidenceLanguage,
    this.senseMatchMethod,
  });

  final int? translationId;

  /// Which sense this row belongs to. Used to refuse cross-sense supersession.
  final String? senseKey;
  final String text;
  final int? supersedesId;
  final String? publicationStatus;
  final String? humanVerification;
  final String? validationStatus;
  final String? evidenceStrength;
  final String? generationMethod;
  final String? originSource;
  final String? originMethod;
  final String? evidenceLanguage;
  final String? senseMatchMethod;

  bool get isQuarantined => publicationStatus == 'quarantined';

  factory TranslationCandidate.fromMap(Map<String, dynamic> m) => TranslationCandidate(
        translationId: m['translation_id'] as int?,
        senseKey: m['sense_key'] as String?,
        text: (m['text'] ?? '') as String,
        supersedesId: m['supersedes_id'] as int?,
        publicationStatus: m['publication_status'] as String?,
        humanVerification: m['human_verification'] as String?,
        validationStatus: m['validation_status'] as String?,
        evidenceStrength: m['evidence_strength'] as String?,
        generationMethod: m['generation_method'] as String?,
        originSource: m['origin_source'] as String?,
        originMethod: m['origin_method'] as String?,
        evidenceLanguage: m['evidence_language'] as String?,
        senseMatchMethod: m['sense_match_method'] as String?,
      );
}

/// Where the displayed text came from.
enum NepaliSource { dictionary, governance, none }

/// The one Nepali meaning the UI renders for one sense, plus its label.
class ResolvedNepali {
  const ResolvedNepali({
    required this.text,
    required this.source,
    required this.status,
    required this.visible,
    this.problem,
  });

  final String text;
  final NepaliSource source;
  final TranslationStatus status;
  final bool visible;

  /// Non-null when stored data is broken; callers must fail closed.
  final String? problem;

  static ResolvedNepali none(TranslationStatus status) =>
      ResolvedNepali(text: '', source: NepaliSource.none, status: status, visible: false);
}

ResolvedNepali _fromDictionary(String text) => ResolvedNepali(
      text: text,
      source: NepaliSource.dictionary,
      status: TranslationStatus.derive(),
      visible: text.isNotEmpty,
    );

/// The one resolution rule, mirrored from `backend/app/translations/resolve.py`.
///
/// Order: quarantine hides the sense > a retired row falls back to the
/// dictionary > a blank governance value falls back to the dictionary > an
/// identical copy is shown once, as the dictionary value > otherwise the
/// governance value is shown. Widgets must never do this themselves.
ResolvedNepali resolveNepali({
  String? dictionaryText,
  TranslationStatus? governanceStatus,
  String? governanceText,
  String? governancePublicationStatus,
  bool hasSuccessor = false,
}) {
  final legacy = (dictionaryText ?? '').trim();
  final storeText = (governanceText ?? '').trim();

  if (governancePublicationStatus == 'quarantined') {
    return ResolvedNepali.none(TranslationStatus.derive(publicationStatus: 'quarantined'));
  }
  if (hasSuccessor) {
    return _fromDictionary(legacy);
  }
  if (governanceStatus == null || storeText.isEmpty) {
    return _fromDictionary(legacy);
  }
  if (storeText == legacy) {
    // The same text in both places is one meaning, attributed to the original.
    return ResolvedNepali(
      text: storeText,
      source: NepaliSource.dictionary,
      status: governanceStatus,
      visible: governanceStatus.visible && storeText.isNotEmpty,
    );
  }
  return ResolvedNepali(
    text: governanceText!,
    source: NepaliSource.governance,
    status: governanceStatus,
    visible: governanceStatus.visible,
  );
}

/// Structural checks on a supersession chain. A repository must fail closed
/// when any of these is non-empty rather than pick a meaning anyway.
class ChainIntegrity {
  const ChainIntegrity({
    required this.cycles,
    required this.branchedParents,
    required this.crossSense,
  });

  final List<int> cycles;

  /// Parent id -> more than one successor, so "the active row" is ambiguous.
  final Map<int, List<int>> branchedParents;

  /// Successor whose sense differs from the row it supersedes.
  final List<int> crossSense;

  bool get ok => cycles.isEmpty && branchedParents.isEmpty && crossSense.isEmpty;

  static ChainIntegrity analyze(List<TranslationCandidate> rows) {
    final byId = <int, TranslationCandidate>{};
    for (final r in rows) {
      if (r.translationId != null) byId[r.translationId!] = r;
    }
    final cycles = <int>{};
    for (final r in rows) {
      final seen = <int>{};
      TranslationCandidate? cur = r;
      var steps = 0;
      while (cur?.supersedesId != null) {
        if (seen.contains(cur!.supersedesId) || steps > rows.length) {
          if (r.translationId != null) cycles.add(r.translationId!);
          break;
        }
        seen.add(cur.translationId ?? -1);
        cur = byId[cur.supersedesId!];
        steps++;
      }
    }
    final children = <int, List<int>>{};
    final crossSense = <int>[];
    for (final r in rows) {
      if (r.supersedesId == null) continue;
      children.putIfAbsent(r.supersedesId!, () => <int>[]).add(r.translationId ?? -1);
      final parent = byId[r.supersedesId!];
      if (parent != null && parent.senseKey != null && r.senseKey != null &&
          parent.senseKey != r.senseKey) {
        crossSense.add(r.translationId ?? -1);
      }
    }
    return ChainIntegrity(
      cycles: cycles.toList()..sort(),
      branchedParents: {
        for (final e in children.entries)
          if (e.value.length > 1) e.key: e.value,
      },
      crossSense: crossSense..sort(),
    );
  }
}

/// Backwards-compatible helpers kept for callers that reason about chains.
class TranslationResolution {
  const TranslationResolution._();

  static List<TranslationCandidate> leaves(List<TranslationCandidate> rows) {
    final superseded = <int>{};
    for (final r in rows) {
      if (r.supersedesId != null) superseded.add(r.supersedesId!);
    }
    return rows
        .where((r) => r.translationId == null || !superseded.contains(r.translationId))
        .toList();
  }

  /// Follow a stored translation id to the row the UI should open.
  /// `policy` is `active` (default) or `pinned`; user data is never rewritten.
  static Map<String, dynamic> resolveReference(
    int translationId,
    List<TranslationCandidate> allRows, {
    String policy = 'active',
  }) {
    final row = allRows.where((r) => r.translationId == translationId).toList();
    if (row.isEmpty) {
      return {
        'requested_id': translationId,
        'active_id': null,
        'found': false,
        'policy': policy,
      };
    }
    final senseRows = allRows
        .where((r) => r.supersedesId == translationId || r.translationId == translationId)
        .toList();
    var target = translationId;
    if (policy == 'active') {
      var cur = translationId;
      var guard = 0;
      while (guard <= allRows.length) {
        final next = senseRows.where((r) => r.supersedesId == cur).toList();
        if (next.isEmpty) break;
        cur = next.first.translationId ?? cur;
        guard++;
      }
      target = cur;
    }
    return {
      'requested_id': translationId,
      'active_id': target,
      'found': true,
      'policy': policy,
      'requested_is_active': target == translationId,
    };
  }

  static Map<String, dynamic> loadGolden(String raw) {
    final decoded = jsonDecode(raw) as Map<String, dynamic>;
    if (!decoded.containsKey('version') || !decoded.containsKey('cases')) {
      throw const FormatException('golden vectors need version and cases');
    }
    return decoded;
  }
}
