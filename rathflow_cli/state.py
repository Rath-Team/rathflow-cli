"""进程内状态：合并「flag > 环境变量 > profile > 默认」并承载惰性 Client。"""

from __future__ import annotations

from . import config
from .http import Client


class State:
    def __init__(
        self,
        *,
        profile_name: str | None = None,
        base_url: str | None = None,
        project: str | None = None,
        json_out: bool = False,
        quiet: bool = False,
    ):
        self.data = config.load()
        self.json_out = json_out
        self.quiet = quiet
        self._client: Client | None = None
        self._flags = {"base_url": base_url, "project": project}
        self.apply(profile_name=profile_name)
        self.token_override = _env(config.ENV_TOKEN)

    def apply(
        self,
        *,
        profile_name: str | None = None,
        base_url: str | None = None,
        project: str | None = None,
        json_out: bool = False,
        quiet: bool = False,
    ) -> None:
        """合并一级选项。根回调先跑；子应用回调再跑一次（命令后写的选项）。

        子应用层的显式选项优先；「优先级」仍是 flag > env > profile > 默认。
        """
        if profile_name:
            self.data["current"] = profile_name
        if base_url:
            self._flags["base_url"] = base_url
        if project:
            self._flags["project"] = project
        self.json_out = self.json_out or json_out
        self.quiet = self.quiet or quiet

        prof = self.profile
        # 原始环境变量值：只用于如实展示「环境变量到底设没设」，不参与合并，
        # 否则 config show 会把生效值当成环境变量回显，让人误以为有 env 覆盖。
        self.env_base_url = _env(config.ENV_BASE_URL)
        self.env_project = _env(config.ENV_PROJECT)
        self.base_url = (
            self._flags.get("base_url")
            or self.env_base_url
            or prof.get("base_url")
            or config.DEFAULT_BASE_URL
        )
        self.project = self._flags.get("project") or self.env_project or prof.get("project")

    @property
    def profile_name(self) -> str:
        return self.data["current"]

    @property
    def profile(self) -> dict:
        return config.profile(self.data, self.profile_name)

    def client(self) -> Client:
        if self._client is None:
            prof = self.profile
            if self.token_override:
                # CI 场景：直接用环境变量令牌，不落盘、不刷新
                self._client = Client(
                    self.base_url, project=self.project, access_token=self.token_override
                )
            else:
                self._client = Client(
                    self.base_url,
                    project=self.project,
                    access_token=prof.get("access_token"),
                    refresh_token=prof.get("refresh_token"),
                    expires_at=prof.get("expires_at", 0),
                    persist=self._persist,
                )
        return self._client

    def _persist(self, client: Client) -> None:
        """令牌变更落盘（refresh 会轮换 refresh token，必须存回）。"""
        prof = self.profile
        prof["access_token"] = client.access_token
        prof["refresh_token"] = client.refresh_token
        prof["expires_at"] = client.expires_at
        config.save(self.data)

    def remember_identity(self, login_payload: dict) -> None:
        """记下登录响应里的身份信息（whoami 的数据源）。"""
        prof = self.profile
        prof["user"] = {
            "user_id": login_payload.get("userId"),
            "org_id": login_payload.get("orgId"),
            "is_platform_admin": bool(login_payload.get("isPlatformAdmin")),
        }
        if login_payload.get("defaultProjectId") and not prof.get("project"):
            prof["project"] = login_payload["defaultProjectId"]
        self.data["profiles"][self.profile_name] = prof
        config.save(self.data)


def _env(name: str) -> str | None:
    import os

    return os.environ.get(name) or None


# 当前进程的 State：根回调在派发子命令前写入，命令实现用 current() 取。
# 用模块级单例而非 click 的 ctx 链：typer 0.16 起自带的 click 已不再是独立包，
# 取「当前 Context」需要私有路径，跨版本不可靠。CLI 是单次进程，单例足够。
_CURRENT: State | None = None


def install(state: State) -> None:
    """根回调调用（每个进程一次）。"""
    global _CURRENT
    _CURRENT = state


def current() -> State:
    """取当前命令的 State（由根回调注入）。"""
    if _CURRENT is None:
        raise RuntimeError("State 未初始化（内部错误）")
    return _CURRENT
