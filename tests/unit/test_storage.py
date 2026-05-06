"""Tests for storage backend."""

import pytest

from juris.core.storage import LocalFileStorage


@pytest.fixture
def storage(tmp_path):
    return LocalFileStorage(tmp_path / "test_storage")


class TestLocalFileStorage:
    @pytest.mark.asyncio
    async def test_put_and_get(self, storage: LocalFileStorage) -> None:
        result = await storage.put("docs/test.pdf", b"hello", "application/pdf")
        assert result.size == 5
        assert result.sha256 is not None
        data = await storage.get("docs/test.pdf")
        assert data == b"hello"

    @pytest.mark.asyncio
    async def test_exists(self, storage: LocalFileStorage) -> None:
        assert await storage.exists("nonexistent") is False
        await storage.put("test.txt", b"data")
        assert await storage.exists("test.txt") is True

    @pytest.mark.asyncio
    async def test_delete(self, storage: LocalFileStorage) -> None:
        await storage.put("test.txt", b"data")
        await storage.delete("test.txt")
        assert await storage.exists("test.txt") is False

    @pytest.mark.asyncio
    async def test_get_nonexistent_raises(self, storage: LocalFileStorage) -> None:
        with pytest.raises(FileNotFoundError):
            await storage.get("nonexistent")

    @pytest.mark.asyncio
    async def test_directory_traversal_blocked(self, storage: LocalFileStorage) -> None:
        with pytest.raises(ValueError, match="directory traversal"):
            await storage.put("../../etc/passwd", b"bad")
