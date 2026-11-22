"""读设置：包里自带的 config.default.toml 打底，用户的 laundry-line.toml 盖在上面（只盖写了的项）。"""

from __future__ import annotations

import copy
import os
import tomllib
from importlib import resources

DEFAULT_NAME = "config.default.toml"
USER_NAME = "laundry-line.toml"


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)          # 列表整个换掉（比如 bed_sets 写了就以你的为准）
    return out


def default_text() -> str:
    return resources.files("laundry_line").joinpath(DEFAULT_NAME).read_text(encoding="utf-8")


def load(path: str | None = None) -> dict:
    cfg = tomllib.loads(default_text())
    if path is None and os.path.exists(USER_NAME):
        path = USER_NAME
    if path:
        with open(path, "rb") as f:
            cfg = _merge(cfg, tomllib.load(f))
    return cfg


def override(cfg: dict, patch: dict) -> dict:
    """测试 / 演示用：在设置上再盖一层。"""
    return _merge(cfg, patch)
