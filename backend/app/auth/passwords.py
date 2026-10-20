"""Password rules and Argon2id hashing.

Hashing uses OWASP's Argon2id configuration of 19 MiB memory, 2 iterations
and 1 thread, which suits small servers (Render's free tier has 512 MB RAM).
The parameters are stored inside each hash, so they can be raised later:
needs_rehash() tells login code when a stored hash should be upgraded.
"""

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 12
# An upper bound stops very long inputs being used to waste server time.
MAX_PASSWORD_LENGTH = 128

_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=19456,  # KiB, i.e. 19 MiB
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


class PasswordPolicyError(ValueError):
    """The password does not meet the rules. The message is safe to show users."""


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters long."
        )
    if not password.strip():
        raise PasswordPolicyError("Password cannot consist only of spaces.")


def hash_password(password: str) -> str:
    """Check the rules, then return an Argon2id hash with a random salt."""
    validate_password(password)
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """True only if the password matches. Never raises for bad input."""
    if len(password) > MAX_PASSWORD_LENGTH:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True if the hash was made with different (for example older) parameters."""
    return _hasher.check_needs_rehash(password_hash)
