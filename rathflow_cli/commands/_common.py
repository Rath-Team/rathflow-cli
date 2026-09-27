"""命令间共用的小工具（参数解析与请求体装配）。"""

from __future__ import annotations

import json
import sys

import typer

from ..errors import UsageError

PATH_OPT = typer.Option(None, "--path", help="路径参数 k=v，可重复（如 --path session_id=abc）")
QUERY_OPT = typer.Option(None, "--query", help="查询参数 k=v，可重复")
BODY_OPT = typer.Option(None, "--body", help="请求体 JSON 字面量")
BODY_FILE_OPT = typer.Option(None, "--body-file", help="从文件读请求体 JSON（- 读 stdin）")
PAGE_SIZE_OPT = typer.Option(None, "--page-size", help="分页大小")
PAGE_TOKEN_OPT = typer.Option(None, "--page-token", help="分页游标")


def pairs(items: list[str] | None) -> dict:
    """['k=v', ...] → {k: v}；值里的 = 保留（只切第一个）。"""
    out: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise UsageError(f"参数需形如 k=v，收到 {item!r}")
        key, _, value = item.partition("=")
        out[key.strip()] = value
    return out


def body_of(body: str | None, body_file: str | None) -> dict | None:
    """装配请求体：字面量或文件（`-` = stdin）。两者互斥。"""
    if body and body_file:
        raise UsageError("--body 与 --body-file 不能同时用")
    raw: str | None = None
    if body_file:
        raw = sys.stdin.read() if body_file == "-" else _read(body_file)
    elif body:
        raw = body
    else:
        return None
    raw = raw.strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UsageError(f"请求体不是合法 JSON：{exc}") from None
    if not isinstance(parsed, dict):
        raise UsageError("请求体必须是 JSON 对象")
    return parsed


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise UsageError(f"读取请求体文件失败：{exc}") from None


def pagination(page_size: int | None, page_token: str | None, extra: dict | None = None) -> dict:
    """装配分页查询串（protojson 查询名用 proto 字段名 snake_case）。"""
    query = dict(extra or {})
    if page_size is not None:
        query["page_size"] = page_size
    if page_token:
        query["page_token"] = page_token
    return query


def id_of(payload: dict, *keys: str) -> str:
    """从响应里挑主键用于 -q 输出。"""
    for key in keys:
        value = (payload or {}).get(key)
        if value:
            return str(value)
    return ""
