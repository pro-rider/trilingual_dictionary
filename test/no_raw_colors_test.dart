import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// Guards the token migration: a widget may not hard-code a colour.
///
/// Allowed files are the ones whose job is to hold literal colours:
///   * `lib/app/theme/app_tokens.dart` — the light/dark palettes
///   * `lib/app/theme/app_theme.dart`  — component theming + system overlay style
///   * `lib/core/constants.dart`       — the language identity colours used as
///                                       the seed for both schemes
void main() {
  test('no hard-coded colours outside the token files', () {
    const allowedSuffixes = <String>[
      'lib/app/theme/app_tokens.dart',
      'lib/app/theme/app_theme.dart',
      'lib/core/constants.dart',
    ];

    // Each entry: what the rule catches and why it is a problem.
    final rules = <String, RegExp>{
      'literal hex': RegExp(r'Color\(0x'),
      'named palette': RegExp(r'\bColors\.'),
      'Color.fromARGB': RegExp(r'Color\.fromARGB'),
      'Color.fromRGBO': RegExp(r'Color\.fromRGBO'),
      'literal opacity': RegExp(r'\.withOpacity\('),
    };

    final offenders = <String>[];
    var scanned = 0;

    final dir = Directory('lib');
    expect(dir.existsSync(), isTrue, reason: 'run from the package root');

    for (final entity in dir.listSync(recursive: true)) {
      if (entity is! File || !entity.path.endsWith('.dart')) continue;
      final rel = entity.path.replaceAll(r'\', '/');
      if (allowedSuffixes.any(rel.endsWith)) continue;
      scanned++;

      final lines = entity.readAsLinesSync();
      for (var i = 0; i < lines.length; i++) {
        // A comment that explains the rule must not trip it.
        final code = lines[i].trimLeft();
        if (code.startsWith('//') || code.startsWith('///')) continue;
        for (final rule in rules.entries) {
          if (rule.value.hasMatch(lines[i])) {
            offenders.add('$rel:${i + 1} [${rule.key}] ${lines[i].trim()}');
          }
        }
      }
    }

    expect(scanned, greaterThan(30), reason: 'expected to scan the app sources');
    expect(offenders, isEmpty,
        reason: 'Use Theme.of(context).extension<AppTokens>() / context.tokens '
            'instead:\n${offenders.join('\n')}');
  });

  test('the allowlisted files are the only place literals may live', () {
    // Sanity check: if the palette file lost its literals, the rule above
    // would pass for the wrong reason.
    final tokens = File('lib/app/theme/app_tokens.dart').readAsStringSync();
    expect(RegExp(r'Color\(0x').allMatches(tokens).length,
        greaterThanOrEqualTo(40),
        reason: 'app_tokens.dart should still hold both palettes');
  });
}
