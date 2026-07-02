"""Local storage for admin hiding-spot reference photos."""

from __future__ import annotations

from pathlib import Path


def spot_path(spots_dir: Path, duck_number: int) -> Path:
    return spots_dir / f"{duck_number:03d}.jpg"


def spot_exists(spots_dir: Path, duck_number: int) -> bool:
    return spot_path(spots_dir, duck_number).is_file()


def save_spot(spots_dir: Path, duck_number: int, image_bytes: bytes) -> None:
    spots_dir.mkdir(parents=True, exist_ok=True)
    spot_path(spots_dir, duck_number).write_bytes(image_bytes)


def load_spot(spots_dir: Path, duck_number: int) -> bytes | None:
    path = spot_path(spots_dir, duck_number)
    if not path.is_file():
        return None
    return path.read_bytes()


def count_saved(spots_dir: Path, total_ducks: int) -> int:
    return sum(1 for n in range(1, total_ducks + 1) if spot_exists(spots_dir, n))


def list_missing(spots_dir: Path, total_ducks: int) -> list[int]:
    return [n for n in range(1, total_ducks + 1) if not spot_exists(spots_dir, n)]
