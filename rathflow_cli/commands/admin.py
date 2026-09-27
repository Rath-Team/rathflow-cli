"""admin：平台管理（用户、上下文令牌签名密钥）。"""

from __future__ import annotations

import typer

from .. import output
from ..commands._common import PAGE_SIZE_OPT, PAGE_TOKEN_OPT, pagination
from ..state import current

app = typer.Typer(no_args_is_help=True, help="平台管理（需平台管理员）")


@app.command("users")
def users(
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
) -> None:
    """列平台用户。"""
    st = current()
    payload = st.client().call("admin.ListUsers", query=pagination(page_size or 50, page_token))
    output.emit_items(
        payload,
        items_key="users",
        columns=[
            ("USER ID", "userId"),
            ("邮箱", "email"),
            ("名称", "displayName"),
            ("状态", "status"),
            ("管理员", "isPlatformAdmin"),
            ("注册时间", "createdAt"),
        ],
        json_out=st.json_out,
    )


@app.command("promote")
def promote(
    user_id: str = typer.Argument(...),
    admin: bool = typer.Option(True, "--admin/--demote", help="授予或收回平台管理员"),
) -> None:
    """授予/收回平台管理员。"""
    st = current()
    body = {"isPlatformAdmin": admin}
    payload = st.client().call(
        "admin.PromoteUser", path_params={"user_id": user_id}, body=body
    )
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(f"{user_id} → {'平台管理员' if admin else '普通用户'}")


@app.command("set-status")
def set_status(
    user_id: str = typer.Argument(...),
    status: str = typer.Option(..., "--status", help="active | disabled"),
) -> None:
    """启用/停用账号。"""
    st = current()
    body = {"status": f"USER_STATUS_{status.upper()}"}
    payload = st.client().call(
        "admin.SetUserStatus", path_params={"user_id": user_id}, body=body
    )
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(f"{user_id} → {status}")


@app.command("rotate-context-key")
def rotate_context_key(
    reason: str = typer.Option(None, "--reason", help="轮换原因（记入审计）"),
) -> None:
    """轮换上下文令牌签名密钥（reason 走 query，该接口无 body）。"""
    st = current()
    payload = st.client().call(
        "admin.RotateContextTokenKey", query={"reason": reason} if reason else None
    )
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(f"新密钥 {payload.get('keyId')} 生效于 {payload.get('effectiveAt')}")
