"""PIN hashing and verification.

Cost parameters are versioned code constants, deliberately NOT user-tunable
(critique finding 7: a settings-based cost would be a downgrade vector).
Every hash record stores its parameters; verification transparently rehashes
when the baseline moved.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

# Version 1 baseline (OWASP-order-of-magnitude scrypt parameters for
# interactive logins; bump _PIN_HASH_VERSION when changing them).
_PIN_HASH_VERSION = 1
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_KEY_LEN = 32


def hash_pin(pin: str) -> dict[str, Any]:
    salt = os.urandom(_SALT_BYTES)
    derived = hashlib.scrypt(
        pin.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_KEY_LEN
    )
    return {
        "version": _PIN_HASH_VERSION,
        "algorithm": "scrypt",
        "salt": salt.hex(),
        "n": _SCRYPT_N,
        "r": _SCRYPT_R,
        "p": _SCRYPT_P,
        "hash": derived.hex(),
    }


def verify_pin(pin: str, record: dict[str, Any]) -> bool:
    if record.get("algorithm") != "scrypt":
        return False
    derived = hashlib.scrypt(
        pin.encode(),
        salt=bytes.fromhex(record["salt"]),
        n=record["n"],
        r=record["r"],
        p=record["p"],
        dklen=_KEY_LEN,
    )
    return hmac.compare_digest(derived.hex(), record["hash"])


def needs_rehash(record: dict[str, Any]) -> bool:
    return record.get("version", 0) < _PIN_HASH_VERSION
