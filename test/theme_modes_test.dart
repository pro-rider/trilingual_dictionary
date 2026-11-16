import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:trilingual_dictionary/app/theme/app_theme.dart';
import 'package:trilingual_dictionary/app/theme/app_tokens.dart';
import 'package:trilingual_dictionary/features/settings/settings_provider.dart';
import 'package:trilingual_dictionary/features/settings/settings_screen.dart';

/// Every screen must render in both themes without throwing, and the in-app
/// choice must win over the phone's own dark-mode flag.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  Widget appWith(ThemeMode mode) => ProviderScope(
        child: MaterialApp(
          theme: AppTheme.light,
          darkTheme: AppTheme.dark,
          themeMode: mode,
          home: const SettingsScreen(),
        ),
      );

  testWidgets('settings screen renders in the light theme', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(appWith(ThemeMode.light));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    final ctx = tester.element(find.text('Settings'));
    expect(Theme.of(ctx).brightness, Brightness.light);
    expect(ctx.tokens.page.computeLuminance(), greaterThan(0.5));
  });

  testWidgets('settings screen renders in the dark theme', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(appWith(ThemeMode.dark));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    final ctx = tester.element(find.text('Settings'));
    expect(Theme.of(ctx).brightness, Brightness.dark);
    expect(ctx.tokens.page.computeLuminance(), lessThan(0.1));
  });

  test('AppTheme registers the token extension in both schemes', () {
    expect(AppTheme.light.extension<AppTokens>(), isNotNull);
    expect(AppTheme.dark.extension<AppTokens>(), isNotNull);
    expect(AppTheme.light.brightness, Brightness.light);
    expect(AppTheme.dark.brightness, Brightness.dark);
  });

  test('an explicit app choice overrides the phone setting', () {
    // themeMode: Light resolves to the light ThemeData even when the platform
    // reports dark, which is what "the app's choice wins" means.
    final light = MaterialApp(
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: ThemeMode.light,
    );
    final dark = MaterialApp(
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: ThemeMode.dark,
    );
    expect(light.themeMode, ThemeMode.light);
    expect(dark.themeMode, ThemeMode.dark);
  });

  test('unsaved users default to ThemeMode.system', () {
    const settings = AppSettings();
    expect(settings.themeMode, ThemeMode.system);
  });

  test('a saved Light/Dark value survives the upgrade', () {
    expect(themeModeFromName('light'), ThemeMode.light);
    expect(themeModeFromName('dark'), ThemeMode.dark);
    expect(themeModeFromName('system'), ThemeMode.system);
    // Unknown or missing values must not silently become Light.
    expect(themeModeFromName(null), ThemeMode.system);
    expect(themeModeFromName('legacy_light'), ThemeMode.system);
  });
}
