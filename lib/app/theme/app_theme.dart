import 'package:flutter/material.dart';

import '../../core/constants.dart';

/// Material theme derived from the app's sky/white identity.
/// Dark theme is a later-phase refinement.
abstract final class AppTheme {
  static ThemeData get light => ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: LanguageColors.brand,
          brightness: Brightness.light,
        ),
        scaffoldBackgroundColor: const Color(0xFFF7FBFF),
        appBarTheme: const AppBarTheme(
          backgroundColor: Color(0xFFF7FBFF),
          foregroundColor: Color(0xFF0F172A),
          elevation: 0,
        ),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: Colors.white,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(16),
            borderSide: const BorderSide(color: Color(0xFFE2E8F0)),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(16),
            borderSide: const BorderSide(color: Color(0xFFE2E8F0)),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(16),
            borderSide: const BorderSide(
                color: LanguageColors.brand, width: 1.6),
          ),
        ),
      );
}
