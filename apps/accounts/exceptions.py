class EmailAlreadyRegisteredError(Exception):
    """Raised when an account with the same email already exists."""


class InvalidVerificationTokenError(Exception):
    """Raised when an email verification link is tampered with, expired, or outdated."""


class InvalidPasswordResetLinkError(Exception):
    """Raised when a password reset link is tampered with, expired, or already used."""


class AccountDeletionBlockedError(Exception):
    """The user still owns organizations, belongs to one, or hosts an upcoming event."""
