import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/app.dart';
import 'core/diagnostics.dart';
import 'data/providers.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Errors are captured locally (no user text, no network) until crash
  // reporting is a deliberate product decision.
  await Diagnostics().init();

  // No cloud SDK is initialised here on purpose: the app talks only to our own
  // FastAPI backend and ships no Supabase key (A24), so there is nothing in the
  // binary an attacker could extract and use to bypass the backend.

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
