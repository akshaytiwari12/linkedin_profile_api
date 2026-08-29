import json
import os
import tempfile
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class JsonTable(Generic[T]):
    """Minimal dependency-free persistence: each 'table' is a JSON object on disk keyed by id.

    Writes are atomic (temp file + rename) so a crash mid-write cannot corrupt the file. A
    single process with one event loop needs no cross-process locking; swap this for SQLite or
    Postgres if this ever runs as multiple workers (see README "Known limitations").
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        if os.path.exists(file_path):
            with open(file_path, encoding="utf-8") as handle:
                self._data: dict[str, Any] = json.load(handle)
        else:
            self._data = {}

    def get(self, key: str) -> T | None:
        return self._data.get(key)

    def set(self, key: str, value: T) -> None:
        self._data[key] = value
        self._persist()

    def delete(self, key: str) -> None:
        self._data.pop(key, None)
        self._persist()

    def values(self) -> list[T]:
        return list(self._data.values())

    def _persist(self) -> None:
        directory = os.path.dirname(self.file_path) or "."
        with tempfile.NamedTemporaryFile(
            "w", dir=directory, delete=False, encoding="utf-8"
        ) as handle:
            json.dump(self._data, handle, indent=2)
            temp_path = handle.name
        os.replace(temp_path, self.file_path)
