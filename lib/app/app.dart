import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../features/settings/settings_provider.dart';
import 'router.dart';
import 'theme/app_theme.dart';

/// Root MaterialApp wired to the go_router + settings.
class TrilingualDictionaryApp extends ConsumerWidget {
  const TrilingualDictionaryApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(settingsProvider);
    final router = ref.watch(routerProvider);
    return MaterialApp.router(
      title: 'Trilingual Dictionary',
      theme: AppTheme.light,
      darkTheme: AppTheme.light,
      themeMode: settings.themeMode,
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(
          textScaler: TextScaler.linear(settings.textScale),
        ),
        child: child!,
      ),
      routerConfig: router,
    );
  }
}
