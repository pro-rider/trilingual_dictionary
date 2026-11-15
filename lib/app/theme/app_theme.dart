import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/constants.dart';
import 'app_tokens.dart';

/// Material 3 themes derived from the app's sky/white identity.
///
/// Both brightnesses are produced by one builder so shapes, typography and
/// component themes cannot drift apart. Every colour comes from [AppTokens];
/// widgets never hard-code one.
abstract final class AppTheme {
  static ThemeData get light => _build(Brightness.light, AppTokens.light);

  static ThemeData get dark => _build(Brightness.dark, AppTokens.dark);

  /// Status-bar and navigation-bar icon appearance.
  ///
  /// Android 15+ draws edge-to-edge, so the bars are transparent and only the
  /// icon brightness decides whether they are readable. Light bars in a dark
  /// app (or dark bars on the light page) are the classic "invisible clock /
  /// invisible back button" bug, so the value is derived from the tokens, not
  /// left to the platform default.
  static SystemUiOverlayStyle overlayFor(Brightness brightness) {
    final tokens =
        brightness == Brightness.dark ? AppTokens.dark : AppTokens.light;
    final dark = brightness == Brightness.dark;
    return SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: dark ? Brightness.light : Brightness.dark,
      statusBarBrightness: dark ? Brightness.dark : Brightness.light,
      systemNavigationBarColor: tokens.page,
      systemNavigationBarDividerColor: tokens.border,
      systemNavigationBarIconBrightness:
          dark ? Brightness.light : Brightness.dark,
    );
  }

  static ThemeData _build(Brightness brightness, AppTokens tokens) {
    final scheme = ColorScheme.fromSeed(
      seedColor: LanguageColors.brand,
      brightness: brightness,
    ).copyWith(
      primary: tokens.brandFill,
      onPrimary: tokens.onBrandFill,
      surface: tokens.surface,
      onSurface: tokens.textPrimary,
      onSurfaceVariant: tokens.textMuted,
      outline: tokens.border,
      outlineVariant: tokens.border,
      surfaceContainerHighest: tokens.surfaceMuted,
      tertiary: tokens.neFill,
      onTertiary: tokens.onNeFill,
      error: tokens.zh,
    );

    final base = ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: scheme,
      scaffoldBackgroundColor: tokens.page,
      canvasColor: tokens.page,
      dividerTheme: DividerThemeData(color: tokens.border, thickness: 1),
      extensions: <ThemeExtension<dynamic>>[tokens],
    );

    return base.copyWith(
      textTheme: base.textTheme.apply(
        bodyColor: tokens.textPrimary,
        displayColor: tokens.textPrimary,
      ),
      iconTheme: IconThemeData(color: tokens.textPrimary),
      primaryIconTheme: IconThemeData(color: tokens.brandInk),
      appBarTheme: AppBarTheme(
        backgroundColor: tokens.page,
        foregroundColor: tokens.textPrimary,
        elevation: 0,
        scrolledUnderElevation: 0,
        surfaceTintColor: Colors.transparent,
        systemOverlayStyle: overlayFor(brightness),
      ),
      cardTheme: CardThemeData(
        color: tokens.surface,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: BorderSide(color: tokens.border),
        ),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: tokens.surface,
        surfaceTintColor: Colors.transparent,
        titleTextStyle: base.textTheme.titleLarge?.copyWith(
          color: tokens.textPrimary,
        ),
        contentTextStyle: base.textTheme.bodyMedium?.copyWith(
          color: tokens.textPrimary,
        ),
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: tokens.surface,
        surfaceTintColor: Colors.transparent,
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: tokens.surfaceMuted,
        contentTextStyle: TextStyle(color: tokens.textPrimary),
        actionTextColor: tokens.brandInk,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: tokens.surface,
        hintStyle: TextStyle(color: tokens.textMuted),
        labelStyle: TextStyle(color: tokens.textMuted),
        border: _border(tokens, tokens.border),
        enabledBorder: _border(tokens, tokens.border),
        focusedBorder: _border(tokens, tokens.brand, width: 1.6),
        errorBorder: _border(tokens, tokens.zh),
      ),
      switchTheme: SwitchThemeData(
        thumbColor: WidgetStateProperty.resolveWith(
          (states) => states.contains(WidgetState.selected)
              ? tokens.brandFill
              : tokens.surfaceMuted,
        ),
        trackColor: WidgetStateProperty.resolveWith(
          (states) => states.contains(WidgetState.selected)
              ? tokens.brandSoft
              : tokens.surfaceMuted,
        ),
      ),
      sliderTheme: SliderThemeData(
        activeTrackColor: tokens.brandFill,
        thumbColor: tokens.brandFill,
        inactiveTrackColor: tokens.surfaceMuted,
      ),
      chipTheme: base.chipTheme.copyWith(
        backgroundColor: tokens.surfaceMuted,
        labelStyle: TextStyle(color: tokens.textMuted),
        side: BorderSide(color: tokens.border),
      ),
      popupMenuTheme: PopupMenuThemeData(
        color: tokens.surface,
        surfaceTintColor: Colors.transparent,
        textStyle: TextStyle(color: tokens.textPrimary),
      ),
      listTileTheme: ListTileThemeData(
        iconColor: tokens.brandInk,
        textColor: tokens.textPrimary,
      ),
      dividerColor: tokens.border,
    );
  }

  static OutlineInputBorder _border(AppTokens tokens, Color color,
          {double width = 1}) =>
      OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: BorderSide(color: color, width: width),
      );
}
