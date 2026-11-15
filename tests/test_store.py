import os

import pytest

from wdchain.evidence.merkle import keccak256
from wdchain.evidence.store import (
    ContentStore,
    StoreConflictError,
    StoreIntegrityError,
)


def test_put_is_content_addressed_and_idempotent(tmp_path):
    store = ContentStore(tmp_path / "store")
    d = store.put(b"hello")
    assert d == keccak256(b"hello").hex()
    assert (tmp_path / "store" / d).read_bytes() == b"hello"
    assert store.put(b"hello") == d
    assert store.get("0x" + d) == b"hello"


def test_store_is_write_once(tmp_path):
    store = ContentStore(tmp_path / "store")
    d = store.put(b"original")
    with pytest.raises(StoreConflictError):
        store.write_once(d, b"different payload")
    assert store.get(d) == b"original"


def test_tampered_chunk_is_not_silently_repaired(tmp_path):
    store = ContentStore(tmp_path / "store")
    d = store.put(b"original")
    path = store.path_for(d)
    os.chmod(path, 0o644)
    path.write_bytes(b"originaX")
    with pytest.raises(StoreConflictError):
        store.put(b"original")
    assert path.read_bytes() == b"originaX"
    with pytest.raises(StoreIntegrityError):
        store.get(d)


def test_refuses_bytes_under_wrong_digest(tmp_path):
    store = ContentStore(tmp_path / "store")
    with pytest.raises(StoreIntegrityError):
        store.write_once(keccak256(b"a"), b"b")
