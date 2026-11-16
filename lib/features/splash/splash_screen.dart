import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../app/theme/app_tokens.dart';

/// Boot screen → routes to /home after a short splash.
class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer(const Duration(milliseconds: 1400), () {
      if (mounted) context.go('/home');
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tokens = context.tokens;
    return Scaffold(
      body: Container(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [tokens.brandSoft, tokens.page],
          ),
        ),
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 96,
                height: 96,
                decoration: BoxDecoration(
                  color: tokens.surface,
                  borderRadius: BorderRadius.circular(24),
                  border: Border.all(color: tokens.border),
                ),
                child: Icon(Icons.translate,
                    size: 52, color: tokens.brandFill),
              ),
              const SizedBox(height: 18),
              Text(
                'Trilingual Dictionary',
                style: TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.w800,
                    color: tokens.textPrimary),
              ),
              const SizedBox(height: 8),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text('English', style: TextStyle(color: tokens.brand)),
                  const SizedBox(width: 8),
                  Text('·', style: TextStyle(color: tokens.textMuted)),
                  const SizedBox(width: 8),
                  Text('中文', style: TextStyle(color: tokens.zh)),
                  const SizedBox(width: 8),
                  Text('·', style: TextStyle(color: tokens.textMuted)),
                  const SizedBox(width: 8),
                  Text('नेपाली', style: TextStyle(color: tokens.ne)),
                ],
              ),
              const SizedBox(height: 24),
              const CircularProgressIndicator(strokeWidth: 2),
            ],
          ),
        ),
      ),
    );
  }
}
