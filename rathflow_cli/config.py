"""本地配置：~/.config/rathflow/config.json（多 profile）。

选 JSON 而非 TOML：tomllib 只读，写 TOML 需额外依赖（违反 P4）。

优先级（由调用方在 cli.py 统一合并）：flag > 环境变量 > profile > 内建默认。
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

# 面向公开发布的内建默认：托管网关。本地开发用 --base-url 或 RATHFLOW_BASE_URL
# 指回 http://127.0.0.1:8080。
DEFAULT_BASE_URL = "https://rathflow.lynwe.com"

# 环境变量名与 Get Started 页 curl 片段逐字同名，页面片段可直接喂 CLI。
ENV_BASE_URL = "RATHFLOW_BASE_URL"
ENV_PROJECT = "RATHFLOW_PROJECT"
ENV_TOKEN = "RATHFLOW_TOKEN"
ENV_CONFIG_DIR = "RATHFLOW_CONFIG_DIR"


def config_dir() -> Path:
    return Path(os.environ.get(ENV_CONFIG_DIR) or (Path.home() / ".config" / "rathflow"))


def config_path() -> Path:
    return config_dir() / "config.json"


def load() -> dict:
    p = config_path()
    if not p.exists():
        return {"current": "default", "profiles": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"配置文件损坏：{p}（{exc}）")
    data.setdefault("current", "default")
    data.setdefault("profiles", {})
    return data


def save(data: dict) -> Path:
    """落盘并收紧权限到 0600（内含令牌，等同口令）。"""
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)
    try:
        p.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # 非 POSIX 文件系统：尽力而为
    return p


def profile(data: dict, name: str | None = None) -> dict:
    return data["profiles"].setdefault(name or data["current"], {})


def mask(secret: str | None) -> str:
    """令牌/密钥打码显示：保留前 8 位。"""
    if not secret:
        return "(未设置)"
    return secret[:8] + "…" if len(secret) > 8 else "…"
