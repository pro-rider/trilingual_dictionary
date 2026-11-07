/// Models for the `/api/v1/images` response (stage 43/44 of the image plan).
class WordImage {
  final int imageId;
  final String thumbUrl;
  final String detailUrl;
  final int width;
  final int height;
  final String attribution;
  final String license;
  final String licenseUrl;
  final String sourceUrl;
  final double confidence;
  final String matchMethod;

  const WordImage({
    required this.imageId,
    required this.thumbUrl,
    required this.detailUrl,
    required this.width,
    required this.height,
    required this.attribution,
    required this.license,
    required this.licenseUrl,
    required this.sourceUrl,
    required this.confidence,
    required this.matchMethod,
  });

  factory WordImage.fromJson(Map<String, dynamic> json) => WordImage(
        imageId: (json['image_id'] as num?)?.toInt() ?? 0,
        thumbUrl: json['thumb_url'] as String? ?? '',
        detailUrl: json['detail_url'] as String? ?? '',
        width: (json['width'] as num?)?.toInt() ?? 0,
        height: (json['height'] as num?)?.toInt() ?? 0,
        attribution: json['attribution'] as String? ?? '',
        license: json['license'] as String? ?? '',
        licenseUrl: json['license_url'] as String? ?? '',
        sourceUrl: json['source_url'] as String? ?? '',
        confidence: (json['confidence'] as num?)?.toDouble() ?? 0,
        matchMethod: json['match_method'] as String? ?? '',
      );
}

class WordImages {
  final String entryId;
  final List<WordImage> items;

  /// Category key used for the fallback icon when no picture exists.
  final String icon;

  const WordImages({
    required this.entryId,
    required this.items,
    required this.icon,
  });

  bool get hasImage => items.isNotEmpty;

  factory WordImages.fromJson(Map<String, dynamic> json) => WordImages(
        entryId: json['entry_id'] as String? ?? '',
        items: ((json['items'] as List?) ?? const [])
            .whereType<Map>()
            .map((e) => WordImage.fromJson(e.cast<String, dynamic>()))
            .toList(),
        icon: json['icon'] as String? ?? 'general',
      );
}
