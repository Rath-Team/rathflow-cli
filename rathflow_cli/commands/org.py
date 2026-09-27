"""org：组织（团队空间）成员身份与邀请码。

注册时创建的 org 就是 web 的「个人空间」（`is_primary`），其余为团队空间。
邀请码一次性：接受即作废，明文只在签发那一次出现。
"""

from __future__ import annotations

import typer

from .. import output
from ..state import current

app = typer.Typer(no_args_is_help=True, help="组织成员身份 / 邀请码")

_COLUMNS = [
    ("ORG ID", "orgId"),
    ("名称", "name"),
    ("slug", "slug"),
    ("角色", "role"),
    ("个人空间", "isPrimary"),
]


@app.command("list")
def list_() -> None:
    """我加入的 org。"""
    st = current()
    payload = st.client().call("tenant.ListMyOrgs")
    output.emit_items(payload, items_key="orgs", columns=_COLUMNS, json_out=st.json_out)


@app.command("invite")
def invite(
    org_id: str = typer.Argument(...),
    ttl: int = typer.Option(None, "--ttl", help="有效期秒数；<=0 用服务端默认（7 天）"),
    role: str = typer.Option(None, "--role", help="加入后的角色：MEMBER（默认）或 ADMIN"),
) -> None:
    """签发成员邀请码（**明文只打印这一次**；OWNER 不发）。"""
    st = current()
    body: dict = {}
    if ttl is not None:
        body["ttlSeconds"] = ttl
    if role:
        body["role"] = role
    payload = st.client().call(
        "tenant.CreateOrgInvitation", path_params={"org_id": org_id}, body=body
    )
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(payload.get("code") or "", err=True)
    expires = payload.get("expiresAt")
    typer.echo(
        f"org={payload.get('orgId') or org_id}"
        + (f"  到期 {expires}" if expires else "")
        + "（明文只此一次）",
        err=True,
    )


@app.command("accept")
def accept(code: str = typer.Argument(..., help="邀请码（一次性，接受即作废）")) -> None:
    """接受邀请加入 org（org 由码反查，不用手填）。"""
    st = current()
    payload = st.client().call("tenant.AcceptOrgInvitation", body={"code": code})
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(f"已加入 {payload.get('orgId') or '?'}  {payload.get('name') or ''}")
