"""MCP 协议层：JSON-RPC 2.0 + stdio 分帧 + 协议版本协商。

分帧形态（MCP 规范 stdio 传输）：**一条消息一行 JSON**，消息内不得出现换行。
stdout 只跑协议，诊断一律走 stderr —— 否则会把日志混进帧里让客户端解析失败。
"""

from __future__ import annotations

import json
from typing import IO, Any

# 本端支持的协议修订（新 → 旧）。客户端在 initialize 里报自己的版本，服务端
# 按这张表协商：认得就沿用客户端的，不认得就回本端最新（规范把最终决定权交给客户端）。
# 表来源：modelcontextprotocol/schema/ 下的修订目录。
PROTOCOL_VERSIONS: tuple[str, ...] = (
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)
LATEST_PROTOCOL_VERSION = PROTOCOL_VERSIONS[0]

JSONRPC_VERSION = "2.0"

# JSON-RPC 2.0 标准错误码（规范保留段）
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class RpcError(Exception):
    """需要以 JSON-RPC ``error`` 对象回给客户端的错误（协议层错误）。"""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_error(self) -> dict:
        error: dict = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return error


def negotiate_version(client_version: Any) -> str:
    """协商协议版本：认识就沿用客户端的，否则回本端最新。"""
    if isinstance(client_version, str) and client_version in PROTOCOL_VERSIONS:
        return client_version
    return LATEST_PROTOCOL_VERSION


def read_message(stream: IO[str]) -> dict | None:
    """读一条消息；EOF 返回 None。

    空行跳过（客户端偶发脏帧时不必整个会话崩掉）；非法 JSON 抛 ``RpcError``，
    由调用方用 ``id: null`` 回一个 parse error —— 规范要求这时也要有响应。
    """
    while True:
        line = stream.readline()
        if line == "":
            return None
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RpcError(PARSE_ERROR, f"消息不是合法 JSON：{exc}") from None
        if not isinstance(message, dict):
            raise RpcError(INVALID_REQUEST, "消息必须是 JSON 对象")
        return message


def write_message(stream: IO[str], message: dict) -> None:
    """写一条消息并立刻 flush：客户端在等这个响应，攒缓冲会死锁。"""
    stream.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")))
    stream.write("\n")
    stream.flush()
