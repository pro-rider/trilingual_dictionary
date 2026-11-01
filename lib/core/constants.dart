import 'package:flutter/material.dart';

/// Central language identities and app constants.
///
/// The app owns a fixed 3-language model:
///   English = sky, 中文 = rose, नेपाली = amber.
abstract final class LanguageColors {
  static const Color en = Color(0xFF0EA5E9); // sky
  static const Color zh = Color(0xFFE11D48); // rose
  static const Color ne = Color(0xFFD97706); // amber

  static const Color brand = Color(0xFF0EA5E9);
  static const Color brandSoft = Color(0xFFE0F2FE);
  static const Color zhSoft = Color(0xFFFFE4E6);
  static const Color neSoft = Color(0xFFFFFBEB);
}

abstract final class AppConstants {
  /// Bundled offline dictionary snapshot (v1 data source).
  static const String offlineDatasetAsset = 'assets/data/en_zh_ne.json';

  /// Bump when the bundled dataset changes.
  static const int datasetVersion = 1;
}
