import base64
import subprocess
import sys

from phoebe.auth import hash_password, verify_password


def test_password_roundtrip():
    h = hash_password("larkspur-demo")
    assert verify_password("larkspur-demo", h) and not verify_password("x", h)


def test_format_and_unique_salt():
    h = hash_password("pw")
    parts = h.split("$")
    assert parts[:4] == ["scrypt", "32768", "8", "1"]
    assert len(base64.b64decode(parts[4])) == 16
    assert len(base64.b64decode(parts[5])) == 32
    assert "\n" not in h
    assert h != hash_password("pw")


def test_malformed_hash_false():
    assert verify_password("x", "garbage") is False
    assert verify_password("x", "") is False
    assert verify_password("x", "scrypt$a$b$c$d$e") is False
    assert verify_password("x", "scrypt$32768$8$1$!!!$!!!") is False
    assert verify_password("x", "bcrypt$32768$8$1$AAAA$AAAA") is False


def test_dos_parameters_rejected():
    salt = base64.b64encode(b"s" * 16).decode()
    h = base64.b64encode(b"h" * 32).decode()
    for n, r, p in [(2**17, 8, 1), (2**15, 17, 1), (2**15, 8, 5)]:
        assert verify_password("x", f"scrypt${n}${r}${p}${salt}${h}") is False


def test_cli_argv_prints_only_hash():
    out = subprocess.run(
        [sys.executable, "-m", "phoebe.auth", "larkspur-demo"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.count("\n") == 1
    assert verify_password("larkspur-demo", out.strip())
