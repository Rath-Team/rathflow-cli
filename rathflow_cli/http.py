"""HTTP 层：JWT 登录/续期 + 错误信封 + 流式解码。

契约依据：
  - contracts/docs/error-envelope.md（错误信封与 HTTP 状态映射）
  - contracts/docs/streaming.md §三（读取端最小实现要求，逐条落实）
  - gateway/internal/gateway/cookiepost.go：「响应体 token 原样保留（SDK/CLI 走 Bearer）」
    → CLI 只读响应体，**不碰 cookie**；也因此天然豁免 CSRF 门。
"""

from __future__ import annotations

import json
import time
from typing import Iterator

import httpx

from . import endpoints
from .errors import ApiError, UsageError, from_response

# 普通调用：读超时给足（上游 gateway 默认 10s，orchestrator 30s）
_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
# 流式：读超时关闭（沙箱命令可能长时间无输出仍存活）
_STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)

# 到期前多久就主动刷新（秒）
_REFRESH_MARGIN = 60


class Client:
    """一次进程内的 API 客户端（令牌变更经 persist 回调落盘）。"""

    def __init__(
        self,
        base_url: str,
        *,
        project: str | None = None,
        access_token: str | None = None,
        refresh_token: str | None = None,
        expires_at: float = 0.0,
        persist=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.project = project or None
        self.access_token = access_token or None
        self.refresh_token = refresh_token or None
        self.expires_at = float(expires_at or 0)
        self._persist = persist
        # 客户端级超时取流式那份（read=None：沙箱里跑长命令时中途没输出也该活着）；
        # 普通调用在 _open 里逐次传 _TIMEOUT 盖掉它。
        self._http = httpx.Client(follow_redirects=False, timeout=_STREAM_TIMEOUT)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------------------------------------------------------------- 令牌

    def _absorb_tokens(self, payload: dict) -> None:
        """从 LoginResponse 吸收令牌。protojson 把 int64 编成 JSON 字符串。"""
        access = payload.get("accessToken") or payload.get("access_token")
        refresh = payload.get("refreshToken") or payload.get("refresh_token")
        if access:
            self.access_token = access
        if refresh:
            self.refresh_token = refresh
        ttl = payload.get("expiresInSeconds", payload.get("expires_in_seconds"))
        try:
            seconds = int(ttl) if ttl is not None else 0
        except (TypeError, ValueError):
            seconds = 0
        if seconds > 0:
            self.expires_at = time.time() + seconds - _REFRESH_MARGIN
        elif access:
            self.expires_at = time.time() + 15 * 60 - _REFRESH_MARGIN
        if self._persist:
            self._persist(self)

    def login(self, email: str, password: str) -> dict:
        payload = self._call_raw(
            "POST",
            endpoints.render_path("auth.Login", {}),
            body={"email": email, "password": password},
            allow_retry=False,
        )
        self._absorb_tokens(payload)
        return payload

    def logout(self) -> None:
        if self.access_token:
            try:
                self._call_raw("POST", endpoints.render_path("auth.Logout", {}), body={})
            except ApiError:
                pass  # 幂等：服务端不可达也清本地
        self.access_token = None
        self.refresh_token = None
        self.expires_at = 0.0
        if self._persist:
            self._persist(self)

    def refresh(self) -> bool:
        """用 refresh token 换新令牌。成功返回 True。refresh 会轮换 → 必须存回。"""
        if not self.refresh_token:
            return False
        try:
            payload = self._call_raw(
                "POST",
                endpoints.render_path("auth.Refresh", {}),
                body={"refreshToken": self.refresh_token},
                allow_retry=False,
            )
        except ApiError:
            return False
        self._absorb_tokens(payload)
        return True

    def ensure_token(self) -> None:
        """无令牌 → 报未登录；临期且有 refresh → 先刷新。"""
        if not self.access_token:
            raise UsageError("未登录：先跑 `rathflow auth login`")
        if self.refresh_token and self.expires_at and time.time() >= self.expires_at:
            self.refresh()

    # ---------------------------------------------------------------- 请求

    def _headers(self) -> dict:
        headers = {
            "Accept": "application/json",
            "User-Agent": "rathflow-cli/0.1.0",
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if self.project:
            # 作用域解析：路径 {project_id} 优先，其次本头（gateway/internal/resolve）
            headers["X-RathFlow-Project"] = self.project
        return headers

    def _send(self, method: str, path: str, *, params=None, body=None, streaming: bool = False):
        """带令牌发请求；401 → 刷新一次并重放。streaming 时响应未读体（调用方 close）。"""
        self.ensure_token()
        url = self.base_url + path
        for attempt in (0, 1):
            # 头必须每轮重建：401 重放前 refresh 会换掉 access_token，
            # 若沿用上一轮的 Authorization，重放仍带着旧令牌、必然再次 401。
            headers = self._headers()
            try:
                if streaming:
                    req = self._http.build_request(
                        method, url, headers=headers, params=params, json=body
                    )
                    resp = self._http.send(req, stream=True)
                else:
                    resp = self._http.request(
                        method, url, headers=headers, params=params, json=body, timeout=_TIMEOUT
                    )
            except httpx.HTTPError as exc:
                raise ApiError(0, "UNAVAILABLE", f"无法连接 {self.base_url}：{exc}") from None
            if resp.status_code == 401 and attempt == 0 and self.refresh():
                resp.close()
                continue
            return resp
        return resp  # pragma: no cover — 循环必返回

    def _send_unauthed(self, method: str, path: str, *, params=None, body=None):
        """免登录端点：不发令牌、不做 401 重放（否则登录/注册会自我递归）。"""
        try:
            return self._http.request(
                method,
                self.base_url + path,
                headers=self._headers(),
                params=params,
                json=body,
                timeout=_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise ApiError(0, "UNAVAILABLE", f"无法连接 {self.base_url}：{exc}") from None

    def _call_raw(
        self, method: str, path: str, *, params=None, body=None, allow_retry: bool = True
    ) -> dict:
        """非流式调用：返回解码后的 JSON（空体 → {}）。"""
        if allow_retry:
            resp = self._send(method, path, params=params, body=body)
        else:
            resp = self._send_unauthed(method, path, params=params, body=body)
        try:
            raw = resp.read()
            payload = _decode(raw) if raw else {}
            if resp.status_code >= 400:
                raise from_response(resp.status_code, payload)
            return payload
        finally:
            resp.close()

    def call(
        self,
        key: str | None = None,
        *,
        method: str | None = None,
        path: str | None = None,
        body: dict | None = None,
        query: dict | None = None,
        path_params: dict | None = None,
        auth: bool = True,
    ) -> dict:
        """按端点 key（或显式 method/path）调用一次，返回响应 JSON。

        auth=False 用于免登录端点（register / 公开读），不要求也不刷新令牌。
        """
        method, path = _resolve(key, method, path, path_params)
        return self._call_raw(
            method, path, params=_clean(query), body=body, allow_retry=auth
        )

    def stream(
        self,
        key: str | None = None,
        *,
        method: str | None = None,
        path: str | None = None,
        body: dict | None = None,
        query: dict | None = None,
        path_params: dict | None = None,
    ) -> Iterator[dict]:
        """流式调用：逐帧产出 `result` payload。

        读取端纪律（streaming.md §三）：按行切帧；只认 result/error 两键；
        未知键拒绝该帧；error 帧即流终结并按信封报错。
        """
        method, path = _resolve(key, method, path, path_params)
        resp = self._send(method, path, params=_clean(query), body=body, streaming=True)
        # 流式只认 GET/POST（其余方法本就不出流）；此处不额外校验，交给服务端
        try:
            if resp.status_code >= 400:
                payload = _decode(resp.read())
                raise from_response(resp.status_code, payload)
            for line in resp.iter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    frame = json.loads(line)
                except json.JSONDecodeError:
                    raise ApiError(
                        resp.status_code, "UNKNOWN", "流中断：收到非 JSON 帧"
                    ) from None
                if not isinstance(frame, dict):
                    raise ApiError(resp.status_code, "UNKNOWN", "流中断：帧不是对象")
                if set(frame) == {"result"}:
                    yield frame["result"]
                elif set(frame) == {"error"}:
                    raise from_response(resp.status_code, frame)
                else:
                    raise ApiError(
                        resp.status_code,
                        "UNKNOWN",
                        f"流帧含未知键 {sorted(frame)}（前后端契约漂移，拒绝该帧）",
                    )
        finally:
            resp.close()


def _resolve(key, method, path, path_params) -> tuple[str, str]:
    if key:
        params = dict(path_params or {})
        return endpoints.method_of(key), endpoints.render_path(key, params)
    if not (method and path):
        raise UsageError("需要端点 key，或显式 --method/--path")
    return method.upper(), path


def _clean(query: dict | None) -> dict | None:
    """去掉 None 值；int64 类查询参数转字符串（protojson 惯例）。"""
    if not query:
        return None
    out = {}
    for k, v in query.items():
        if v is None:
            continue
        out[k] = str(v).lower() if isinstance(v, bool) else v
    return out or None


def _decode(raw: bytes) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {"data": data}
