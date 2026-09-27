"""sandbox：沙箱生命周期、执行（流式）、文件读取与日志。"""

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
from ..errors import ApiError, UsageError
from ..state import current

app = typer.Typer(no_args_is_help=True, help="沙箱 / 执行 / 文件 / 日志")

SANDBOX_COLUMNS = [
    ("SANDBOX ID", "sandboxId"),
    ("名称", "name"),
    ("状态", "status"),
    ("隔离级别", "effectiveIsolation"),
    ("到期", "expiresAt"),
]


@app.command("list")
def list_(
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
) -> None:
    """列本项目沙箱（含已终止）。"""
    st = current()
    payload = st.client().call("sandbox.List", query=pagination(page_size or 50, page_token))
    output.emit_items(payload, items_key="sandboxes", columns=SANDBOX_COLUMNS, json_out=st.json_out)


@app.command("get")
def get(sandbox_id: str = typer.Argument(...)) -> None:
    """沙箱详情。"""
    st = current()
    payload = st.client().call("sandbox.Get", path_params={"sandbox_id": sandbox_id})
    output.emit_object(payload, json_out=st.json_out)


@app.command("create")
def create(
    name: str = typer.Option(None, "--name", "-n"),
    body: str = BODY_OPT,
    body_file: str = BODY_FILE_OPT,
) -> None:
    """建沙箱（隔离级别等用 --body 传）。"""
    st = current()
    payload_body = body_of(body, body_file) or {}
    if name:
        payload_body.setdefault("name", name)
    payload = st.client().call("sandbox.Create", body=payload_body)
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(payload.get("sandboxId") or "")


@app.command("terminate")
def terminate(
    sandbox_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """终止沙箱。"""
    st = current()
    if not yes:
        typer.confirm(f"确认终止沙箱 {sandbox_id}？", abort=True)
    st.client().call("sandbox.Terminate", path_params={"sandbox_id": sandbox_id})
    typer.echo(f"已终止 {sandbox_id}")


@app.command("renew")
def renew(
    sandbox_id: str = typer.Argument(...),
    body: str = BODY_OPT,
    body_file: str = BODY_FILE_OPT,
) -> None:
    """续期沙箱。"""
    st = current()
    payload = st.client().call(
        "sandbox.Renew", path_params={"sandbox_id": sandbox_id}, body=body_of(body, body_file) or {}
    )
    output.emit_object(payload, json_out=st.json_out)


@app.command("expose-port")
def expose_port(
    sandbox_id: str = typer.Argument(...),
    port: int = typer.Argument(..., help="沙箱内端口"),
    protocol: str = typer.Option(None, "--protocol"),
) -> None:
    """暴露端口，打印可达地址。"""
    st = current()
    body = {"port": port}
    if protocol:
        body["protocol"] = protocol
    payload = st.client().call(
        "sandbox.ExposePort", path_params={"sandbox_id": sandbox_id}, body=body
    )
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(payload.get("url") or f"(backend 未上报地址；assigned_port={payload.get('assignedPort')})")


# ------------------------------------------------------------------ 执行

@app.command("exec")
def exec_(
    sandbox_id: str = typer.Argument(...),
    command: str = typer.Argument(..., help="要执行的命令（经 shell 解释）"),
    workdir: str = typer.Option(None, "--workdir", "-w"),
    env: list[str] = typer.Option(None, "--env", "-e", help="环境变量 k=v，可重复"),
) -> None:
    """在沙箱里执行命令（流式；远端非零退出码原样透传为 CLI 退出码）。"""
    st = current()
    body = {"command": command}
    if workdir:
        body["workdir"] = workdir
    if env:
        body["env"] = dict(item.partition("=")[::2] for item in env)
    if st.json_out:
        _stream_json(st, "sandbox.RunCommand", sandbox_id, body)
        return
    code = _pump(st, "sandbox.RunCommand", sandbox_id, body)
    if code:
        raise SystemExit(code)


@app.command("code")
def code(
    sandbox_id: str = typer.Argument(...),
    language: str = typer.Option(..., "--language", "-l", help="python / bash / ..."),
    file: str = typer.Argument(None, help="源码文件；缺省或 - 读 stdin"),
) -> None:
    """在沙箱里跑一段源码（流式）。"""
    st = current()
    if file and file != "-":
        try:
            with open(file, encoding="utf-8") as fh:
                source = fh.read()
        except OSError as exc:
            raise UsageError(f"读取源码失败：{exc}") from None
    else:
        source = sys.stdin.read()
    body = {"language": language, "code": source}
    if st.json_out:
        _stream_json(st, "sandbox.RunCode", sandbox_id, body)
        return
    exit_code = _pump(st, "sandbox.RunCode", sandbox_id, body)
    if exit_code:
        raise SystemExit(exit_code)


@app.command("logs")
def logs(
    sandbox_id: str = typer.Argument(...),
    tail: int = typer.Option(None, "--tail", help="回看行数（服务端支持时生效）"),
) -> None:
    """沙箱日志（流式；stderr 分流到 stderr）。Ctrl-C 退出。

    注意：当前 backend 未实现沙箱级日志面（返回 CODE_UNIMPLEMENTED），
    要取实时输出请用 `sandbox exec` 的 stdout/stderr 流帧。
    """
    st = current()
    query = {"tail": tail} if tail is not None else None
    for chunk in st.client().stream(
        "sandbox.StreamLogs", path_params={"sandbox_id": sandbox_id}, query=query
    ):
        if st.json_out:
            output.emit_json(chunk)
            continue
        data = _bytes(chunk.get("data"))
        if not data:
            continue
        if chunk.get("stderr"):
            output.write_bytes(data, to_stderr=True)
        else:
            output.write_bytes(data)
        if chunk.get("truncated"):
            typer.echo("\n[截断：输出达服务端上限]", err=True)


# ------------------------------------------------------------------ 文件

@app.command("ls")
def ls(
    sandbox_id: str = typer.Argument(...),
    path: str = typer.Option("/", "--path", "-p", help="相对沙箱根；缺省根目录"),
) -> None:
    """列目录。"""
    st = current()
    # 该 backend 要求 path 必填（传空报 CODE_INVALID_ARGUMENT），故缺省给根
    query = {"path": path}
    payload = st.client().call(
        "sandbox.ListDir", path_params={"sandbox_id": sandbox_id}, query=query
    )
    output.emit_table(
        payload.get("entries") or [],
        [("类型", "type"), ("大小", "sizeBytes"), ("时间", "modifiedAt"), ("名称", "name")],
        json_out=st.json_out,
    )


@app.command("stat")
def stat(
    sandbox_id: str = typer.Argument(...),
    path: str = typer.Option(..., "--path", "-p"),
) -> None:
    """看单个路径的元信息（须为单文件路径，见 StatRequest 注释）。"""
    st = current()
    payload = st.client().call(
        "sandbox.Stat", path_params={"sandbox_id": sandbox_id}, query={"path": path}
    )
    output.emit_object(payload.get("entry") or payload, json_out=st.json_out)


@app.command("cat")
def cat(
    sandbox_id: str = typer.Argument(...),
    path: str = typer.Option(..., "--path", "-p", help="沙箱内相对路径"),
) -> None:
    """读文件到 stdout（流式分片直写，不整包缓冲）。"""
    st = current()
    for chunk in st.client().stream(
        "sandbox.ReadFile", path_params={"sandbox_id": sandbox_id, "path": path}
    ):
        if st.json_out:
            output.emit_json(chunk)
            continue
        data = _bytes(chunk.get("data"))
        if data:
            output.write_bytes(data)


# ------------------------------------------------------------------ 内部

def _pump(st, key: str, sandbox_id: str, body: dict) -> int:
    """流式抽干一个执行流：stdout→stdout，stderr→stderr，返回远端退出码。"""
    exit_code = 0
    for chunk in st.client().stream(key, path_params={"sandbox_id": sandbox_id}, body=body):
        stdout = _bytes(chunk.get("stdout"))
        stderr = _bytes(chunk.get("stderr"))
        if stdout:
            output.write_bytes(stdout)
        if stderr:
            output.write_bytes(stderr, to_stderr=True)
        if chunk.get("errorCode"):
            raise ApiError(0, chunk["errorCode"], chunk.get("errorMessage") or "执行失败")
        if chunk.get("truncated"):
            typer.echo("[截断：输出达服务端上限]", err=True)
        if chunk.get("exitCode") is not None:
            exit_code = int(chunk["exitCode"])
    return exit_code


def _stream_json(st, key: str, sandbox_id: str, body: dict) -> None:
    for chunk in st.client().stream(key, path_params={"sandbox_id": sandbox_id}, body=body):
        output.emit_json(chunk)


def _bytes(value) -> bytes:
    """protojson 把 bytes 编成 base64；解失败就当纯文本用。"""
    if not value:
        return b""
    if isinstance(value, bytes):
        return value
    try:
        return base64.b64decode(value, validate=True)
    except Exception:
        return str(value).encode()
