import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/constants.dart';
import '../../core/normalizer.dart';
import '../../data/api_client.dart';
import '../history/history_provider.dart';
import 'search_provider.dart';

/// Home: hero + search bar + popular words + quick links.
class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  final TextEditingController _controller = TextEditingController();
  InputLanguage _inputLang = InputLanguage.english;

  void _submit(String value) {
    final q = value.trim();
    if (q.isEmpty) return;
    final lang = Normalizer.detectLanguage(q);
    ref.read(historyProvider.notifier).add(q);
    final route = _shouldAnalyze(q, lang)
        ? '/analyze?q=${Uri.encodeComponent(q)}&lang=${lang.name}'
        : '/result?q=${Uri.encodeComponent(q)}&lang=${lang.name}';
    context.push(route);
  }

  /// Smart switch: single words → the dictionary result page; sentences,
  /// paragraphs, mixed or long Chinese input → the analyze view.
  bool _shouldAnalyze(String q, InputLanguage lang) {
    if (RegExp(r'[.?!。？！，,;；]').hasMatch(q)) return true;
    final tokens = q.trim().split(RegExp(r'\s+')).where((t) => t.isNotEmpty);
    if (tokens.length > 1) return true;
    if (lang == InputLanguage.chinese) {
      final cjk = RegExp(r'[\u3400-\u4dbf\u4e00-\u9fff]');
      final chars = q.split('').where((c) => cjk.hasMatch(c)).length;
      if (chars > 4) return true;
    }
    return false;
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final history = ref.watch(historyProvider);
    final popular = ref.watch(popularProvider);

    return Scaffold(
      appBar: AppBar(
        actions: [
          IconButton(
            tooltip: 'Favorites',
            onPressed: () => context.push('/favorites'),
            icon: const Icon(Icons.bookmark_border),
          ),
          IconButton(
            tooltip: 'History',
            onPressed: () => context.go('/history'),
            icon: const Icon(Icons.history),
          ),
          IconButton(
            tooltip: 'Settings',
            onPressed: () => context.go('/settings'),
            icon: const Icon(Icons.settings_outlined),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
        children: [
          const SizedBox(height: 4),
          const Text(
            'Trilingual Dictionary',
            style: TextStyle(fontSize: 24, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 4),
          const Text(
            'Search English or 中文 — read it in English, 中文 and नेपाली',
            style: TextStyle(fontSize: 14, color: Color(0xFF475569)),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              _LangSwitcher(
                value: _inputLang,
                onChanged: (l) => setState(() => _inputLang = l),
              ),
            ],
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _controller,
            onSubmitted: _submit,
            textInputAction: TextInputAction.search,
            decoration: InputDecoration(
              hintText: _inputLang == InputLanguage.english
                  ? 'Search a word… e.g. light'
                  : '输入中文… 例如 光',
              prefixIcon: const Icon(Icons.search, color: LanguageColors.brand),
              suffixIcon: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  ValueListenableBuilder<TextEditingValue>(
                    valueListenable: _controller,
                    builder: (context, value, _) => value.text.isEmpty
                        ? const SizedBox.shrink()
                        : IconButton(
                            tooltip: 'Clear',
                            onPressed: () {
                              _controller.clear();
                              setState(() {});
                            },
                            icon: const Icon(Icons.close, size: 18),
                          ),
                  ),
                  IconButton(
                    tooltip: 'Search',
                    onPressed: () => _submit(_controller.text),
                    icon: const Icon(Icons.arrow_forward,
                        color: LanguageColors.brand),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 20),

          // Quick links
          Row(
            children: [
              _QuickCard(
                icon: Icons.favorite_border,
                label: 'Favorites',
                color: LanguageColors.en,
                onTap: () => context.push('/favorites'),
              ),
              const SizedBox(width: 10),
              _QuickCard(
                icon: Icons.auto_stories,
                label: 'Learn',
                color: LanguageColors.ne,
                onTap: () =>
                    ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Learning — later phase')),
                ),
              ),
            ],
          ),

          // History chips
          if (history.isNotEmpty) ...[
            const SizedBox(height: 20),
            const Text('Recent',
                style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final h in history.take(6))
                  ActionChip(
                    label: Text(h),
                    onPressed: () => _submit(h),
                  ),
              ],
            ),
          ],

          // Popular words
          const SizedBox(height: 20),
          const Text('Popular words',
              style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          popular.when(
            data: (entries) => Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final e in entries)
                  ActionChip(
                    avatar: const Icon(Icons.tag, size: 16,
                        color: LanguageColors.brand),
                    label: Text('${e.wordEn} · ${e.wordZh}'),
                    onPressed: () => _submit(e.wordEn),
                  ),
              ],
            ),
            loading: () => const Center(
                child: Padding(
                  padding: EdgeInsets.all(12),
                  child: CircularProgressIndicator(),
                )),
            error: (e, _) => Text('$e',
                style: const TextStyle(color: Color(0xFFB45309))),
          ),
          const SizedBox(height: 8),
          _BackendStatus(),
        ],
      ),
    );
  }
}

/// Live indicator: is the FastAPI backend reachable? (falls back to offline)
class _BackendStatus extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(backendReachableProvider);
    final (Color, String) tuple = status.value == true
        ? (const Color(0xFF16A34A), 'API online — search uses the backend')
        : (const Color(0xFF94A3B8), 'Offline mode · backend not reachable');
    return Row(
      children: [
        Icon(Icons.circle, size: 10, color: tuple.$1),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            'Dataset v${AppConstants.datasetVersion} · ${tuple.$2}',
            style: const TextStyle(fontSize: 12, color: Color(0xFF94A3B8)),
          ),
        ),
      ],
    );
  }
}

class _LangSwitcher extends StatelessWidget {
  final InputLanguage value;
  final ValueChanged<InputLanguage> onChanged;
  const _LangSwitcher({required this.value, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return SegmentedButton<InputLanguage>(
      segments: const [
        ButtonSegment(
            value: InputLanguage.english,
            label: Text('English'),
            icon: Icon(Icons.translate, color: LanguageColors.en)),
        ButtonSegment(
            value: InputLanguage.chinese,
            label: Text('中文'),
            icon: Icon(Icons.translate, color: LanguageColors.zh)),
      ],
      selected: {value},
      onSelectionChanged: (s) => onChanged(s.first),
    );
  }
}

class _QuickCard extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;
  const _QuickCard(
      {required this.icon, required this.label, required this.color, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(14),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 14),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: const Color(0xFFE2E8F0)),
          ),
          child: Column(
            children: [
              Icon(icon, color: color),
              const SizedBox(height: 6),
              Text(label,
                  style:
                      const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
            ],
          ),
        ),
      ),
    );
  }
}
