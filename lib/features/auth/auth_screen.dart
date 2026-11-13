import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/constants.dart';

/// Account screen — deliberately empty of fields until the FastAPI client lands.
///
/// The previous version signed in against Supabase from the device, which
/// shipped a public anon key inside the APK and let anyone bypass the FastAPI
/// gate (A24). There is no way to sign in from here now: the real flow
/// (email → code → username/password, all through FastAPI) is Phase 4, and a
/// half-built form would collect a password for no reason.
class AuthScreen extends StatelessWidget {
  const AuthScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Account')),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 460),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.account_circle,
                    size: 64, color: LanguageColors.brand),
                const SizedBox(height: 12),
                Text(
                  'Accounts are not open yet',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.titleLarge,
                ),
                const SizedBox(height: 12),
                Text(
                  'The dictionary works fully offline without an account.\n\n'
                  'Sign-in is being built against our own backend — one email '
                  'code, then a username and password — so nothing here asks '
                  'for a password before that flow exists.',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodyMedium,
                ),
                const SizedBox(height: 24),
                OutlinedButton(
                  onPressed: () => context.pop(),
                  child: const Text('Back to the dictionary'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
