class EmailAlreadyRegisteredError(Exception):
    """Raised when an account with the same email already exists."""


class InvalidVerificationTokenError(Exception):
    """Raised when an email verification link is tampered with, expired, or outdated."""
