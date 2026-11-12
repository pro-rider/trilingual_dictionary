import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

/// Minimal crash/error hook.
///
/// Deliberately not an SDK: shipping a crash reporter is a privacy decision
/// (see docs/PLAY_DATA_SAFETY.md), so this records failures locally and hands
/// them to a sink. No user text is ever written: the record is the error
/// object, the stack trace and a short context tag.
class Diagnostics {
  Diagnostics({this.sink});

  /// Where a record goes. Null means "local file only".
  final void Function(String record)? sink;

  File? _file;

  Future<void> init() async {
    try {
      final dir = await getApplicationSupportDirectory();
      _file = File(p.join(dir.path, 'diagnostics.log'));
    } catch (_) {
      _file = null;
    }

    FlutterError.onError = (details) {
      record(
        'flutter_error',
        details.exceptionAsString(),
        details.stack?.toString(),
      );
      FlutterError.presentError(details);
    };

    PlatformDispatcher.instance.onError = (error, stack) {
      record('platform_error', error.toString(), stack.toString());
      return true; // handled: the app keeps running rather than dying silently
    };
  }

  /// Append one line. Errors here must never themselves crash the app.
  void record(String kind, String error, String? stack) {
    final line = '${DateTime.now().toUtc().toIso8601String()} $kind $error '
        '${stack == null ? '' : stack.split('\n').take(6).join(' | ')}';
    try {
      _file?.writeAsStringSync('$line\n', mode: FileMode.append, flush: true);
    } catch (_) {}
    try {
      sink?.call(line);
    } catch (_) {}
    if (kDebugMode) debugPrint('[diagnostics] $error');
  }
}
