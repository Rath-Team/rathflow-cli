"""agent：Agent 定义、版本、运行与 Agent 目录。"""

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

app = typer.Typer(no_args_is_help=True, help="Agent 定义 / 版本 / 运行 / 目录")

DEF_COLUMNS = [
    ("AGENT DEF ID", "agentDefId"),
    ("名称", "name"),
    ("版本", "version"),
    ("状态", "status"),
    ("更新时间", "updatedAt"),
]
RUN_COLUMNS = [
    ("RUN ID", "runId"),
    ("状态", "status"),
    ("提示词", "promptText"),
    ("创建时间", "createdAt"),
]


# ------------------------------------------------------------------ 定义

@app.command("defs")
def defs(
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
) -> None:
    """列 Agent 定义。"""
    st = current()
    payload = st.client().call("agent.ListAgentDefs", query=pagination(page_size or 50, page_token))
    output.emit_items(payload, items_key="agentDefs", columns=DEF_COLUMNS, json_out=st.json_out)


@app.command("def")
def def_get(agent_def_id: str = typer.Argument(...)) -> None:
    """看定义详情。"""
    st = current()
    payload = st.client().call("agent.GetAgentDef", path_params={"agent_def_id": agent_def_id})
    output.emit_object(payload, json_out=st.json_out)


@app.command("def-create")
def def_create(
    name: str = typer.Option(..., "--name", "-n"),
    description: str = typer.Option(None, "--description", "-d"),
    config: str = typer.Option(None, "--config", help="config_json 字面量（自由 JSON 文本）"),
    config_file: str = typer.Option(None, "--config-file", help="从文件读 config_json（- 读 stdin）"),
    memory_binding: str = typer.Option(None, "--memory-binding", help="记忆绑定，如 memories/agents"),
    body: str = BODY_OPT,
    body_file: str = BODY_FILE_OPT,
) -> None:
    """建 Agent 定义。"""
    st = current()
    payload_body = body_of(body, body_file) or {}
    payload_body.setdefault("name", name)
    if description:
        payload_body.setdefault("description", description)
    if memory_binding:
        payload_body.setdefault("memoryBinding", memory_binding)
    text = _text_of(config, config_file)
    if text is not None:
        payload_body.setdefault("configJson", text)
    payload = st.client().call("agent.CreateAgentDef", body=payload_body)
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(payload.get("agentDefId") or "")


@app.command("def-update")
def def_update(
    agent_def_id: str = typer.Argument(...),
    name: str = typer.Option(None, "--name", "-n"),
    description: str = typer.Option(None, "--description", "-d"),
    config: str = typer.Option(None, "--config"),
    config_file: str = typer.Option(None, "--config-file"),
    memory_binding: str = typer.Option(None, "--memory-binding"),
    status: str = typer.Option(None, "--status", help="AgentDefStatus 枚举"),
    body: str = BODY_OPT,
    body_file: str = BODY_FILE_OPT,
) -> None:
    """改定义（PATCH 语义；改完通常产生新版本）。"""
    st = current()
    payload_body = body_of(body, body_file) or {}
    for key, value in (
        ("name", name),
        ("description", description),
        ("memoryBinding", memory_binding),
        ("status", status),
    ):
        if value:
            payload_body.setdefault(key, value)
    text = _text_of(config, config_file)
    if text is not None:
        payload_body.setdefault("configJson", text)
    if not payload_body:
        raise UsageError("至少给一项要改的字段（--name/--description/--config/--memory-binding/--status）")
    payload = st.client().call(
        "agent.UpdateAgentDef", path_params={"agent_def_id": agent_def_id}, body=payload_body
    )
    output.emit_object(payload, json_out=st.json_out)


@app.command("def-delete")
def def_delete(
    agent_def_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """删定义。"""
    st = current()
    if not yes:
        typer.confirm(f"确认删除 Agent 定义 {agent_def_id}？", abort=True)
    st.client().call("agent.DeleteAgentDef", path_params={"agent_def_id": agent_def_id})
    typer.echo(f"已删除 {agent_def_id}")


@app.command("versions")
def versions(
    agent_def_id: str = typer.Argument(...),
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
) -> None:
    """列定义的版本。"""
    st = current()
    payload = st.client().call(
        "agent.ListAgentDefVersions",
        path_params={"agent_def_id": agent_def_id},
        query=pagination(page_size or 50, page_token),
    )
    output.emit_items(
        payload,
        items_key="versions",
        columns=[("版本", "version"), ("创建人", "createdBy"), ("创建时间", "createdAt")],
        json_out=st.json_out,
    )


@app.command("version")
def version(
    agent_def_id: str = typer.Argument(...),
    version: int = typer.Argument(...),
) -> None:
    """看某个版本。"""
    st = current()
    payload = st.client().call(
        "agent.GetAgentDefVersion",
        path_params={"agent_def_id": agent_def_id, "version": version},
    )
    output.emit_object(payload, json_out=st.json_out)


# ------------------------------------------------------------------ 运行

@app.command("prompt")
def prompt(
    session_id: str = typer.Argument(...),
    text: str = typer.Argument(None, help="提示词；缺省或 - 读 stdin"),
    body: str = BODY_OPT,
    body_file: str = BODY_FILE_OPT,
) -> None:
    """给会话发提示词，起一个 run（返回 runId；进度用 `session watch` 跟）。"""
    st = current()
    payload_body = body_of(body, body_file)
    if payload_body is None:
        if text in (None, "-"):
            import sys

            text = sys.stdin.read()
        payload_body = {"text": text}
    payload = st.client().call(
        "agent.Prompt", path_params={"session_id": session_id}, body=payload_body
    )
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(payload.get("runId") or "")


@app.command("runs")
def runs(
    session_id: str = typer.Argument(...),
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
) -> None:
    """列会话下的 run。"""
    st = current()
    payload = st.client().call(
        "agent.ListRuns",
        path_params={"session_id": session_id},
        query=pagination(page_size or 50, page_token),
    )
    output.emit_items(payload, items_key="runs", columns=RUN_COLUMNS, json_out=st.json_out)


@app.command("run")
def run(run_id: str = typer.Argument(...)) -> None:
    """看单个 run。"""
    st = current()
    payload = st.client().call("agent.GetRun", path_params={"run_id": run_id})
    output.emit_object(payload, json_out=st.json_out)


# ------------------------------------------------------------------ 目录

@app.command("directory")
def directory(
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
) -> None:
    """列 Agent 目录（跨 project 可见的 agent 地址）。"""
    st = current()
    payload = st.client().call(
        "agent.ListAgentDirectory", query=pagination(page_size or 50, page_token)
    )
    output.emit_items(
        payload,
        items_key="entries",
        columns=[("AGENT ID", "agentId"), ("地址", "address"), ("状态", "status")],
        json_out=st.json_out,
    )


@app.command("resolve")
def resolve(agent_id: str = typer.Argument(...)) -> None:
    """把 agent id 解析成地址。"""
    st = current()
    payload = st.client().call(
        "agent.ResolveAgentAddress", path_params={"agent_id": agent_id}
    )
    output.emit_object(payload, json_out=st.json_out)


@app.command("messages")
def messages(
    agent_id: str = typer.Argument(...),
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
) -> None:
    """看某个 agent 的消息记录。"""
    st = current()
    payload = st.client().call(
        "agent.ListAgentMessages",
        path_params={"agent_id": agent_id},
        query=pagination(page_size or 50, page_token),
    )
    output.emit_items(
        payload,
        items_key="messages",  # 见 ListAgentMessagesResponse
        columns=[
            ("MESSAGE ID", "messageId"),
            ("方向", "direction"),
            ("对端", "peerAgentId"),
            ("负载", "payloadJson"),
        ],
        json_out=st.json_out,
    )


def _text_of(text: str | None, file: str | None) -> str | None:
    """config_json 是自由 JSON 文本：字面量或文件（- 读 stdin）。"""
    if text and file:
        raise UsageError("--config 与 --config-file 不能同时用")
    if file:
        if file == "-":
            import sys

            return sys.stdin.read()
        try:
            with open(file, encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            raise UsageError(f"读取失败：{exc}") from None
    return text
