import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/constants.dart';
import '../../core/normalizer.dart';
import '../../core/supabase_config.dart';
import '../../data/auth_provider.dart';
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
          if (SupabaseConfig.isConfigured)
            _accountTile(context, ref)
          else
            ListTile(
              leading: const Icon(Icons.cloud_off, color: LanguageColors.brand),
              title: const Text('Sign in (Supabase)'),
              subtitle: const Text('Cloud sync — not configured yet'),
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
          const ListTile(
            title: Text('About'),
            subtitle: Text(
                'Trilingual Dictionary v0.1\nEnglish · 中文 · नेपाली\nDataset v${AppConstants.datasetVersion}'),
          ),
        ],
      ),
    );
  }

  Widget _accountTile(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authUserProvider).value;
    final controller = ref.read(authControllerProvider);
    if (auth == null) {
      return ListTile(
        leading: const Icon(Icons.login, color: LanguageColors.brand),
        title: const Text('Sign in'),
        subtitle: const Text('Sync favorites across devices'),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => context.push('/auth'),
      );
    }
    return ListTile(
      leading: const Icon(Icons.account_circle, color: LanguageColors.brand),
      title: Text(auth.email.isEmpty ? 'Signed in' : auth.email),
      subtitle: const Text('Signed in'),
      trailing: TextButton(
        onPressed: () async => controller.signOut(),
        child: const Text('Sign out'),
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
