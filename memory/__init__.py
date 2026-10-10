"""Agent memory: a sliding-window buffer and Chroma-backed semantic memory.

Importing this package first makes sure Chroma can load on hosts with an old system sqlite3.
"""

from memory import sqlite_compat  # noqa: F401
