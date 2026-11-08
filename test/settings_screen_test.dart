import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:trilingual_dictionary/features/settings/settings_screen.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('settings screen lays out (trailing widgets sized)', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(
      const ProviderScope(
        child: MaterialApp(home: SettingsScreen()),
      ),
    );
    await tester.pumpAndSettle();

    // Regression: an unbounded Slider in ListTile.trailing threw
    // "Trailing widget consumes the entire tile width" and left the route blank.
    expect(tester.takeException(), isNull);
    expect(find.text('Settings'), findsOneWidget);
    expect(find.text('Text size'), findsOneWidget);
    expect(find.byType(Slider), findsOneWidget);

    // Scroll to the diagnostic entry point added for prompt V1.
    await tester.scrollUntilVisible(find.text('TTS diagnosis'), 200,
        scrollable: find.byType(Scrollable).first);
    expect(find.text('TTS diagnosis'), findsOneWidget);
  });
}
