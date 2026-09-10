"""Generate a password hash for AUTH_PASSWORD_HASH.

    python -m src.auth.hash_password

Reads the password without echoing it, and prints the line to paste into .env.
"""
import getpass
import sys

from src.auth.security import generate_secret_key, hash_password


def main() -> int:
    password = getpass.getpass("Password: ")
    if not password:
        print("No password entered.", file=sys.stderr)
        return 1
    if password != getpass.getpass("Confirm: "):
        print("Passwords did not match.", file=sys.stderr)
        return 1

    print("\nAdd these to .env:\n")
    print(f"AUTH_PASSWORD_HASH={hash_password(password)}")
    print(f"SECRET_KEY={generate_secret_key()}")
    print("\nKeep .env out of version control; it is already gitignored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
