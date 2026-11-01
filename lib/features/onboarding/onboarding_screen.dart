import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/constants.dart';

/// Onboarding — 3 slides. Not forced in v1 (splash goes straight home),
/// but kept as an accessible intro.
class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key});

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  int _index = 0;
  final _controller = PageController();

  static const _slides = [
    (icon: Icons.search, title: 'Search English or 中文',
        body: 'Look up any word in English or Chinese. Nepali is never a search input.'),
    (icon: Icons.auto_stories, title: 'Read it in three languages',
        body: 'Every result gives the meaning in English, 中文 and नेपाली.'),
    (icon: Icons.sentiment_satisfied_alt, title: 'Learn from aligned sentences',
        body: 'One example sentence per meaning, aligned across all three languages.'),
  ];

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: PageView.builder(
                controller: _controller,
                itemCount: _slides.length,
                onPageChanged: (i) => setState(() => _index = i),
                itemBuilder: (_, i) {
                  final s = _slides[i];
                  return Padding(
                    padding: const EdgeInsets.all(28),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Container(
                          width: 96,
                          height: 96,
                          decoration: BoxDecoration(
                            color: LanguageColors.brandSoft,
                            borderRadius: BorderRadius.circular(24),
                          ),
                          child: Icon(s.icon,
                              size: 48, color: LanguageColors.brand),
                        ),
                        const SizedBox(height: 24),
                        Text(s.title,
                            textAlign: TextAlign.center,
                            style: const TextStyle(
                                fontSize: 20, fontWeight: FontWeight.w800)),
                        const SizedBox(height: 10),
                        Text(s.body,
                            textAlign: TextAlign.center,
                            style: const TextStyle(
                                fontSize: 14,
                                color: Color(0xFF475569),
                                height: 1.4)),
                      ],
                    ),
                  );
                },
              ),
            ),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                for (var i = 0; i < _slides.length; i++)
                  AnimatedContainer(
                    duration: const Duration(milliseconds: 200),
                    margin: const EdgeInsets.symmetric(horizontal: 3),
                    width: i == _index ? 18 : 8,
                    height: 8,
                    decoration: BoxDecoration(
                      color: i == _index
                          ? LanguageColors.brand
                          : const Color(0xFFCBD5E1),
                      borderRadius: BorderRadius.circular(8),
                    ),
                  ),
              ],
            ),
            Padding(
              padding: const EdgeInsets.all(20),
              child: FilledButton(
                onPressed: () {
                  if (_index < _slides.length - 1) {
                    _controller.nextPage(
                        duration: const Duration(milliseconds: 250),
                        curve: Curves.easeOut);
                  } else {
                    context.go('/home');
                  }
                },
                child: Padding(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 24, vertical: 4),
                  child: Text(_index < _slides.length - 1
                      ? 'Next'
                      : 'Start searching'),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
