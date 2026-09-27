"""config：本地配置档（base_url / project / 令牌存放）。"""

from __future__ import annotations

import typer

from .. import config, output
from ..errors import UsageError
from ..state import current

app = typer.Typer(no_args_is_help=True, help="本地配置档管理")

_KEYS = ("base_url", "project")


@app.command("list")
def list_() -> None:
    """列出全部配置档。"""
    st = current()
    profiles = st.data.get("profiles") or {}
    rows = []
    for name, prof in profiles.items():
        rows.append(
            {
                "name": name,
                "current": "*" if name == st.profile_name else "",
                "base_url": prof.get("base_url") or config.DEFAULT_BASE_URL,
                "project": prof.get("project") or "",
                "email": (prof.get("user") or {}).get("email", ""),
                "token": config.mask(prof.get("access_token")),
            }
        )
    output.emit_table(
        rows,
        [
            ("", "current"),
            ("配置档", "name"),
            ("地址", "base_url"),
            ("项目", "project"),
            ("邮箱", "email"),
            ("令牌", "token"),
        ],
        json_out=st.json_out,
    )


@app.command("show")
def show() -> None:
    """显示当前生效配置（flag/env 覆盖后的结果）。"""
    st = current()
    output.emit_object(
        {
            "profile": st.profile_name,
            "base_url": st.base_url,
            "project": st.project or "(未设置)",
            "token": config.mask(st.profile.get("access_token")),
            "config_file": str(config.config_path()),
            # 只回显真实存在的环境变量；未设时明确写「(未设置)」，
            # 否则会把 profile/默认值伪装成 env 覆盖，误导用户与模型。
            "env": {
                config.ENV_BASE_URL: st.env_base_url or "(未设置)",
                config.ENV_PROJECT: st.env_project or "(未设置)",
                config.ENV_TOKEN: config.mask(st.token_override),
            },
        },
        json_out=st.json_out,
    )


@app.command("set")
def set_(
    key: str = typer.Argument(..., help="base_url | project"),
    value: str = typer.Argument(..., help="值；project 传 - 表示清空"),
) -> None:
    """写当前配置档的一项。"""
    st = current()
    if key not in _KEYS:
        raise UsageError(f"可设的键：{', '.join(_KEYS)}")
    prof = st.profile
    if key == "project" and value == "-":
        prof.pop("project", None)
        # 清掉登录时记下的默认项目，否则下次仍会回填
        prof.pop("default_project_id", None)
        typer.echo("已清空 project")
    else:
        prof[key] = value
        typer.echo(f"{key} = {value}")
    st.data["profiles"][st.profile_name] = prof
    config.save(st.data)


@app.command("use")
def use(profile: str = typer.Argument(..., help="配置档名；不存在则新建")) -> None:
    """切换当前配置档。"""
    st = current()
    if profile not in (st.data.get("profiles") or {}):
        st.data.setdefault("profiles", {})[profile] = {}
    st.data["current"] = profile
    config.save(st.data)
    typer.echo(f"已切到配置档 {profile}（首次使用需在该档下 auth login）")
