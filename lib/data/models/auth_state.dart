/// A signed-in Supabase session (lightweight view model).
class AuthState {
  const AuthState({required this.uid, required this.email});

  final String uid;
  final String email;
}
