"""mcp：把 CLI 的能力以 MCP（stdio）暴露给 Codex / Claude 等客户端。

这个命令**不给人手动跑**（跑了就是一串 JSON 帧）；它是给客户端注册的入口：
`.mcp.json` 里写 ``{"command": "rathflow", "args": ["mcp", "serve"]}``。
"""

from __future__ import annotations

import typer

from ..mcp.server import serve

app = typer.Typer(no_args_is_help=True, help="MCP 服务端（stdio；给客户端注册用）")


@app.command("serve")
def serve_() -> None:
    """以 stdio 跑 MCP 服务端。stdout 是协议通道，终端里手跑看不到人话是正常的。"""
    from ..state import current

    raise typer.Exit(serve(current()))
