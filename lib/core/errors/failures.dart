/// Domain failures used across the app.
class Failure implements Exception {
  final String message;
  const Failure(this.message);

  @override
  String toString() => message;
}

class NotFoundFailure extends Failure {
  const NotFoundFailure(
      [super.message = 'No entry found for this query.']);
}

class DatasetLoadFailure extends Failure {
  const DatasetLoadFailure(
      [super.message = 'Could not load the dictionary.']);
}
