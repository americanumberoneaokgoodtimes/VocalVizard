from vv_io.cache import ChunkCache


def test_put_and_get_roundtrip(tmp_path):
    cache = ChunkCache(str(tmp_path))
    key = cache.make_key("abc123", 0, {"alpha": 2.2})
    cache.put(key, [1.0, 2.0, 3.0])
    assert cache.get(key) == [1.0, 2.0, 3.0]


def test_get_missing_returns_none(tmp_path):
    cache = ChunkCache(str(tmp_path))
    assert cache.get("nonexistent") is None


def test_clear_file_removes_entries(tmp_path):
    cache = ChunkCache(str(tmp_path))
    k1 = cache.make_key("file1", 0, {})
    k2 = cache.make_key("file2", 0, {})
    cache.put(k1, "a")
    cache.put(k2, "b")
    cache.clear_file("file1")
    assert cache.get(k1) is None
    assert cache.get(k2) == "b"


def test_make_key_is_deterministic(tmp_path):
    cache = ChunkCache(str(tmp_path))
    k1 = cache.make_key("f", 0, {"a": 1, "b": 2})
    k2 = cache.make_key("f", 0, {"b": 2, "a": 1})
    assert k1 == k2          # param order must not matter
