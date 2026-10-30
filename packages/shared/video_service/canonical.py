"""Shared deterministic JSON/digest contract. No media/runtime dependency."""
import hashlib
import json

def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()
