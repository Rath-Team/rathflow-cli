/** HTTP 层：JWT 登录/续期 + 错误信封 + 流式解码（零依赖，只用内建 fetch）。
 *
 * 契约依据：
 *   - contracts/docs/error-envelope.md（错误信封与 HTTP 状态映射）
 *   - contracts/docs/streaming.md §三（读取端最小实现要求，逐条落实）
 *   - gateway/internal/gateway/cookiepost.go：「响应体 token 原样保留（SDK/CLI 走 Bearer）」
 *     → CLI 只读响应体，**不碰 cookie**；也因此天然豁免 CSRF 门。
 */

import * as endpoints from "./endpoints.js";
import { ApiError, UsageError, fromResponse } from "./errors.js";

// 普通调用：读超时给足（上游 gateway 默认 10s，orchestrator 30s）
const TIMEOUT_MS = 120_000;
// 流式：不设超时（沙箱命令可能长时间无输出仍存活）

// 到期前多久就主动刷新（秒）
const REFRESH_MARGIN = 60;

const USER_AGENT = "rathflow-cli-node/0.1.0";

export class Client {
  /** 一次进程内的 API 客户端（令牌变更经 persist 回调落盘）。 */
  constructor(baseUrl, { project, accessToken, refreshToken, expiresAt, persist } = {}) {
    this.baseUrl = String(baseUrl).replace(/\/+$/, "");
    this.project = project || null;
    this.accessToken = accessToken || null;
    this.refreshToken = refreshToken || null;
    this.expiresAt = Number(expiresAt || 0);
    this.persist = persist;
  }

  // ---------------------------------------------------------------- 令牌

  /** 从 LoginResponse 吸收令牌。protojson 把 int64 编成 JSON 字符串。 */
  absorbTokens(payload) {
    const access = payload.accessToken || payload.access_token;
    const refresh = payload.refreshToken || payload.refresh_token;
    if (access) this.accessToken = access;
    if (refresh) this.refreshToken = refresh;
    const ttl = payload.expiresInSeconds ?? payload.expires_in_seconds;
    const seconds = Number.parseInt(ttl, 10);
    if (Number.isFinite(seconds) && seconds > 0) {
      this.expiresAt = nowSeconds() + seconds - REFRESH_MARGIN;
    } else if (access) {
      this.expiresAt = nowSeconds() + 15 * 60 - REFRESH_MARGIN;
    }
    if (this.persist) this.persist(this);
  }

  async login(email, password) {
    const payload = await this.#callRaw("POST", endpoints.renderPath("auth.Login"), {
      body: { email, password },
      allowRetry: false,
    });
    this.absorbTokens(payload);
    return payload;
  }

  async logout() {
    if (this.accessToken) {
      try {
        await this.#callRaw("POST", endpoints.renderPath("auth.Logout"), { body: {} });
      } catch (err) {
        if (!(err instanceof ApiError)) throw err;
        // 幂等：服务端不可达也清本地
      }
    }
    this.accessToken = null;
    this.refreshToken = null;
    this.expiresAt = 0;
    if (this.persist) this.persist(this);
  }

  /** 用 refresh token 换新令牌。成功返回 true。refresh 会轮换 → 必须存回。 */
  async refresh() {
    if (!this.refreshToken) return false;
    let payload;
    try {
      payload = await this.#callRaw("POST", endpoints.renderPath("auth.Refresh"), {
        body: { refreshToken: this.refreshToken },
        allowRetry: false,
      });
    } catch (err) {
      if (!(err instanceof ApiError)) throw err;
      return false;
    }
    this.absorbTokens(payload);
    return true;
  }

  /** 无令牌 → 报未登录；临期且有 refresh → 先刷新。 */
  async ensureToken() {
    if (!this.accessToken) throw new UsageError("未登录：先跑 `rathflow auth login`");
    if (this.refreshToken && this.expiresAt && nowSeconds() >= this.expiresAt) {
      await this.refresh();
    }
  }

  // ---------------------------------------------------------------- 请求

  headers() {
    const out = { Accept: "application/json", "User-Agent": USER_AGENT };
    if (this.accessToken) out.Authorization = `Bearer ${this.accessToken}`;
    // 作用域解析：路径 {project_id} 优先，其次本头（gateway/internal/resolve）
    if (this.project) out["X-RathFlow-Project"] = this.project;
    return out;
  }

  /** 带令牌发请求；401 → 刷新一次并重放。streaming 时响应体未读（调用方 cancel）。 */
  async #send(method, path, { params, body, streaming = false } = {}) {
    await this.ensureToken();
    const url = this.baseUrl + path + queryString(params);
    const headers = this.headers();
    if (body !== undefined && body !== null) headers["Content-Type"] = "application/json";
    let resp;
    for (const attempt of [0, 1]) {
      try {
        const init = { method, headers, redirect: "manual" };
        if (body !== undefined && body !== null) init.body = JSON.stringify(body);
        // 流式不设超时：沙箱长命令中途没输出也该活着
        if (!streaming) init.signal = AbortSignal.timeout(TIMEOUT_MS);
        resp = await fetch(url, init);
      } catch (err) {
        throw new ApiError(0, "UNAVAILABLE", `无法连接 ${this.baseUrl}：${err.message}`);
      }
      if (resp.status === 401 && attempt === 0 && (await this.refresh())) {
        await discard(resp);
        continue;
      }
      return resp;
    }
    return resp; // 不会走到
  }

  /** 免登录端点：不发令牌、不做 401 重放（否则登录/注册会自我递归）。 */
  async #sendUnauthed(method, path, { params, body } = {}) {
    const headers = this.headers();
    if (body !== undefined && body !== null) headers["Content-Type"] = "application/json";
    try {
      const init = { method, headers, redirect: "manual", signal: AbortSignal.timeout(TIMEOUT_MS) };
      if (body !== undefined && body !== null) init.body = JSON.stringify(body);
      return await fetch(this.baseUrl + path + queryString(params), init);
    } catch (err) {
      throw new ApiError(0, "UNAVAILABLE", `无法连接 ${this.baseUrl}：${err.message}`);
    }
  }

  /** 非流式调用：返回解码后的 JSON（空体 → {}）。 */
  async #callRaw(method, path, { params, body, allowRetry = true } = {}) {
    const resp = allowRetry
      ? await this.#send(method, path, { params, body })
      : await this.#sendUnauthed(method, path, { params, body });
    const raw = await resp.text();
    const payload = raw ? decode(raw) : {};
    if (resp.status >= 400) throw fromResponse(resp.status, payload);
    return payload;
  }

  /** 按端点 key（或显式 method/path）调用一次，返回响应 JSON。
   *
   * auth=false 用于免登录端点（register / 公开读），不要求也不刷新令牌。 */
  async call(key, { method, path, body, query, pathParams, auth = true } = {}) {
    const [m, p] = resolve(key, method, path, pathParams);
    return this.#callRaw(m, p, { params: clean(query), body, allowRetry: auth });
  }

  /** 流式调用：逐帧产出 `result` payload。
   *
   * 读取端纪律（streaming.md §三）：按行切帧；只认 result/error 两键；
   * 未知键拒绝该帧；error 帧即流终结并按信封报错。 */
  async *stream(key, { method, path, body, query, pathParams } = {}) {
    const [m, p] = resolve(key, method, path, pathParams);
    const resp = await this.#send(m, p, { params: clean(query), body, streaming: true });
    const status = resp.status;
    if (status >= 400) {
      throw fromResponse(status, decode(await resp.text()));
    }
    if (!resp.body) return;

    const emit = (rawLine) => {
      const line = rawLine.trim();
      if (!line) return undefined;
      let frame;
      try {
        frame = JSON.parse(line);
      } catch {
        throw new ApiError(status, "UNKNOWN", "流中断：收到非 JSON 帧");
      }
      if (!frame || typeof frame !== "object" || Array.isArray(frame)) {
        throw new ApiError(status, "UNKNOWN", "流中断：帧不是对象");
      }
      const keys = Object.keys(frame);
      if (keys.length === 1 && keys[0] === "result") return frame.result;
      if (keys.length === 1 && keys[0] === "error") throw fromResponse(status, frame);
      throw new ApiError(
        status,
        "UNKNOWN",
        `流帧含未知键 ${JSON.stringify(keys.sort())}（前后端契约漂移，拒绝该帧）`,
      );
    };

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, nl);
          buf = buf.slice(nl + 1);
          const frame = emit(line);
          if (frame !== undefined) yield frame;
        }
      }
      buf += decoder.decode();
      const tail = emit(buf);
      if (tail !== undefined) yield tail;
    } finally {
      try {
        await reader.cancel();
      } catch {
        // 流已收干：忽略
      }
    }
  }
}

function resolve(key, method, path, pathParams) {
  if (key) {
    return [endpoints.methodOf(key), endpoints.renderPath(key, pathParams || {})];
  }
  if (!method || !path) throw new UsageError("需要端点 key，或显式 --method/--path");
  return [String(method).toUpperCase(), path];
}

/** 去掉空值；布尔转 "true"/"false"（protojson 惯例）。 */
function clean(query) {
  if (!query) return undefined;
  const out = {};
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    out[k] = typeof v === "boolean" ? String(v) : v;
  }
  return Object.keys(out).length ? out : undefined;
}

function queryString(params) {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null) continue;
    search.append(k, String(v));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

function decode(raw) {
  if (!raw) return {};
  try {
    const data = JSON.parse(raw);
    return data !== null && typeof data === "object" && !Array.isArray(data) ? data : { data };
  } catch {
    return {};
  }
}

async function discard(resp) {
  try {
    await resp.body?.cancel();
  } catch {
    // 忽略
  }
}

function nowSeconds() {
  return Date.now() / 1000;
}
