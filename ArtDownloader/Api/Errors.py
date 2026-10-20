class ApiError(Exception):
    """A safe, user-facing failure while talking to a source."""


class AuthError(ApiError):
    """Credentials were rejected, or the session could not be restored."""
