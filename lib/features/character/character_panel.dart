import 'package:flutter/material.dart';

import '../../app/theme/app_tokens.dart';
import 'stroke_pack.dart';
import 'stroke_painter.dart';

/// The minimal character panel: one character at a time, stroke order, speed
/// slider, radical row, and an honest fallback when the data is missing.
///
/// Deliberately not here (out of scope for this stage): auto-play, emoji or
/// images, Nepali glosses, and per-screen settings wiring. The only setting it
/// touches is `settings.strokeSpeed`.
class CharacterPanel extends StatefulWidget {
  const CharacterPanel({
    super.key,
    required this.characters,
    this.speed = 1.0,
    this.onSpeedChanged,
    this.nepaliEnabled = false,
    this.title = 'Stroke order',
  });

  /// Characters of the word, already resolved for the user's variant.
  final List<String> characters;

  /// Playback speed multiplier (1.0 = the default duration).
  final double speed;

  /// Called when the slider moves; the caller persists `settings.strokeSpeed`.
  final ValueChanged<double>? onSpeedChanged;

  /// When false, no Nepali text may appear anywhere in this panel.
  final bool nepaliEnabled;

  final String title;

  @override
  State<CharacterPanel> createState() => _CharacterPanelState();
}

class _CharacterPanelState extends State<CharacterPanel>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: _durationFor(widget.speed),
  );

  int _index = 0;
  double _speed = 1.0;
  bool _playing = false;

  static const double _baseDurationMs = 900;

  Duration _durationFor(double speed) =>
      Duration(milliseconds: (_baseDurationMs / speed.clamp(0.25, 3.0)).round());

  @override
  void initState() {
    super.initState();
    _speed = widget.speed;
    _controller.addListener(() => setState(() {}));
    _controller.addStatusListener((status) {
      if (status == AnimationStatus.completed) {
        setState(() => _playing = false);
      }
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _play() {
    _controller
      ..duration = _durationFor(_speed)
      ..reset()
      ..forward();
    setState(() => _playing = true);
  }

  void _select(int index) {
    if (index == _index) return;
    _controller.reset();
    setState(() {
      _index = index;
      _playing = false;
    });
  }

  void _setSpeed(double value) {
    setState(() => _speed = value);
    _controller.duration = _durationFor(value);
    widget.onSpeedChanged?.call(value);
  }

  @override
  Widget build(BuildContext context) {
    final tokens = context.tokens;
    final chars = widget.characters.isEmpty ? const [''] : widget.characters;
    final char = chars[_index.clamp(0, chars.length - 1)];
    final reducedMotion = MediaQuery.disableAnimationsOf(context);

    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(widget.title, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            if (chars.length > 1) _characterTabs(chars, tokens),
            if (chars.length > 1) const SizedBox(height: 8),
            FutureBuilder<StrokePack>(
              future: StrokePack.load(),
              builder: (context, snapshot) {
                if (snapshot.connectionState != ConnectionState.done) {
                  return _placeholder(tokens, const CircularProgressIndicator());
                }
                final pack = snapshot.data;
                final glyph = pack?.glyph(char);
                if (pack == null || glyph == null) {
                  return _missing(char, pack, tokens);
                }
                return _drawn(char, glyph, pack, tokens, reducedMotion,
                    showPlay: !reducedMotion);
              },
            ),
          ],
        ),
      ),
    );
  }

  Widget _characterTabs(List<String> chars, AppTokens tokens) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (var i = 0; i < chars.length; i++)
          Semantics(
            button: true,
            selected: i == _index,
            label: 'Character ${i + 1} of ${chars.length}: ${chars[i]}',
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 48),
              child: ChoiceChip(
                label: Text(chars[i]),
                selected: i == _index,
                onSelected: (_) => _select(i),
                // Inherit the theme's font family: a bare TextStyle loses it.
                labelStyle: Theme.of(context).textTheme.titleMedium?.copyWith(
                  fontSize: 18,
                  color: i == _index ? tokens.textPrimary : tokens.textMuted,
                ),
              ),
            ),
          ),
      ],
    );
  }

  Widget _placeholder(AppTokens tokens, Widget child) {
    return SizedBox(
      height: 48,
      child: Center(
        child: IconTheme(
          data: IconThemeData(color: tokens.textMuted),
          child: child,
        ),
      ),
    );
  }

  Widget _missing(String char, StrokePack? pack, AppTokens tokens) {
    // No stroke data: show the plain character and say so. Never guess strokes.
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Semantics(
          container: true,
          label: '$char. Stroke order not available.',
          child: ExcludeSemantics(
            child: Text(
              char,
              style: TextStyle(fontSize: 96, color: tokens.textPrimary),
            ),
          ),
        ),
        const SizedBox(height: 4),
        Text(
          'Stroke order not available',
          style: TextStyle(color: tokens.textMuted),
        ),
        const SizedBox(height: 2),
        Text(
          'This character is not in the stroke data set (top ${pack?.topWords ?? 0} words).',
          style: TextStyle(fontSize: 12, color: tokens.textMuted),
        ),
      ],
    );
  }

  Widget _drawn(String char, StrokeGlyph glyph, StrokePack pack, AppTokens tokens,
      bool reducedMotion, {required bool showPlay}) {
    final radicalGlyph = pack.radicalGlyph(char);
    final radicalNumber = pack.radicalNumber(char);
    final radicalName = pack.radicalName(char);
    final radicalLabel = radicalGlyph == null
        ? 'Radical not listed'
        : 'Radical $radicalGlyph${radicalName == null ? '' : ' · $radicalName'}'
            '${radicalNumber == null ? '' : ' ($radicalNumber)'}';

    // A count that disagrees with Unihan and has not been adjudicated is not
    // printed: the animation is still honest (it comes from the data), the
    // number would not be.
    final disputed = pack.isDisputed(char);
    final semantics = disputed
        ? '$char, stroke count not reviewed, $radicalLabel'
        : '$char, ${glyph.strokeCount} strokes, $radicalLabel';
    final countLabel =
        disputed ? 'Stroke order not reviewed' : '${glyph.strokeCount} strokes';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Flex(
          direction: Axis.horizontal,
          children: [
            Flexible(
              child: Semantics(
                container: true,
                label: semantics,
                child: ExcludeSemantics(
                  child: _canvas(glyph, tokens, reducedMotion),
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Text(
          countLabel,
          style: TextStyle(
            color: disputed ? tokens.textMuted : tokens.textPrimary,
            fontSize: 13,
            fontStyle: disputed ? FontStyle.italic : FontStyle.normal,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          radicalLabel,
          style: TextStyle(color: tokens.textMuted, fontSize: 13),
        ),
        const SizedBox(height: 8),
        if (reducedMotion)
          Text(
            'Animation is off because reduced motion is enabled in system settings.',
            style: TextStyle(color: tokens.textMuted, fontSize: 12),
          )
        else
          Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 12,
            runSpacing: 8,
            children: [
              ConstrainedBox(
                constraints: const BoxConstraints(minHeight: 48, minWidth: 48),
                child: FilledButton.tonalIcon(
                  onPressed: _play,
                  icon: const Icon(Icons.play_arrow),
                  label: Text(_playing ? 'Replay' : 'Play'),
                ),
              ),
              SizedBox(
                width: 180,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text('Speed ${_speed.toStringAsFixed(2)}×',
                        style: TextStyle(color: tokens.textMuted, fontSize: 12)),
                    Slider(
                      value: _speed,
                      min: 0.5,
                      max: 2.0,
                      divisions: 6,
                      label: '${_speed.toStringAsFixed(2)}×',
                      onChanged: (value) => _setSpeed(value),
                    ),
                  ],
                ),
              ),
            ],
          ),
      ],
    );
  }

  Widget _canvas(StrokeGlyph glyph, AppTokens tokens, bool reducedMotion) {
    final progress = reducedMotion ? 1.0 : (_playing ? _controller.value : 1.0);
    // A fixed, modest square: the page scrolls, the drawing area does not grow
    // with the window (which is what made a 744 px-wide window overflow before).
    return LayoutBuilder(
      builder: (context, constraints) {
        final available = constraints.maxWidth;
        final side = available.isFinite && available < 240 ? available : 240.0;
        return Align(
          alignment: Alignment.centerLeft,
          child: GestureDetector(
            onHorizontalDragEnd: (details) {
              final velocity = details.primaryVelocity ?? 0;
              if (velocity < 0) {
                _select((_index + 1).clamp(0, widget.characters.length - 1));
              } else if (velocity > 0) {
                _select((_index - 1).clamp(0, widget.characters.length - 1));
              }
            },
            child: SizedBox(
              width: side,
              height: side,
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: tokens.surfaceMuted,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: CustomPaint(
                  painter: StrokePainter(
                    glyph: glyph,
                    progress: progress,
                    color: tokens.textPrimary,
                    penColor: tokens.brand,
                    guideColor: tokens.border,
                  ),
                  child: const SizedBox.expand(),
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}
