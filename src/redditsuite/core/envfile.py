"""Read and update the ``.env`` file in place.

Lets the Settings page persist credentials by editing ``.env`` without the user
ever opening a text editor. Existing comments and unrelated lines are preserved;
only the given keys are changed or appended.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_PATH = ".env"


def read_env(path: str | Path = DEFAULT_PATH) -> dict[str, str]:
    """Return the key/value pairs currently in ``.env`` (ignoring comments)."""
    data: dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return data
    for line in p.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def update_env(updates: dict[str, str], path: str | Path = DEFAULT_PATH) -> None:
    """Apply ``updates`` to ``.env``, preserving existing lines and comments.

    If the file doesn't exist yet, it is seeded from ``.env.example`` when that
    is available so the helpful comments come along.
    """
    p = Path(path)
    if not p.exists():
        example = Path(".env.example")
        lines = example.read_text().splitlines() if example.exists() else []
    else:
        lines = p.read_text().splitlines()

    applied: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                applied.add(key)
                continue
        out.append(line)

    for key, value in updates.items():
        if key not in applied:
            out.append(f"{key}={value}")

    p.write_text("\n".join(out) + "\n")
