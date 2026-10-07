"""Project paths and secrets. Secret values are never printed, logged, or put in reprs."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "lab.duckdb"
CONFIG_DIR = ROOT / "config"

load_dotenv(ROOT / ".env", override=False)


class Secret:
    """Holds a credential. str()/repr() are masked; call .reveal() only to build a request."""

    __slots__ = ("_name", "_value")

    def __init__(self, name: str, value: str) -> None:
        self._name = name
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"Secret({self._name}=***)"

    __str__ = __repr__


def get_secret(name: str, *, required: bool = True) -> Secret | None:
    value = os.environ.get(name, "").strip()
    if not value:
        if required:
            # Message names the variable only, never a value.
            raise RuntimeError(f"{name} is not set. Add it to .env (see .env.example).")
        return None
    return Secret(name, value)


def fred_api_key() -> Secret:
    secret = get_secret("FRED_API_KEY")
    assert secret is not None
    return secret
