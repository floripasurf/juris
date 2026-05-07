"""Tests for storage backend."""

from pathlib import Path

import pytest

from juris.core.storage import LocalFileStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
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

    @pytest.mark.asyncio
    async def test_absolute_path_blocked(self, storage: LocalFileStorage) -> None:
        with pytest.raises(ValueError, match="absolute path"):
            await storage.put("/etc/passwd", b"bad")

    @pytest.mark.asyncio
    async def test_symlink_escape_blocked(self, storage: LocalFileStorage, tmp_path: Path) -> None:
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        link_path = storage._root / "linked"
        link_path.symlink_to(outside_dir, target_is_directory=True)

        with pytest.raises(ValueError, match="escapes root"):
            await storage.put("linked/escape.txt", b"bad")

    @pytest.mark.asyncio
    async def test_resolved_path_stays_under_root(self, storage: LocalFileStorage) -> None:
        path = storage._path("docs/test.pdf")

        assert path.is_relative_to(storage._root.resolve())
