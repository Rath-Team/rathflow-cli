/** 本地配置：~/.config/rathflow/config.json（多 profile，与 Python 版同文件同格式）。
 *
 * 优先级（由 state.js 统一合并）：flag > 环境变量 > profile > 内建默认。
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const DEFAULT_BASE_URL = "https://rathflow.lynwe.com";

// 环境变量名与 Get Started 页 curl 片段逐字同名，页面片段可直接喂 CLI。
export const ENV_BASE_URL = "RATHFLOW_BASE_URL";
export const ENV_PROJECT = "RATHFLOW_PROJECT";
export const ENV_TOKEN = "RATHFLOW_TOKEN";
export const ENV_CONFIG_DIR = "RATHFLOW_CONFIG_DIR";

const FILE_MODE = 0o600; // 内含令牌，等同口令

export function configDir() {
  return process.env[ENV_CONFIG_DIR] || path.join(os.homedir(), ".config", "rathflow");
}

export function configPath() {
  return path.join(configDir(), "config.json");
}

export function load() {
  const p = configPath();
  if (!fs.existsSync(p)) return { current: "default", profiles: {} };
  let data;
  try {
    data = JSON.parse(fs.readFileSync(p, "utf8"));
  } catch (err) {
    throw new Error(`配置文件损坏：${p}（${err.message}）`);
  }
  if (!data || typeof data !== "object") data = {};
  data.current ??= "default";
  data.profiles ??= {};
  return data;
}

/** 落盘并收紧权限到 0600（先写临时文件再 rename，避免半个文件）。 */
export function save(data) {
  const p = configPath();
  fs.mkdirSync(path.dirname(p), { recursive: true });
  const tmp = `${p}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify(data, null, 2)}\n`, { encoding: "utf8", mode: FILE_MODE });
  fs.renameSync(tmp, p);
  try {
    fs.chmodSync(p, FILE_MODE);
  } catch {
    // 非 POSIX 文件系统：尽力而为
  }
  return p;
}

export function profile(data, name) {
  const key = name || data.current || "default";
  data.profiles[key] ??= {};
  return data.profiles[key];
}

/** 令牌/密钥打码显示：保留前 8 位。 */
export function mask(secret) {
  if (!secret) return "(未设置)";
  const text = String(secret);
  return text.length > 8 ? `${text.slice(0, 8)}…` : "…";
}
