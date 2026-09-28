"""MCP 工具面：把 endpoints.py 的端点表收敛成**任务型**工具。

设计取舍（与 CLI 自带的 `rathflow api` 逃生舱同源）：

- **不做 111 个工具**。逐一映射会让模型在长清单里挑错，也吃满上下文。这里只做
  十几个任务型工具（含聚合），其余端点走 `rathflow_api_call` 逃生舱。
- **写操作默认关闭**，需 `RATHFLOW_MCP_WRITE=1`；关闭时写工具连 `tools/list` 都不出现。
- **鉴权沿用 CLI**：同一份 `~/.config/rathflow/config.json`（或 `RATHFLOW_TOKEN`），
  令牌续期由 `http.Client` 负责。未登录时**只提示用户去配置**，不做任何本地部署尝试。
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from .. import endpoints
from ..errors import ApiError, UsageError
from ..mcp.protocol import INVALID_PARAMS, RpcError
from ..state import State

# 写操作总开关。MCP 客户端的提示词可能被第三方内容牵着走，默认不给写权限。
WRITE_ENV = "RATHFLOW_MCP_WRITE"

# 未认证时的唯一正确动作：让用户去配。**不要**引导模型去找源码或本地部署 ——
# CLI 是已发布的包，装一次就有；本地起 Gateway 既无必要也会把用户环境搞乱。
AUTH_HINT = (
    "RathFlow 还没有可用的登录凭据。请让用户在他自己的终端里执行：\n"
    "  rathflow auth login -e <登录邮箱>\n"
    "（或在 MCP 服务端的环境变量里给 RATHFLOW_TOKEN。）完成后重试本工具。\n"
    "RathFlow CLI 是已发布的包，用包管理器安装即可："
    "`uv tool install rathflow-cli` 或 `npm install -g rathflow-cli`。"
    "不要克隆 RathFlow 源码、不要本地部署、不要自己启动 Gateway。"
)

WRITE_HINT = (
    f"写操作当前未启用（环境变量 {WRITE_ENV} 未开），这是刻意的默认值。"
    f"确需写权限时，让用户把 MCP 服务端的环境变量 {WRITE_ENV}=1 打开，然后重开客户端会话。"
)


class ToolError(Exception):
    """工具执行失败 → ``CallToolResult.isError=true``（不是 JSON-RPC error）。"""


@dataclass
class ToolContext:
    state: State
    write_enabled: bool = False


@dataclass
class ToolResult:
    text: str
    data: Any = None
    #: 置真 → CallToolResult.isError。工具自己也能报错（例如 whoami 探到未登录），
    #: 这样既给模型「这步失败了」的强信号，又保留结构化数据。
    is_error: bool = False


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    input_schema: dict
    run: Callable[[ToolContext, dict], ToolResult]
    write: bool = False
    destructive: bool = False

    def annotations(self) -> dict:
        return {
            "title": self.title,
            "readOnlyHint": not self.write,
            "destructiveHint": self.destructive,
            "idempotentHint": not self.write,
            "openWorldHint": True,
        }


# ------------------------------------------------------------------ schema 工具


def _schema(props: dict, required: list[str] | None = None) -> dict:
    schema: dict = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


def _str(desc: str, **extra: Any) -> dict:
    return {"type": "string", "description": desc, **extra}


def _int(desc: str, **extra: Any) -> dict:
    return {"type": "integer", "description": desc, **extra}


def _bool(desc: str) -> dict:
    return {"type": "boolean", "description": desc}


def _obj(desc: str, *, free: bool = False) -> dict:
    schema: dict = {"type": "object", "description": desc}
    schema["additionalProperties"] = True if free else {"type": "string"}
    return schema


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


PAGE_PROPS = {
    "page_size": _int("返回条数上限"),
    "page_token": _str("翻页游标：把上一页返回的 nextPageToken 原样传回"),
}


# ------------------------------------------------------------------ 调用辅助


def _has_token(ctx: ToolContext) -> bool:
    if ctx.state.token_override:
        return True
    return bool(ctx.state.profile.get("access_token"))


def _invoke(ctx: ToolContext, thunk: Callable[[], Any]) -> Any:
    """执行一次请求，把「未登录 / 401 / 403 / 其它」翻译成对模型有指导性的错误。

    这里刻意不重试、不改网关地址：凭据问题只有一个正确解法 —— 让用户去配置。
    """
    if not _has_token(ctx):
        raise ToolError(AUTH_HINT)
    try:
        return thunk()
    except UsageError as exc:
        raise ToolError(str(exc)) from None
    except ApiError as exc:
        if exc.status == 401:
            raise ToolError(f"令牌被服务端拒绝（401）。\n\n{AUTH_HINT}\n\n原始错误：{exc}") from None
        if exc.status == 403:
            raise ToolError(
                f"当前账号或令牌没有这个权限（403）：{exc}\n"
                "这多半是账号角色问题，不是配置问题 —— 不要改代码、不要换网关地址。"
            ) from None
        raise ToolError(f"RathFlow 接口报错：{exc}") from None


def _call(ctx: ToolContext, key: str | None = None, **kwargs: Any) -> dict:
    """调一个端点（key 或显式 method/path）。"""
    return _invoke(ctx, lambda: ctx.state.client().call(key, **kwargs))


def _page(args: dict, *, default: int | None = None, extra: dict | None = None) -> dict:
    query = {k: v for k, v in (extra or {}).items() if v not in (None, "")}
    size = args.get("page_size") or default
    if size:
        query["page_size"] = size
    if args.get("page_token"):
        query["page_token"] = args["page_token"]
    return query


def _text_of(value: Any) -> str:
    """解 protojson 的 bytes（base64）为文本；解不开就当纯文本透传。"""
    if not value:
        return ""
    if isinstance(value, bytes):
        raw = value
    else:
        try:
            raw = base64.b64decode(str(value), validate=True)
        except Exception:
            return str(value)
    return raw.decode("utf-8", "replace")


def _stream_collect(
    ctx: ToolContext,
    *,
    key: str | None = None,
    method: str | None = None,
    path: str | None = None,
    path_params: dict | None = None,
    query: dict | None = None,
    body: dict | None = None,
    limit: int = 200,
) -> tuple[list, bool]:
    """抽干一条流，最多 limit 帧（超出即断开并标记 truncated）。"""
    frames: list = []
    truncated = False

    def _pump() -> None:
        nonlocal truncated
        stream = ctx.state.client().stream(
            key=key,
            method=method,
            path=path,
            path_params=path_params,
            query=query,
            body=body,
        )
        for frame in stream:
            if len(frames) >= limit:
                truncated = True
                break
            frames.append(frame)

    _invoke(ctx, _pump)
    return frames, truncated


# ------------------------------------------------------------------ 只读工具


def _t_whoami(ctx: ToolContext, args: dict) -> ToolResult:
    """身份探针：未登录也能调，用来判断"要不要让用户先登录"。"""
    state = ctx.state
    profile_user = state.profile.get("user") or {}
    if not _has_token(ctx):
        data = {"authenticated": False, "baseUrl": state.base_url, "profile": state.profile_name}
        return ToolResult(text="尚未登录。\n\n" + AUTH_HINT, data=data, is_error=True)
    payload = _call(ctx, "tenant.ListProjects", query={"page_size": 50})
    projects = payload.get("projects") or []
    lines = [
        f"网关地址  {state.base_url}",
        f"配置档    {state.profile_name}",
    ]
    if profile_user.get("email"):
        lines.append(f"用户      {profile_user['email']}")
    if profile_user.get("user_id"):
        lines.append(f"用户 id   {profile_user['user_id']}")
    lines.append(f"平台管理员 {'是' if profile_user.get('is_platform_admin') else '否'}")
    lines.append(f"当前项目  {state.project or '(未设置：让用户跑 rathflow project use <project_id>)'}")
    if projects:
        lines.append("")
        lines.append("可访问项目：")
        lines.extend(f"  {p.get('projectId')}  {p.get('name')}" for p in projects)
    data = {
        "authenticated": True,
        "baseUrl": state.base_url,
        "profile": state.profile_name,
        "user": profile_user,
        "project": state.project,
        "projects": projects,
    }
    return ToolResult(text="\n".join(lines), data=data)


def _t_project_list(ctx: ToolContext, args: dict) -> ToolResult:
    payload = _call(ctx, "tenant.ListProjects", query=_page(args, default=50))
    projects = payload.get("projects") or []
    data = {"projects": projects, "nextPageToken": payload.get("nextPageToken")}
    return ToolResult(text=_json(data), data=data)


def _t_session_list(ctx: ToolContext, args: dict) -> ToolResult:
    query = _page(args, default=20, extra={"status": args.get("status")})
    payload = _call(ctx, "session.ListSessions", query=query)
    data = {"sessions": payload.get("sessions") or [], "nextPageToken": payload.get("nextPageToken")}
    return ToolResult(text=_json(data), data=data)


def _t_session_get(ctx: ToolContext, args: dict) -> ToolResult:
    payload = _call(ctx, "session.GetSession", path_params={"session_id": args["session_id"]})
    return ToolResult(text=_json(payload), data=payload)


def _t_session_context(ctx: ToolContext, args: dict) -> ToolResult:
    """一次拿齐「会话 + 区块 + 记忆索引」，省掉模型来回三轮。"""
    session_id = args["session_id"]
    session = _call(ctx, "session.GetSession", path_params={"session_id": session_id})
    blocks = _call(
        ctx,
        "session.ListBlocks",
        path_params={"session_id": session_id},
        query={"page_size": int(args.get("block_limit") or 50)},
    )
    memory = _call(
        ctx,
        "memory.List",
        query={
            "prefix": args.get("memory_prefix") or "memories",
            "recursive": True,
            "page_size": int(args.get("memory_limit") or 100),
        },
    )
    data = {
        "session": session,
        "blocks": blocks.get("blocks") or [],
        "memory": memory.get("entries") or [],
    }
    return ToolResult(text=_json(data), data=data)


def _t_memory_list(ctx: ToolContext, args: dict) -> ToolResult:
    query = _page(args, default=100, extra={"prefix": args.get("prefix") or "memories"})
    query["recursive"] = bool(args.get("recursive", True))
    payload = _call(ctx, "memory.List", query=query)
    data = {"entries": payload.get("entries") or [], "nextPageToken": payload.get("nextPageToken")}
    return ToolResult(text=_json(data), data=data)


def _t_memory_read(ctx: ToolContext, args: dict) -> ToolResult:
    query = {"level": args.get("level")} if args.get("level") else None
    payload = _call(
        ctx, "memory.Read", path_params={"memory_path": args["memory_path"]}, query=query
    )
    content = _text_of(payload.get("content"))
    data = {"memoryPath": args["memory_path"], "content": content}
    if payload.get("contentType"):
        data["contentType"] = payload["contentType"]
    return ToolResult(text=content if content else _json(payload), data=data)


def _t_memory_search(ctx: ToolContext, args: dict) -> ToolResult:
    body: dict = {"query": args["query"]}
    for src, dst in (("top_k", "topK"), ("min_score", "minScore"), ("scope", "scope"), ("mode", "mode")):
        if args.get(src) is not None:
            body[dst] = args[src]
    limit = int(args.get("limit") or 50)
    hits, truncated = _stream_collect(ctx, key="memory.Search", body=body, limit=limit)
    data = {"hits": hits, "truncated": truncated}
    return ToolResult(text=_json(data), data=data)


def _t_sandbox_list(ctx: ToolContext, args: dict) -> ToolResult:
    payload = _call(ctx, "sandbox.List", query=_page(args, default=50))
    data = {"sandboxes": payload.get("sandboxes") or [], "nextPageToken": payload.get("nextPageToken")}
    return ToolResult(text=_json(data), data=data)


def _t_sandbox_read_file(ctx: ToolContext, args: dict) -> ToolResult:
    path = args["path"]
    chunks, truncated = _stream_collect(
        ctx,
        key="sandbox.ReadFile",
        path_params={"sandbox_id": args["sandbox_id"], "path": path},
        limit=int(args.get("limit") or 2000),
    )
    content = "".join(_text_of(chunk.get("data")) for chunk in chunks)
    data = {"path": path, "content": content, "truncated": truncated}
    return ToolResult(text=content if content else "(空文件)", data=data)


def _t_workflow_list(ctx: ToolContext, args: dict) -> ToolResult:
    payload = _call(ctx, "workflow.ListWorkflows", query=_page(args, default=50))
    data = {"workflows": payload.get("workflows") or [], "nextPageToken": payload.get("nextPageToken")}
    return ToolResult(text=_json(data), data=data)


def _t_usage(ctx: ToolContext, args: dict) -> ToolResult:
    query = {
        "project_id": args.get("project_id") or ctx.state.project,
        "start_time": args.get("start_time"),
        "end_time": args.get("end_time"),
        "metrics": args.get("metrics"),
    }
    payload = _call(ctx, "billing.GetUsage", query=query)
    data = {
        "usages": payload.get("usages") or [],
        "projectId": query["project_id"],
        "period": {"start": query["start_time"], "end": query["end_time"]},
    }
    return ToolResult(text=_json(data), data=data)


def _t_endpoints(ctx: ToolContext, args: dict) -> ToolResult:
    """端点表发现：喂给 rathflow_api_call 的 key 从这里查。"""
    needle = (args.get("filter") or "").lower()
    rows = []
    for key, (method, path) in sorted(endpoints.ENDPOINTS.items()):
        if needle and needle not in key.lower() and needle not in path.lower():
            continue
        rows.append(
            {
                "key": key,
                "method": method,
                "path": path,
                "stream": endpoints.is_streaming(key),
                "write": method != "GET",
            }
        )
    data = {"count": len(rows), "endpoints": rows}
    return ToolResult(text=_json(rows), data=data)


def _t_api_call(ctx: ToolContext, args: dict) -> ToolResult:
    """逃生舱：端点表里没做成具名工具的调用走这里（等价 `rathflow api <Key>`）。"""
    key = args.get("key")
    if key:
        if key not in endpoints.ENDPOINTS:
            raise ToolError(f"未知端点 key {key!r}。用 rathflow_endpoints 列出全部 key。")
        method = endpoints.method_of(key)
        is_stream = endpoints.is_streaming(key)
        target: dict = {"key": key}
    else:
        method = (args.get("method") or "").upper()
        path = args.get("path")
        if not (method and path):
            raise ToolError("要么给 key，要么同时给 method 与 path。")
        if not str(path).startswith("/"):
            raise ToolError("path 必须是以 / 开头的绝对路径（网关会把相对路径打到别处）。")
        is_stream = bool(args.get("stream"))
        target = {"key": None, "method": method, "path": path}

    if method != "GET" and not ctx.write_enabled:
        raise ToolError(WRITE_HINT)

    query = dict(args.get("query") or {})
    if args.get("page_size"):
        query["page_size"] = args["page_size"]
    if args.get("page_token"):
        query["page_token"] = args["page_token"]
    path_params = args.get("path_params") or {}
    body = args.get("body")

    if is_stream:
        frames, truncated = _stream_collect(
            ctx,
            **target,
            path_params=path_params,
            query=query or None,
            body=body,
            limit=int(args.get("limit") or 200),
        )
        data = {"key": key, "frames": frames, "truncated": truncated}
        return ToolResult(text=_json(data), data=data)

    payload = _call(ctx, **target, path_params=path_params, query=query or None, body=body)
    return ToolResult(text=_json(payload), data={"key": key, "response": payload})


def _t_session_create(ctx: ToolContext, args: dict) -> ToolResult:
    body = dict(args.get("body") or {})
    if args.get("title"):
        body.setdefault("title", args["title"])
    payload = _call(ctx, "session.CreateSession", body=body)
    session_id = payload.get("sessionId") or ""
    return ToolResult(text=f"已创建会话 {session_id}", data=payload)


def _t_session_archive(ctx: ToolContext, args: dict) -> ToolResult:
    payload = _call(ctx, "session.ArchiveSession", path_params={"session_id": args["session_id"]})
    return ToolResult(text=f"已归档会话 {args['session_id']}", data=payload)


def _t_memory_write(ctx: ToolContext, args: dict) -> ToolResult:
    content = args.get("content")
    if not isinstance(content, str):
        raise ToolError("content 必须是字符串。")
    body: dict = {"content": base64.b64encode(content.encode("utf-8")).decode()}
    if args.get("content_type"):
        body["contentType"] = args["content_type"]
    if args.get("ttl_seconds") is not None:
        body["ttlSeconds"] = args["ttl_seconds"]
    payload = _call(ctx, "memory.Write", path_params={"memory_path": args["memory_path"]}, body=body)
    written = payload.get("bytesWritten", len(content.encode("utf-8")))
    data = {"memoryPath": args["memory_path"], "bytesWritten": written}
    return ToolResult(text=f"已写入 {args['memory_path']}（{written} 字节）", data=data)


def _t_sandbox_create(ctx: ToolContext, args: dict) -> ToolResult:
    body = dict(args.get("body") or {})
    if args.get("name"):
        body.setdefault("name", args["name"])
    payload = _call(ctx, "sandbox.Create", body=body)
    sandbox_id = payload.get("sandboxId") or ""
    return ToolResult(text=f"已创建沙箱 {sandbox_id}", data=payload)


def _t_sandbox_run(ctx: ToolContext, args: dict) -> ToolResult:
    """在沙箱里跑命令：流式抽干后一次性返回 stdout/stderr 与退出码。

    没做 `notifications/progress`（客户端对进度支持参差）；改为墙钟上限，
    超时就断开并标记 truncated —— 至少不会把 MCP 会话挂死。
    """
    body: dict = {"command": args["command"]}
    if args.get("workdir"):
        body["workdir"] = args["workdir"]
    if args.get("env"):
        body["env"] = dict(args["env"])
    deadline = time.monotonic() + int(args.get("timeout_seconds") or 120)

    stdout: list[str] = []
    stderr: list[str] = []
    exit_code: int | None = None
    truncated = False
    for chunk in _iter_stream(
        ctx, key="sandbox.RunCommand", path_params={"sandbox_id": args["sandbox_id"]}, body=body
    ):
        stdout.append(_text_of(chunk.get("stdout")))
        stderr.append(_text_of(chunk.get("stderr")))
        if chunk.get("errorCode"):
            raise ToolError(
                f"沙箱执行失败：{chunk.get('errorCode')} {chunk.get('errorMessage') or ''}".strip()
            )
        if chunk.get("truncated"):
            truncated = True
        if chunk.get("exitCode") is not None:
            exit_code = int(chunk["exitCode"])
        if time.monotonic() > deadline:
            truncated = True
            break

    data = {
        "exitCode": exit_code,
        "stdout": "".join(stdout),
        "stderr": "".join(stderr),
        "truncated": truncated,
    }
    head = f"退出码 {exit_code}" if exit_code is not None else "未收到退出码（可能被超时截断）"
    if truncated:
        head += "；输出被截断"
    text = f"{head}\n\n--- stdout ---\n{data['stdout']}"
    if data["stderr"]:
        text += f"\n--- stderr ---\n{data['stderr']}"
    return ToolResult(text=text, data=data)


def _iter_stream(ctx: ToolContext, *, key: str, path_params: dict, body: dict):
    """沙箱执行流：逐帧产出（与 _stream_collect 的区别是不设帧数上限）。"""
    if not _has_token(ctx):
        raise ToolError(AUTH_HINT)
    try:
        yield from ctx.state.client().stream(key, path_params=path_params, body=body)
    except UsageError as exc:
        raise ToolError(str(exc)) from None
    except ApiError as exc:
        raise ToolError(f"RathFlow 流式接口报错：{exc}") from None


# ------------------------------------------------------------------ 工具表


TOOLS: tuple[Tool, ...] = (
    Tool(
        name="rathflow_whoami",
        title="RathFlow 登录状态",
        description=(
            "查当前 RathFlow 登录状态、网关地址、当前项目与可访问项目。未登录时返回"
            "「让用户去 rathflow auth login」的指引 —— 排查 MCP 配置问题先调这个。"
        ),
        input_schema=_schema({}),
        run=_t_whoami,
    ),
    Tool(
        name="rathflow_project_list",
        title="列出 RathFlow 项目",
        description="列出当前账号可访问的项目（projectId / 名称）。",
        input_schema=_schema(dict(PAGE_PROPS)),
        run=_t_project_list,
    ),
    Tool(
        name="rathflow_session_list",
        title="列出会话",
        description="列出当前项目下的会话，可按状态过滤。",
        input_schema=_schema(
            {**PAGE_PROPS, "status": _str("按状态过滤，如 active / archived")}
        ),
        run=_t_session_list,
    ),
    Tool(
        name="rathflow_session_get",
        title="会话详情",
        description="按 session_id 取单个会话的元信息。",
        input_schema=_schema({"session_id": _str("会话 id")}, ["session_id"]),
        run=_t_session_get,
    ),
    Tool(
        name="rathflow_session_context",
        title="会话上下文（聚合）",
        description=(
            "一次返回「会话 + 区块列表 + 记忆索引」。比分别调三个工具省往返，"
            "适合让模型先摸清一个会话的全貌。"
        ),
        input_schema=_schema(
            {
                "session_id": _str("会话 id"),
                "block_limit": _int("区块条数上限，默认 50"),
                "memory_limit": _int("记忆条数上限，默认 100"),
                "memory_prefix": _str("记忆前缀，默认 memories"),
            },
            ["session_id"],
        ),
        run=_t_session_context,
    ),
    Tool(
        name="rathflow_memory_list",
        title="列记忆条目",
        description="按前缀列记忆/资源条目（memoryPath、大小、更新时间）。",
        input_schema=_schema(
            {
                **PAGE_PROPS,
                "prefix": _str("路径前缀，如 memories 或 memories/notes，默认 memories"),
                "recursive": _bool("是否递归，默认 true"),
            }
        ),
        run=_t_memory_list,
    ),
    Tool(
        name="rathflow_memory_read",
        title="读记忆内容",
        description="按 memory_path 读记忆正文（首段须是 memories 或 resources）。",
        input_schema=_schema(
            {"memory_path": _str("记忆路径，如 memories/notes/a.md"), "level": _str("读层级，如 L0/L1")},
            ["memory_path"],
        ),
        run=_t_memory_read,
    ),
    Tool(
        name="rathflow_memory_search",
        title="语义检索记忆",
        description="对记忆库做语义检索，返回命中路径、得分与片段。",
        input_schema=_schema(
            {
                "query": _str("检索词"),
                "top_k": _int("返回条数"),
                "min_score": {"type": "number", "description": "最低得分"},
                "scope": _str("限定路径前缀"),
                "mode": _str("检索模式枚举"),
                "limit": _int("本地最多收集多少帧，默认 50"),
            },
            ["query"],
        ),
        run=_t_memory_search,
    ),
    Tool(
        name="rathflow_sandbox_list",
        title="列沙箱",
        description="列出当前项目的沙箱（含已终止）。",
        input_schema=_schema(dict(PAGE_PROPS)),
        run=_t_sandbox_list,
    ),
    Tool(
        name="rathflow_sandbox_read_file",
        title="读沙箱文件",
        description="读沙箱内的文件内容（文本）。",
        input_schema=_schema(
            {
                "sandbox_id": _str("沙箱 id"),
                "path": _str("沙箱内相对路径"),
                "limit": _int("最多收多少帧，默认 2000"),
            },
            ["sandbox_id", "path"],
        ),
        run=_t_sandbox_read_file,
    ),
    Tool(
        name="rathflow_workflow_list",
        title="列工作流",
        description="列出当前项目的工作流定义。",
        input_schema=_schema(dict(PAGE_PROPS)),
        run=_t_workflow_list,
    ),
    Tool(
        name="rathflow_usage",
        title="用量汇总",
        description="按项目取用量汇总（配合时间区间与指标名）。",
        input_schema=_schema(
            {
                "project_id": _str("缺省用当前作用域项目"),
                "start_time": _str("起始时间 RFC3339"),
                "end_time": _str("结束时间 RFC3339"),
                "metrics": _str("逗号分隔的指标名"),
            }
        ),
        run=_t_usage,
    ),
    Tool(
        name="rathflow_endpoints",
        title="列 REST 端点表",
        description=(
            "列出 CLI 覆盖的全部 REST 端点 key（111 个）、方法、路径与是否流式。"
            "配合 rathflow_api_call 使用；建议先用 filter 缩小范围。"
        ),
        input_schema=_schema({"filter": _str("子串过滤：匹配 key 或路径")}),
        run=_t_endpoints,
    ),
    Tool(
        name="rathflow_api_call",
        title="任意端点调用（逃生舱）",
        description=(
            "调用端点表里的任意 key（等价 `rathflow api <Key>`），覆盖具名工具没做的端点。"
            "key 从 rathflow_endpoints 查；非 GET 端点需要写权限。"
        ),
        input_schema=_schema(
            {
                "key": _str("端点 key，如 memory.Tree"),
                "method": _str("不给 key 时用：HTTP 方法"),
                "path": _str("不给 key 时用：路径（须以 / 开头）"),
                "stream": _bool("不给 key 时用：是否按流式读"),
                "path_params": _obj("路径占位符，如 {\"session_id\": \"abc\"}"),
                "query": _obj("查询参数"),
                "body": _obj("请求体 JSON 对象", free=True),
                "page_size": _int("快捷查询参数 page_size"),
                "page_token": _str("快捷查询参数 page_token"),
                "limit": _int("流式最多收集多少帧，默认 200"),
            }
        ),
        run=_t_api_call,
        destructive=True,
    ),
    # ---- 写工具：默认不注册，需 RATHFLOW_MCP_WRITE=1 ----
    Tool(
        name="rathflow_session_create",
        title="创建会话",
        description="新建一个会话；title 可省，其余字段用 body 传。",
        input_schema=_schema(
            {"title": _str("会话标题"), "body": _obj("完整请求体（透传给 CreateSession）", free=True)}
        ),
        run=_t_session_create,
        write=True,
    ),
    Tool(
        name="rathflow_session_archive",
        title="归档会话",
        description="归档一个会话（不删除内容）。",
        input_schema=_schema({"session_id": _str("会话 id")}, ["session_id"]),
        run=_t_session_archive,
        write=True,
    ),
    Tool(
        name="rathflow_memory_write",
        title="写记忆",
        description="把文本写入记忆库（CLI 负责 base64 编码）。",
        input_schema=_schema(
            {
                "memory_path": _str("记忆路径，如 memories/notes/a.md"),
                "content": _str("正文（UTF-8 文本）"),
                "content_type": _str("如 text/markdown"),
                "ttl_seconds": _int("存活秒数"),
            },
            ["memory_path", "content"],
        ),
        run=_t_memory_write,
        write=True,
    ),
    Tool(
        name="rathflow_sandbox_create",
        title="创建沙箱",
        description="新建一个沙箱；隔离级别等字段用 body 传。",
        input_schema=_schema(
            {"name": _str("沙箱名"), "body": _obj("完整请求体（透传给 Create）", free=True)}
        ),
        run=_t_sandbox_create,
        write=True,
        destructive=True,
    ),
    Tool(
        name="rathflow_sandbox_run",
        title="在沙箱里执行命令",
        description=(
            "在指定沙箱里跑一条命令，返回退出码与 stdout/stderr。有真实副作用（计费），"
            "默认墙钟上限 120 秒。"
        ),
        input_schema=_schema(
            {
                "sandbox_id": _str("沙箱 id"),
                "command": _str("要执行的命令（经 shell 解释）"),
                "workdir": _str("工作目录"),
                "env": _obj("环境变量 k=v"),
                "timeout_seconds": _int("墙钟上限秒数，默认 120"),
            },
            ["sandbox_id", "command"],
        ),
        run=_t_sandbox_run,
        write=True,
        destructive=True,
    ),
)

_BY_NAME = {tool.name: tool for tool in TOOLS}


def write_enabled(env: Any = None) -> bool:
    """写开关：RATHFLOW_MCP_WRITE 为非空且非 0/false/no 即视为开。"""
    import os

    raw = (env if env is not None else os.environ.get(WRITE_ENV)) or ""
    return str(raw).strip().lower() not in ("", "0", "false", "no", "off")


def list_tools(ctx: ToolContext) -> list[Tool]:
    """写权限没开时，写工具连列都不列（客户端就不会去调）。"""
    if ctx.write_enabled:
        return list(TOOLS)
    return [tool for tool in TOOLS if not tool.write]


def _validate(tool: Tool, args: Any) -> dict:
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise RpcError(INVALID_PARAMS, f"{tool.name}: arguments 必须是 JSON 对象")
    props = tool.input_schema.get("properties") or {}
    unknown = sorted(set(args) - set(props))
    if unknown:
        raise RpcError(INVALID_PARAMS, f"{tool.name}: 未知参数 {unknown}")
    missing = [k for k in tool.input_schema.get("required", []) if args.get(k) in (None, "")]
    if missing:
        raise RpcError(INVALID_PARAMS, f"{tool.name}: 缺必填参数 {missing}")
    return args


def get_tool(name: Any) -> Tool:
    tool = _BY_NAME.get(name) if isinstance(name, str) else None
    if tool is None:
        raise RpcError(INVALID_PARAMS, f"未知工具 {name!r}。可用工具见 tools/list。")
    return tool


def call_tool(ctx: ToolContext, name: Any, args: Any) -> ToolResult:
    """执行工具，返回 ToolResult（``is_error`` 决定客户端看到的是成功还是失败）。

    协议层错误（未知工具、参数不合法、未开写权限）直接抛 ``RpcError``；
    执行期失败（未登录、接口报错、工具自报）走 isError —— 让模型看得到并自行纠正。
    """
    tool = get_tool(name)
    if tool.write and not ctx.write_enabled:
        raise RpcError(INVALID_PARAMS, f"{tool.name} 未启用。{WRITE_HINT}")
    checked = _validate(tool, args)
    try:
        return tool.run(ctx, checked)
    except ToolError as exc:
        return ToolResult(text=str(exc), is_error=True)
