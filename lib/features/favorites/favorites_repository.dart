import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Favorites live on the device and only on the device.
///
/// Cloud sync is out of v1 (A28): there is no server-side favorites table, no
/// Supabase client and no key in the app. A previous version merged rows from a
/// Supabase table; that path is gone, so a network failure cannot silently
/// resurrect entries the user deleted, and uninstalling is the only thing that
/// loses data.
final favoritesProvider =
    AsyncNotifierProvider<FavoritesRepository, List<String>>(
        FavoritesRepository.new);

class FavoritesRepository extends AsyncNotifier<List<String>> {
  static const _localKey = 'favorites';

  @override
  Future<List<String>> build() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getStringList(_localKey) ?? <String>[];
  }

  Future<void> toggle(String entryId) async {
    final current = List<String>.from(state.value ?? const []);
    if (!current.remove(entryId)) {
      current.add(entryId);
    }
    current.sort();
    state = AsyncData(current);
    await _saveLocal(current);
  }

  /// Used by "Log out and clear local data" — the one place favorites are
  /// removed on purpose, and only when the user asks for it.
  Future<void> clear() async {
    state = const AsyncData(<String>[]);
    await _saveLocal(const <String>[]);
  }

  Future<void> _saveLocal(List<String> value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(_localKey, value);
  }
}
