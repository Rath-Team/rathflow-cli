"""轻量自检（不联服务端）：``python -m rathflow_cli.selftest``

查两件事，都是「装得上但会打错 URL」的那类毛病：

1. **命令实现里不写 URL 字面量** —— 所有请求必须走 ``endpoints.py`` 的端点 key；
2. **端点表与生成物一致** —— 生成物 ``endpoints.ts`` 由上游 proto 生成，本包的
   ``endpoints.py`` 手工同步；两者漂移就会打错 URL。生成物在本仓库中不存在
   （它是上游 monorepo 的产物），此时这一项跳过，可用环境变量
   ``RATHFLOW_ENDPOINTS_TS`` 指向它来启用比对。
"""

from __future__ import annotations

import re
import os
import sys
from pathlib import Path

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
    problems = generated_problems + _check_no_url_literals()
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


def _names(raw: str) -> set[str]:
    return set(re.findall(r'"([^"]+)"', raw))


if __name__ == "__main__":
    raise SystemExit(main())
