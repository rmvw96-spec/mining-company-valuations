"""Paths and settings shared by every command."""
import os
import tomllib
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"
DERIVED = DATA / "derived"      # company-level results (committed to git)
RESEARCH = DATA / "research"    # hand-researched inputs (committed to git)
CACHE = ROOT / "cache"          # raw downloads from Yahoo (not committed)
OUT = ROOT / "out"              # reports, payloads and portfolio results (not committed)
PRIVATE = ROOT / "private"      # your own settings and portfolio (not committed)


@lru_cache(maxsize=None)
def settings() -> dict:
    with open(CONFIG / "settings.toml", "rb") as f:
        return tomllib.load(f)


@lru_cache(maxsize=None)
def local() -> dict:
    """Personal settings from private/local.toml, overridden by environment variables."""
    p = PRIVATE / "local.toml"
    d = {}
    if p.exists():
        with open(p, "rb") as f:
            d = tomllib.load(f)
    env = {"sheet_id": "MINERVAL_SHEET_ID", "credentials": "GOOGLE_APPLICATION_CREDENTIALS"}
    for key, var in env.items():
        if os.environ.get(var):
            d[key] = os.environ[var]
    return d


def table(name: str) -> pd.DataFrame:
    """A CSV from config/ (or a path relative to the repo)."""
    p = CONFIG / name if (CONFIG / name).exists() else ROOT / name
    return pd.read_csv(p, keep_default_na=False, na_values=[""])


def fund_metal() -> dict:
    return {f: v["metal"] for f, v in settings()["funds"].items()}


def ensure(*dirs: Path):
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
