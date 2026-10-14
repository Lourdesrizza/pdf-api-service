from typing import Protocol


class ResultCache(Protocol):
    async def get(self, checksum: str) -> dict | None: ...
    async def set(self, checksum: str, value: dict) -> None: ...


class NullResultCache:
    async def get(self, checksum: str) -> None:
        return None

    async def set(self, checksum: str, value: dict) -> None:
        return None
