import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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
      darkTheme: AppTheme.dark,
      themeMode: settings.themeMode,
      builder: (context, child) {
        final media = MediaQuery.of(context);
        // The in-app size slider and the phone's own font-size setting both
        // matter: before Phase 1 this replaced the platform scaler outright,
        // which silently ignored Accessibility > Font size (and would have
        // failed the 200 % requirement). Multiply, then clamp.
        final systemScale = media.textScaler.scale(1.0);
        final effective = (systemScale * settings.textScale).clamp(0.8, 2.0);
        // Status/navigation bar icons follow the *resolved* theme, not the
        // phone setting, so an explicit Light choice keeps dark icons on a
        // phone that is otherwise in dark mode.
        return AnnotatedRegion<SystemUiOverlayStyle>(
          value: AppTheme.overlayFor(Theme.of(context).brightness),
          child: MediaQuery(
            data: media.copyWith(textScaler: TextScaler.linear(effective)),
            child: child!,
          ),
        );
      },
      routerConfig: router,
    );
  }
}
