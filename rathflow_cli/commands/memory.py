"""memory：记忆文件读写、检索、树与 commit 任务。

路径规律（engine-memory/internal/engine/path.go）：`memory_path` 的**首段**必须是
`memories`（项目私有）或 `resources`（共享资源）之一，其余自由。路径是 `{path=**}`
多段通配，逐段 encode 由 endpoints.py 负责。
"""

from __future__ import annotations

import base64
import sys

import typer

from .. import output
from ..commands._common import (
    BODY_FILE_OPT,
    BODY_OPT,
    PAGE_SIZE_OPT,
    PAGE_TOKEN_OPT,
    body_of,
    pagination,
)
from ..errors import UsageError
from ..state import current

app = typer.Typer(no_args_is_help=True, help="记忆库 / 任务")

ROOTS = ("memories", "resources")
PATH_ARG = typer.Argument(..., help=f"记忆路径，首段须是 {'/'.join(ROOTS)}（如 memories/notes/a.md）")
FILE_ARG = typer.Argument(None, help="内容文件；缺省或 - 读 stdin")


@app.command("list")
def list_(
    prefix: str = typer.Option(None, "--prefix", help="路径前缀，如 memories/notes"),
    recursive: bool = typer.Option(False, "--recursive", "-r"),
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
) -> None:
    """列记忆条目（当前缀为空时服务端通常返回空，建议 --prefix memories）。"""
    st = current()
    query = pagination(
        page_size or 100,
        page_token,
        {"prefix": _checked(prefix, allow_empty=True), "recursive": recursive or None},
    )
    payload = st.client().call("memory.List", query=query)
    output.emit_items(
        payload,
        items_key="entries",
        columns=[("路径", "memoryPath"), ("大小", "sizeBytes"), ("更新时间", "updatedAt")],
        json_out=st.json_out,
    )


@app.command("read")
def read(
    memory_path: str = PATH_ARG,
    level: str = typer.Option(None, "--level", help="读层级（ReadLevel 枚举，如 L0/L1）"),
) -> None:
    """读记忆内容（原始字节写 stdout，可直接重定向）。"""
    st = current()
    query = {"level": level} if level else None
    payload = st.client().call(
        "memory.Read", path_params={"memory_path": _checked(memory_path)}, query=query
    )
    if st.json_out:
        output.emit_json(payload)
        return
    content = payload.get("content")
    if content is None:
        output.emit_object(payload, json_out=False)
        return
    output.write_bytes(_bytes(content))


@app.command("write")
def write(
    memory_path: str = PATH_ARG,
    file: str = FILE_ARG,
    content_type: str = typer.Option(None, "--content-type", help="如 text/markdown"),
    ttl: int = typer.Option(None, "--ttl", help="存活秒数"),
) -> None:
    """写记忆内容（`-` 或省略 = 读 stdin；content 是 bytes，编码由 CLI 负责）。"""
    st = current()
    data = _read(file)
    body = {"content": base64.b64encode(data).decode()}
    if content_type:
        body["contentType"] = content_type
    if ttl is not None:
        body["ttlSeconds"] = ttl
    payload = st.client().call(
        "memory.Write", path_params={"memory_path": _checked(memory_path)}, body=body
    )
    if st.json_out:
        output.emit_json(payload)
        return
    written = payload.get("bytesWritten", len(data))
    typer.echo(f"已写入 {memory_path}（{written} 字节）")


@app.command("search")
def search(
    query: str = typer.Argument(..., help="语义检索词"),
    top_k: int = typer.Option(None, "--top-k", help="返回条数（服务端要求 > 0）"),
    min_score: float = typer.Option(None, "--min-score"),
    scope: str = typer.Option(None, "--scope", help="限定路径前缀"),
    mode: str = typer.Option(None, "--mode", help="SearchMode 枚举"),
    paths: bool = typer.Option(False, "--paths", help="只列命中路径（喂给 xargs）"),
    body: str = BODY_OPT,
    body_file: str = BODY_FILE_OPT,
) -> None:
    """语义检索（流式：命中逐条到，不必等全量）。"""
    st = current()
    payload_body = body_of(body, body_file) or {}
    payload_body.setdefault("query", query)
    if top_k is not None:
        payload_body.setdefault("topK", top_k)
    if min_score is not None:
        payload_body.setdefault("minScore", min_score)
    if scope:
        payload_body.setdefault("scope", scope)
    if mode:
        payload_body.setdefault("mode", mode)
    rows = []
    empty = True
    for hit in st.client().stream("memory.Search", body=payload_body):
        empty = False
        if st.json_out:
            output.emit_json(hit)
            continue
        if paths:
            typer.echo(hit.get("memoryPath") or "")
            continue
        rows.append(hit)
    if not empty and rows and not st.json_out:
        output.emit_table(
            rows,
            [("路径", "memoryPath"), ("得分", "score"), ("片段", "snippet")],
            json_out=False,
        )
    elif empty and not st.json_out and not paths:
        typer.echo("(无命中)")


@app.command("tree")
def tree(
    root: str = typer.Option(None, "--root", help=f"子树根，如 {' 或 '.join(ROOTS)}"),
    depth: int = typer.Option(None, "--depth", help="深度上限"),
) -> None:
    """目录树。"""
    st = current()
    body = {k: v for k, v in {"root": root, "depthLimit": depth}.items() if v is not None}
    payload = st.client().call("memory.Tree", body=body)
    if st.json_out:
        output.emit_json(payload)
        return
    _print_tree(payload.get("nodes") or [])


@app.command("commit")
def commit(
    session_id: str = typer.Option(..., "--session", "-s", help="源会话 id"),
    note: str = typer.Option(None, "--note", help="备注（写进提交说明）"),
) -> None:
    """把会话提交成记忆（异步，返回 taskId）。"""
    st = current()
    body = {"sessionId": session_id}
    if note:
        body["note"] = note
    payload = st.client().call("memory.CommitSession", body=body)
    if st.json_out:
        output.emit_json(payload)
        return
    task_id = payload.get("taskId")
    typer.echo(f"任务 {task_id}；进度：rathflow memory watch-task {task_id}")


@app.command("tasks")
def tasks(
    session_id: str = typer.Option(None, "--session", "-s", help="只看某会话的任务"),
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
) -> None:
    """列 commit/索引任务。"""
    st = current()
    query = pagination(page_size or 50, page_token, {"session_id": session_id})
    payload = st.client().call("memory.ListTasks", query=query)
    output.emit_items(
        payload,
        items_key="tasks",
        columns=[("TASK ID", "taskId"), ("状态", "status"), ("创建", "createdAt"), ("完成", "finishedAt")],
        json_out=st.json_out,
    )


@app.command("task")
def task(task_id: str = typer.Argument(...)) -> None:
    """看单个任务。"""
    st = current()
    payload = st.client().call("memory.GetTask", path_params={"task_id": task_id})
    output.emit_object(payload, json_out=st.json_out)


@app.command("watch-task")
def watch_task(
    task_id: str = typer.Argument(...),
    wait: bool = typer.Option(False, "--wait", help="阻塞到终态；失败时非零退出"),
) -> None:
    """跟任务进度流（Ctrl-C 退出）。"""
    st = current()
    final: dict | None = None
    for frame in st.client().stream("memory.WatchTask", path_params={"task_id": task_id}):
        final = frame
        status = frame.get("status") or "?"
        if st.json_out:
            output.emit_json(frame)
        else:
            typer.echo(status)
        if wait and status.endswith(("SUCCEEDED", "FAILED", "CANCELED")):
            break
    if wait and final and (final.get("status") or "").endswith(("FAILED", "CANCELED")):
        raise UsageError(final.get("error") or "任务失败")


# ------------------------------------------------------------------ 内部

def _checked(memory_path: str | None, allow_empty: bool = False) -> str | None:
    """首段校验：服务端只认 memories/resources，早点报错比往返一趟强。"""
    if not memory_path:
        if allow_empty:
            return None
        raise UsageError(f"需要记忆路径（首段须是 {'/'.join(ROOTS)}）")
    head = memory_path.strip("/").split("/", 1)[0]
    if head not in ROOTS:
        raise UsageError(
            f"路径首段 {head!r} 不在域内（只允许 {'、'.join(ROOTS)}）"
            f"—— 试 {ROOTS[0]}/{memory_path.lstrip('/')}"
        )
    return memory_path


def _read(file: str | None) -> bytes:
    if not file or file == "-":
        return sys.stdin.buffer.read()
    try:
        with open(file, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise UsageError(f"读取失败：{exc}") from None


def _bytes(value) -> bytes:
    """protojson 把 bytes 编成 base64；解失败就当纯文本用。"""
    if isinstance(value, bytes):
        return value
    if not value:
        return b""
    try:
        return base64.b64decode(value, validate=True)
    except Exception:
        return str(value).encode()


def _print_tree(nodes, indent: int = 0) -> None:
    for node in nodes or []:
        name = node.get("memoryPath") or "?"
        size = node.get("sizeBytes")
        mark = "/ " if node.get("isDir") else "  "
        extra = f"  ({size}B)" if size else ""
        typer.echo("  " * indent + mark + str(name) + extra)
        children = node.get("children")
        if children:
            _print_tree(children, indent + 1)
