"""Operator-only helper; prints a one-way hash, never writes credentials to disk."""
import getpass
import hmac
from dashboard import make_password_hash

if __name__ == "__main__":
    first = getpass.getpass("Administrator password (minimum 12 characters): ")
    second = getpass.getpass("Confirm password: ")
    if not hmac.compare_digest(first.encode(), second.encode()):
        raise SystemExit("Passwords did not match")
    print(make_password_hash(first))
