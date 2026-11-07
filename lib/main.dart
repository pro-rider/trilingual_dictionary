import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'app/app.dart';
import 'core/supabase_config.dart';
import 'data/providers.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Optional cloud layer: skip init entirely until Supabase keys are set, so
  // the offline dictionary always works.
  if (SupabaseConfig.isConfigured) {
    await Supabase.initialize(
      url: SupabaseConfig.url,
      publishableKey: SupabaseConfig.anonKey,
    );
  }

  // Unpack the bundled 123k-entry database in the background; every screen
  // still works while it runs (about 3–6 s on first launch only).
  final container = ProviderContainer();
  unawaited(container.read(dictionaryRepositoryProvider).warmUp());

  runApp(
    UncontrolledProviderScope(
      container: container,
      child: const TrilingualDictionaryApp(),
    ),
  );
}
