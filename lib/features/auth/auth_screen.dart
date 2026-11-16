import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/theme/app_tokens.dart';
import '../../data/auth_api.dart';
import '../../data/auth_token.dart';

/// The account screen: real sign-in and sign-up against our own FastAPI.
///
/// Flow for a new account: e-mail → 6-digit code → username + password. No
/// password exists before the code is verified, so an attacker cannot claim
/// someone else's address (A27). Sign-in is username-or-e-mail + password.
///
/// The dictionary itself never needs this screen.
class AuthScreen extends ConsumerStatefulWidget {
  const AuthScreen({super.key});

  @override
  ConsumerState<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends ConsumerState<AuthScreen> {
  bool _busy = false;
  String? _error;
  String? _notice;

  @override
  Widget build(BuildContext context) {
    final signedIn = ref.watch(authTokenProvider) != null;
    return Scaffold(
      appBar: AppBar(title: Text(signedIn ? 'Your account' : 'Account')),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(24, 16, 24, 32),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 460),
              child: signedIn
                  ? _AccountBody(
                      busy: _busy,
                      error: _error,
                      notice: _notice,
                      run: _run,
                    )
                  : _SignedOutBody(
                      busy: _busy,
                      error: _error,
                      notice: _notice,
                      run: _run,
                    ),
            ),
          ),
        ),
      ),
    );
  }

  /// Runs one action with the shared busy/error handling, so every button on the
  /// screen reports failures the same way.
  Future<void> _run(Future<String?> Function() action) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });
    try {
      final notice = await action();
      if (mounted) setState(() => _notice = notice);
    } on AuthFailure catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (e) {
      if (mounted) {
        setState(() => _error = 'No answer from the server. Check your connection.');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

// ---------------------------------------------------------------------------
// signed out
// ---------------------------------------------------------------------------

class _SignedOutBody extends ConsumerStatefulWidget {
  const _SignedOutBody({
    required this.busy,
    required this.error,
    required this.notice,
    required this.run,
  });

  final bool busy;
  final String? error;
  final String? notice;
  final Future<void> Function(Future<String?> Function()) run;

  @override
  ConsumerState<_SignedOutBody> createState() => _SignedOutBodyState();
}

enum _Step { signIn, email, code, details, forgotEmail, forgotCode }

class _SignedOutBodyState extends ConsumerState<_SignedOutBody> {
  _Step _step = _Step.signIn;

  final _identifier = TextEditingController();
  final _password = TextEditingController();
  final _email = TextEditingController();
  final _code = TextEditingController();
  final _username = TextEditingController();
  final _newPassword = TextEditingController();

  String _signupToken = '';
  bool _usernameFree = false;
  String? _usernameNote;

  @override
  void dispose() {
    _identifier.dispose();
    _password.dispose();
    _email.dispose();
    _code.dispose();
    _username.dispose();
    _newPassword.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Icon(Icons.account_circle, size: 56, color: context.tokens.brandFill),
        const SizedBox(height: 8),
        Text(
          switch (_step) {
            _Step.signIn => 'Sign in',
            _Step.email => 'Create an account',
            _Step.code => 'Enter the code',
            _Step.details => 'Choose your username',
            _Step.forgotEmail => 'Reset your password',
            _Step.forgotCode => 'Enter the code',
          },
          textAlign: TextAlign.center,
          style: theme.textTheme.titleLarge,
        ),
        const SizedBox(height: 6),
        Text(
          switch (_step) {
            _Step.signIn => 'Your favourites and history stay on this phone whether you sign in or not.',
            _Step.email => 'We send a 6-digit code to this address. No password is set until the code is verified.',
            _Step.code => 'Check your inbox for ${_email.text.trim()}.',
            _Step.details => '3–20 characters: letters, digits, dot or underscore.',
            _Step.forgotEmail => 'We send a 6-digit code to the address on your account.',
            _Step.forgotCode => 'Check ${_email.text.trim()} for the code.',
          },
          textAlign: TextAlign.center,
          style: theme.textTheme.bodyMedium,
        ),
        const SizedBox(height: 20),
        ..._fields(theme),
        if (widget.notice != null) ...[
          const SizedBox(height: 14),
          _Message(text: widget.notice!, tone: _Tone.info),
        ],
        if (widget.error != null) ...[
          const SizedBox(height: 14),
          _Message(text: widget.error!, tone: _Tone.error),
        ],
        const SizedBox(height: 20),
        FilledButton(
          onPressed: widget.busy ? null : _submit,
          child: widget.busy
              ? const SizedBox(
                  width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
              : Text(switch (_step) {
                  _Step.signIn => 'Sign in',
                  _Step.email || _Step.forgotEmail => 'Send the code',
                  _Step.code => 'Verify',
                  _Step.details => 'Create account',
                  _Step.forgotCode => 'Set the new password',
                }),
        ),
        const SizedBox(height: 10),
        ..._secondary(theme),
      ],
    );
  }

  List<Widget> _fields(ThemeData theme) {
    switch (_step) {
      case _Step.signIn:
        return [
          TextField(
            controller: _identifier,
            autocorrect: false,
            keyboardType: TextInputType.emailAddress,
            textInputAction: TextInputAction.next,
            decoration: const InputDecoration(
              labelText: 'Username or e-mail',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          _passwordField(_password, 'Password', TextInputAction.done),
        ];
      case _Step.email:
      case _Step.forgotEmail:
        return [
          TextField(
            controller: _email,
            autocorrect: false,
            keyboardType: TextInputType.emailAddress,
            decoration: const InputDecoration(
              labelText: 'E-mail',
              border: OutlineInputBorder(),
            ),
          ),
        ];
      case _Step.code:
        return [
          TextField(
            controller: _code,
            keyboardType: TextInputType.number,
            maxLength: 6,
            decoration: const InputDecoration(
              labelText: '6-digit code',
              counterText: '',
              border: OutlineInputBorder(),
            ),
          ),
        ];
      case _Step.details:
        return [
          TextField(
            controller: _username,
            autocorrect: false,
            onChanged: _onUsernameChanged,
            decoration: InputDecoration(
              labelText: 'Username',
              border: const OutlineInputBorder(),
              helperText: _usernameNote,
              suffixIcon: _usernameFree
                  ? Icon(Icons.check, color: context.tokens.brandFill)
                  : null,
            ),
          ),
          const SizedBox(height: 12),
          _passwordField(_newPassword, 'Password (8+ characters)', TextInputAction.done),
        ];
      case _Step.forgotCode:
        return [
          TextField(
            controller: _code,
            keyboardType: TextInputType.number,
            maxLength: 6,
            decoration: const InputDecoration(
              labelText: '6-digit code',
              counterText: '',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          _passwordField(_newPassword, 'New password (8+ characters)', TextInputAction.done),
        ];
    }
  }

  Widget _passwordField(TextEditingController c, String label, TextInputAction action) {
    return TextField(
      controller: c,
      obscureText: true,
      autocorrect: false,
      textInputAction: action,
      decoration: InputDecoration(labelText: label, border: const OutlineInputBorder()),
    );
  }

  List<Widget> _secondary(ThemeData theme) {
    switch (_step) {
      case _Step.signIn:
        return [
          TextButton(
            onPressed: widget.busy ? null : () => setState(() => _step = _Step.email),
            child: const Text('I need an account'),
          ),
          TextButton(
            onPressed: widget.busy ? null : () => setState(() => _step = _Step.forgotEmail),
            child: const Text('Forgot your password?'),
          ),
        ];
      case _Step.email:
        return [
          TextButton(
            onPressed: widget.busy ? null : () => setState(() => _step = _Step.signIn),
            child: const Text('I already have an account'),
          ),
        ];
      case _Step.code:
        return [
          TextButton(
            onPressed: widget.busy ? null : () => setState(() => _step = _Step.email),
            child: const Text('Use a different address'),
          ),
        ];
      case _Step.details:
        return [
          TextButton(
            onPressed: widget.busy ? null : () => setState(() => _step = _Step.code),
            child: const Text('Back'),
          ),
        ];
      case _Step.forgotEmail:
      case _Step.forgotCode:
        return [
          TextButton(
            onPressed: widget.busy ? null : () => setState(() => _step = _Step.signIn),
            child: const Text('Back to sign in'),
          ),
        ];
    }
  }

  Future<void> _onUsernameChanged(String value) async {
    final name = value.trim();
    if (name.length < 3) {
      setState(() {
        _usernameFree = false;
        _usernameNote = null;
      });
      return;
    }
    try {
      final free = await ref.read(authApiProvider).usernameAvailable(name);
      if (mounted && _username.text.trim() == name) {
        setState(() {
          _usernameFree = free;
          _usernameNote = free ? 'Available' : 'Taken or reserved';
        });
      }
    } on AuthFailure catch (e) {
      if (mounted) {
        setState(() {
          _usernameFree = false;
          _usernameNote = e.message;
        });
      }
    }
  }

  Future<void> _submit() async {
    final api = ref.read(authApiProvider);
    switch (_step) {
      case _Step.signIn:
        final identifier = _identifier.text.trim();
        final password = _password.text;
        if (identifier.isEmpty || password.isEmpty) {
          return;
        }
        await widget.run(() async {
          final deviceId = ref.read(deviceIdProvider);
          await api.login(identifier: identifier, password: password, deviceId: deviceId);
          return 'Signed in';
        });
      case _Step.email:
        final email = _email.text.trim();
        if (email.isEmpty) return;
        await widget.run(() async {
          await api.registerStart(email);
          if (mounted) setState(() => _step = _Step.code);
          return 'If that address can be used, a code is on its way.';
        });
      case _Step.code:
        final code = _code.text.trim();
        if (code.length != 6) return;
        await widget.run(() async {
          _signupToken = await api.registerVerify(_email.text.trim(), code);
          if (mounted) setState(() => _step = _Step.details);
          return 'Address verified';
        });
      case _Step.details:
        final username = _username.text.trim();
        final password = _newPassword.text;
        if (username.length < 3 || password.length < 8) return;
        await widget.run(() async {
          await api.registerComplete(
            signupToken: _signupToken,
            username: username,
            password: password,
          );
          return 'Account created';
        });
      case _Step.forgotEmail:
        final email = _email.text.trim();
        if (email.isEmpty) return;
        await widget.run(() async {
          await api.passwordForgot(email);
          if (mounted) setState(() => _step = _Step.forgotCode);
          return 'If that address has an account, a code is on its way.';
        });
      case _Step.forgotCode:
        final code = _code.text.trim();
        final password = _newPassword.text;
        if (code.length != 6 || password.length < 8) return;
        await widget.run(() async {
          await api.passwordReset(
            email: _email.text.trim(),
            code: code,
            password: password,
          );
          return 'Password changed. Every other device was signed out.';
        });
    }
  }
}

// ---------------------------------------------------------------------------
// signed in
// ---------------------------------------------------------------------------

class _AccountBody extends ConsumerStatefulWidget {
  const _AccountBody({
    required this.busy,
    required this.error,
    required this.notice,
    required this.run,
  });

  final bool busy;
  final String? error;
  final String? notice;
  final Future<void> Function(Future<String?> Function()) run;

  @override
  ConsumerState<_AccountBody> createState() => _AccountBodyState();
}

class _AccountBodyState extends ConsumerState<_AccountBody> {
  Future<AuthProfile>? _profile;
  Future<List<SessionRow>>? _sessions;
  bool _loaded = false;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() {
    final api = ref.read(authApiProvider);
    _profile = api.profile();
    _sessions = api.sessions();
    _loaded = true;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (!_loaded) ...[
          const Center(child: CircularProgressIndicator()),
        ] else
          FutureBuilder<AuthProfile>(
            future: _profile,
            builder: (context, snap) {
              if (snap.connectionState != ConnectionState.done) {
                return const Center(child: CircularProgressIndicator());
              }
              if (snap.hasError) {
                return _Message(
                  text: snap.error is AuthFailure
                      ? (snap.error as AuthFailure).message
                      : 'Could not load the profile',
                  tone: _Tone.error,
                );
              }
              final p = snap.data!;
              return Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text('@${p.username ?? 'account'}',
                      textAlign: TextAlign.center, style: theme.textTheme.titleLarge),
                  const SizedBox(height: 4),
                  Text(p.email, textAlign: TextAlign.center, style: theme.textTheme.bodyMedium),
                  const SizedBox(height: 4),
                  Text('Status: ${p.status}',
                      textAlign: TextAlign.center, style: theme.textTheme.bodySmall),
                ],
              );
            },
          ),
        const SizedBox(height: 20),
        Text('Devices signed in', style: theme.textTheme.titleSmall),
        const SizedBox(height: 8),
        FutureBuilder<List<SessionRow>>(
          future: _sessions,
          builder: (context, snap) {
            if (snap.connectionState != ConnectionState.done) {
              return const Padding(
                padding: EdgeInsets.all(8),
                child: Center(child: CircularProgressIndicator()),
              );
            }
            if (snap.hasError) {
              return Text(
                snap.error is AuthFailure
                    ? (snap.error as AuthFailure).message
                    : 'Could not list the devices',
                style: theme.textTheme.bodySmall,
              );
            }
            final rows = snap.data ?? const <SessionRow>[];
            if (rows.isEmpty) {
              return Text('No active sessions', style: theme.textTheme.bodySmall);
            }
            return Column(
              children: [
                for (final s in rows)
                  Card(
                    margin: const EdgeInsets.only(bottom: 8),
                    child: ListTile(
                      leading: const Icon(Icons.smartphone),
                      title: Text(s.current ? '${s.label} (this device)' : s.label),
                      subtitle: Text('Last seen ${_ago(s.lastSeen)}'),
                      trailing: s.current
                          ? null
                          : TextButton(
                              onPressed: widget.busy
                                  ? null
                                  : () => widget.run(() async {
                                        await ref
                                            .read(authApiProvider)
                                            .revokeSession(s.id);
                                        if (mounted) setState(_reload);
                                        return 'That device was signed out';
                                      }),
                              child: const Text('Sign out'),
                            ),
                    ),
                  ),
              ],
            );
          },
        ),
        if (widget.notice != null) ...[
          const SizedBox(height: 12),
          _Message(text: widget.notice!, tone: _Tone.info),
        ],
        if (widget.error != null) ...[
          const SizedBox(height: 12),
          _Message(text: widget.error!, tone: _Tone.error),
        ],
        const SizedBox(height: 20),
        OutlinedButton(
          onPressed: widget.busy
              ? null
              : () => widget.run(() async {
                    await ref.read(authApiProvider).logout();
                    return 'Signed out on this device';
                  }),
          child: const Text('Sign out'),
        ),
        const SizedBox(height: 8),
        OutlinedButton(
          onPressed: widget.busy
              ? null
              : () => widget.run(() async {
                    await ref.read(authApiProvider).logoutAll();
                    return 'Every device was signed out';
                  }),
          child: const Text('Sign out everywhere'),
        ),
        const SizedBox(height: 8),
        TextButton(
          onPressed: widget.busy ? null : _changePassword,
          child: const Text('Change password'),
        ),
        const SizedBox(height: 8),
        TextButton(
          onPressed: widget.busy ? null : _deleteAccount,
          style: TextButton.styleFrom(foregroundColor: context.tokens.zh),
          child: const Text('Delete account'),
        ),
        const SizedBox(height: 8),
        TextButton(
          onPressed: () => context.pop(),
          child: const Text('Back to the dictionary'),
        ),
      ],
    );
  }

  Future<void> _changePassword() async {
    final current = TextEditingController();
    final next = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Change password'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: current,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'Current password'),
            ),
            TextField(
              controller: next,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'New password (8+)'),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Change')),
        ],
      ),
    );
    if (ok != true) return;
    await widget.run(() async {
      await ref.read(authApiProvider).changePassword(
            currentPassword: current.text,
            newPassword: next.text,
          );
      return 'Password changed. All devices, including this one, must sign in again.';
    });
  }

  Future<void> _deleteAccount() async {
    final password = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete account?'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'This removes the account and its profile from the server. '
              'Favourites and history on this phone are removed too.',
            ),
            const SizedBox(height: 12),
            TextField(
              controller: password,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'Your password'),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            style: FilledButton.styleFrom(backgroundColor: context.tokens.zh),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    await widget.run(() async {
      await ref.read(authApiProvider).deleteAccount(password: password.text);
      return 'Account deleted';
    });
  }

  String _ago(DateTime t) {
    final d = DateTime.now().difference(t);
    if (d.inMinutes < 1) return 'just now';
    if (d.inHours < 1) return '${d.inMinutes} min ago';
    if (d.inDays < 1) return '${d.inHours} h ago';
    return '${d.inDays} d ago';
  }
}

// ---------------------------------------------------------------------------
// shared bits
// ---------------------------------------------------------------------------

enum _Tone { info, error }

class _Message extends StatelessWidget {
  const _Message({required this.text, required this.tone});

  final String text;
  final _Tone tone;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color =
        tone == _Tone.error ? context.tokens.zh : context.tokens.brandFill;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        border: Border.all(color: color.withValues(alpha: 0.35)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(text, style: theme.textTheme.bodyMedium?.copyWith(color: color)),
    );
  }
}
