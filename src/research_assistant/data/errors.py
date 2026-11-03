"""One error type for every data provider, so tools can turn any failure into a status."""


class DataError(Exception):
    """A provider gave no usable answer. `code` is stable: not_configured, not_found, http_error,
    network, too_large or bad_data."""

    def __init__(self, message: str, code: str, status: int | None = None):
        super().__init__(message)
        self.code, self.status = code, status
