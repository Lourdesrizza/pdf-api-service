import hashlib


def calculate_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
