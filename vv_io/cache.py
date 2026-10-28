"""ChunkCache — filesystem-backed cache using diskcache."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

import diskcache


class ChunkCache:
    def __init__(self, cache_dir: str = ".vocvizard_cache") -> None:
        self._cache = diskcache.Cache(cache_dir)

    def get(self, key: str) -> Optional[Any]:
        return self._cache.get(key)

    def put(self, key: str, value: Any) -> None:
        self._cache.set(key, value)

    def make_key(self, file_id: str, chunk_idx: int, params: dict) -> str:
        params_hash = hashlib.md5(
            json.dumps(params, sort_keys=True).encode()
        ).hexdigest()[:8]
        return f"{file_id}:{chunk_idx}:{params_hash}"

    def clear_file(self, file_id: str) -> None:
        prefix = f"{file_id}:"
        to_delete = [k for k in self._cache if isinstance(k, str) and k.startswith(prefix)]
        for k in to_delete:
            del self._cache[k]

    def size_mb(self) -> float:
        return self._cache.volume() / (1024 * 1024)
