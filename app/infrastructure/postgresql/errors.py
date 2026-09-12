"""Safe infrastructure lifecycle failures without SQL or connection details."""


class DatabaseUnavailableError(RuntimeError):
    """The pool or server cannot currently complete the requested operation."""


class TransactionRetryError(RuntimeError):
    """A replayable transaction exhausted its bounded concurrency retries."""


class SchemaCompatibilityError(RuntimeError):
    """Explicit operator migration is required before this application can run."""


class MigrationError(RuntimeError):
    """The operator migration failed and its transaction was rolled back."""
