"""typer 根应用与全局选项。"""

from __future__ import annotations

import sys

import typer

from . import __version__, errors, state as state_mod
from .state import State

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="RathFlow 命令行客户端（JWT 登录；命令覆盖北向 REST 全部端点）。",
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"rathflow {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    ctx: typer.Context,
    profile: str = typer.Option(None, "--profile", "-p", help="配置档名（缺省 default）"),
    base_url: str = typer.Option(None, "--base-url", help="gateway 地址（env RATHFLOW_BASE_URL）"),
    project: str = typer.Option(None, "--project", help="项目作用域（env RATHFLOW_PROJECT）"),
    json_out: bool = typer.Option(False, "--json", help="以 JSON 输出（脚本消费的稳定形态）"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="只输出主键"),
    version: bool = typer.Option(
        False, "--version", callback=_print_version, is_eager=True, help="显示版本并退出"
    ),
) -> None:
    ctx.obj = state_mod.install(
        State(
            profile_name=profile,
            base_url=base_url,
            project=project,
            json_out=json_out,
            quiet=quiet,
        )
    )


def _register() -> None:
    from .commands import (
        admin,
        agent,
        api_cmd,
        asset,
        auth_cmd,
        billing,
        config_cmd,
        mcp_cmd,
        memory,
        org,
        project,
        sandbox,
        session,
        workflow,
    )

    app.add_typer(auth_cmd.app, name="auth")
    app.add_typer(config_cmd.app, name="config")
    app.add_typer(mcp_cmd.app, name="mcp")
    app.add_typer(org.app, name="org")
    app.add_typer(project.app, name="project")
    app.add_typer(session.app, name="session")
    app.add_typer(memory.app, name="memory")
    app.add_typer(sandbox.app, name="sandbox")
    app.add_typer(agent.app, name="agent")
    app.add_typer(asset.app, name="asset")
    app.add_typer(billing.app, name="billing")
    app.add_typer(workflow.app, name="workflow")
    app.add_typer(admin.app, name="admin")

    from .commands.auth_cmd import whoami

    app.command("whoami", help="显示登录身份、作用域与可访问项目")(whoami)
    # 逃生舱直接挂根：`rathflow api <Key>` 不必多打一层 `call`
    app.command("api", help="任意端点调用（`rathflow api --list` 看全部）")(api_cmd.call)


_register()


# 可以挪到命令行最前的全局选项：前者是布尔旗标，后者各吃一个值。
_HOIST_FLAGS = frozenset({"--json", "--quiet"})
_HOIST_OPTS = frozenset({"--profile", "--base-url", "--project"})


def _value_opts() -> set[str]:
    """全 app 里「吃下一个词」的选项名 —— 用来判断挪旗标安不安全。

    走 click 命令树而非 Typer 对象：Typer 只是注册表，click Group 是懒构建的。
    """

    def walk(cmd) -> set[str]:
        found: set[str] = set()
        for param in getattr(cmd, "params", []):
            if getattr(param, "is_flag", False) or getattr(param, "count", False):
                continue
            # 只认真正的选项（以 "-" 开头）。位置参数的 opts 是它自己的名字
            # （例如 `auth profile` 的 `profile`），把它当吃值的选项会让
            # `rathflow auth profile --json` 里的 --json 不被前移而报错。
            found.update(o for o in getattr(param, "opts", []) if o.startswith("-"))
        for sub in getattr(cmd, "commands", {}).values():
            found |= walk(sub)
        return found

    return walk(typer.main.get_command(app))


def _hoist_globals(argv: list[str]) -> list[str]:
    """把写在命令**后面**的全局选项挪到最前。

    click 只认组级选项出现在子命令之前，故 `rathflow project list --json` 会被
    当成给 `list` 传参而报错。脚本里这个顺序太自然了，于是这里做一次改写：
    只挪白名单里的选项，且前一个词不是吃值的选项（否则那个词是被当值用的，
    例如 `--body --json` 里的 `--json` 是值，不能动）。
    """
    if len(argv) < 2:
        return argv
    value_opts = _value_opts()
    head, tail = [argv[0]], []
    hoisted: list[str] = []
    idx = 1
    while idx < len(argv):
        tok = argv[idx]
        prev = argv[idx - 1]
        # 前一个词若是吃值的选项，本词就是它的值（click 也这么看），别动
        safe = prev not in value_opts
        if safe and tok in _HOIST_FLAGS:
            hoisted.append(tok)
            idx += 1
            continue
        if safe and tok in _HOIST_OPTS and idx + 1 < len(argv) and not argv[idx + 1].startswith("-"):
            hoisted.extend([tok, argv[idx + 1]])
            idx += 2
            continue
        tail.append(tok)
        idx += 1
    return head + hoisted + tail


def main() -> None:
    sys.argv = _hoist_globals(sys.argv)
    try:
        app()
    except errors.UsageError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(errors.EXIT_USAGE)
    except errors.ApiError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        for detail in exc.details:
            print(f"  - {detail}", file=sys.stderr)
        sys.exit(exc.exit_code)
    except ImportError as exc:
        if "socksio" in str(exc):
            print(
                "错误：当前环境走 SOCKS 代理，但这个 CLI 没装 socksio。"
                "带上 extras 重装即可：uv tool install 'rathflow-cli[socks]'",
                file=sys.stderr,
            )
            sys.exit(errors.EXIT_ERROR)
        raise
    except ValueError as exc:
        if "Unknown scheme for proxy URL" in str(exc):
            print(
                "错误：代理地址的协议 httpx 不认（只支持 http/https/socks5/socks5h）。"
                "把 ALL_PROXY / HTTPS_PROXY 里的 socks:// 改成 socks5h://，"
                "或升级到 rathflow-cli >= 0.1.5（会自动改写）。",
                file=sys.stderr,
            )
            sys.exit(errors.EXIT_ERROR)
        raise
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
