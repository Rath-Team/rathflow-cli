"""asset：资产（skill / mcp_server / plugin）、版本、可见性与装配。

管理面（/admin/...）与消费面（/api/v1/...）同放一组命令：
能不能跑通由服务端权限决定，CLI 不预先拦（403 会带原因回来）。
"""

from __future__ import annotations

import base64

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

app = typer.Typer(no_args_is_help=True, help="资产 / 版本 / 装配")

KINDS = "skill | mcp_server | plugin"
TIERS = "core | optional"
LIFECYCLES = "active | retired"
SCOPES = "global | plan | org"
POLICIES = "immediate | on_idle | manual"

COLUMNS = [
    ("ASSET ID", "assetId"),
    ("类型", "kind"),
    ("层级", "tier"),
    ("名称", "name"),
    ("启用", "enabled"),
    ("生效版本", "effectiveVersion"),
]


# ------------------------------------------------------------------ 消费面

@app.command("list")
def list_(
    kind: str = typer.Option(None, "--kind", help=KINDS),
    tier: str = typer.Option(None, "--tier", help=TIERS),
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
) -> None:
    """列资产（含未启用）。"""
    st = current()
    query = pagination(page_size or 50, page_token, {"kind": _enum("ASSET_KIND", kind), "tier": _enum("ASSET_TIER", tier)})
    payload = st.client().call("assets.ListAssets", query=query)
    output.emit_items(payload, items_key="assets", columns=COLUMNS, json_out=st.json_out)


@app.command("enabled")
def enabled(
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
) -> None:
    """只看本项目已启用的资产。"""
    st = current()
    payload = st.client().call(
        "assets.ListEnabledAssets", query=pagination(page_size or 50, page_token)
    )
    output.emit_items(payload, items_key="assets", columns=COLUMNS, json_out=st.json_out)


@app.command("get")
def get(asset_id: str = typer.Argument(...)) -> None:
    """资产详情。"""
    st = current()
    payload = st.client().call("assets.GetAsset", path_params={"asset_id": asset_id})
    output.emit_object(payload, json_out=st.json_out)


@app.command("pin")
def pin(
    asset_id: str = typer.Argument(...),
    version_id: str = typer.Option(..., "--version-id", help="要钉住的版本 id"),
) -> None:
    """把资产钉到指定版本。"""
    st = current()
    payload = st.client().call(
        "assets.PinAssetVersion", path_params={"asset_id": asset_id}, body={"versionId": version_id}
    )
    output.emit_object(payload, json_out=st.json_out)


@app.command("set-config")
def set_config(
    asset_id: str = typer.Argument(...),
    body: str = BODY_OPT,
    body_file: str = BODY_FILE_OPT,
) -> None:
    """写资产配置（Struct，用 --body 传）。"""
    st = current()
    config = body_of(body, body_file)
    if config is None:
        raise UsageError('需要 --body \'{"...":...}\' 或 --body-file')
    payload = st.client().call(
        "assets.SetAssetConfig", path_params={"asset_id": asset_id}, body={"config": config}
    )
    output.emit_object(payload, json_out=st.json_out)


@app.command("enable")
def enable(asset_id: str = typer.Argument(...)) -> None:
    """在本项目启用资产。"""
    _set_enabled(asset_id, True)


@app.command("disable")
def disable(asset_id: str = typer.Argument(...)) -> None:
    """在本项目停用资产。"""
    _set_enabled(asset_id, False)


@app.command("set-credential")
def set_credential(
    asset_id: str = typer.Argument(...),
    cred_ref: str = typer.Option(..., "--cred-ref", help="凭据引用（服务端密钥库里的键）"),
    inject_as: str = typer.Option(None, "--inject-as"),
    inject_key: str = typer.Option(None, "--inject-key"),
) -> None:
    """绑定凭据引用（**只填引用名，不传密钥本体**）。"""
    st = current()
    body = {"credRef": cred_ref}
    if inject_as:
        body["injectAs"] = inject_as
    if inject_key:
        body["injectKey"] = inject_key
    payload = st.client().call(
        "assets.SetCredential", path_params={"asset_id": asset_id}, body=body
    )
    output.emit_object(payload, json_out=st.json_out)


# ------------------------------------------------------------------ 管理面

@app.command("create")
def create(
    kind: str = typer.Option(..., "--kind", help=KINDS),
    tier: str = typer.Option(..., "--tier", help=TIERS),
    name: str = typer.Option(..., "--name", "-n"),
    description: str = typer.Option(None, "--description", "-d"),
    body: str = BODY_OPT,
    body_file: str = BODY_FILE_OPT,
) -> None:
    """建资产（payload 用 --body 传）。"""
    st = current()
    payload_body = {
        "kind": _enum("ASSET_KIND", kind),
        "tier": _enum("ASSET_TIER", tier),
        "name": name,
    }
    if description:
        payload_body["description"] = description
    payload = body_of(body, body_file)
    if payload:
        payload_body["payload"] = payload
    out = st.client().call("assets.CreateAsset", body=payload_body)
    if st.json_out:
        output.emit_json(out)
        return
    typer.echo(out.get("assetId") or "")


@app.command("create-version")
def create_version(
    asset_id: str = typer.Argument(...),
    version: str = typer.Option(..., "--version", "-v", help="版本号（语义化字符串）"),
    engine_compat: str = typer.Option(None, "--engine-compat"),
    content_digest: str = typer.Option(None, "--content-digest"),
    body: str = BODY_OPT,
    body_file: str = BODY_FILE_OPT,
) -> None:
    """建版本（contribution_spec 用 --body 传）。"""
    st = current()
    payload_body = {"version": version}
    if engine_compat:
        payload_body["engineCompat"] = engine_compat
    if content_digest:
        payload_body["contentDigest"] = content_digest
    spec = body_of(body, body_file)
    if spec:
        payload_body["contributionSpec"] = spec
    out = st.client().call(
        "assets.CreateAssetVersion", path_params={"asset_id": asset_id}, body=payload_body
    )
    if st.json_out:
        output.emit_json(out)
        return
    typer.echo(out.get("versionId") or "")


@app.command("update")
def update(
    asset_id: str = typer.Argument(...),
    body: str = BODY_OPT,
    body_file: str = BODY_FILE_OPT,
) -> None:
    """改资产元信息（PATCH）。"""
    st = current()
    payload_body = body_of(body, body_file)
    if not payload_body:
        raise UsageError("需要 --body（name/description/payload 中至少一项）")
    payload = st.client().call(
        "assets.UpdateAsset", path_params={"asset_id": asset_id}, body=payload_body
    )
    output.emit_object(payload, json_out=st.json_out)


@app.command("put-content")
def put_content(
    asset_id: str = typer.Argument(...),
    version_id: str = typer.Option(..., "--version-id"),
    file: str = typer.Option(..., "--file", "-f", help="本地文件路径（- = 读 stdin）"),
    content_type: str = typer.Option(None, "--content-type"),
) -> None:
    """上传版本内容（本地文件 → bytes；base64 编码由 CLI 负责）。"""
    import sys

    if file == "-":
        data = sys.stdin.buffer.read()
    else:
        try:
            with open(file, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            raise UsageError(f"读取失败：{exc}") from None
    body = {
        "content": base64.b64encode(data).decode(),
    }
    if content_type:
        body["contentType"] = content_type
    payload = st.client().call(
        "assets.PutAssetContent",
        path_params={"asset_id": asset_id, "version_id": version_id},
        body=body,
    )
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(f"已上传 {len(data)} 字节 → {asset_id}/{version_id}")


@app.command("publish")
def publish(
    asset_id: str = typer.Argument(...),
    version_id: str = typer.Option(..., "--version-id"),
) -> None:
    """发布版本。"""
    _version_action("assets.PublishVersion", asset_id, version_id, "已发布")


@app.command("yank")
def yank(
    asset_id: str = typer.Argument(...),
    version_id: str = typer.Option(..., "--version-id"),
) -> None:
    """撤回版本。"""
    _version_action("assets.YankVersion", asset_id, version_id, "已撤回")


@app.command("set-lifecycle")
def set_lifecycle(
    asset_id: str = typer.Argument(...),
    lifecycle: str = typer.Option(..., "--lifecycle", help=LIFECYCLES),
) -> None:
    """改资产生命周期。"""
    st = current()
    payload = st.client().call(
        "assets.SetAssetLifecycle",
        path_params={"asset_id": asset_id},
        body={"lifecycle": _enum("ASSET_LIFECYCLE", lifecycle)},
    )
    output.emit_object(payload, json_out=st.json_out)


@app.command("set-visibility")
def set_visibility(
    asset_id: str = typer.Argument(...),
    scope: str = typer.Option(..., "--scope", help=SCOPES),
    scope_ref: str = typer.Option(None, "--scope-ref", help="plan/org 作用域的目标 id"),
    visible: bool = typer.Option(True, "--visible/--hidden"),
) -> None:
    """改可见性。"""
    st = current()
    body = {"scope": _enum("VISIBILITY_SCOPE", scope), "visible": visible}
    if scope_ref:
        body["scopeRef"] = scope_ref
    payload = st.client().call(
        "assets.SetVisibility", path_params={"asset_id": asset_id}, body=body
    )
    output.emit_object(payload, json_out=st.json_out)


@app.command("sync-core")
def sync_core() -> None:
    """把内置 core 资产同步进库。"""
    st = current()
    payload = st.client().call("assets.SyncCoreAssets", body={})
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(f"新增 {payload.get('added', 0)}，更新 {payload.get('updated', 0)}")


# ------------------------------------------------------------------ 装配

@app.command("assembly-status")
def assembly_status() -> None:
    """看装配状态（desired/applied revision）。"""
    st = current()
    payload = st.client().call("assets.GetAssemblyStatus")
    output.emit_object(payload, json_out=st.json_out)


@app.command("assembly-dispatch")
def assembly_dispatch(
    project_id: str = typer.Option(None, "--project-id", help="缺省用当前作用域项目"),
    org_id: str = typer.Option(None, "--org-id"),
    reason: str = typer.Option(None, "--reason"),
    restart_policy: str = typer.Option(None, "--restart-policy", help=POLICIES),
) -> None:
    """触发一次装配下发。"""
    st = current()
    body: dict = {}
    pid = project_id or st.project
    if pid:
        body["projectId"] = pid
    if org_id:
        body["orgId"] = org_id
    if reason:
        body["reason"] = reason
    if restart_policy:
        body["restartPolicy"] = _enum("RESTART_POLICY", restart_policy)
    payload = st.client().call("assets.TriggerAssemblyDispatch", body=body)
    if st.json_out:
        output.emit_json(payload)
        return
    dispatch = payload.get("dispatch") or {}
    typer.echo(f"已触发：revision={dispatch.get('revision')} state={dispatch.get('state')}")


@app.command("assembly-revisions")
def assembly_revisions(
    project_id: str = typer.Option(None, "--project-id"),
    org_id: str = typer.Option(None, "--org-id"),
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
) -> None:
    """列装配 revision 历史。"""
    st = current()
    query = pagination(page_size or 20, page_token, {"project_id": project_id or st.project, "org_id": org_id})
    payload = st.client().call("assets.ListAssemblyRevisions", query=query)
    output.emit_items(
        payload,
        items_key="revisions",
        columns=[
            ("REV", "revision"),
            ("状态", "state"),
            ("需重启", "restartRequired"),
            ("原因", "reason"),
            ("创建时间", "createdAt"),
        ],
        json_out=st.json_out,
    )


@app.command("assembly-artifact")
def assembly_artifact(
    project_id: str = typer.Argument(...),
    revision: int = typer.Argument(...),
    out: str = typer.Option(None, "--out", "-o", help="写入文件；缺省 stdout"),
    meta: bool = typer.Option(False, "--meta", help="只打印元信息，不吐 patch_content"),
) -> None:
    """取装配产物（patch_content 是 bytes）。"""
    st = current()
    payload = st.client().call(
        "assets.GetAssemblyArtifact",
        path_params={"project_id": project_id, "revision": revision},
    )
    if st.json_out and not meta:
        output.emit_json(payload)
        return
    info = {k: v for k, v in payload.items() if k != "patchContent"}
    output.emit_object(info, json_out=st.json_out)
    raw = payload.get("patchContent")
    if meta or not raw:
        return
    try:
        data = base64.b64decode(raw)
    except Exception:
        data = str(raw).encode()
    if out:
        with open(out, "wb") as fh:
            fh.write(data)
        typer.echo(f"已写入 {out}（{len(data)} 字节）", err=True)
    else:
        output.write_bytes(data)


# ------------------------------------------------------------------ 内部

_ENUM_PREFIX = {
    "ASSET_KIND": "ASSET_KIND_",
    "ASSET_TIER": "ASSET_TIER_",
    "ASSET_LIFECYCLE": "ASSET_LIFECYCLE_",
    "VISIBILITY_SCOPE": "VISIBILITY_SCOPE_",
    "RESTART_POLICY": "RESTART_POLICY_",
}
# CLI 上写的短名 → 枚举全名（protojson 认全名，也认短名，但只认大写）
_ENUM_ALIAS = {"global": "GLOBAL", "plan": "PLAN", "org": "ORG"}


def _enum(prefix: str, value: str | None) -> str | None:
    """'mcp_server' → 'ASSET_KIND_MCP_SERVER'；已是大写全名则原样。"""
    if not value:
        return None
    text = _ENUM_ALIAS.get(value.lower(), value.upper())
    full = _ENUM_PREFIX[prefix]
    return text if text.startswith(full) else full + text


def _set_enabled(asset_id: str, enabled: bool) -> None:
    st = current()
    payload = st.client().call(
        "assets.SetAssetEnabled", path_params={"asset_id": asset_id}, body={"enabled": enabled}
    )
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(f"已{'启用' if enabled else '停用'} {asset_id}")


def _version_action(key: str, asset_id: str, version_id: str, done: str) -> None:
    st = current()
    payload = st.client().call(
        key, path_params={"asset_id": asset_id, "version_id": version_id}, body={}
    )
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(f"{done} {asset_id}/{version_id}")
