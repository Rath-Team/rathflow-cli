"""输出渲染：默认人类可读，`--json` 原样透传（脚本消费的唯一稳定形态）。

`--json` **不重新编码**：protojson 已把 int64 编成字符串、Timestamp 编成 RFC3339、
bytes 编成 base64；重新编码会失真，故直接 json.dumps 透传。
"""

from __future__ import annotations

import json
import sys

_MAX_CELL = 48


def _get(obj, dotted: str):
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value)
    text = text.replace("\n", " ")
    if len(text) > _MAX_CELL:
        text = text[: _MAX_CELL - 1] + "…"
    return text


def emit_json(payload) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def emit_object(obj: dict, *, json_out: bool) -> None:
    if json_out:
        emit_json(obj)
        return
    if not isinstance(obj, dict):
        print(obj)
        return
    width = max((len(k) for k in obj), default=0)
    for key, value in obj.items():
        if value is None or value == "" or value == [] or value == {}:
            continue
        print(f"{key.ljust(width)}  {_cell(value)}")


def emit_table(rows, columns, *, json_out: bool) -> None:
    """rows = 对象列表；columns = [(表头, 点分路径)]。"""
    if json_out:
        emit_json(rows)
        return
    rows = list(rows or [])
    if not rows:
        print("(空)")
        return
    headers = [h for h, _ in columns]
    body = [[_cell(_get(r, path)) for _, path in columns] for r in rows]
    widths = [
        max(len(headers[i]), max((len(row[i]) for row in body), default=0))
        for i in range(len(headers))
    ]
    print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    for row in body:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))


def emit_items(payload, *, items_key: str, columns, json_out: bool) -> None:
    """分页响应：取 items_key 列表渲染；JSON 模式透传整包（保留 nextPageToken）。"""
    if json_out:
        emit_json(payload)
        return
    emit_table((payload or {}).get(items_key) or [], columns, json_out=False)
    token = (payload or {}).get("nextPageToken")
    if token:
        print(f"\n(还有下一页：--page-token {token})")


def write_bytes(data: bytes, *, to_stderr: bool = False) -> None:
    stream = sys.stderr.buffer if to_stderr else sys.stdout.buffer
    stream.write(data)
    stream.flush()
