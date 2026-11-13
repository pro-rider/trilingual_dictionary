import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/constants.dart';
import '../../core/normalizer.dart';
import 'settings_provider.dart';

/// Settings screen (v1): theme, text size, UI language, default input
/// language, offline-first, sound. Other toggles are later-phase.
class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(settingsProvider);
    final notifier = ref.read(settingsProvider.notifier);

    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _section('Appearance'),
          _tile(
            leading: const Icon(Icons.brightness_6, color: LanguageColors.brand),
            title: 'Theme',
            trailing: DropdownButton<ThemeMode>(
              value: settings.themeMode,
              underline: const SizedBox.shrink(),
              items: const [
                DropdownMenuItem(value: ThemeMode.light, child: Text('Light')),
                DropdownMenuItem(value: ThemeMode.dark, child: Text('Dark')),
                DropdownMenuItem(
                    value: ThemeMode.system, child: Text('System')),
              ],
              onChanged: (v) {
                if (v != null) notifier.setThemeMode(v);
              },
            ),
          ),
          _tile(
            leading:
                const Icon(Icons.format_size, color: LanguageColors.brand),
            title: 'Text size',
            subtitle: '${settings.textScale.toStringAsFixed(1)}×',
            trailing: SizedBox(
              width: 168,
              child: Slider(
                value: settings.textScale,
                min: 0.8,
                max: 1.4,
                divisions: 6,
                onChanged: (v) => notifier.setTextScale(v),
              ),
            ),
          ),
          _section('Language'),
          _tile(
            leading: const Icon(Icons.language, color: LanguageColors.brand),
            title: 'UI language',
            trailing: DropdownButton<AppLanguage>(
              value: settings.uiLanguage,
              underline: const SizedBox.shrink(),
              items: const [
                DropdownMenuItem(value: AppLanguage.english, child: Text('English')),
                DropdownMenuItem(value: AppLanguage.chinese, child: Text('中文')),
                DropdownMenuItem(value: AppLanguage.nepali, child: Text('नेपाली')),
              ],
              onChanged: (v) {
                if (v != null) notifier.setUiLanguage(v);
              },
            ),
          ),
          _tile(
            leading:
                const Icon(Icons.translate, color: LanguageColors.brand),
            title: 'Default input language',
            trailing: SegmentedButton<InputLanguage>(
              segments: const [
                ButtonSegment(
                    value: InputLanguage.english, label: Text('EN')),
                ButtonSegment(
                    value: InputLanguage.chinese, label: Text('中文')),
              ],
              selected: {settings.defaultInputLang},
              onSelectionChanged: (s) =>
                  notifier.setDefaultInputLang(s.first),
            ),
          ),
          _section('Behaviour'),
          SwitchListTile(
            secondary: const Icon(Icons.offline_pin, color: LanguageColors.brand),
            title: const Text('Offline-first search'),
            subtitle: const Text('Use the bundled dictionary before the API'),
            value: settings.offlineFirst,
            onChanged: (_) => notifier.toggleOfflineFirst(),
          ),
          SwitchListTile(
            secondary: const Icon(Icons.volume_up, color: LanguageColors.ne),
            title: const Text('Sound & TTS'),
            subtitle: const Text('Later phase — needs a TTS plugin'),
            value: settings.soundEnabled,
            onChanged: (_) => notifier.toggleSound(),
          ),
          const SizedBox(height: 12),
          const Divider(),
          _section('Account & Sync'),
          ListTile(
            leading: const Icon(Icons.favorite, color: LanguageColors.brand),
            title: const Text('My favorites'),
            subtitle: const Text('Saved words'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => context.push('/favorites'),
          ),
          ListTile(
            leading: const Icon(Icons.login, color: Color(0xFF64748B)),
            title: const Text('Account'),
            subtitle: const Text('Not open yet — works offline without one'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => context.push('/auth'),
          ),
          const Divider(),
          ListTile(
            leading: const Icon(Icons.record_voice_over, color: Color(0xFF64748B)),
            title: const Text('TTS diagnosis'),
            subtitle: const Text('Temporary: engine, voices and tap-to-sound latency'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => context.push('/tts-debug'),
          ),
          const Divider(),
          ListTile(
            leading: const Icon(Icons.workspace_premium_outlined,
                color: Color(0xFF64748B)),
            title: const Text('Credits & licences'),
            subtitle: const Text('CC-CEDICT, Chinese Wiktionary, images'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => context.push('/credits'),
          ),
          ListTile(
            leading: const Icon(Icons.fact_check_outlined,
                color: Color(0xFF64748B)),
            title: const Text('About data quality'),
            subtitle: const Text('What "reviewed" and "pending" mean'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => context.push('/data-quality'),
          ),
          ListTile(
            leading: const Icon(Icons.privacy_tip_outlined,
                color: Color(0xFF64748B)),
            title: const Text('Privacy policy'),
            subtitle: const Text('What is sent to AI providers, and what is kept'),
            trailing: const Icon(Icons.open_in_new),
            // TODO(release): point at the published policy URL before submission.
            // Kept blank on purpose so nobody ships a dead link silently.
            onTap: () => _showPrivacySummary(context),
          ),
          const ListTile(
            title: Text('About'),
            subtitle: Text(
                'Trilingual Dictionary v0.1\nEnglish · 中文 · नेपाली\nDataset v${AppConstants.datasetVersion}'),
          ),
        ],
      ),
    );
  }

  /// The published policy is a `[CONTACT_EMAIL]` draft (docs/PRIVACY_POLICY.md),
  /// so the app shows the same summary inline instead of linking to a URL that
  /// does not exist yet.
  void _showPrivacySummary(BuildContext context) {
    showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Privacy summary'),
        content: const SingleChildScrollView(
          child: Text(
            'Offline by default: the bundled dictionary never leaves the device.\n\n'
            'AI features are opt-in. When you use one, the text you typed is sent '
            'to a third-party AI provider to produce a translation or example. '
            'Nothing else is sent.\n\n'
            'Results are saved on this device only, together with your favorites '
            'and search history. The server stores request counts, never your text.\n\n'
            'The full policy ships with the release build.',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }

  Widget _section(String title) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 18, 4, 8),
        child: Text(
          title,
          style: const TextStyle(
              fontSize: 13, fontWeight: FontWeight.w800, color: Color(0xFF64748B)),
        ),
      );

  Widget _tile({
    required Widget leading,
    required String title,
    String? subtitle,
    Widget? trailing,
  }) =>
      ListTile(
        leading: leading,
        title: Text(title),
        subtitle: subtitle != null ? Text(subtitle) : null,
        trailing: trailing,
      );
}
