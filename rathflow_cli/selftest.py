"""轻量自检（不联服务端）：``python -m rathflow_cli.selftest``

查三件事，都是「装得上但会打错 URL」的那类毛病：

1. **命令实现里不写 URL 字面量** —— 所有请求必须走 ``endpoints.py`` 的端点 key；
2. **端点表与生成物一致** —— 生成物 ``endpoints.ts`` 由上游 proto 生成，本包的
   ``endpoints.py`` 手工同步；两者漂移就会打错 URL。生成物在本仓库中不存在
   （它是上游 monorepo 的产物），此时这一项跳过，可用环境变量
   ``RATHFLOW_ENDPOINTS_TS`` 指向它来启用比对。
3. **多段路径参数拦住点段** —— ``..`` 会被 HTTP 客户端按 URL 语义归一化，
   把请求打到别的端点上（还会绕过命令自己的域检查）。
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




def _names(raw: str) -> set[str]:
    return set(re.findall(r'"([^"]+)"', raw))


if __name__ == "__main__":
    raise SystemExit(main())
