import base64
import binascii
import getpass
import hashlib
import hmac
import os
import sys

_N, _R, _P = 2**15, 8, 1
_MAX_N, _MAX_R, _MAX_P = 2**16, 16, 4
_MAXMEM = 64 * 1024 * 1024
_DKLEN = 32


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=_MAXMEM, dklen=_DKLEN
    )
    return "$".join(
        [
            "scrypt",
            str(_N),
            str(_R),
            str(_P),
            base64.b64encode(salt).decode(),
            base64.b64encode(digest).decode(),
        ]
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n_s, r_s, p_s, salt_b64, hash_b64 = encoded.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        if not (1 < n <= _MAX_N and 0 < r <= _MAX_R and 0 < p <= _MAX_P):
            return False
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(hash_b64, validate=True)
        if not expected:
            return False
        actual = hashlib.scrypt(
            password.encode(),
            salt=salt,
            n=n,
            r=r,
            p=p,
            maxmem=_MAXMEM,
            dklen=len(expected),
        )
    except ValueError, TypeError, binascii.Error:
        return False
    return hmac.compare_digest(actual, expected)


def main(argv: list[str]) -> int:
    password = argv[1] if len(argv) > 1 else getpass.getpass("Password: ")
    print(hash_password(password))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
