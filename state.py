"""Persisted bot state (survives restarts)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


def _key(user_id: int, duck_number: int) -> str:
    return f"{user_id}:{duck_number}"


class BotState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.game_active: bool = True
        self.fail_streaks: dict[str, int] = {}
        self.pending_review: dict[str, dict[str, Any]] = {}
        self.admin_reviews: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        self.game_active = bool(data.get("game_active", True))
        self.fail_streaks = dict(data.get("fail_streaks", {}))
        self.pending_review = dict(data.get("pending_review", {}))
        self.admin_reviews = dict(data.get("admin_reviews", {}))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "game_active": self.game_active,
            "fail_streaks": self.fail_streaks,
            "pending_review": self.pending_review,
            "admin_reviews": self.admin_reviews,
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def get_streak(self, user_id: int, duck_number: int) -> int:
        return self.fail_streaks.get(_key(user_id, duck_number), 0)

    def set_streak(self, user_id: int, duck_number: int, streak: int) -> None:
        key = _key(user_id, duck_number)
        if streak <= 0:
            self.fail_streaks.pop(key, None)
        else:
            self.fail_streaks[key] = streak
        self.save()

    def get_pending(self, user_id: int, duck_number: int) -> Optional[dict[str, Any]]:
        return self.pending_review.get(_key(user_id, duck_number))

    def set_pending(self, user_id: int, duck_number: int, data: dict[str, Any]) -> None:
        self.pending_review[_key(user_id, duck_number)] = data
        self.save()

    def clear_fail_state(self, user_id: int, duck_number: int) -> None:
        key = _key(user_id, duck_number)
        self.fail_streaks.pop(key, None)
        self.pending_review.pop(key, None)
        self.save()

    def pop_admin_review(self, review_id: str) -> Optional[dict[str, Any]]:
        review = self.admin_reviews.pop(review_id, None)
        if review is not None:
            self.save()
        return review

    def set_admin_review(self, review_id: str, data: dict[str, Any]) -> None:
        self.admin_reviews[review_id] = data
        self.save()
