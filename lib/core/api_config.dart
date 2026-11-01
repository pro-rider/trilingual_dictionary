/// Backend API configuration.
///
/// Default points at the local FastAPI server. On the **Android emulator**,
/// `127.0.0.1` is the emulator itself — change to `http://10.0.2.2:8000`
/// (the host machine) to reach your backend.
class ApiConfig {
  static const String baseUrl =
      String.fromEnvironment('API_BASE_URL', defaultValue: 'http://127.0.0.1:8000');

  // 25s: single-word AI is fast, but a whole-paragraph batched analyze call
  // (multi-provider failover) can take noticeably longer than the old 6s.
  static const Duration timeout = Duration(seconds: 25);
}
