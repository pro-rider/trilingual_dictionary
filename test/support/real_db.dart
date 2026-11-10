import 'dart:io';

/// Locates the locally built dictionary for tests that exercise the real data.
///
/// The file is about 96 MB and is gitignored, so a fresh clone and CI have no
/// data until the builder runs. It used to be referenced by an absolute
/// `C:\Users\...` path baked into the tests, which leaked this machine's layout
/// into the repository and made every one of these tests fail on any other host.
///
/// `flutter test` runs with the package root as the working directory, so the
/// path is resolved from there and works on Windows, macOS and Linux.
String realDictionaryPath() =>
    '${Directory.current.path}/backend/data/build/dictionary.sqlite';

/// True when the built dictionary is absent, i.e. these tests cannot run.
bool missingRealDictionary() => !File(realDictionaryPath()).existsSync();

/// Skip reason used by every test that needs the built dictionary. It names the
/// command that produces it, so a reader of a red-to-yellow run knows the test
/// was not disabled on purpose.
const String kMissingDictionarySkip =
    'dictionary.sqlite not built on this machine: it is gitignored, so CI and a '
    'fresh clone have no data. Run "python backend/tools/build_dictionary.py" '
    'locally to exercise this test.';
