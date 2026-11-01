import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../core/api_config.dart';
import '../core/normalizer.dart';
import '../core/supabase_config.dart';
import 'models/analyzed_text.dart';
import 'models/dictionary_entry.dart';

/// Thin client for the FastAPI backend. Failures return null so the offline
/// dictionary always takes over instead of throwing on the user.
final apiClientProvider = Provider<ApiClient>((ref) {
  final dio = Dio(
    BaseOptions(
      baseUrl: ApiConfig.baseUrl,
      connectTimeout: ApiConfig.timeout,
      receiveTimeout: ApiConfig.timeout,
    ),
  );
  // Attach the Supabase JWT when a user is signed in (for protected endpoints).
  dio.interceptors.add(InterceptorsWrapper(onRequest: (options, handler) {
    if (SupabaseConfig.isConfigured) {
      final token = Supabase.instance.client.auth.currentSession?.accessToken;
      if (token != null) {
        options.headers['Authorization'] = 'Bearer $token';
      }
    }
    handler.next(options);
  }));
  return ApiClient(dio);
});

/// Cached: is the FastAPI backend reachable right now?
final backendReachableProvider =
    FutureProvider<bool>((ref) => ref.watch(apiClientProvider).isReachable());

class ApiClient {
  ApiClient(this._dio);
  final Dio _dio;

  /// Search the backend. Returns null when offline / not found / error.
  Future<DictionaryEntry?> search(String query, InputLanguage lang) async {
    try {
      final resp = await _dio.post(
        '/api/v1/search',
        data: {
          'q': query.trim(),
          'lang': lang == InputLanguage.chinese ? 'zh' : 'en',
        },
      );
      final entry = (resp.data as Map?)?['entry'];
      if (entry == null) return null;
      return DictionaryEntry.fromJson(entry as Map<String, dynamic>);
    } on DioException {
      return null;
    } catch (_) {
      return null;
    }
  }

  /// Liveness check — is the backend reachable right now?
  Future<bool> isReachable() async {
    try {
      await _dio.get('/api/v1/health');
      return true;
    } catch (_) {
      return false;
    }
  }

  /// Analyze a word / phrase / sentence / paragraph into per-unit meanings.
  /// Returns null when offline / on error (the screen degrades gracefully).
  Future<AnalyzedText?> analyzeText(String text, InputLanguage lang) async {
    try {
      final resp = await _dio.post(
        '/api/v1/analyze/text',
        data: {
          'text': text.trim(),
          'lang': lang == InputLanguage.chinese ? 'zh' : 'en',
        },
      );
      final data = resp.data;
      if (data == null) return null;
      return AnalyzedText.fromJson(data as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }
}
