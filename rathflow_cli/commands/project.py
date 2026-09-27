"""project：项目（租户单元）的增删改查与作用域切换。"""

from __future__ import annotations

import typer

from .. import config, output
from ..commands._common import PAGE_SIZE_OPT, PAGE_TOKEN_OPT, BODY_FILE_OPT, BODY_OPT, body_of, pagination
from ..errors import UsageError
from ..state import current

app = typer.Typer(no_args_is_help=True, help="项目管理与作用域切换")

_COLUMNS = [("PROJECT ID", "projectId"), ("名称", "name"), ("创建时间", "createdAt")]


@app.command("list")
def list_(
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
) -> None:
    """列出当前账号可访问的项目。"""
    st = current()
    payload = st.client().call(
        "tenant.ListProjects", query=pagination(page_size or 50, page_token)
    )
    output.emit_items(payload, items_key="projects", columns=_COLUMNS, json_out=st.json_out)


@app.command("get")
def get(project_id: str = typer.Argument(None, help="缺省用当前作用域项目")) -> None:
    """查看项目详情。"""
    st = current()
    pid = project_id or _require_project(st.project)
    payload = st.client().call("tenant.GetProject", path_params={"project_id": pid})
    output.emit_object(payload, json_out=st.json_out)


@app.command("create")
def create(
    name: str = typer.Option(..., "--name", "-n", help="项目名"),
) -> None:
    """建项目（创建者自动成为 owner）。"""
    st = current()
    payload = st.client().call("tenant.CreateProject", body={"name": name})
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(f"已创建 {payload.get('projectId')}  {payload.get('name') or name}")
    typer.echo(f"切过去：rathflow project use {payload.get('projectId')}")


@app.command("update")
def update(
    project_id: str = typer.Argument(None),
    name: str = typer.Option(None, "--name", "-n"),
    body: str = BODY_OPT,
    body_file: str = BODY_FILE_OPT,
) -> None:
    """改项目名（或用 --body 传整包）。"""
    st = current()
    pid = project_id or _require_project(st.project)
    payload_body = body_of(body, body_file)
    if payload_body is None:
        if not name:
            raise UsageError("至少给 --name，或用 --body 传整包")
        payload_body = {"name": name}
    payload = st.client().call(
        "tenant.UpdateProject", body=payload_body, path_params={"project_id": pid}
    )
    output.emit_object(payload, json_out=st.json_out)


@app.command("delete")
def delete(
    project_id: str = typer.Argument(None),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认"),
) -> None:
    """删项目（不可逆）。"""
    st = current()
    pid = project_id or _require_project(st.project)
    if not yes:
        typer.confirm(f"确认删除项目 {pid}？此操作不可逆", abort=True)
    st.client().call("tenant.DeleteProject", path_params={"project_id": pid})
    typer.echo(f"已删除 {pid}")


@app.command("use")
def use(project_id: str = typer.Argument(..., help="写入配置档的默认作用域")) -> None:
    """把项目设为默认作用域（此后所有命令都带它）。"""
    st = current()
    prof = st.profile
    prof["project"] = project_id
    st.data["profiles"][st.profile_name] = prof
    config.save(st.data)
    typer.echo(f"当前项目 → {project_id}")


@app.command("config-get")
def config_get(project_id: str = typer.Argument(None)) -> None:
    """读项目配置（模型、限额等）。"""
    st = current()
    pid = project_id or _require_project(st.project)
    payload = st.client().call("tenant.GetProjectConfig", path_params={"project_id": pid})
    output.emit_object(payload, json_out=st.json_out)


@app.command("config-set")
def config_set(
    project_id: str = typer.Argument(None),
    body: str = BODY_OPT,
    body_file: str = BODY_FILE_OPT,
) -> None:
    """改项目配置（PATCH 语义，只传要改的字段）。"""
    st = current()
    pid = project_id or _require_project(st.project)
    payload_body = body_of(body, body_file)
    if not payload_body:
        raise UsageError('需要 --body \'{"...":...}\'（只传要改的字段）')
    payload = st.client().call(
        "tenant.UpdateProjectConfig", body=payload_body, path_params={"project_id": pid}
    )
    output.emit_object(payload, json_out=st.json_out)


# ------------------------------------------------------------------ 分享链接
# 链接 = 能力凭证：明文 `link` 只在**创建/轮换那一次**的响应里出现，服务端只
# 存摘要（同 API key 的「只显示一次」纪律）。撤销/过期后 `project shared` 里
# 也不再出现。


@app.command("share-set")
def share_set(
    project_id: str = typer.Argument(None),
    permission: str = typer.Option(None, "--permission", help="SharePermission 枚举，如 VIEW/EDIT"),
    password: str = typer.Option(None, "--password", help="设密码；给空串=清除（不给=保留原值）"),
    ttl: int = typer.Option(None, "--ttl", help="有效期秒数；<=0 永不过期（仅创建时生效）"),
    rotate: bool = typer.Option(False, "--rotate", help="重发令牌，旧链接立即失效"),
) -> None:
    """建/改本项目的分享链接。

    只传要改的字段（PATCH 语义）。要换有效期得用 --rotate 重发。
    """
    st = current()
    pid = project_id or _require_project(st.project)
    body: dict = {}
    if permission:
        body["permission"] = permission
    # password 是三态（保留/清除/覆盖），故判 None 而非真假
    if password is not None:
        body["password"] = password
    if ttl is not None:
        body["ttlSeconds"] = ttl
    if rotate:
        body["rotate"] = True
    if not body:
        raise UsageError("至少给一项要改的字段（--permission/--password/--ttl/--rotate）")
    payload = st.client().call(
        "tenant.UpdateProjectShare", path_params={"project_id": pid}, body=body
    )
    if st.json_out:
        output.emit_json(payload)
        return
    link = payload.get("link")
    if link:
        typer.echo(link, err=True)
        typer.echo("（明文只此一次，请立即存好）", err=True)
    output.emit_object({k: v for k, v in payload.items() if k != "link"}, json_out=False)


@app.command("share-revoke")
def share_revoke(
    project_id: str = typer.Argument(None),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """撤销分享（已在用的人立即失去入口）。"""
    st = current()
    pid = project_id or _require_project(st.project)
    if not yes:
        typer.confirm(f"确认撤销项目 {pid} 的分享链接？", abort=True)
    st.client().call("tenant.RevokeProjectShare", path_params={"project_id": pid})
    typer.echo(f"已撤销 {pid} 的分享")


@app.command("shared")
def shared(
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
) -> None:
    """我认领过的共享 project（分享被撤销/过期后不再出现）。"""
    st = current()
    payload = st.client().call(
        "tenant.ListSharedProjects", query=pagination(page_size or 50, page_token)
    )
    output.emit_items(payload, items_key="projects", columns=_COLUMNS, json_out=st.json_out)


@app.command("claim")
def claim(
    token: str = typer.Argument(..., help="分享链接里的不透明令牌（整条链接也行）"),
    password: str = typer.Option(None, "--password", help="链接设了密码时必填"),
) -> None:
    """认领一个共享 project（认领后进入 `project list`）。"""
    st = current()
    body: dict = {"token": token.rstrip("/").rsplit("/", 1)[-1]}
    if password is not None:
        body["password"] = password
    payload = st.client().call("tenant.JoinSharedProject", body=body)
    if st.json_out:
        output.emit_json(payload)
        return
    project = payload.get("project") or {}
    typer.echo(f"已认领 {project.get('projectId') or '?'}  {project.get('name') or ''}")
    if project.get("projectId"):
        typer.echo(f"切过去：rathflow project use {project['projectId']}")


def _require_project(pid: str | None) -> str:
    if not pid:
        raise UsageError(
            "无项目作用域：`rathflow project use <id>`，或加 --project <id>，或设 RATHFLOW_PROJECT"
        )
    return pid
