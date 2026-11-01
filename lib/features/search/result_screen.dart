import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/normalizer.dart';
import '../../data/models/dictionary_entry.dart';
import '../favorites/favorites_repository.dart';
import 'search_provider.dart';
import 'widgets/result_card.dart';
import 'widgets/sense_selector.dart';

/// Shows the 3-language result for a search.
class ResultScreen extends ConsumerStatefulWidget {
  final String query;
  final InputLanguage lang;

  const ResultScreen({super.key, required this.query, required this.lang});

  @override
  ConsumerState<ResultScreen> createState() => _ResultScreenState();
}

class _ResultScreenState extends ConsumerState<ResultScreen> {
  int _senseIndex = 0;

  @override
  Widget build(BuildContext context) {
    final result =
        ref.watch(resultProvider(SearchArgs(widget.query, widget.lang)));

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          tooltip: 'Back',
          icon: const Icon(Icons.arrow_back),
          onPressed: () {
            if (context.canPop()) {
              context.pop();
            } else {
              context.go('/home');
            }
          },
        ),
        title: Text('“${widget.query}”'),
        actions: [
          IconButton(
            tooltip: 'Copy result',
            onPressed: () => ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Copy — coming in v1.1')),
            ),
            icon: const Icon(Icons.copy, size: 20),
          ),
        ],
      ),
      body: result.when(
        data: (entry) => entry == null ? _empty() : _entry(entry),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => _error('$e'),
      ),
    );
  }

  Widget _entry(DictionaryEntry entry) {
    final senses = entry.senses;
    if (_senseIndex >= senses.length) _senseIndex = 0;
    final sense = senses[_senseIndex];
    final favorites = ref.watch(favoritesProvider).value ?? const [];
    final isFav = favorites.contains(entry.entryId);

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
      children: [
        // Word header
        Row(
          children: [
            Expanded(
              child: Text(
                entry.wordEn,
                style: const TextStyle(
                    fontSize: 26, fontWeight: FontWeight.w800),
              ),
            ),
            IconButton(
              tooltip: isFav ? 'Remove from favorites' : 'Save to favorites',
              onPressed: () =>
                  ref.read(favoritesProvider.notifier).toggle(entry.entryId),
              icon: Icon(
                isFav ? Icons.star : Icons.star_border,
                color: isFav ? const Color(0xFFEAB308) : null,
              ),
            ),
            TextButton.icon(
              onPressed: () =>
                  context.push('/detail/${entry.entryId}?sense=$_senseIndex'),
              icon: const Icon(Icons.open_in_full, size: 18),
              label: const Text('Detail'),
            ),
          ],
        ),
        const SizedBox(height: 6),
        SenseSelector(
          senses: senses,
          selectedIndex: _senseIndex,
          onSelect: (i) => setState(() => _senseIndex = i),
        ),
        const SizedBox(height: 4),
        ResultCard(sense: sense),
      ],
    );
  }

  Widget _empty() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.search_off, size: 56, color: Color(0xFF94A3B8)),
            const SizedBox(height: 12),
            const Text('No entry found',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            const SizedBox(height: 6),
            Text(
              '“${widget.query}” is not in the offline dataset yet.\n'
              'It will be added in a future data update.',
              textAlign: TextAlign.center,
              style: const TextStyle(color: Color(0xFF64748B)),
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: () => context.go('/home'),
              icon: const Icon(Icons.arrow_back),
              label: const Text('Back to search'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _error(String message) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline,
                size: 56, color: Color(0xFFE11D48)),
            const SizedBox(height: 12),
            const Text('Something went wrong',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            const SizedBox(height: 6),
            Text(message, style: const TextStyle(color: Color(0xFF64748B))),
          ],
        ),
      ),
    );
  }
}
