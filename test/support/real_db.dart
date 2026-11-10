import 'dart:io';

/// Where the Flutter tests find a dictionary database, and why.
///
/// There are two candidates, and every test goes through [testDictionaryPath]
/// so the choice is made in one place:
///
/// 1. **The committed fixture** — `backend/data/test_fixtures/dictionary_fixture.sqlite`.
///    A ~160 KB subset of *real* rows (same schema, same ids, same glosses),
///    built by `python backend/tools/make_test_fixture.py`. It is tracked by
///    git, so a fresh clone and GitHub Actions both have it. The offline
///    search, image and analysis suites run against it in CI.
///
/// 2. **The full build** — `backend/data/build/dictionary.sqlite`, about 96 MB.
///    Gitignored: only a machine that ran `build_dictionary.py` has it. When the
///    fixture is missing (someone deleted it, or a source tree without the
///    generated file), the suites use this instead so a developer still tests
///    against the complete dictionary.
///
/// Both paths are resolved from the package root. `flutter test` sets the
/// working directory to the package root on Windows, macOS and Linux, so no
/// test needs an absolute path and none depends on a specific user name.
///
/// If neither file exists, the suites skip with [kMissingDictionarySkip]
/// instead of failing on an empty database — a skip that names the command
/// which produces the data, so it never looks like a test that was disabled to
/// make a build green.
String fixtureDictionaryPath() =>
    '${Directory.current.path}/backend/data/test_fixtures/dictionary_fixture.sqlite';

String fullDictionaryPath() =>
    '${Directory.current.path}/backend/data/build/dictionary.sqlite';

/// The database the tests should use: the committed fixture when present,
/// otherwise the locally built full dictionary.
String testDictionaryPath() =>
    File(fixtureDictionaryPath()).existsSync()
        ? fixtureDictionaryPath()
        : fullDictionaryPath();

/// True when neither the fixture nor the full build is available.
bool missingTestDictionary() => !File(testDictionaryPath()).existsSync();

/// True when the suite is running against the small committed fixture rather
/// than the full dictionary. Tests that need full-corpus behaviour (ranking
/// across thousands of candidates) should assert on this and skip if true.
bool usingFixture() => testDictionaryPath() == fixtureDictionaryPath();

/// Skip reason used by every test that needs a dictionary and has none. It
/// names the command that produces the data.
const String kMissingDictionarySkip =
    'no dictionary database available: the committed fixture '
    '(backend/data/test_fixtures/dictionary_fixture.sqlite) is missing, and the '
    'full build is not present either. Run "python backend/tools/make_test_fixture.py" '
    'or "python backend/tools/build_dictionary.py" to exercise these tests.';
