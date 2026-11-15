import 'package:flutter/material.dart';

/// Semantic colour tokens for the two app themes.
///
/// Why this exists: before Phase 1 the app had one light theme plus ~86
/// hard-coded `Color(0x…)` literals across 14 widgets, so a dark theme could
/// never be added without white boxes and invisible text. Widgets now read
/// semantic names only; the literal values live here (light + dark) and
/// nowhere else.
///
/// Every text/background pair in this file is asserted at >= 4.5:1 by
/// `test/theme_contrast_test.dart`, and `test/no_raw_colors_test.dart` fails
/// if a `Color(0x…)` literal appears outside the allowlisted token files.
class AppTokens extends ThemeExtension<AppTokens> {
  /// Page background (Scaffold).
  final Color page;

  /// Card / tile / filled-input surface.
  final Color surface;

  /// Inset surface: chips, quote boxes, grouped rows behind a card.
  final Color surfaceMuted;

  /// Hairline border for cards, inputs, dividers.
  final Color border;

  /// Primary reading colour.
  final Color textPrimary;

  /// Secondary/helper colour. 5.96:1 on [page] in light, 9.13:1 in dark.
  final Color textMuted;

  /// Accent for icons, progress, links-as-icons. Not for small text: see
  /// [brandInk].
  final Color brand;

  /// Soft accent fill behind [brandInk].
  final Color brandSoft;

  /// Accent colour safe for text (>= 4.5:1 on [surface] and [brandSoft]).
  final Color brandInk;

  /// Solid accent fill (badges, buttons) — always paired with [onBrandFill].
  final Color brandFill;

  /// Text/icon colour on [brandFill]. Never hard-code `Colors.white` there:
  /// white on the old #0EA5E9 sky was only 2.77:1.
  final Color onBrandFill;

  /// Chinese accent.
  final Color zh;
  final Color zhSoft;
  final Color zhInk;

  /// Nepali accent.
  final Color ne;
  final Color neSoft;
  final Color neInk;
  final Color neFill;
  final Color onNeFill;

  /// Amber warning block.
  final Color warning;
  final Color warningSoft;
  final Color warningInk;

  /// Green "resolved OK" block.
  final Color success;
  final Color successSoft;
  final Color successInk;

  const AppTokens({
    required this.page,
    required this.surface,
    required this.surfaceMuted,
    required this.border,
    required this.textPrimary,
    required this.textMuted,
    required this.brand,
    required this.brandSoft,
    required this.brandInk,
    required this.brandFill,
    required this.onBrandFill,
    required this.zh,
    required this.zhSoft,
    required this.zhInk,
    required this.ne,
    required this.neSoft,
    required this.neInk,
    required this.neFill,
    required this.onNeFill,
    required this.warning,
    required this.warningSoft,
    required this.warningInk,
    required this.success,
    required this.successSoft,
    required this.successInk,
  });

  /// Light theme.
  ///
  /// The three language accents (`brand` / `zh` / `ne`) are also used as text
  /// (language labels, speaker icons, the dot that marks a row) and as borders,
  /// so each one must clear 4.5:1 on white/page rather than only 3:1. The
  /// brighter `#0EA5E9` sky and `#D97706` amber were measured at 2.77:1 and
  /// 3.19:1 on white and are therefore only available as `brandFill`/`neFill`
  /// backgrounds, never as text. Hue is unchanged; only the lightness step.
  static const AppTokens light = AppTokens(
    page: Color(0xFFF7FBFF),
    surface: Color(0xFFFFFFFF),
    surfaceMuted: Color(0xFFF1F5F9),
    border: Color(0xFFE2E8F0),
    textPrimary: Color(0xFF0F172A),
    textMuted: Color(0xFF52627A),
    brand: Color(0xFF0369A1),
    brandSoft: Color(0xFFE0F2FE),
    brandInk: Color(0xFF0369A1),
    brandFill: Color(0xFF0369A1),
    onBrandFill: Color(0xFFFFFFFF),
    zh: Color(0xFFBE123C),
    zhSoft: Color(0xFFFFE4E6),
    zhInk: Color(0xFFBE123C),
    ne: Color(0xFFB45309),
    neSoft: Color(0xFFFFFBEB),
    neInk: Color(0xFFB45309),
    neFill: Color(0xFFB45309),
    onNeFill: Color(0xFFFFFFFF),
    warning: Color(0xFFB45309),
    warningSoft: Color(0xFFFFFBEB),
    warningInk: Color(0xFF92400E),
    success: Color(0xFF15803D),
    successSoft: Color(0xFFF0FDF4),
    successInk: Color(0xFF15803D),
  );

  static const AppTokens dark = AppTokens(
    page: Color(0xFF0B1220),
    surface: Color(0xFF141D2E),
    surfaceMuted: Color(0xFF1C2637),
    border: Color(0xFF2A3550),
    textPrimary: Color(0xFFE6EDF8),
    textMuted: Color(0xFFA9B6CB),
    brand: Color(0xFF38BDF8),
    brandSoft: Color(0xFF0C2A3D),
    brandInk: Color(0xFF7DD3FC),
    brandFill: Color(0xFF38BDF8),
    onBrandFill: Color(0xFF0B1220),
    zh: Color(0xFFFB7185),
    zhSoft: Color(0xFF3A1220),
    zhInk: Color(0xFFFDA4AF),
    ne: Color(0xFFFBBF24),
    neSoft: Color(0xFF3A2A0B),
    neInk: Color(0xFFFCD34D),
    neFill: Color(0xFFFBBF24),
    onNeFill: Color(0xFF0B1220),
    warning: Color(0xFFFBBF24),
    warningSoft: Color(0xFF3A2A0B),
    warningInk: Color(0xFFFCD34D),
    success: Color(0xFF4ADE80),
    successSoft: Color(0xFF0F2A1A),
    successInk: Color(0xFF86EFAC),
  );

  @override
  AppTokens copyWith({
    Color? page,
    Color? surface,
    Color? surfaceMuted,
    Color? border,
    Color? textPrimary,
    Color? textMuted,
    Color? brand,
    Color? brandSoft,
    Color? brandInk,
    Color? brandFill,
    Color? onBrandFill,
    Color? zh,
    Color? zhSoft,
    Color? zhInk,
    Color? ne,
    Color? neSoft,
    Color? neInk,
    Color? neFill,
    Color? onNeFill,
    Color? warning,
    Color? warningSoft,
    Color? warningInk,
    Color? success,
    Color? successSoft,
    Color? successInk,
  }) {
    return AppTokens(
      page: page ?? this.page,
      surface: surface ?? this.surface,
      surfaceMuted: surfaceMuted ?? this.surfaceMuted,
      border: border ?? this.border,
      textPrimary: textPrimary ?? this.textPrimary,
      textMuted: textMuted ?? this.textMuted,
      brand: brand ?? this.brand,
      brandSoft: brandSoft ?? this.brandSoft,
      brandInk: brandInk ?? this.brandInk,
      brandFill: brandFill ?? this.brandFill,
      onBrandFill: onBrandFill ?? this.onBrandFill,
      zh: zh ?? this.zh,
      zhSoft: zhSoft ?? this.zhSoft,
      zhInk: zhInk ?? this.zhInk,
      ne: ne ?? this.ne,
      neSoft: neSoft ?? this.neSoft,
      neInk: neInk ?? this.neInk,
      neFill: neFill ?? this.neFill,
      onNeFill: onNeFill ?? this.onNeFill,
      warning: warning ?? this.warning,
      warningSoft: warningSoft ?? this.warningSoft,
      warningInk: warningInk ?? this.warningInk,
      success: success ?? this.success,
      successSoft: successSoft ?? this.successSoft,
      successInk: successInk ?? this.successInk,
    );
  }

  @override
  AppTokens lerp(ThemeExtension<AppTokens>? other, double t) {
    if (other is! AppTokens) return this;
    Color mix(Color a, Color b) => Color.lerp(a, b, t) ?? a;
    return AppTokens(
      page: mix(page, other.page),
      surface: mix(surface, other.surface),
      surfaceMuted: mix(surfaceMuted, other.surfaceMuted),
      border: mix(border, other.border),
      textPrimary: mix(textPrimary, other.textPrimary),
      textMuted: mix(textMuted, other.textMuted),
      brand: mix(brand, other.brand),
      brandSoft: mix(brandSoft, other.brandSoft),
      brandInk: mix(brandInk, other.brandInk),
      brandFill: mix(brandFill, other.brandFill),
      onBrandFill: mix(onBrandFill, other.onBrandFill),
      zh: mix(zh, other.zh),
      zhSoft: mix(zhSoft, other.zhSoft),
      zhInk: mix(zhInk, other.zhInk),
      ne: mix(ne, other.ne),
      neSoft: mix(neSoft, other.neSoft),
      neInk: mix(neInk, other.neInk),
      neFill: mix(neFill, other.neFill),
      onNeFill: mix(onNeFill, other.onNeFill),
      warning: mix(warning, other.warning),
      warningSoft: mix(warningSoft, other.warningSoft),
      warningInk: mix(warningInk, other.warningInk),
      success: mix(success, other.success),
      successSoft: mix(successSoft, other.successSoft),
      successInk: mix(successInk, other.successInk),
    );
  }
}

/// `context.tokens` — one lookup for the semantic palette.
///
/// Falls back to the plain palette for the current brightness when a route is
/// mounted under a Theme that does not carry the extension (a nested Theme
/// override, a widget test with a bare MaterialApp). A screen must never crash
/// just because the tokens are missing — the app theme always provides them.
extension AppTokensX on BuildContext {
  AppTokens get tokens =>
      Theme.of(this).extension<AppTokens>() ??
      (Theme.of(this).brightness == Brightness.dark
          ? AppTokens.dark
          : AppTokens.light);
}
