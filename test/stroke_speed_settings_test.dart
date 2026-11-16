import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:trilingual_dictionary/features/settings/settings_provider.dart';

/// `settings.strokeSpeed` is the only setting the character panel adds. It must
/// survive a restart and stay inside the slider's range.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('stroke speed is stored and read back', () async {
    SharedPreferences.setMockInitialValues({'settings.strokeSpeed': 1.75});
    final container = ProviderContainer();
    addTearDown(container.dispose);
    await container.read(settingsProvider.notifier).ready;

    expect(container.read(settingsProvider).strokeSpeed, 1.75);
    expect(await SharedPreferences.getInstance()
        .then((p) => p.getDouble('settings.strokeSpeed')), 1.75);
  });

  test('changing the speed writes the key immediately', () async {
    SharedPreferences.setMockInitialValues({});
    final container = ProviderContainer();
    addTearDown(container.dispose);
    await container.read(settingsProvider.notifier).ready;

    container.read(settingsProvider.notifier).setStrokeSpeed(0.5);
    expect(container.read(settingsProvider).strokeSpeed, 0.5);
    await pumpEventQueue(); // the write is fire-and-forget; let it land

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getDouble('settings.strokeSpeed'), 0.5);
  });

  test('out-of-range values are clamped, not stored', () async {
    SharedPreferences.setMockInitialValues({'settings.strokeSpeed': 12.0});
    final container = ProviderContainer();
    addTearDown(container.dispose);
    await container.read(settingsProvider.notifier).ready;

    expect(container.read(settingsProvider).strokeSpeed, 2.0);
    container.read(settingsProvider.notifier).setStrokeSpeed(0.01);
    expect(container.read(settingsProvider).strokeSpeed, 0.5);
  });
}
