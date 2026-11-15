import 'package:flutter_riverpod/flutter_riverpod.dart';

/// The access token issued by **our** FastAPI backend after sign-in.
///
/// A24: the mobile client talks only to FastAPI and never holds a Supabase key.
/// An anon key in an APK is extractable, and anyone who extracts it can call
/// Supabase Auth directly — past our lockouts, blocklist, Turnstile and event
/// log. So there is no Supabase client here at all; this in-memory holder is
/// filled by the FastAPI login flow and persisted to secure storage.
///
final authTokenProvider = StateProvider<String?>((ref) => null);
