"""api：端点表逃生舱 —— 表里没有的调用（或想自己拼参数时）走这里。

设计取舍：**不留未覆盖端点**。新 proto 先于 CLI 发布时，用 `rathflow api <Key>`
即可调通；CLI 补上具名命令后再切回来。端点 key 见 `rathflow api --list`。

本模块只暴露两个普通函数，由 cli.py 直接注册成根命令（不是 Typer 子组）：
这样 `rathflow api <Key>` 才是最短形态，不必多打一层 `call`。
"""

from __future__ import annotations

import typer

from .. import endpoints, output
from ..commands._common import BODY_FILE_OPT, BODY_OPT, PATH_OPT, QUERY_OPT, body_of, pairs
from ..errors import UsageError
from ..state import current


def list_endpoints(filter: str | None = None) -> None:
    """列出全部端点 key（含是否流式）。本函数不是命令，由 call() 调用。"""
    st = current()
    rows = [
        {
            "key": key,
            "method": spec[0],
            "path": spec[1],
            "stream": "stream" if endpoints.is_streaming(key) else "",
        }
        for key, spec in sorted(endpoints.ENDPOINTS.items())
        if not filter or filter.lower() in key.lower()
    ]
    output.emit_table(
        rows,
        [("KEY", "key"), ("方法", "method"), ("路径", "path"), ("流", "stream")],
        json_out=st.json_out,
    )


def call(
    key: str = typer.Argument(None, help="端点 key，如 sandbox.RunCommand"),
    list_: bool = typer.Option(False, "--list", "-l", help="列端点而不调用"),
    filter: str = typer.Option(None, "--filter", "-f", help="配合 --list：按子串过滤 key"),
    path: list[str] = PATH_OPT,
    query: list[str] = QUERY_OPT,
    body: str = BODY_OPT,
    body_file: str = BODY_FILE_OPT,
    stream: bool = typer.Option(None, "--stream/--no-stream", help="强制流式；缺省按端点表判定"),
    url: str = typer.Option(None, "--url", help="直接给路径，配合 --method（绕过端点表）"),
    method: str = typer.Option(None, "--method", "-X", help="配合 --url 用"),
) -> None:
    """调一个端点；`--url`/`--method` 可绕过端点表。"""
    if list_:
        list_endpoints(filter)
        return
    if not key and not url:
        raise UsageError("给端点 key，或 --url/--method；列端点用 `rathflow api --list`")
    st = current()
    payload_body = body_of(body, body_file)
    common = {"body": payload_body, "query": pairs(query)}

    if url:
        is_stream = bool(stream)
        target = dict(common, method=method or "GET", path=url)
    else:
        if stream is False and endpoints.is_streaming(key):
            raise UsageError(f"{key} 是流式端点，不能 --no-stream（其响应体是逐行 JSON）")
        is_stream = endpoints.is_streaming(key) if stream is None else stream
        target = dict(common, key=key, path_params=pairs(path))

    if is_stream:
        for frame in st.client().stream(**target):
            output.emit_json(frame)
        return
    output.emit_json(st.client().call(**target))
