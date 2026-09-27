"""session：会话、block、事件流与 block 分享。"""

from __future__ import annotations

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

app = typer.Typer(no_args_is_help=True, help="会话 / block / 事件流")

SESSION_COLUMNS = [
    ("SESSION ID", "sessionId"),
    ("状态", "status"),
    ("标题", "title"),
    ("AGENT", "agentDefId"),
    ("创建时间", "createdAt"),
]
BLOCK_COLUMNS = [
    ("BLOCK ID", "blockId"),
    ("标题", "title"),
    ("事件区间", "fromSeq"),
    ("到", "toSeq"),
    ("创建时间", "createdAt"),
]


# ------------------------------------------------------------------ 会话

@app.command("list")
def list_(
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
    status: str = typer.Option(None, "--status", help="按状态过滤"),
) -> None:
    """列出本项目会话。"""
    st = current()
    payload = st.client().call(
        "session.ListSessions", query=pagination(page_size or 50, page_token, {"status": status})
    )
    output.emit_items(payload, items_key="sessions", columns=SESSION_COLUMNS, json_out=st.json_out)


@app.command("get")
def get(session_id: str = typer.Argument(...)) -> None:
    """会话详情。"""
    st = current()
    payload = st.client().call("session.GetSession", path_params={"session_id": session_id})
    output.emit_object(payload, json_out=st.json_out)


@app.command("create")
def create(
    body: str = BODY_OPT,
    body_file: str = BODY_FILE_OPT,
    title: str = typer.Option(None, "--title", help="标题（等价于 --body 里给 title）"),
) -> None:
    """建会话。"""
    st = current()
    payload_body = body_of(body, body_file)
    if payload_body is None:
        payload_body = {"title": title} if title else {}
    payload = st.client().call("session.CreateSession", body=payload_body)
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(payload.get("sessionId") or "")


@app.command("delete")
def delete(
    session_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """删会话。"""
    st = current()
    if not yes:
        typer.confirm(f"确认删除会话 {session_id}？", abort=True)
    st.client().call("session.DeleteSession", path_params={"session_id": session_id})
    typer.echo(f"已删除 {session_id}")


@app.command("archive")
def archive(session_id: str = typer.Argument(...)) -> None:
    """归档会话。"""
    st = current()
    payload = st.client().call("session.ArchiveSession", path_params={"session_id": session_id})
    output.emit_object(payload, json_out=st.json_out)


@app.command("lineage")
def lineage(session_id: str = typer.Argument(...)) -> None:
    """血统（fork/派生关系）。"""
    st = current()
    payload = st.client().call("session.GetSessionLineage", path_params={"session_id": session_id})
    output.emit_object(payload, json_out=st.json_out)


@app.command("interrupt")
def interrupt(session_id: str = typer.Argument(...)) -> None:
    """打断正在跑的 run（agent.Interrupt）。"""
    st = current()
    payload = st.client().call("agent.Interrupt", path_params={"session_id": session_id}, body={})
    output.emit_object(payload, json_out=st.json_out)


# ------------------------------------------------------------------ block

@app.command("blocks")
def blocks(
    session_id: str = typer.Argument(...),
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
) -> None:
    """列会话下的 block。"""
    st = current()
    payload = st.client().call(
        "session.ListBlocks",
        path_params={"session_id": session_id},
        query=pagination(page_size or 50, page_token),
    )
    output.emit_items(payload, items_key="blocks", columns=BLOCK_COLUMNS, json_out=st.json_out)


@app.command("block")
def block_get(block_id: str = typer.Argument(...)) -> None:
    """看单个 block。"""
    st = current()
    payload = st.client().call("session.GetBlock", path_params={"block_id": block_id})
    output.emit_object(payload, json_out=st.json_out)


@app.command("block-create")
def block_create(
    session_id: str = typer.Argument(...),
    body: str = BODY_OPT,
    body_file: str = BODY_FILE_OPT,
) -> None:
    """给会话加 block（内容用 --body/--body-file 传）。"""
    st = current()
    payload_body = body_of(body, body_file)
    if payload_body is None:
        raise UsageError('需要 --body \'{"type":...,...}\' 或 --body-file <路径|->')
    payload = st.client().call(
        "session.CreateBlock", path_params={"session_id": session_id}, body=payload_body
    )
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(payload.get("blockId") or "")


@app.command("block-delete")
def block_delete(
    block_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """删 block。"""
    st = current()
    if not yes:
        typer.confirm(f"确认删除 block {block_id}？", abort=True)
    st.client().call("session.DeleteBlock", path_params={"block_id": block_id})
    typer.echo(f"已删除 {block_id}")


@app.command("share")
def share(
    block_id: str = typer.Argument(...),
    body: str = BODY_OPT,
    body_file: str = BODY_FILE_OPT,
) -> None:
    """把 block 分享给别人（scope 用 --body 传）。"""
    st = current()
    payload = st.client().call(
        "session.ShareBlock", path_params={"block_id": block_id}, body=body_of(body, body_file) or {}
    )
    output.emit_object(payload, json_out=st.json_out)


@app.command("unshare")
def unshare(share_id: str = typer.Argument(...)) -> None:
    """撤销 block 分享。"""
    st = current()
    st.client().call("session.RevokeBlockShare", path_params={"share_id": share_id})
    typer.echo(f"已撤销 {share_id}")


# ------------------------------------------------------------------ 事件

@app.command("events")
def events(
    session_id: str = typer.Argument(...),
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
) -> None:
    """拉历史事件（一次性）。"""
    st = current()
    payload = st.client().call(
        "session.GetSessionEvents",
        path_params={"session_id": session_id},
        query=pagination(page_size or 100, page_token),
    )
    output.emit_items(
        payload,
        items_key="events",
        columns=[("SEQ", "seq"), ("数据", "payloadJson"), ("时间", "createdAt")],
        json_out=st.json_out,
    )


@app.command("watch")
def watch(
    session_id: str = typer.Argument(...),
    raw: bool = typer.Option(False, "--raw", help="逐帧原样打印 JSON，不渲染"),
    from_seq: int = typer.Option(None, "--from-seq", help="从该 seq 续传（断线重连用）"),
) -> None:
    """跟事件流（:stream，长连，Ctrl-C 退出）。"""
    st = current()
    query = {"from_seq": from_seq} if from_seq is not None else None
    for frame in st.client().stream(
        "session.StreamSessionEvents", path_params={"session_id": session_id}, query=query
    ):
        if st.json_out or raw:
            output.emit_json(frame)
            continue
        seq = frame.get("seq")
        prefix = f"{str(seq).rjust(6)}  " if seq is not None else ""
        typer.echo(prefix + output._cell(frame.get("payloadJson") or frame))
