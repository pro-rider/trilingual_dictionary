import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../core/api_config.dart';
import '../core/normalizer.dart';
import '../core/supabase_config.dart';
import 'models/analyzed_text.dart';
import 'models/dictionary_entry.dart';
import 'models/word_image.dart';

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

  /// Approved images for one entry. Returns null when offline / no backend.
  Future<WordImages?> images(String entryId) async {
    try {
      final resp = await _dio.get(
        '/api/v1/images',
        queryParameters: {'entry_id': entryId},
      );
      final data = resp.data;
      if (data == null) return null;
      return WordImages.fromJson(data as Map<String, dynamic>);
    } on DioException {
      return null;
    } catch (_) {
      return null;
    }
  }

  /// Fill missing Nepali glosses + example sentences for the senses the user
  /// just opened. Returns `{key: {ne, example_en, example_zh, example_ne}}`,
  /// empty when offline — the app then stores what it got locally.
  Future<Map<String, Map<String, String>>> enrich(
      List<MapEntry<String, String>> items) async {
    if (items.isEmpty) return const {};
    try {
      final resp = await _dio.post(
        '/api/v1/dictionary/enrich',
        data: {
          'items': [
            for (final item in items) {
              // key<TAB>chinese<TAB>english: the key is an opaque handle the
              // server echoes back, so the caller never has to parse it.
              'key': item.key,
              'zh': item.value.split('\u0001').first,
              'en': item.value.split('\u0001').last,
            }
          ]
        },
      );
      final list = (resp.data as Map?)?['items'] as List? ?? const [];
      final out = <String, Map<String, String>>{};
      for (final raw in list) {
        final map = raw as Map<String, dynamic>;
        out[map['key'] as String] = {
          'ne': map['ne'] as String? ?? '',
          'example_en': map['example_en'] as String? ?? '',
          'example_zh': map['example_zh'] as String? ?? '',
          'example_ne': map['example_ne'] as String? ?? '',
        };
      }
      return out;
    } catch (_) {
      return const {};
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
