"""auth 与 whoami。"""

from __future__ import annotations

import base64
import mimetypes
import sys

import typer

from .. import config, output
from ..errors import UsageError
from ..state import current

app = typer.Typer(no_args_is_help=True, help="登录 / 登出 / 注册 / 身份")


@app.command("login")
def login(
    email: str = typer.Option(None, "--email", "-e", help="邮箱（缺省交互输入）"),
    password: str = typer.Option(None, "--password", help="密码（缺省交互输入，不回显）"),
) -> None:
    """用邮箱密码换取 JWT（响应体令牌交给 CLI，见 gateway cookiepost.go）。"""
    st = current()
    email = email or typer.prompt("邮箱")
    password = password or typer.prompt("密码", hide_input=True)
    client = st.client()
    payload = client.login(email, password)
    st.remember_identity(payload)
    st.profile["user"] = {**st.profile.get("user", {}), "email": email}
    config.save(st.data)
    role = "平台管理员" if payload.get("isPlatformAdmin") else "普通用户"
    typer.echo(f"已登录 {email}（{role}）")
    if payload.get("defaultProjectId"):
        typer.echo(f"默认项目：{payload['defaultProjectId']}")


@app.command("logout")
def logout() -> None:
    """清本地令牌并通知服务端（幂等）。"""
    st = current()
    client = st.client()
    client.logout()
    st.profile.pop("user", None)
    config.save(st.data)
    typer.echo("已登出")


@app.command("register")
def register(
    email: str = typer.Option(..., "--email", "-e"),
    password: str = typer.Option(None, "--password", help="缺省交互输入"),
    display_name: str = typer.Option(None, "--display-name"),
) -> None:
    """注册新账号（成功后自动登录）。"""
    st = current()
    password = password or typer.prompt("密码", hide_input=True)
    body = {"email": email, "password": password}
    if display_name:
        body["display_name"] = display_name
    payload = st.client().call("auth.Register", body=body, auth=False)
    if st.json_out:
        output.emit_json(payload)
    else:
        typer.echo(f"注册成功：user={payload.get('userId')} org={payload.get('orgId')}")
        typer.echo(f"默认项目：{payload.get('projectId')}")
    # 注册响应里没有令牌，接着登录一次；两边的身份信息一起落盘
    st.remember_identity(st.client().login(email, password))
    prof = st.profile
    prof["user"] = {**prof.get("user", {}), "email": email}
    st.data["profiles"][st.profile_name] = prof
    config.save(st.data)
    typer.echo("已自动登录。")


# ------------------------------------------------------------------ API key
# 注意：签发/吊销都走 JWT（IssueAPIKey 的认证是 jwt），所以必须先用邮箱登录。
# 密钥只在签发那一次出现，之后服务端只留摘要 —— 落盘责任在调用方。


@app.command("keys")
def keys() -> None:
    """列本账号的 API key（不含密钥本体）。"""
    st = current()
    payload = st.client().call("auth.ListAPIKeys", query={"page_size": 100})
    output.emit_table(
        payload.get("keys") or [],
        [
            ("KEY ID", "keyId"),
            ("名称", "name"),
            ("项目", "projectIds"),
            ("创建时间", "createdAt"),
            ("最后使用", "lastUsedAt"),
            ("已吊销", "revokedAt"),
        ],
        json_out=st.json_out,
    )


@app.command("key-create")
def key_create(
    name: str = typer.Option(..., "--name", "-n", help="用途备注，便于日后吊销"),
    project_ids: list[str] = typer.Option(None, "--project-id", help="限定项目，可重复；缺省不限定"),
) -> None:
    """签发 API key（**明文只打印这一次**）。"""
    st = current()
    body: dict = {"name": name}
    if project_ids:
        body["projectIds"] = ",".join(project_ids)
    payload = st.client().call("auth.IssueAPIKey", body=body)
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(payload.get("apiKey") or "", err=True)
    typer.echo(f"key_id={payload.get('keyId')}（明文只此一次，请立即存好）", err=True)


@app.command("key-revoke")
def key_revoke(
    key_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """吊销 API key。"""
    st = current()
    if not yes:
        typer.confirm(f"确认吊销 {key_id}？", abort=True)
    st.client().call("auth.RevokeAPIKey", path_params={"key_id": key_id})
    typer.echo(f"已吊销 {key_id}")


# ------------------------------------------------------------------ 个人资料

_AVATAR_MEDIA_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


@app.command("profile")
def profile() -> None:
    """看当前账号资料（头像以 base64 内联，这里只显示「有/类型」，字节走 --json）。"""
    st = current()
    payload = st.client().call("auth.GetProfile")
    if st.json_out:
        output.emit_json(payload)
        return
    view = {k: v for k, v in payload.items() if k != "avatarBytes"}
    if payload.get("avatarBytes"):
        view["avatar"] = payload.get("avatarMediaType") or "有（--json 取字节）"
    output.emit_object(view, json_out=False)


@app.command("profile-update")
def profile_update(
    display_name: str = typer.Option(None, "--display-name", help="显示名"),
    username: str = typer.Option(None, "--username"),
    phone: str = typer.Option(None, "--phone"),
) -> None:
    """改资料；只发显式给出的字段（都不给 = 用法错，避免空 PATCH）。"""
    st = current()
    body: dict = {}
    if display_name is not None:
        body["displayName"] = display_name
    if username is not None:
        body["username"] = username
    if phone is not None:
        body["phone"] = phone
    if not body:
        raise UsageError("至少给一个：--display-name / --username / --phone")
    output.emit_object(st.client().call("auth.UpdateProfile", body=body), json_out=st.json_out)


@app.command("change-password")
def change_password(
    current_password: str = typer.Option(None, "--current-password", help="缺省交互输入，不进 shell 历史"),
    new_password: str = typer.Option(None, "--new-password", help="缺省交互输入；>=8 位且含大小写"),
) -> None:
    """改密码（旧密码证明是本人）。"""
    st = current()
    current_password = current_password or typer.prompt("当前密码", hide_input=True)
    new_password = new_password or typer.prompt("新密码", hide_input=True, confirmation_prompt=True)
    st.client().call(
        "auth.ChangePassword",
        body={"currentPassword": current_password, "newPassword": new_password},
    )
    typer.echo("密码已更新")


@app.command("set-email")
def set_email(
    new_email: str = typer.Option(..., "--email", "-e", help="新登录邮箱"),
    current_password: str = typer.Option(None, "--current-password", help="缺省交互输入"),
) -> None:
    """换登录邮箱（要当前密码，防止被盗会话直接改）。"""
    st = current()
    current_password = current_password or typer.prompt("当前密码", hide_input=True)
    payload = st.client().call(
        "auth.UpdateEmail",
        body={"newEmail": new_email, "currentPassword": current_password},
    )
    output.emit_object(payload, json_out=st.json_out)


@app.command("set-avatar")
def set_avatar(
    file: str = typer.Option(None, "--file", "-f", help="图片文件；传 - 读 stdin"),
    media_type: str = typer.Option(None, "--media-type", help="缺省按扩展名猜"),
    clear: bool = typer.Option(False, "--clear", help="清除头像"),
) -> None:
    """换/清头像（base64 内联，服务端限 64KB 方图）。"""
    st = current()
    if clear and file:
        raise UsageError("--clear 与 --file 互斥")
    if not clear and not file:
        raise UsageError("给 --file <图片>，或用 --clear 清除头像")
    body: dict = {}
    if clear:
        body = {"data": "", "mediaType": ""}
    else:
        raw = sys.stdin.buffer.read() if file == "-" else open(file, "rb").read()
        mt = media_type or (mimetypes.guess_type(file)[0] if file != "-" else None)
        if mt not in _AVATAR_MEDIA_TYPES:
            raise UsageError(
                f"媒体类型 {mt or '(未知)'} 不在白名单：{', '.join(sorted(_AVATAR_MEDIA_TYPES))}（用 --media-type 指定）"
            )
        body = {"data": base64.b64encode(raw).decode(), "mediaType": mt}
    output.emit_object(st.client().call("auth.UpdateAvatar", body=body), json_out=st.json_out)


def whoami() -> None:
    """显示登录身份 + 作用域 + 可访问项目（后者顺带证明令牌有效）。"""
    st = current()
    prof_user = st.profile.get("user") or {}
    payload = st.client().call(
        "tenant.ListProjects", query={"page_size": 50}
    )
    projects = payload.get("projects") or []
    if st.json_out:
        output.emit_json(
            {
                "baseUrl": st.base_url,
                "profile": st.profile_name,
                "user": prof_user,
                "project": st.project,
                "projects": projects,
            }
        )
        return
    typer.echo(f"地址      {st.base_url}")
    typer.echo(f"配置档    {st.profile_name}")
    if prof_user.get("email"):
        typer.echo(f"用户      {prof_user['email']}")
    if prof_user.get("user_id"):
        typer.echo(f"用户 id   {prof_user['user_id']}")
    if prof_user.get("org_id"):
        typer.echo(f"组织 id   {prof_user['org_id']}")
    typer.echo(f"平台管理员 {'是' if prof_user.get('is_platform_admin') else '否'}")
    typer.echo(f"当前项目  {st.project or '(未设置 —— 用 rathflow project use <id>)'}")
    typer.echo("")
    output.emit_table(
        projects,
        [("PROJECT ID", "projectId"), ("名称", "name"), ("创建时间", "createdAt")],
        json_out=False,
    )
