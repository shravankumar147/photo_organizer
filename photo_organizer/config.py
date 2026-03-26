from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from omegaconf import DictConfig, OmegaConf

DEFAULT_CONFIG = Path("config.default.yaml")


def load_dotenv_into_environ(path: Path | None = None) -> None:
    env_path = path or Path(".env")
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), raw.strip().strip("'\""))


def resolve_config_path(config_path: str | None = None) -> Path:
    if config_path:
        return Path(config_path)
    return DEFAULT_CONFIG


def resolve_base_config_path(selected: Path) -> Path:
    sibling_default = selected.parent / DEFAULT_CONFIG.name
    if sibling_default.exists():
        return sibling_default
    return DEFAULT_CONFIG


def load_settings(config_path: str | None = None) -> DictConfig:
    load_dotenv_into_environ()

    selected = resolve_config_path(config_path)
    base_path = resolve_base_config_path(selected)
    base = OmegaConf.load(base_path) if base_path.exists() else OmegaConf.create()
    if selected == base_path or not selected.exists():
        return base
    override = OmegaConf.load(selected)
    return OmegaConf.merge(base, override)


def to_path(value: Any) -> Path:
    return Path(str(value))
