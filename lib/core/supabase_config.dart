import 'package:flutter/foundation.dart';

/// Supabase project configuration.
///
/// v1 runs fully offline, so Supabase is optional: until you paste your real
/// project URL + anon key here (from the Supabase dashboard), the app keeps
/// working with local storage only and hides the cloud features.
class SupabaseConfig {
  /// Your Supabase project URL, e.g. `https://xxxx.supabase.co`.
  static const String url = '';

  /// The public anon key from Settings → API in your Supabase dashboard.
  static const String anonKey = '';

  /// Table used for favorites sync (create it in Supabase SQL editor):
  /// ```sql
  /// create table public.favorites (
  ///   id bigint generated always as identity primary key,
  ///   user_id uuid not null references auth.users(id) on delete cascade,
  ///   entry_id text not null,
  ///   created_at timestamptz not null default now(),
  ///   unique (user_id, entry_id)
  /// );
  /// alter table public.favorites enable row level security;
  /// ```
  static const String favoritesTable = 'favorites';

  /// True once a real URL + anon key are set. Cloud features are hidden when false.
  static bool get isConfigured =>
      url.isNotEmpty && anonKey.isNotEmpty && !kIsWeb;

  /// Setup snippet for the Flutter app entry (see main.dart).
  static String get hint =>
      'Supabase not configured yet.\nPaste your project URL + anon key in '
      'lib/core/supabase_config.dart to enable account sync.';
}
