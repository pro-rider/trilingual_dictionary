import 'dart:convert';
import 'dart:io' show Platform, gzip;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart'
    show compute, debugPrint, kReleaseMode;
import 'package:flutter/services.dart' show AssetBundle, rootBundle;

/// Reads and parses the single bundled stroke pack produced by
/// `tools/build_stroke_pack.py`.
///
/// The pack is one gzipped payload plus an index of byte offsets. Nothing here
/// invents data: a character absent from the pack stays absent, and the caller
/// must fall back.
///
/// Cost model: the gzip decode and the index parse run once, in a background
/// isolate (see [_decodePack]); a single character is parsed only when it is
/// first drawn, then cached. Stage 2 measures the real numbers in profile mode
/// on the SM-M166P.
///
/// Licence: the data is under the Arphic Public License, and
/// `assets/strokes/ARPHICPL.TXT` ships beside it. See `docs/LICENSE-ARPHIC.md`.
class StrokePack {
  StrokePack._(
    this._raw,
    this._entries,
    this._radicalOf,
    this._radicalNames,
    this._radicalChars,
    this._disputed,
    this.topWords,
    this.characterCount,
  );

  static const String indexAsset = 'assets/strokes/strokes.index.json';
  static const String payloadAsset = 'assets/strokes/strokes.bin.gz';

  /// Glyph units per em in the source data (Hanzi Writer's coordinate system).
  static const double emUnits = 1024;

  /// Baseline offset used by Hanzi Writer: glyph y grows upwards from y=900.
  static const double baseline = 900;

  final Uint8List _raw;
  final Map<String, List<int>> _entries;
  final Map<String, int> _radicalOf;
  final Map<String, String> _radicalNames;
  final Map<String, String> _radicalChars;
  final Set<String> _disputed;

  /// How many words the pack was built for (1000 or 3000 today).
  final int topWords;

  /// Number of characters with stroke data.
  final int characterCount;

  final Map<String, StrokeGlyph> _glyphs = {};
  final Map<String, StrokeGlyph?> _missing = {};

  static StrokePack? _instance;
  static Future<StrokePack>? _loading;

  /// True when the decode must not go to a background isolate.
  ///
  /// `flutter test` drives widgets under fake async: an isolate's future is
  /// never completed inside `pumpAndSettle`, so every widget test would time
  /// out. Tests therefore decode inline. The app always decodes off the UI
  /// isolate; the real cost is measured on the device in Stage 2, not here.
  static bool _decodeInline = Platform.environment['FLUTTER_TEST'] == 'true';

  /// Test hook: force inline decoding on or off.
  static set debugDecodeInline(bool value) => _decodeInline = value;

  /// Loads (once per process) from the asset bundle.
  static Future<StrokePack> load({AssetBundle? bundle}) {
    final cached = _instance;
    if (cached != null) return Future.value(cached);
    return _loading ??= _load(bundle ?? rootBundle).then((pack) {
      _instance = pack;
      _loading = null;
      return pack;
    });
  }

  /// Drops the cache. Tests use this between cases.
  static void resetForTests() {
    _instance = null;
    _loading = null;
  }

  static Future<StrokePack> _load(AssetBundle bundle) async {
    final watch = Stopwatch()..start();
    final indexBytes = await bundle.load(indexAsset);
    final payloadBytes = await bundle.load(payloadAsset);
    final bytes = <Uint8List>[
      indexBytes.buffer.asUint8List(),
      payloadBytes.buffer.asUint8List(),
    ];
    // 2.4 MB of gzip plus a 32 KB index parse: not on the UI isolate.
    final decoded = _decodeInline ? _decodePack(bytes) : await compute(_decodePack, bytes);
    final raw = decoded[0] as Uint8List;
    final entries = (decoded[1] as Map).cast<String, List<int>>();
    final radicalOf = (decoded[2] as Map).cast<String, int>();
    final radicalNames = (decoded[3] as Map).cast<String, String>();
    final radicalChars = (decoded[4] as Map).cast<String, String>();
    final disputed = (decoded[5] as Set).cast<String>();
    final topWords = decoded[6] as int;
    final pack = StrokePack._(
      raw,
      entries,
      radicalOf,
      radicalNames,
      radicalChars,
      disputed,
      topWords,
      entries.length,
    );
    watch.stop();
    if (!kReleaseMode) {
      // One line per process, non-release only: Stage 2 reads it from logcat.
      debugPrint('StrokePack.load ${watch.elapsedMilliseconds} ms '
          '(${entries.length} chars, ${raw.length} B raw, top $topWords words)');
    }
    return pack;
  }

  bool has(String char) => _entries.containsKey(char);

  /// True when the character's stroke count disagrees with Unihan and no human
  /// decision has been recorded yet. The UI draws it but does not print a count.
  bool isDisputed(String char) => _disputed.contains(char);

  /// Parsed glyph, or null when the character is not in the pack.
  StrokeGlyph? glyph(String char) {
    if (_missing.containsKey(char)) return _missing[char];
    final slice = _entries[char];
    if (slice == null) {
      _missing[char] = null;
      return null;
    }
    final start = slice[0];
    final length = slice[1];
    final json = utf8.decode(_raw.sublist(start, start + length));
    final decoded = (jsonDecode(json) as Map<String, dynamic>)[char] as Map<String, dynamic>;
    final glyph = StrokeGlyph.fromJson(char, decoded);
    _glyphs[char] = glyph;
    return glyph;
  }

  /// Radical number (1..214), or null when Unihan has no kRSUnicode entry.
  int? radicalNumber(String char) => _radicalOf[char];

  /// Kangxi radical as an ordinary ideograph (戈, 人, 水), or null.
  String? radicalGlyph(String char) {
    final number = radicalNumber(char);
    if (number == null) return null;
    return _radicalChars['$number'];
  }

  /// Official English radical name from the Unicode Kangxi list, or null.
  String? radicalName(String char) {
    final number = radicalNumber(char);
    if (number == null) return null;
    return _radicalNames['$number'];
  }
}

/// Runs in a background isolate: gunzip the payload and parse the index.
///
/// The return value is a plain list of sendable collections so the cost stays
/// off the UI isolate without shipping a custom class across the boundary.
List<Object> _decodePack(List<Uint8List> bytes) {
  final index = jsonDecode(utf8.decode(bytes[0])) as Map<String, dynamic>;
  final raw = Uint8List.fromList(gzip.decode(bytes[1]));
  final entries = <String, List<int>>{};
  for (final entry in (index['entries'] as Map<String, dynamic>).entries) {
    entries[entry.key] = (entry.value as List).cast<int>();
  }
  final radicalOf =
      (index['radicalOf'] as Map<String, dynamic>? ?? const {}).map((k, v) => MapEntry(k, v as int));
  final radicalNames = (index['radicalNames'] as Map<String, dynamic>? ?? const {})
      .map((k, v) => MapEntry(k, v as String));
  final radicalChars = (index['radicalChars'] as Map<String, dynamic>? ?? const {})
      .map((k, v) => MapEntry(k, v as String));
  final disputed = ((index['disputed'] as List?) ?? const []).cast<String>().toSet();
  return <Object>[
    raw,
    entries,
    radicalOf,
    radicalNames,
    radicalChars,
    disputed,
    index['topWords'] as int? ?? 0,
  ];
}

/// One character's drawing data, with paths built exactly once at load time.
class StrokeGlyph {
  StrokeGlyph._(this.character, this.outlines, this.medians, this.radicalStrokes)
      : medianMetrics = [
          for (final path in medians) path.computeMetrics().first,
        ];

  final String character;

  /// Filled stroke outlines, in glyph units.
  final List<ui.Path> outlines;

  /// Pen paths (stroke medians), used for the in-progress stroke.
  final List<ui.Path> medians;

  /// Precomputed metrics for each median; nothing is rebuilt per frame.
  final List<ui.PathMetric> medianMetrics;

  /// Stroke indices that belong to the radical (empty when the source has none).
  final List<int> radicalStrokes;

  int get strokeCount => outlines.length;

  factory StrokeGlyph.fromJson(
    String character,
    Map<String, dynamic> json,
  ) {
    final outlines = <ui.Path>[
      for (final d in (json['s'] as List).cast<String>()) parseSvgPath(d),
    ];
    final medians = <ui.Path>[];
    for (final median in (json['m'] as List)) {
      final points = <ui.Offset>[
        for (final point in (median as List))
          ui.Offset((point[0] as num).toDouble(), (point[1] as num).toDouble()),
      ];
      medians.add(polylinePath(points));
    }
    final radical = (json['r'] as List?)?.cast<int>() ?? const <int>[];
    return StrokeGlyph._(character, outlines, medians, radical);
  }
}

/// Builds one open path through the given points.
ui.Path polylinePath(List<ui.Offset> points) {
  final path = ui.Path();
  if (points.isEmpty) return path;
  path.moveTo(points.first.dx, points.first.dy);
  for (final point in points.skip(1)) {
    path.lineTo(point.dx, point.dy);
  }
  return path;
}

/// Parses the subset of SVG path syntax that the stroke data uses:
/// `M`, `L`, `Q`, `C`, `Z` (absolute and relative), with implicit repeated
/// coordinate pairs. It throws [FormatException] on anything else rather than
/// guessing, so a future data change fails loudly instead of drawing nonsense.
ui.Path parseSvgPath(String d) {
  final tokens = tokensOf(d);
  final path = ui.Path();
  var index = 0;
  var command = '';
  var current = ui.Offset.zero;
  var start = ui.Offset.zero;

  double next() {
    if (index >= tokens.length || tokens[index] is! double) {
      throw const FormatException('SVG path ended in the middle of a command');
    }
    return tokens[index++] as double;
  }

  while (index < tokens.length) {
    final token = tokens[index];
    if (token is String) {
      command = token;
      index++;
      if (command == 'Z' || command == 'z') {
        path.close();
        current = start;
        continue;
      }
    }
    final relative = command == command.toLowerCase();
    switch (command.toUpperCase()) {
      case 'M':
        final x = next();
        final y = next();
        current = relative ? ui.Offset(current.dx + x, current.dy + y) : ui.Offset(x, y);
        start = current;
        path.moveTo(current.dx, current.dy);
        command = relative ? 'l' : 'L'; // further pairs are linetos
      case 'L':
        final x = next();
        final y = next();
        current = relative ? ui.Offset(current.dx + x, current.dy + y) : ui.Offset(x, y);
        path.lineTo(current.dx, current.dy);
      case 'Q':
        final cx = next();
        final cy = next();
        final x = next();
        final y = next();
        final ctrl = relative
            ? ui.Offset(current.dx + cx, current.dy + cy)
            : ui.Offset(cx, cy);
        final end = relative ? ui.Offset(current.dx + x, current.dy + y) : ui.Offset(x, y);
        path.quadraticBezierTo(ctrl.dx, ctrl.dy, end.dx, end.dy);
        current = end;
      case 'C':
        final c1x = next();
        final c1y = next();
        final c2x = next();
        final c2y = next();
        final x = next();
        final y = next();
        final c1 = relative
            ? ui.Offset(current.dx + c1x, current.dy + c1y)
            : ui.Offset(c1x, c1y);
        final c2 = relative
            ? ui.Offset(current.dx + c2x, current.dy + c2y)
            : ui.Offset(c2x, c2y);
        final end = relative ? ui.Offset(current.dx + x, current.dy + y) : ui.Offset(x, y);
        path.cubicTo(c1.dx, c1.dy, c2.dx, c2.dy, end.dx, end.dy);
        current = end;
      default:
        throw FormatException('Unsupported SVG command "$command"');
    }
  }
  return path;
}

/// Splits an SVG path into a stream of command letters and numbers.
///
/// How it reads the string matters: `M 10-5` means two numbers (10 and -5),
/// and a `-` or `+` right after a digit starts a new number rather than
/// continuing the previous one.
List<dynamic> tokensOf(String d) {
  final tokens = <dynamic>[];
  var i = 0;
  while (i < d.length) {
    final c = d[i];
    if (_isLetter(c)) {
      tokens.add(c);
      i++;
      continue;
    }
    if (_isDigit(c) || c == '.' || c == '-' || c == '+') {
      final start = i;
      i++;
      while (i < d.length) {
        final next = d[i];
        if (_isDigit(next) || next == '.') {
          i++;
          continue;
        }
        // Exponent: "1e-3" stays one number.
        if ((next == 'e' || next == 'E') &&
            i + 1 < d.length &&
            (_isDigit(d[i + 1]) || d[i + 1] == '-' || d[i + 1] == '+')) {
          i += 2;
          continue;
        }
        break;
      }
      final text = d.substring(start, i);
      final value = double.tryParse(text);
      if (value == null) {
        throw FormatException('Unparseable number "$text" in SVG path');
      }
      tokens.add(value);
      continue;
    }
    i++; // separators (spaces, commas)
  }
  return tokens;
}

bool _isDigit(String c) {
  final unit = c.codeUnitAt(0);
  return unit >= 0x30 && unit <= 0x39;
}

bool _isLetter(String c) {
  final unit = c.codeUnitAt(0);
  return (unit >= 0x41 && unit <= 0x5A) || (unit >= 0x61 && unit <= 0x7A);
}
