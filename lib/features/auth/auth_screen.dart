import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/constants.dart';
import '../../core/supabase_config.dart';
import '../../data/auth_provider.dart';

/// Sign in / Sign up screen (Supabase). Hidden until Supabase is configured.
class AuthScreen extends ConsumerStatefulWidget {
  const AuthScreen({super.key});

  @override
  ConsumerState<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends ConsumerState<AuthScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _signUpMode = false;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final controller = ref.read(authControllerProvider);
      if (_signUpMode) {
        await controller.signUp(_email.text, _password.text);
        _error = 'Check your email to confirm, then sign in.';
      } else {
        await controller.signIn(_email.text, _password.text);
        if (mounted) Navigator.of(context).pop();
      }
    } catch (e) {
      setState(() => _error = 'Could not sign in: ${e.toString()}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Account')),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Icon(Icons.account_circle,
                    size: 64, color: LanguageColors.brand),
                const SizedBox(height: 8),
                Text(
                  _signUpMode ? 'Create an account' : 'Welcome back',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 24),
                TextField(
                  controller: _email,
                  keyboardType: TextInputType.emailAddress,
                  decoration: const InputDecoration(
                    labelText: 'Email',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _password,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: 'Password',
                    border: OutlineInputBorder(),
                  ),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!,
                      style: const TextStyle(color: Colors.redAccent)),
                ],
                const SizedBox(height: 20),
                FilledButton(
                  onPressed: _busy ? null : _submit,
                  child: Text(_busy
                      ? 'Please wait…'
                      : (_signUpMode ? 'Sign up' : 'Sign in')),
                ),
                TextButton(
                  onPressed: () =>
                      setState(() => _signUpMode = !_signUpMode),
                  child: Text(_signUpMode
                      ? 'Already have an account? Sign in'
                      : 'No account? Sign up'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Helper shown when Supabase isn't configured.
class AuthUnavailable extends StatelessWidget {
  const AuthUnavailable({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Account')),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(SupabaseConfig.hint, textAlign: TextAlign.center),
        ),
      ),
    );
  }
}
