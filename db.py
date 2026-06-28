"""SQLite database helpers for duck claims."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class DuckClaim:
    duck_number: int
    finder_user_id: int
    finder_handle: Optional[str]
    finder_name: str
    claimed_at: str


@dataclass
class LeaderboardEntry:
    finder_user_id: int
    finder_handle: Optional[str]
    finder_name: str
    count: int


class DuckDatabase:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ducks (
                    duck_number INTEGER PRIMARY KEY,
                    finder_user_id INTEGER,
                    finder_handle TEXT,
                    finder_name TEXT,
                    claimed_at TEXT
                )
                """
            )

    def seed_ducks(self, total_ducks: int) -> int:
        """Insert missing duck rows 1..total_ducks. Returns rows inserted."""
        with self._connect() as conn:
            existing = {
                row["duck_number"]
                for row in conn.execute("SELECT duck_number FROM ducks")
            }
            to_insert = [
                (duck_number,)
                for duck_number in range(1, total_ducks + 1)
                if duck_number not in existing
            ]
            if to_insert:
                conn.executemany(
                    "INSERT INTO ducks (duck_number) VALUES (?)",
                    to_insert,
                )
            return len(to_insert)

    def get_claim(self, duck_number: int) -> Optional[DuckClaim]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT duck_number, finder_user_id, finder_handle, finder_name, claimed_at
                FROM ducks
                WHERE duck_number = ? AND finder_user_id IS NOT NULL
                """,
                (duck_number,),
            ).fetchone()
            if row is None:
                return None
            return DuckClaim(
                duck_number=row["duck_number"],
                finder_user_id=row["finder_user_id"],
                finder_handle=row["finder_handle"],
                finder_name=row["finder_name"],
                claimed_at=row["claimed_at"],
            )

    def claim_duck(
        self,
        duck_number: int,
        finder_user_id: int,
        finder_handle: Optional[str],
        finder_name: str,
    ) -> bool:
        """Atomically claim a duck. Returns True if this claim succeeded."""
        claimed_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE ducks
                SET finder_user_id = ?,
                    finder_handle = ?,
                    finder_name = ?,
                    claimed_at = ?
                WHERE duck_number = ? AND finder_user_id IS NULL
                """,
                (
                    finder_user_id,
                    finder_handle,
                    finder_name,
                    claimed_at,
                    duck_number,
                ),
            )
            return cursor.rowcount == 1

    def remove_claim(self, duck_number: int) -> Optional[DuckClaim]:
        """Clear a duck claim. Returns the removed claim, or None if unclaimed."""
        existing = self.get_claim(duck_number)
        if existing is None:
            return None
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ducks
                SET finder_user_id = NULL,
                    finder_handle = NULL,
                    finder_name = NULL,
                    claimed_at = NULL
                WHERE duck_number = ?
                """,
                (duck_number,),
            )
        return existing

    def count_remaining(self, total_ducks: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS remaining
                FROM ducks
                WHERE duck_number BETWEEN 1 AND ? AND finder_user_id IS NULL
                """,
                (total_ducks,),
            ).fetchone()
            return int(row["remaining"])

    def get_leaderboard(self, total_ducks: int) -> list[LeaderboardEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    finder_user_id,
                    finder_handle,
                    finder_name,
                    COUNT(*) AS count
                FROM ducks
                WHERE duck_number BETWEEN 1 AND ?
                  AND finder_user_id IS NOT NULL
                GROUP BY finder_user_id, finder_handle, finder_name
                ORDER BY count DESC, finder_name ASC
                """,
                (total_ducks,),
            ).fetchall()
            return [
                LeaderboardEntry(
                    finder_user_id=row["finder_user_id"],
                    finder_handle=row["finder_handle"],
                    finder_name=row["finder_name"],
                    count=row["count"],
                )
                for row in rows
            ]
