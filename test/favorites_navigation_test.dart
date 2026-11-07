import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'package:trilingual_dictionary/data/dictionary_repository.dart';
import 'package:trilingual_dictionary/data/models/dictionary_entry.dart';
import 'package:trilingual_dictionary/data/providers.dart';
import 'package:trilingual_dictionary/features/favorites/favorites_repository.dart';
import 'package:trilingual_dictionary/features/favorites/favorites_screen.dart';

class _FakeFavorites extends FavoritesRepository {
  @override
  Future<List<String>> build() async => ['light'];
}

class _FakeDictionary extends DictionaryRepository {
  _FakeDictionary() : super(rootBundle);

  @override
  Future<DictionaryEntry?> findById(String entryId) async {
    if (entryId != 'light') return null;
    return const DictionaryEntry(
      entryId: 'light',
      wordEn: 'light',
      wordZh: '光',
      senses: [],
    );
  }
}

void main() {
  testWidgets('tapping a favorite opens the detail route', (tester) async {
    final router = GoRouter(
      initialLocation: '/favorites',
      routes: [
        GoRoute(
          path: '/favorites',
          builder: (_, _) => const FavoritesScreen(),
        ),
        GoRoute(
          path: '/detail/:entryId',
          builder: (_, state) => Scaffold(
            body: Text('detail:${state.pathParameters['entryId']}'),
          ),
        ),
      ],
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          favoritesProvider.overrideWith(_FakeFavorites.new),
          dictionaryRepositoryProvider.overrideWithValue(_FakeDictionary()),
        ],
        child: MaterialApp.router(routerConfig: router),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('light'), findsOneWidget);
    await tester.tap(find.text('light'));
    await tester.pumpAndSettle();

    expect(find.text('detail:light'), findsOneWidget);
  });
}
