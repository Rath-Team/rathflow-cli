/** 进程内状态：合并「flag > 环境变量 > profile > 默认」并承载惰性 Client。 */

import * as config from "./config.js";
import { Client } from "./http.js";

export class State {
  constructor({ profile, baseUrl, project, jsonOut = false, quiet = false } = {}) {
    this.data = config.load();
    this.jsonOut = Boolean(jsonOut);
    this.quiet = Boolean(quiet);
    this.#flags = { baseUrl, project };
    if (profile) this.data.current = profile;
    this.tokenOverride = env(config.ENV_TOKEN);

    const prof = this.profile;
    // 原始环境变量值：只用于如实展示「环境变量到底设没设」，不参与合并，
    // 否则 config show 会把生效值当成环境变量回显，让人误以为有 env 覆盖。
    this.envBaseUrl = env(config.ENV_BASE_URL);
    this.envProject = env(config.ENV_PROJECT);
    this.baseUrl =
      this.#flags.baseUrl || this.envBaseUrl || prof.base_url || config.DEFAULT_BASE_URL;
    this.project = this.#flags.project || this.envProject || prof.project || undefined;
  }

  #flags;
  #client = null;

  get profileName() {
    return this.data.current || "default";
  }

  get profile() {
    return config.profile(this.data, this.profileName);
  }

  client() {
    if (this.#client === null) {
      const prof = this.profile;
      if (this.tokenOverride) {
        // CI 场景：直接用环境变量令牌，不落盘、不刷新
        this.#client = new Client(this.baseUrl, {
          project: this.project,
          accessToken: this.tokenOverride,
        });
      } else {
        this.#client = new Client(this.baseUrl, {
          project: this.project,
          accessToken: prof.access_token,
          refreshToken: prof.refresh_token,
          expiresAt: prof.expires_at,
          persist: (client) => this.persist(client),
        });
      }
    }
    return this.#client;
  }

  /** 令牌变更落盘（refresh 会轮换 refresh token，必须存回）。 */
  persist(client) {
    const prof = this.profile;
    prof.access_token = client.accessToken;
    prof.refresh_token = client.refreshToken;
    prof.expires_at = client.expiresAt;
    config.save(this.data);
  }

  /** 记下登录响应里的身份信息（whoami 的数据源）。 */
  rememberIdentity(loginPayload) {
    const prof = this.profile;
    prof.user = {
      user_id: loginPayload.userId,
      org_id: loginPayload.orgId,
      is_platform_admin: Boolean(loginPayload.isPlatformAdmin),
    };
    if (loginPayload.defaultProjectId && !prof.project) {
      prof.project = loginPayload.defaultProjectId;
    }
    this.data.profiles[this.profileName] = prof;
    config.save(this.data);
  }

  save() {
    config.save(this.data);
  }
}

function env(name) {
  return process.env[name] || undefined;
}
