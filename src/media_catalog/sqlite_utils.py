from __future__ import annotations

import sqlite3
from pathlib import Path

# The UI polls, the worker writes and the heartbeat thread writes concurrently.
# Wait instead of failing fast with "database is locked".
BUSY_TIMEOUT_SECONDS = 30.0


class ClosingConnection(sqlite3.Connection):
    """``with connect(...)`` commits or rolls back *and* closes the handle.

    The stock ``sqlite3.Connection`` context manager only ends the transaction,
    so every ``with`` block used to leak an open file handle until GC.
    """

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(path: Path | str, *, timeout: float = BUSY_TIMEOUT_SECONDS) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=timeout, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    return connection
