"""Domain errors and exceptions."""


class PMDError(Exception):
    """Base exception for Pinterest Mass Downloader."""

    pass


class ValidationError(PMDError):
    """Raised when input parameters fail validation."""

    pass


class StateTransitionError(PMDError):
    """Raised when an invalid job status transition is requested."""

    pass


class PersistenceError(PMDError):
    """Raised when settings or queue loading/saving fails."""

    pass


class AdapterError(PMDError):
    """Raised when the upstream Pinterest adapter encounters an error."""

    pass


class CancellationError(PMDError):
    """Raised when an operation is cancelled."""

    pass
