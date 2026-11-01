/// A signed-in user (lightweight view model, distinct from Supabase's AuthState).
class SignedInUser {
  const SignedInUser({required this.uid, required this.email});

  final String uid;
  final String email;
}
