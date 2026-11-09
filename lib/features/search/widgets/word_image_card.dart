import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../data/api_client.dart';
import '../../../data/models/word_image.dart';
import '../../../data/providers.dart';
import '../../../data/local/offline_dictionary.dart';

/// Approved image for one entry.
///
/// Offline first (Issue 12): the WebP thumbnail bundled inside the APK is shown
/// immediately, with no network. Only when the packaged database has no verified
/// picture does this fall back to the backend image API, and only when that also
/// returns nothing does the card show the placeholder — never an error card, so
/// the meanings stay readable.
final localImageProvider =
    FutureProvider.family<EntryImage?, int>((ref, entryPk) async {
  return ref.watch(offlineDictionaryProvider).imageForEntry(entryPk);
});

/// Second key for the same picture: the Chinese headword.
///
/// Entries that do not come from the packaged database (bundled seeds, AI
/// answers) have ids like `seed:book`, so the id lookup can never hit. Asking
/// by headword finds 书/册/玩具/玩意 regardless of which row the photo was
/// indexed on.
final localWordImageProvider =
    FutureProvider.family<EntryImage?, String>((ref, wordZh) async {
  if (wordZh.isEmpty) return null;
  return ref.watch(offlineDictionaryProvider).imageForWord(wordZh);
});

final wordImagesProvider =
    FutureProvider.family<WordImages?, String>((ref, entryId) {
  return ref.watch(apiClientProvider).images(entryId);
});

class WordImageCard extends ConsumerWidget {
  const WordImageCard({
    super.key,
    required this.entryId,
    this.wordZh = '',
    this.compact = false,
  });

  final String entryId;

  /// Chinese headword, used as a second key when the id is not a local row.
  final String wordZh;

  /// `compact` is the small thumbnail used in result lists.
  final bool compact;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (entryId.isEmpty && wordZh.isEmpty) return const SizedBox.shrink();
    final pk = int.tryParse(entryId.replaceFirst('zh', ''));

    final byId = pk == null ? null : ref.watch(localImageProvider(pk)).valueOrNull;
    final local = byId ??
        (wordZh.isEmpty ? null : ref.watch(localWordImageProvider(wordZh)).valueOrNull);
    if (local != null && local.assetPath.isNotEmpty) {
      return _bundledImage(context, local, compact);
    }

    if (entryId.isEmpty) return _iconFallback(context, 'general');
    final async = ref.watch(wordImagesProvider(entryId));
    return async.when(
      loading: () => _placeholder(context, compact),
      error: (_, _) => _iconFallback(context, 'general'),
      data: (images) {
        final first =
            images?.items.isNotEmpty == true ? images!.items.first : null;
        if (first == null) return _iconFallback(context, images?.icon ?? 'general');
        return _networkImage(context, first, compact);
      },
    );
  }

  /// The thumbnail shipped in the APK: instant, offline, ≤15 KB.
  Widget _bundledImage(
      BuildContext context, EntryImage image, bool compact) {
    final picture = ClipRRect(
      borderRadius: BorderRadius.circular(14),
      child: AspectRatio(
        aspectRatio: image.width > 0 && image.height > 0
            ? (image.width / image.height).clamp(0.8, 1.8)
            : 1.4,
        child: Image.asset(
          image.assetPath,
          fit: BoxFit.cover,
          width: double.infinity,
          errorBuilder: (_, _, _) => _iconFallback(context, 'general', inline: true),
        ),
      ),
    );
    if (compact) {
      return GestureDetector(onTap: () => _openLocal(context, image), child: picture);
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        GestureDetector(onTap: () => _openLocal(context, image), child: picture),
        const SizedBox(height: 6),
        Row(
          children: [
            const Icon(Icons.photo_camera_outlined,
                size: 13, color: Color(0xFF94A3B8)),
            const SizedBox(width: 4),
            Expanded(
              child: Text(
                image.attribution.isEmpty
                    ? 'Wikimedia Commons · tap to enlarge'
                    : '${image.attribution} · tap to enlarge',
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 11, color: Color(0xFF64748B)),
              ),
            ),
          ],
        ),
      ],
    );
  }

  void _openLocal(BuildContext context, EntryImage image) {
    showDialog<void>(
      context: context,
      builder: (dialogContext) => Dialog(
        insetPadding: const EdgeInsets.all(12),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: InteractiveViewer(
                maxScale: 4,
                child: Image.asset(image.assetPath, fit: BoxFit.contain),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(image.attribution, style: const TextStyle(fontSize: 12)),
                  const SizedBox(height: 4),
                  Text(
                    '${image.license} · ${image.matchMethod} · '
                    'confidence ${image.confidence.toStringAsFixed(2)}',
                    style: const TextStyle(
                        fontSize: 11, color: Color(0xFF64748B)),
                  ),
                  const SizedBox(height: 8),
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton(
                      onPressed: () => Navigator.of(dialogContext).pop(),
                      child: const Text('Close'),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _networkImage(BuildContext context, WordImage image, bool compact) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        GestureDetector(
          onTap: () => _openViewer(context, image),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(14),
            child: AspectRatio(
              aspectRatio: image.width > 0 && image.height > 0
                  ? (image.width / image.height).clamp(0.8, 1.8)
                  : 1.4,
              child: Image.network(
                compact ? image.thumbUrl : image.detailUrl,
                fit: BoxFit.cover,
                width: double.infinity,
                frameBuilder: (context, child, frame, wasSync) {
                  if (wasSync || frame != null) {
                    return AnimatedOpacity(
                      opacity: 1,
                      duration: const Duration(milliseconds: 250),
                      child: child,
                    );
                  }
                  return _shimmer(context);
                },
                errorBuilder: (_, _, _) =>
                    _iconFallback(context, 'general', inline: true),
              ),
            ),
          ),
        ),
        if (!compact) ...[
          const SizedBox(height: 6),
          Row(
            children: [
              const Icon(Icons.photo_camera_outlined,
                  size: 13, color: Color(0xFF94A3B8)),
              const SizedBox(width: 4),
              Expanded(
                child: Text(
                  _attribution(image),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 11, color: Color(0xFF64748B)),
                ),
              ),
            ],
          ),
        ],
      ],
    );
  }

  /// Title — author — licence. Required by CC BY / CC BY-SA, and honest about
  /// the match method so a wrong picture can be spotted and reported.
  String _attribution(WordImage image) {
    final bits = <String>[
      if (image.attribution.isNotEmpty) image.attribution else 'Wikimedia Commons',
      'tap to enlarge',
    ];
    return bits.join(' · ');
  }

  void _openViewer(BuildContext context, WordImage image) {
    showDialog<void>(
      context: context,
      builder: (dialogContext) => Dialog(
        insetPadding: const EdgeInsets.all(12),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: InteractiveViewer(
                maxScale: 4,
                child: Image.network(
                  image.detailUrl,
                  fit: BoxFit.contain,
                  errorBuilder: (_, _, _) =>
                      _iconFallback(dialogContext, 'general'),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    image.attribution,
                    style: const TextStyle(fontSize: 12),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '${image.license} · ${image.matchMethod} · '
                    'confidence ${image.confidence.toStringAsFixed(2)}',
                    style: const TextStyle(
                        fontSize: 11, color: Color(0xFF64748B)),
                  ),
                  const SizedBox(height: 8),
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton(
                      onPressed: () => Navigator.of(dialogContext).pop(),
                      child: const Text('Close'),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _placeholder(BuildContext context, bool compact) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(14),
      child: AspectRatio(
        aspectRatio: compact ? 1.6 : 1.4,
        child: _shimmer(context),
      ),
    );
  }

  Widget _shimmer(BuildContext context) {
    return DecoratedBox(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFFE2E8F0), Color(0xFFF1F5F9)],
        ),
      ),
      child: const Center(
        child: SizedBox(
          width: 18,
          height: 18,
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
      ),
    );
  }

  static const _categoryIcons = <String, IconData>{
    'nature': Icons.park_outlined,
    'science_medicine': Icons.biotech_outlined,
    'transport': Icons.directions_car_outlined,
    'tools_instruments': Icons.handyman_outlined,
    'technology': Icons.memory_outlined,
    'people_society': Icons.groups_outlined,
    'everyday': Icons.local_grocery_store_outlined,
    'geography_environment': Icons.public_outlined,
    'language': Icons.translate,
    'business': Icons.work_outline,
    'idiom': Icons.auto_awesome_outlined,
    'proper_noun': Icons.badge_outlined,
    'general': Icons.image_outlined,
  };

  Widget _iconFallback(BuildContext context, String category, {bool inline = false}) {
    final icon = _categoryIcons[category] ?? Icons.image_outlined;
    final box = Container(
      height: inline ? null : 120,
      width: double.infinity,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: const Color(0xFFF1F5F9),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 34, color: const Color(0xFF94A3B8)),
          const SizedBox(height: 6),
          Text(
            'No picture yet · ${category.replaceAll('_', ' ')}',
            style: const TextStyle(fontSize: 11, color: Color(0xFF94A3B8)),
          ),
        ],
      ),
    );
    if (inline) return box;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        box,
        const SizedBox(height: 4),
        const Text(
          'No verified picture for this word yet — add freely licensed images '
          'from the curation queue.',
          style: TextStyle(fontSize: 11, color: Color(0xFF94A3B8)),
        ),
      ],
    );
  }
}
