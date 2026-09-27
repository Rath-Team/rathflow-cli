/** 命令间共用的小工具（选项描述、参数解析与请求体装配）。 */

import fs from "node:fs";

import { opt } from "../args.js";
import { Aborted, UsageError } from "../errors.js";

export const PATH_OPT = opt("path", ["--path"], {
  take: true,
  list: true,
  help: "路径参数 k=v，可重复（如 --path session_id=abc）",
});
export const QUERY_OPT = opt("query", ["--query"], {
  take: true,
  list: true,
  help: "查询参数 k=v，可重复",
});
export const BODY_OPT = opt("body", ["--body"], { take: true, help: "请求体 JSON 字面量" });
export const BODY_FILE_OPT = opt("bodyFile", ["--body-file"], {
  take: true,
  help: "从文件读请求体 JSON（- 读 stdin）",
});
export const PAGE_SIZE_OPT = opt("pageSize", ["--page-size"], {
  take: true,
  int: true,
  help: "分页大小",
});
export const PAGE_TOKEN_OPT = opt("pageToken", ["--page-token"], { take: true, help: "分页游标" });
export const YES_OPT = opt("yes", ["--yes", "-y"], { help: "跳过确认" });

/** `["k=v", ...]` → `{k: v}`；值里的 = 保留（只切第一个）。 */
export function pairs(items) {
  const out = {};
  for (const item of items || []) {
    const at = item.indexOf("=");
    if (at < 0) throw new UsageError(`参数需形如 k=v，收到 ${JSON.stringify(item)}`);
    out[item.slice(0, at).trim()] = item.slice(at + 1);
  }
  return out;
}

/** 装配请求体：`--body` 字面量或 `--body-file`（`-` = stdin）。两者互斥。 */
export async function bodyOf(opts) {
  const { body, bodyFile } = opts;
  if (body && bodyFile) throw new UsageError("--body 与 --body-file 不能同时用");
  let raw = null;
  if (bodyFile) raw = bodyFile === "-" ? (await readStdin()).toString("utf8") : readText(bodyFile);
  else if (body) raw = body;
  else return undefined;
  raw = raw.trim();
  if (!raw) return {};
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    throw new UsageError(`请求体不是合法 JSON：${err.message}`);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new UsageError("请求体必须是 JSON 对象");
  }
  return parsed;
}

/** 读一个文本文件。 */
export function readText(path) {
  try {
    return fs.readFileSync(path, "utf8");
  } catch (err) {
    throw new UsageError(`读取失败：${err.message}`);
  }
}

/** 读一个二进制文件。 */
export function readBinary(path) {
  try {
    return fs.readFileSync(path);
  } catch (err) {
    throw new UsageError(`读取失败：${err.message}`);
  }
}

/** 读干 stdin（二进制）。 */
export async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks);
}

/** 装配分页查询串（protojson 查询名用 proto 字段名 snake_case）。 */
export function pagination(pageSize, pageToken, extra = {}) {
  const query = { ...extra };
  if (pageSize !== undefined && pageSize !== null) query.page_size = pageSize;
  if (pageToken) query.page_token = pageToken;
  return query;
}

/** 交互确认（typer.confirm 等价）：非交互环境直接报错，别静静地「确认」掉。 */
export async function confirm(question) {
  if (!process.stdin.isTTY) throw new UsageError("当前不是交互终端：加 --yes 跳过确认");
  const { createInterface } = await import("node:readline/promises");
  const rl = createInterface({ input: process.stdin, output: process.stderr });
  let answer = "";
  try {
    answer = await rl.question(`${question} [y/N] `);
  } finally {
    rl.close();
  }
  if (!/^y(es)?$/i.test(answer.trim())) throw new Aborted();
}

/** 缺省 project 的兜底报错（与 Python 版同一句话）。 */
export function requireProject(pid) {
  if (!pid) {
    throw new UsageError(
      "无项目作用域：`rathflow project use <id>`，或加 --project <id>，或设 RATHFLOW_PROJECT",
    );
  }
  return pid;
}

/** protojson 把 bytes 编成 base64；解失败就当纯文本用。 */
export function bytesOf(value) {
  if (!value) return Buffer.alloc(0);
  if (Buffer.isBuffer(value)) return value;
  const text = String(value);
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(text) || text.length % 4 !== 0) return Buffer.from(text);
  return Buffer.from(text, "base64");
}
