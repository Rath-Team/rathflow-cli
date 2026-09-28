"""MCP 服务端：stdio 上的 JSON-RPC 读写循环与方法分发。

调用方：``rathflow mcp serve``（由客户端在 `.mcp.json` / `codex mcp add` 里注册）。

纪律：**stdout 只跑协议**，任何诊断都走 stderr —— 混一行日志进去，客户端就解析失败。
"""

from __future__ import annotations

import sys
from typing import IO

from .. import __version__
from ..state import State
from . import tools
from .protocol import (
    INTERNAL_ERROR,
    INVALID_REQUEST,
    JSONRPC_VERSION,
    METHOD_NOT_FOUND,
    RpcError,
    negotiate_version,
    read_message,
    write_message,
)

SERVER_NAME = "rathflow"

# 会话开始时由客户端带给模型；这是"该怎么做"最省事的一处落点，
# 所以把「未登录就让用户去配置，不要找源码/本地部署」写死在这里。
INSTRUCTIONS = (
    "RathFlow 的能力（项目、会话、记忆、沙箱、用量、工作流）通过**已发布的** `rathflow` CLI "
    "访问，凭据存在 ~/.config/rathflow/config.json。\n"
    "1. 先调 rathflow_whoami 判断是否已登录。未登录时让用户在**他自己的终端**运行 "
    "`rathflow auth login -e <登录邮箱>`，然后重试。\n"
    "2. 不要去找 RathFlow 源码、不要本地构建或部署、不要自己启动 Gateway。CLI 是发布在 "
    "PyPI / npm 上的包；确需安装时用 `uv tool install rathflow-cli` 或 "
    "`npm install -g rathflow-cli`。\n"
    "3. 默认作用域是 CLI 里用 `rathflow project use <project_id>` 选定的项目；"
    "要操作别的项目就显式传 project_id。\n"
    "4. 写操作默认关闭。具名工具没覆盖的端点，用 rathflow_endpoints 查 key，"
    "再走 rathflow_api_call。"
)


def log(*parts: object) -> None:
    """诊断一律走 stderr（stdout 是协议通道）。"""
    print("[rathflow-mcp]", *parts, file=sys.stderr, flush=True)


def _utf8(stream: IO[str]) -> IO[str]:
    """强制 UTF-8：Windows 默认代码页会把中文 JSON 编成 GBK，客户端解不开。"""
    try:
        stream.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[attr-defined]
    except (AttributeError, ValueError, OSError):
        pass
    return stream


def serve(state: State, *, stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> int:
    """跑读写循环；stdin EOF（客户端退出）时返回 0。"""
    ctx = tools.ToolContext(state=state, write_enabled=tools.write_enabled())
    if not ctx.write_enabled:
        log(f"写操作未启用（设 {tools.WRITE_ENV}=1 打开）")
    return _loop(ctx, _utf8(stdin or sys.stdin), _utf8(stdout or sys.stdout))


def _loop(ctx: tools.ToolContext, stdin: IO[str], stdout: IO[str]) -> int:
    while True:
        try:
            message = read_message(stdin)
        except RpcError as exc:
            # 连 id 都取不到（帧本身坏了）：规范要求也回一个 id: null 的错误。
            write_message(stdout, _error_response(None, exc))
            continue
        if message is None:
            log("stdin 关闭，结束")
            return 0
        try:
            response = _dispatch(ctx, message)
        except Exception as exc:  # 兜底：循环不能因为一条消息就安静退出
            log(f"分发异常：{exc!r}")
            response = _error_response(message.get("id"), RpcError(INTERNAL_ERROR, f"内部错误：{exc}"))
        if response is not None:
            write_message(stdout, response)


def _dispatch(ctx: tools.ToolContext, message: dict) -> dict | None:
    """单条消息 → 响应（通知返回 None：JSON-RPC 通知不要求响应）。"""
    msg_id = message.get("id")
    is_notification = "id" not in message
    method = message.get("method")
    params = message.get("params") or {}
    try:
        if message.get("jsonrpc") != JSONRPC_VERSION:
            raise RpcError(INVALID_REQUEST, 'jsonrpc 必须是 "2.0"')
        if not isinstance(method, str):
            raise RpcError(INVALID_REQUEST, "缺少 method")
        if not isinstance(params, dict):
            raise RpcError(INVALID_REQUEST, "params 必须是 JSON 对象")
        result = _handle(ctx, method, params)
    except RpcError as exc:
        return None if is_notification else _error_response(msg_id, exc)
    if is_notification:
        return None
    return {"jsonrpc": JSONRPC_VERSION, "id": msg_id, "result": result}


def _error_response(msg_id: object, exc: RpcError) -> dict:
    return {"jsonrpc": JSONRPC_VERSION, "id": msg_id, "error": exc.to_error()}


def _handle(ctx: tools.ToolContext, method: str, params: dict) -> dict:
    if method == "initialize":
        return _initialize(params)
    if method.startswith("notifications/"):
        return {}  # 通知：不回内容，也不报"方法未实现"
    if method == "ping":
        return {}
    if method == "tools/list":
        return _tools_list(ctx)
    if method == "tools/call":
        return _tools_call(ctx, params)
    if method in ("resources/list", "prompts/list"):
        # 没实现的面：回空清单而不是报错（我们也没在 capabilities 里宣告它们）。
        return {"resources": []} if method.startswith("resources") else {"prompts": []}
    raise RpcError(METHOD_NOT_FOUND, f"未实现的方法：{method}")


def _initialize(params: dict) -> dict:
    return {
        "protocolVersion": negotiate_version(params.get("protocolVersion")),
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "title": "RathFlow", "version": __version__},
        "instructions": INSTRUCTIONS,
    }


def _tools_list(ctx: tools.ToolContext) -> dict:
    return {
        "tools": [
            {
                "name": tool.name,
                "title": tool.title,
                "description": tool.description,
                "inputSchema": tool.input_schema,
                "annotations": tool.annotations(),
            }
            for tool in tools.list_tools(ctx)
        ]
    }


def _tools_call(ctx: tools.ToolContext, params: dict) -> dict:
    result = tools.call_tool(ctx, params.get("name"), params.get("arguments"))
    if result.is_error:
        log(f"工具 {params.get('name')} 失败：{result.text.splitlines()[0]}")
    payload: dict = {
        "content": [{"type": "text", "text": result.text}],
        "isError": result.is_error,
    }
    if result.data is not None:
        payload["structuredContent"] = (
            result.data if isinstance(result.data, dict) else {"result": result.data}
        )
    return payload
