import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/constants.dart';

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
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFFE0F2FE), Color(0xFFF7FBFF)],
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
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(24),
                  border: Border.all(color: const Color(0xFFBAE6FD)),
                ),
                child: const Icon(Icons.translate,
                    size: 52, color: LanguageColors.brand),
              ),
              const SizedBox(height: 18),
              const Text(
                'Trilingual Dictionary',
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 8),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: const [
                  Text('English', style: TextStyle(color: LanguageColors.en)),
                  SizedBox(width: 8),
                  Text('·', style: TextStyle(color: Color(0xFF94A3B8))),
                  SizedBox(width: 8),
                  Text('中文', style: TextStyle(color: LanguageColors.zh)),
                  SizedBox(width: 8),
                  Text('·', style: TextStyle(color: Color(0xFF94A3B8))),
                  SizedBox(width: 8),
                  Text('नेपाली', style: TextStyle(color: LanguageColors.ne)),
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
