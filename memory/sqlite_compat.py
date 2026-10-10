"""Make Chroma importable on hosts whose system sqlite3 is too old.

Chroma requires sqlite3 >= 3.35. Some Linux distributions (for example RHEL 8, which ships 3.26)
are older, so when that is the case and ``pysqlite3-binary`` is installed, this module registers
it as ``sqlite3`` before Chroma is imported. Import this module before ``chromadb``.
"""

import sqlite3
import sys

MINIMUM_SQLITE_VERSION = (3, 35, 0)


def ensure_compatible_sqlite() -> None:
    """Swap in the bundled ``pysqlite3`` module when the system sqlite3 is too old."""
    if sqlite3.sqlite_version_info >= MINIMUM_SQLITE_VERSION:
        return
    try:
        import pysqlite3  # type: ignore[import-not-found]
    except ImportError:
        return  # Chroma will raise its own clear error about the sqlite3 version.
    sys.modules["sqlite3"] = pysqlite3


ensure_compatible_sqlite()
