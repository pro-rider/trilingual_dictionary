import 'dart:math' as math;

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api_config.dart';
import 'auth_token.dart';

/// Everything the account screen calls, against **our** FastAPI backend.
///
/// No Supabase key is ever held here (A24): the app posts e-mail and password to
/// FastAPI, which owns the code, the lockouts and the sessions.
class AuthFailure implements Exception {
  AuthFailure(this.message, {this.status});

  final String message;
  final int? status;

  @override
  String toString() => message;
}

final authApiProvider = Provider<AuthApi>((ref) {
  final dio = Dio(
    BaseOptions(
      baseUrl: ApiConfig.baseUrl,
      connectTimeout: ApiConfig.timeout,
      receiveTimeout: ApiConfig.timeout,
      // We handle every status ourselves: the account screen has to show the
      // server's message ("service not configured", "code expired", ...).
      validateStatus: (_) => true,
    ),
  );
  dio.interceptors.add(InterceptorsWrapper(onRequest: (options, handler) {
    final token = ref.read(authTokenProvider);
    if (token != null && token.isNotEmpty) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    handler.next(options);
  }));
  return AuthApi(dio, ref);
});

/// A per-install identifier for the session list. Random, not a hardware id, and
/// it is only ever sent as a hash on the server side.
final deviceIdProvider = Provider<String>((ref) {
  final rnd = math.Random.secure();
  return List.generate(16, (_) => rnd.nextInt(16).toRadixString(16)).join();
});

class SessionRow {
  SessionRow({
    required this.id,
    required this.label,
    required this.createdAt,
    required this.lastSeen,
    required this.current,
  });

  final String id;
  final String label;
  final DateTime createdAt;
  final DateTime lastSeen;
  final bool current;

  factory SessionRow.fromJson(Map<String, dynamic> json) => SessionRow(
        id: json['session_id'] as String,
        label: (json['device_label'] as String?) ?? 'app',
        createdAt: DateTime.fromMillisecondsSinceEpoch(
            ((json['created_at'] as num?) ?? 0).toInt() * 1000),
        lastSeen: DateTime.fromMillisecondsSinceEpoch(
            ((json['last_seen'] as num?) ?? 0).toInt() * 1000),
        current: (json['current'] as bool?) ?? false,
      );
}

class AuthProfile {
  AuthProfile({
    required this.email,
    required this.username,
    required this.status,
    required this.nepaliEnabled,
  });

  final String email;
  final String? username;
  final String status;
  final bool nepaliEnabled;

  factory AuthProfile.fromJson(Map<String, dynamic> json) => AuthProfile(
        email: (json['email'] as String?) ?? '',
        username: json['username'] as String?,
        status: (json['status'] as String?) ?? '',
        nepaliEnabled: (json['nepali_enabled'] as bool?) ?? true,
      );
}

class AuthApi {
  AuthApi(this._dio, this._ref);

  final Dio _dio;
  final Ref _ref;

  void _storeTokens(Map<String, dynamic> body) {
    final access = body['access_token'] as String?;
    if (access != null && access.isNotEmpty) {
      _ref.read(authTokenProvider.notifier).state = access;
    }
  }

  Future<void> _expectOk(Response<dynamic> r, {String fallback = 'Something went wrong'}) async {
    final status = r.statusCode ?? 0;
    if (status >= 200 && status < 300) return;
    throw AuthFailure(_detail(r.data, fallback: fallback), status: status);
  }

  String _detail(dynamic data, {String fallback = 'Something went wrong'}) {
    if (data is Map) {
      final detail = data['detail'];
      if (detail is String && detail.trim().isNotEmpty) return detail;
      // 422 from the strict models: never echo the input, so show the field.
      if (detail is List && detail.isNotEmpty) {
        final first = detail.first;
        if (first is Map) {
          final loc = first['loc'];
          final msg = first['msg'];
          if (msg is String) {
            final field = (loc is List && loc.isNotEmpty) ? loc.last.toString() : '';
            return field.isEmpty ? msg : '$field: $msg';
          }
        }
      }
      final error = data['error'];
      if (error is String) return error;
    }
    return fallback;
  }

  /// Step 1 — always the same answer, whether or not the address is known.
  Future<void> registerStart(String email) async {
    final r = await _dio.post('/api/v1/auth/register/start', data: {'email': email});
    await _expectOk(r, fallback: 'Could not send the code');
  }

  /// Step 2 — the code proves the address belongs to the caller.
  Future<String> registerVerify(String email, String code) async {
    final r = await _dio.post(
      '/api/v1/auth/register/verify',
      data: {'email': email, 'code': code},
    );
    await _expectOk(r, fallback: 'That code did not work');
    final token = ((r.data as Map?)?['signup_token'] as String?) ?? '';
    if (token.isEmpty) throw AuthFailure('The server did not return a signup token');
    return token;
  }

  /// Step 3 — only here does an account (and a password) exist.
  Future<void> registerComplete({
    required String signupToken,
    required String username,
    required String password,
  }) async {
    final r = await _dio.post(
      '/api/v1/auth/register/complete',
      data: {
        'signup_token': signupToken,
        'username': username,
        'password': password,
      },
      options: Options(headers: {'X-Device-Label': 'app'}),
    );
    await _expectOk(r, fallback: 'Could not create the account');
    _storeTokens(r.data as Map<String, dynamic>? ?? const {});
  }

  Future<void> login({
    required String identifier,
    required String password,
    required String deviceId,
  }) async {
    final r = await _dio.post(
      '/api/v1/auth/login',
      data: {
        'identifier': identifier,
        'password': password,
        'device_id': deviceId,
      },
      options: Options(headers: {'X-Device-Label': 'app'}),
    );
    await _expectOk(r, fallback: 'Invalid username or password');
    _storeTokens(r.data as Map<String, dynamic>? ?? const {});
  }

  Future<void> logout() async {
    final r = await _dio.post('/api/v1/auth/logout', data: const {});
    _ref.read(authTokenProvider.notifier).state = null;
    // A best-effort call: a network failure must not keep the user signed in
    // locally.
    if (r.statusCode != null && r.statusCode! >= 400 && r.statusCode! != 401) {
      throw AuthFailure(_detail(r.data, fallback: 'Signed out on this device only'),
          status: r.statusCode);
    }
  }

  Future<AuthProfile> profile() async {
    final r = await _dio.get('/api/v1/auth/profile');
    await _expectOk(r, fallback: 'Could not read the profile');
    return AuthProfile.fromJson(r.data as Map<String, dynamic>);
  }

  Future<List<SessionRow>> sessions() async {
    final r = await _dio.get('/api/v1/auth/sessions');
    await _expectOk(r, fallback: 'Could not list the sessions');
    final list = ((r.data as Map?)?['sessions'] as List?) ?? const [];
    return [
      for (final raw in list) SessionRow.fromJson(raw as Map<String, dynamic>),
    ];
  }

  Future<void> logoutAll() async {
    final r = await _dio.post('/api/v1/auth/logout-all', data: const {});
    _ref.read(authTokenProvider.notifier).state = null;
    await _expectOk(r, fallback: 'Could not end the other sessions');
  }

  Future<void> revokeSession(String sessionId) async {
    final r = await _dio.delete('/api/v1/auth/sessions/$sessionId');
    await _expectOk(r, fallback: 'Could not end that session');
  }

  Future<bool> usernameAvailable(String username) async {
    final r = await _dio.get(
      '/api/v1/auth/username/available',
      queryParameters: {'username': username},
    );
    await _expectOk(r, fallback: 'Could not check that username');
    return ((r.data as Map?)?['available'] as bool?) ?? false;
  }

  Future<void> passwordForgot(String email) async {
    final r = await _dio.post('/api/v1/auth/password/forgot', data: {'email': email});
    await _expectOk(r, fallback: 'Could not send the code');
  }

  Future<void> passwordReset({required String email, required String code, required String password}) async {
    final r = await _dio.post(
      '/api/v1/auth/password/reset',
      data: {'email': email, 'code': code, 'new_password': password},
    );
    await _expectOk(r, fallback: 'Could not reset the password');
    _storeTokens(r.data as Map<String, dynamic>? ?? const {});
  }

  Future<void> changePassword({required String currentPassword, required String newPassword}) async {
    final r = await _dio.post(
      '/api/v1/auth/password/change',
      data: {'current_password': currentPassword, 'new_password': newPassword},
    );
    await _expectOk(r, fallback: 'Could not change the password');
  }

  /// Needs the account's own credential: a stolen token cannot delete an account.
  Future<void> deleteAccount({required String password}) async {
    final r = await _dio.delete(
      '/api/v1/auth/account',
      data: {'confirm': true, 'password': password},
    );
    _ref.read(authTokenProvider.notifier).state = null;
    await _expectOk(r, fallback: 'Could not delete the account');
  }
}
