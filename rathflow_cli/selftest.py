"""轻量自检（不联服务端）：``python -m rathflow_cli.selftest``

查三件事，都是「装得上但会打错 URL」的那类毛病：

1. **命令实现里不写 URL 字面量** —— 所有请求必须走 ``endpoints.py`` 的端点 key；
2. **端点表与生成物一致** —— 生成物 ``endpoints.ts`` 由上游 proto 生成，本包的
   ``endpoints.py`` 手工同步；两者漂移就会打错 URL。生成物在本仓库中不存在
   （它是上游 monorepo 的产物），此时这一项跳过，可用环境变量
   ``RATHFLOW_ENDPOINTS_TS`` 指向它来启用比对。
3. **多段路径参数拦住点段** —— ``..`` 会被 HTTP 客户端按 URL 语义归一化，
   把请求打到别的端点上（还会绕过命令自己的域检查）。
4. **MCP 服务端守协议** —— 握手版本协商、工具 schema 合法、stdout 只有 JSON 帧、
   未登录时给出的是「去配置」而不是「去找源码」。
5. **代理协议名归一化** —— Clash 常导出 ``socks://``，httpx 不认，必须改写成
   ``socks5h://``；不改写就会在第一次调用时裸崩。
"""

from __future__ import annotations

import re
import os
import sys
from pathlib import Path

from .errors import UsageError

from . import endpoints

_COMMANDS = Path(__file__).resolve().parent / "commands"


def _find_generated() -> Path | None:
    """定位上游生成的 endpoints.ts；找不到就返回 None（跳过比对）。"""
    override = os.environ.get("RATHFLOW_ENDPOINTS_TS")
    if override:
        candidate = Path(override)
        return candidate if candidate.exists() else None
    for base in Path(__file__).resolve().parents:
        candidate = base / "web" / "lib" / "api" / "generated" / "endpoints.ts"
        if candidate.exists():
            return candidate
    return None


_GENERATED = _find_generated()

_ROW = re.compile(
    r'\{ key: "(?P<key>[^"]+)", method: "(?P<method>\w+)", path: "(?P<path>[^"]+)",'
    r" pathParams: \[(?P<pp>[^\]]*)\], multiParams: \[(?P<mp>[^\]]*)\],"
    r".*?stream: (?P<stream>true|false),"
)
_URL_LITERAL = re.compile(r'"(?:/api/|/admin/api/)')


def main() -> int:
    generated_problems, compared = _check_generated()
    problems = (
        generated_problems
        + _check_no_url_literals()
        + _check_path_guard()
        + _check_hoist_flags()
        + _check_mcp()
        + _check_proxy_env()
    )
    if problems:
        print(f"自检未通过（{len(problems)} 项）：", file=sys.stderr)
        for line in problems:
            print(f"  - {line}", file=sys.stderr)
        return 1
    total = len(endpoints.ENDPOINTS)
    if compared:
        print(f"自检通过：端点表与生成物一致（{total} 个端点）")
    else:
        print(f"自检通过：命令层无 URL 字面量（{total} 个端点；未找到生成物，跳过端点表比对）")
    return 0


def _check_generated() -> tuple[list[str], bool]:
    """比对端点表与上游生成物；返回 (问题列表, 是否真的比对了)。"""
    if _GENERATED is None or not _GENERATED.exists():
        return [], False
    rows = {}
    for line in _GENERATED.read_text(encoding="utf-8").splitlines():
        m = _ROW.search(line)
        if not m:
            continue
        rows[m["key"]] = {
            "method": m["method"],
            "path": m["path"],
            "multi": _names(m["mp"]),
            "stream": m["stream"] == "true",
        }

    problems = []
    missing = sorted(rows.keys() - endpoints.ENDPOINTS.keys())
    extra = sorted(endpoints.ENDPOINTS.keys() - rows.keys())
    if missing:
        problems.append(f"endpoints.py 缺 {len(missing)} 个端点：{missing[:5]}…")
    if extra:
        problems.append(f"endpoints.py 多出 {len(extra)} 个端点：{extra[:5]}…")

    for key in sorted(rows.keys() & endpoints.ENDPOINTS.keys()):
        want, got = rows[key], endpoints.ENDPOINTS[key]
        if (got[1], got[0]) != (want["path"], want["method"]):
            problems.append(f"{key}: 路径/方法不一致 {got} vs {want['path']}/{want['method']}")
        have_multi = set(endpoints.MULTI_PARAMS.get(key, frozenset()))
        if have_multi != want["multi"]:
            problems.append(f"{key}: multiParams 不一致 {sorted(have_multi)} vs {sorted(want['multi'])}")
        if endpoints.is_streaming(key) != want["stream"]:
            problems.append(f"{key}: stream 标记不一致 {endpoints.is_streaming(key)} vs {want['stream']}")

    # 模板参数与 MULTI_PARAMS 声明必须对得上（多段参数一定出现在模板里）
    for key in endpoints.ENDPOINTS:
        declared = set(endpoints.MULTI_PARAMS.get(key, frozenset()))
        unknown = declared - set(endpoints.path_params(key))
        if unknown:
            problems.append(f"{key}: MULTI_PARAMS 声明了模板里没有的参数 {sorted(unknown)}")
    return problems, True


def _check_no_url_literals() -> list[str]:
    problems = []
    for path in sorted(_COMMANDS.glob("*.py")):
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _URL_LITERAL.search(line) and not line.lstrip().startswith("#"):
                problems.append(f"{path.name}:{no} 出现 URL 字面量（该走端点 key）")
    return problems


def _check_hoist_flags() -> list[str]:
    """全局旗标写在子命令后面也必须能用（脚本里最常见的写法）。"""
    from . import cli

    problems = []
    for argv in (
        ["rathflow", "auth", "profile", "--json"],
        ["rathflow", "project", "list", "--json"],
        ["rathflow", "config", "use", "default", "--json"],
        ["rathflow", "session", "get", "S1", "--json"],
    ):
        hoisted = cli._hoist_globals(list(argv))
        if hoisted[1:2] != ["--json"]:
            problems.append(f"{' '.join(argv)}: 末尾 --json 未被前移（会报 no such option）")
    return problems


def _check_path_guard() -> list[str]:
    """多段路径里的 ``.``/``..``/空段必须被拒，正常路径仍要能渲染。"""
    cases = {"memory.Read": "memory_path", "sandbox.ReadFile": "path"}
    bad_inputs = ("a/../b", "../x", "/abs", "a//b", "a/./b")
    problems = []
    for key, name in cases.items():
        others = {p: "X1" for p in endpoints.path_params(key) if p != name}
        for bad in bad_inputs:
            try:
                rendered = endpoints.render_path(key, {name: bad, **others})
            except UsageError:
                continue
            except Exception as exc:  # noqa: BLE001 - 自检要报「类型不对」
                problems.append(f"{key}: {name}={bad!r} 抛了 {type(exc).__name__}，应抛 UsageError")
            else:
                problems.append(
                    f"{key}: {name}={bad!r} 未被拒绝，会渲染成 {rendered}（URL 归一化后打到别的端点）"
                )
        good = endpoints.render_path(key, {name: "a/b c.md", **others})
        if not good.endswith("a/b%20c.md"):
            problems.append(f"{key}: 正常路径渲染异常 {good}")
    return problems




_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _check_mcp() -> list[str]:
    """MCP 服务端的协议自检（不联网关，全部在进程内跑一遍读写循环）。

    专抓「装得上但客户端连不上」的那类毛病：版本协商错、工具 schema 不合法、
    把日志混进 stdout、未登录时给不出可执行的下一步。
    """
    import contextlib
    import io
    import json
    import os
    import tempfile

    from .mcp import protocol, server, tools
    from .state import State

    problems: list[str] = []
    saved_dir = os.environ.get("RATHFLOW_CONFIG_DIR")
    saved_token = os.environ.get("RATHFLOW_TOKEN")
    saved_write = os.environ.get(tools.WRITE_ENV)

    def run(messages: list, *, write: bool = False, raw: str | None = None) -> list:
        """跑一轮读写循环，返回解析出的响应帧。"""
        if write:
            os.environ[tools.WRITE_ENV] = "1"
        else:
            os.environ.pop(tools.WRITE_ENV, None)
        payload = raw if raw is not None else "".join(
            json.dumps(m, ensure_ascii=False) + "\n" for m in messages
        )
        stdin, stdout = io.StringIO(payload), io.StringIO()
        with contextlib.redirect_stderr(io.StringIO()):
            server.serve(State(), stdin=stdin, stdout=stdout)
        frames = []
        for line in stdout.getvalue().splitlines():
            if not line.strip():
                continue
            try:
                frames.append(json.loads(line))
            except json.JSONDecodeError:
                problems.append(f"MCP stdout 出现非 JSON 行：{line[:80]!r}")
        return frames

    try:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["RATHFLOW_CONFIG_DIR"] = tmp
            os.environ.pop("RATHFLOW_TOKEN", None)

            # 握手：认识客户端的版本就沿用，不认识就回本端最新
            init = run([{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "2025-11-25"}}])
            result = (init[0].get("result") or {}) if init else {}
            if result.get("protocolVersion") != "2025-11-25":
                problems.append(f"initialize 未沿用客户端版本：{result.get('protocolVersion')!r}")
            if not (result.get("capabilities") or {}).get("tools"):
                problems.append("initialize 未宣告 tools 能力")
            if "rathflow auth login" not in (result.get("instructions") or ""):
                problems.append("initialize instructions 没写「未登录就让用户去 auth login」")
            unknown = run([{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                            "params": {"protocolVersion": "1999-01-01"}}])
            got = ((unknown[0].get("result") or {}).get("protocolVersion") if unknown else None)
            if got != protocol.LATEST_PROTOCOL_VERSION:
                problems.append(f"未知版本未回退到最新：{got!r}")

            # 工具表：只读模式不出现写工具；schema 必须是合法对象
            read_frames = run([{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
            read_tools = ((read_frames[0].get("result") or {}).get("tools") if read_frames else None) or []
            names = [t.get("name") for t in read_tools]
            if len(set(names)) != len(names):
                problems.append("tools/list 出现重名工具")
            bad_readonly = [
                t.get("name")
                for t in read_tools
                if not (t.get("annotations") or {}).get("readOnlyHint")
            ]
            if bad_readonly:
                problems.append(f"只读工具没标 readOnlyHint：{bad_readonly[:3]}")
            for tool in read_tools:
                name = tool.get("name") or ""
                if not _TOOL_NAME.match(name):
                    problems.append(f"工具名不合规：{name!r}")
                schema = tool.get("inputSchema") or {}
                if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
                    problems.append(f"{name}: inputSchema 不是合法对象 schema")
                    continue
                extra_required = set(schema.get("required") or []) - set(schema["properties"])
                if extra_required:
                    problems.append(f"{name}: required 里有未声明的字段 {sorted(extra_required)}")
                if not (tool.get("description") or "").strip():
                    problems.append(f"{name}: 缺 description（模型全靠它选工具）")

            write_frames = run([{"jsonrpc": "2.0", "id": 3, "method": "tools/list"}], write=True)
            write_tools = ((write_frames[0].get("result") or {}).get("tools") if write_frames else None) or []
            if len(write_tools) <= len(read_tools):
                problems.append(f"打开 {tools.WRITE_ENV} 后写工具没出现（{len(read_tools)} → {len(write_tools)}）")

            # 未登录时的 whoami：要 isError，且给的是「去配置」
            who = run([{"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                        "params": {"name": "rathflow_whoami", "arguments": {}}}])
            payload = (who[0].get("result") or {}) if who else {}
            text = "".join(c.get("text", "") for c in payload.get("content") or [])
            if not payload.get("isError"):
                problems.append("未登录时 whoami 没有回 isError")
            if "rathflow auth login" not in text:
                problems.append("未登录时 whoami 没给出 `rathflow auth login` 的指引")

            # 协议层错误：未知工具 -32602、未知方法 -32601、坏帧 -32700、通知不响应
            cases = [
                ("未知工具", {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                              "params": {"name": "no_such_tool", "arguments": {}}}, -32602),
                ("未知方法", {"jsonrpc": "2.0", "id": 6, "method": "nope/nope"}, -32601),
                ("缺必填参数", {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                "params": {"name": "rathflow_memory_read", "arguments": {}}}, -32602),
                ("未知参数", {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                              "params": {"name": "rathflow_session_get",
                                         "arguments": {"session_id": "s", "nope": 1}}}, -32602),
            ]
            for label, message, want in cases:
                out = run([message])
                code = ((out[0].get("error") or {}) if out else {}).get("code")
                if code != want:
                    problems.append(f"{label}: 错误码 {code!r}，应为 {want}")
            bad = run([], raw='{"jsonrpc": "2.0", \n')
            code = ((bad[0].get("error") or {}) if bad else {}).get("code")
            if code != protocol.PARSE_ERROR:
                problems.append(f"坏帧未回 parse error：{code!r}")
            if run([{"jsonrpc": "2.0", "method": "notifications/initialized"}]):
                problems.append("通知消息不应产生响应")
    finally:
        for name, value in (
            ("RATHFLOW_CONFIG_DIR", saved_dir),
            ("RATHFLOW_TOKEN", saved_token),
            (tools.WRITE_ENV, saved_write),
        ):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    return problems



def _names(raw: str) -> set[str]:
    return set(re.findall(r'"([^"]+)"', raw))


def _check_proxy_env() -> list[str]:
    """socks:// 与 socks4:// 必须被改写成 httpx 认得的 socks5h://，其余原样。"""
    from . import http

    saved = {name: os.environ.get(name) for name in http._PROXY_VARS}
    problems: list[str] = []
    try:
        os.environ["ALL_PROXY"] = "socks://127.0.0.1:7897"
        os.environ["all_proxy"] = "socks4://127.0.0.1:7897"
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7897"
        http.normalize_proxy_env()
        if os.environ["ALL_PROXY"] != "socks5h://127.0.0.1:7897":
            problems.append(f"ALL_PROXY=socks:// 未归一化：{os.environ['ALL_PROXY']}")
        if os.environ["all_proxy"] != "socks5h://127.0.0.1:7897":
            problems.append(f"all_proxy=socks4:// 未归一化：{os.environ['all_proxy']}")
        if os.environ["HTTPS_PROXY"] != "http://127.0.0.1:7897":
            problems.append(f"http 代理被误改：{os.environ['HTTPS_PROXY']}")
        http.normalize_proxy_env()
        if os.environ["ALL_PROXY"] != "socks5h://127.0.0.1:7897":
            problems.append("归一化不是幂等的")
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    return problems


if __name__ == "__main__":
    raise SystemExit(main())
