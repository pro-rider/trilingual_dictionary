import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../../core/supabase_config.dart';

/// Favorites: always stored locally (offline), and synced to Supabase when a
/// user is signed in and the project is configured. Failures are swallowed so
/// a network issue never breaks the app.
final favoritesProvider =
    AsyncNotifierProvider<FavoritesRepository, List<String>>(
        FavoritesRepository.new);

class FavoritesRepository extends AsyncNotifier<List<String>> {
  static const _localKey = 'favorites';

  @override
  Future<List<String>> build() async {
    final prefs = await SharedPreferences.getInstance();
    final local = prefs.getStringList(_localKey) ?? <String>[];
    await _syncFromRemote(local);
    return local;
  }

  Future<void> _syncFromRemote(List<String> local) async {
    final client = _client();
    if (client == null) return;
    try {
      final user = client.auth.currentUser;
      if (user == null) return;
      final rows = await client
          .from(SupabaseConfig.favoritesTable)
          .select('entry_id');
      final remote = (rows as List)
          .map((r) => (r as Map)['entry_id'] as String)
          .toSet();
      final merged = {...local, ...remote}.toList()..sort();
      await _saveLocal(merged);
      state = AsyncData(merged);
    } catch (_) {
      // Remote unavailable → keep local.
    }
  }

  Future<void> toggle(String entryId) async {
    final current = List<String>.from(state.value ?? const []);
    final contains = current.contains(entryId);
    if (contains) {
      current.remove(entryId);
    } else {
      current.add(entryId);
    }
    current.sort();
    state = AsyncData(current);
    await _saveLocal(current);

    final client = _client();
    final user = client?.auth.currentUser;
    if (client == null || user == null) return;
    try {
      final table = client.from(SupabaseConfig.favoritesTable);
      if (contains) {
        await table
            .delete()
            .eq('user_id', user.id)
            .eq('entry_id', entryId);
      } else {
        await table.insert({'user_id': user.id, 'entry_id': entryId});
      }
    } catch (_) {
      // Remote sync failed → local copy still holds the change.
    }
  }

  Future<void> _saveLocal(List<String> value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(_localKey, value);
  }

  SupabaseClient? _client() =>
      SupabaseConfig.isConfigured ? Supabase.instance.client : null;
}
