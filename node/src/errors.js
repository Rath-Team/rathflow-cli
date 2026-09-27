/** 错误信封与退出码（contracts/docs/error-envelope.md）。
 *
 * 信封形状：`{"error": {"code","message","details"}}`。终端只显示 message，
 * code 供程序判定。退出码与 Python 版逐条一致（docs：CLI 设计 §3.8）。
 */

export const EXIT_OK = 0;
export const EXIT_ERROR = 1; // 未分类
export const EXIT_USAGE = 2; // 参数 / 缺 project / 未登录
export const EXIT_AUTH = 3; // 401（刷新也无效）
export const EXIT_FORBIDDEN = 4; // 403
export const EXIT_NOT_FOUND = 5; // 404
export const EXIT_INVALID = 6; // 400 INVALID_ARGUMENT / FAILED_PRECONDITION / OUT_OF_RANGE
export const EXIT_CONFLICT = 7; // 409
export const EXIT_RATE_LIMIT = 8; // 429
export const EXIT_SERVER = 9; // 5xx

const BY_STATUS = {
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
};

/** 一次失败的 API 调用（信封已解出，或传输层失败）。 */
export class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.message = message;
    this.details = Array.isArray(details) ? details.slice() : [];
  }

  get exitCode() {
    return BY_STATUS[this.status] ?? EXIT_ERROR;
  }

  toString() {
    if (this.code && this.code !== "UNKNOWN") return `${this.message} [${this.code}]`;
    return this.message;
  }
}

/** 本地用法错误（未登录、缺 project、参数不合法）。退出码 2。 */
export class UsageError extends Error {
  constructor(message) {
    super(message);
    this.name = "UsageError";
    this.exitCode = EXIT_USAGE;
  }
}

/** 交互确认里用户答了「否」：退出码 1（对齐 click 的 Abort）。 */
export class Aborted extends Error {
  constructor(message = "已取消") {
    super(message);
    this.name = "Aborted";
    this.exitCode = EXIT_ERROR;
  }
}

/** 从响应体解出信封；形状不符时退回通用文案（不外泄内部细节）。 */
export function fromResponse(status, payload) {
  const body = payload && typeof payload === "object" && !Array.isArray(payload) ? payload : {};
  const err = body.error;
  if (!err || typeof err !== "object") {
    return new ApiError(status, "UNKNOWN", `请求失败（HTTP ${status}）`);
  }
  return new ApiError(
    status,
    String(err.code || "UNKNOWN"),
    String(err.message || `请求失败（HTTP ${status}）`),
    err.details,
  );
}
