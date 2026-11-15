import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trilingual_dictionary/app/theme/app_tokens.dart';

/// WCAG 2.1 relative-contrast maths, the same formula the palette was chosen
/// with. Text pairs must reach 4.5:1 (normal-weight body text); the solid
/// accent fills use the same bar because their label is small (11–12 sp).
double _ratio(Color a, Color b) {
  final la = a.computeLuminance();
  final lb = b.computeLuminance();
  final hi = la > lb ? la : lb;
  final lo = la > lb ? lb : la;
  return (hi + 0.05) / (lo + 0.05);
}

void _checkPair(String label, Color fg, Color bg) {
  final r = _ratio(fg, bg);
  // ignore: avoid_print
  print('${label.padRight(34)} ${r.toStringAsFixed(2)}:1');
  expect(r, greaterThanOrEqualTo(4.5),
      reason: '$label only reaches ${r.toStringAsFixed(2)}:1');
}

void _checkTheme(String name, AppTokens t) {
  // ignore: avoid_print
  print('--- $name');
  _checkPair('$name textPrimary / page', t.textPrimary, t.page);
  _checkPair('$name textPrimary / surface', t.textPrimary, t.surface);
  _checkPair('$name textPrimary / surfaceMuted', t.textPrimary, t.surfaceMuted);
  _checkPair('$name textMuted / page', t.textMuted, t.page);
  _checkPair('$name textMuted / surface', t.textMuted, t.surface);
  _checkPair('$name textMuted / surfaceMuted', t.textMuted, t.surfaceMuted);
  _checkPair('$name brandInk / surface', t.brandInk, t.surface);
  _checkPair('$name brandInk / brandSoft', t.brandInk, t.brandSoft);
  _checkPair('$name zhInk / zhSoft', t.zhInk, t.zhSoft);
  _checkPair('$name neInk / neSoft', t.neInk, t.neSoft);
  _checkPair('$name warningInk / warningSoft', t.warningInk, t.warningSoft);
  _checkPair('$name successInk / successSoft', t.successInk, t.successSoft);
  _checkPair('$name onBrandFill / brandFill', t.onBrandFill, t.brandFill);
  _checkPair('$name onNeFill / neFill', t.onNeFill, t.neFill);
  _checkPair('$name brand / surface (accent text)', t.brand, t.surface);
  _checkPair('$name zh / surface (accent text)', t.zh, t.surface);
  _checkPair('$name ne / surface (accent text)', t.ne, t.surface);
}

void main() {
  test('light theme text and fill pairs clear 4.5:1', () {
    _checkTheme('light', AppTokens.light);
  });

  test('dark theme text and fill pairs clear 4.5:1', () {
    _checkTheme('dark', AppTokens.dark);
  });

  test('both palettes keep a visible page/surface separation', () {
    for (final t in [AppTokens.light, AppTokens.dark]) {
      expect(_ratio(t.page, t.surface), lessThan(1.35),
          reason: 'page and surface must stay a subtle step, not a jump');
    }
  });

  test('lerp stays inside the two endpoints', () {
    final mid = AppTokens.light.lerp(AppTokens.dark, 0.5);
    expect(mid.textPrimary, isNot(equals(AppTokens.light.textPrimary)));
    expect(mid.textPrimary, isNot(equals(AppTokens.dark.textPrimary)));
  });
}
