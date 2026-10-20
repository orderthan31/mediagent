"""Password primitives and throttling exception for PostgreSQL accounts."""
import hashlib
import hmac
import secrets
from functools import lru_cache
from threading import Lock

_kdf_lock = Lock()


def _derive(password, salt):
    # Bound concurrent 128 MiB scrypt allocations in the API process.
    with _kdf_lock:
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=131072, r=8, p=1, maxmem=256*1024**2)


def password_hash(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("Password must contain 12 to 256 characters")
    salt = secrets.token_bytes(16)
    digest = _derive(password, salt)
    return f"scrypt-v1${salt.hex()}${digest.hex()}"


def verify_password(password, encoded):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        return False
    try:
        version, salt, expected = encoded.split("$")
        if version != "scrypt-v1" or len(salt) != 32 or len(expected) != 128:
            return False
        actual = _derive(password, bytes.fromhex(salt))
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError, AttributeError):
        return False


@lru_cache(maxsize=1)
def dummy_hash():
    return password_hash(secrets.token_urlsafe(32))


class LoginThrottled(Exception):
    def __init__(self, retry_after):
        self.retry_after = retry_after
