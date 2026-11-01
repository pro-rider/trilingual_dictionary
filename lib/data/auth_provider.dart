import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../core/supabase_config.dart';
import 'models/signed_in_user.dart';

/// Current authenticated user (null when signed out).
final authUserProvider = StreamProvider<SignedInUser?>((ref) {
  if (!SupabaseConfig.isConfigured) {
    // Cloud not configured → stay signed out.
    return Stream.value(null);
  }
  return Supabase.instance.client.auth.onAuthStateChange.map((state) {
    final user = state.session?.user;
    return user == null
        ? null
        : SignedInUser(uid: user.id, email: user.email ?? '');
  });
});

/// Auth actions: sign in / sign up / sign out.
final authControllerProvider = Provider<AuthController>((_) => AuthController());

class AuthController {
  bool get isConfigured => SupabaseConfig.isConfigured;

  Future<void> signIn(String email, String password) async {
    await Supabase.instance.client.auth.signInWithPassword(
      email: email.trim(),
      password: password,
    );
  }

  Future<void> signUp(String email, String password) async {
    await Supabase.instance.client.auth.signUp(
      email: email.trim(),
      password: password,
    );
  }

  Future<void> signOut() async {
    await Supabase.instance.client.auth.signOut();
  }
}
