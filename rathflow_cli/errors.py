"""错误信封与退出码（contracts/docs/error-envelope.md）。

信封形状：{"error": {"code","message","details"}}。终端只显示 message，code 供程序判定。
"""

from __future__ import annotations

# 退出码约定（docs：CLI 设计 §3.8）
EXIT_OK = 0
EXIT_ERROR = 1        # 未分类
EXIT_USAGE = 2        # 参数/缺 project/未登录
EXIT_AUTH = 3         # 401（刷新也无效）
EXIT_FORBIDDEN = 4    # 403
EXIT_NOT_FOUND = 5    # 404
EXIT_INVALID = 6      # 400 INVALID_ARGUMENT / FAILED_PRECONDITION / OUT_OF_RANGE
EXIT_CONFLICT = 7     # 409
EXIT_RATE_LIMIT = 8   # 429
EXIT_SERVER = 9       # 5xx

_BY_STATUS = {
    400: EXIT_INVALID,
    401: EXIT_AUTH,
    403: EXIT_FORBIDDEN,
    404: EXIT_NOT_FOUND,
    409: EXIT_CONFLICT,
    429: EXIT_RATE_LIMIT,
    499: EXIT_ERROR,
    500: EXIT_SERVER,
    501: EXIT_SERVER,
    503: EXIT_SERVER,
    504: EXIT_SERVER,
}


class ApiError(Exception):
    """一次失败的 API 调用（信封已解出，或传输层失败）。"""

    def __init__(self, status: int, code: str, message: str, details=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = list(details or [])

    @property
    def exit_code(self) -> int:
        return _BY_STATUS.get(self.status, EXIT_ERROR)

    def __str__(self) -> str:
        if self.code and self.code not in ("UNKNOWN", ""):
            return f"{self.message} [{self.code}]"
        return self.message


class UsageError(Exception):
    """本地用法错误（未登录、缺 project、参数不合法）。退出码 2。"""


def from_response(status: int, payload) -> ApiError:
    """从响应体解出信封；形状不符时退回通用文案（不外泄内部细节）。"""
    body = payload if isinstance(payload, dict) else {}
    err = body.get("error")
    if not isinstance(err, dict):
        return ApiError(status, "UNKNOWN", f"请求失败（HTTP {status}）")
    return ApiError(
        status,
        str(err.get("code") or "UNKNOWN"),
        str(err.get("message") or f"请求失败（HTTP {status}）"),
        err.get("details"),
    )
