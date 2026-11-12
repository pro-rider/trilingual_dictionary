import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/normalizer.dart';
import '../features/auth/auth_screen.dart';
import '../features/favorites/favorites_screen.dart';
import '../features/onboarding/onboarding_screen.dart';
import '../features/search/home_screen.dart';
import '../features/search/result_screen.dart';
import '../features/analyze/analyze_screen.dart';
import '../features/settings/settings_screen.dart';
import '../features/settings/tts_diagnostic_screen.dart';
import '../features/history/history_screen.dart';
import '../features/splash/splash_screen.dart';
import '../features/detail/detail_screen.dart';
import '../features/about/credits_screen.dart';

/// App routes. '/' boots splash → '/home'.
final routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: '/',
    routes: [
      GoRoute(
        path: '/',
        builder: (_, _) => const SplashScreen(),
      ),
      GoRoute(
        path: '/home',
        builder: (_, _) => const HomeScreen(),
      ),
      GoRoute(
        path: '/onboarding',
        builder: (_, _) => const OnboardingScreen(),
      ),
      GoRoute(
        path: '/result',
        builder: (_, state) {
          final params = state.uri.queryParameters;
          final langText = params['lang'] ?? 'english';
          final lang = langText == 'chinese'
              ? InputLanguage.chinese
              : InputLanguage.english;
          return ResultScreen(query: params['q'] ?? '', lang: lang);
        },
      ),
      GoRoute(
        path: '/analyze',
        builder: (_, state) {
          final params = state.uri.queryParameters;
          return AnalyzeScreen(
            query: params['q'] ?? '',
            langText: params['lang'] ?? 'english',
          );
        },
      ),
      GoRoute(
        path: '/detail/:entryId',
        builder: (_, state) =>
            DetailScreen(entryId: state.pathParameters['entryId'] ?? ''),
      ),
      GoRoute(
        path: '/history',
        builder: (_, _) => const HistoryScreen(),
      ),
      GoRoute(
        path: '/settings',
        builder: (_, _) => const SettingsScreen(),
      ),
      // Temporary: prompt V1 voice diagnosis. Remove when speech is fixed.
      GoRoute(
        path: '/tts-debug',
        builder: (_, _) => const TtsDiagnosticScreen(),
      ),
      GoRoute(
        path: '/auth',
        builder: (_, _) => const AuthScreen(),
      ),
      GoRoute(
        path: '/favorites',
        builder: (_, _) => const FavoritesScreen(),
      ),
      GoRoute(
        path: '/credits',
        builder: (_, _) => const CreditsScreen(),
      ),
      GoRoute(
        path: '/data-quality',
        builder: (_, _) => const DataQualityScreen(),
      ),
    ],
  );
});
