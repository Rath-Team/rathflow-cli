/** 输出渲染：默认人类可读，`--json` 原样透传（脚本消费的唯一稳定形态）。
 *
 * `--json` **不重新编码**：protojson 已把 int64 编成字符串、Timestamp 编成 RFC3339、
 * bytes 编成 base64；重新编码会失真，故直接 JSON.stringify 透传。
 */

const MAX_CELL = 48;

function get(obj, dotted) {
  let cur = obj;
  for (const part of dotted.split(".")) {
    if (!cur || typeof cur !== "object") return undefined;
    cur = cur[part];
    if (cur === undefined || cur === null) return undefined;
  }
  return cur;
}

export function cell(value) {
  if (value === undefined || value === null) return "";
  let text;
  if (typeof value === "boolean") text = value ? "true" : "false";
  else if (typeof value === "object") text = JSON.stringify(value);
  else text = String(value);
  text = text.replaceAll("\n", " ");
  return text.length > MAX_CELL ? `${text.slice(0, MAX_CELL - 1)}…` : text;
}

export function emitJson(payload) {
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
}

export function emitObject(obj, { jsonOut = false } = {}) {
  if (jsonOut) {
    emitJson(obj);
    return;
  }
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) {
    process.stdout.write(`${cell(obj)}\n`);
    return;
  }
  const keys = Object.keys(obj);
  const width = keys.reduce((max, k) => Math.max(max, k.length), 0);
  for (const key of keys) {
    const value = obj[key];
    if (value === undefined || value === null || value === "" ) continue;
    if (Array.isArray(value) && value.length === 0) continue;
    if (typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0) continue;
    process.stdout.write(`${key.padEnd(width)}  ${cell(value)}\n`);
  }
}

/** rows = 对象列表；columns = [[表头, 点分路径], ...]。 */
export function emitTable(rows, columns, { jsonOut = false } = {}) {
  if (jsonOut) {
    emitJson(rows);
    return;
  }
  const list = rows || [];
  if (list.length === 0) {
    process.stdout.write("(空)\n");
    return;
  }
  const headers = columns.map(([h]) => h);
  const body = list.map((row) => columns.map(([, p]) => cell(get(row, p))));
  const widths = headers.map((h, i) =>
    body.reduce((max, row) => Math.max(max, row[i].length), h.length),
  );
  process.stdout.write(`${headers.map((h, i) => h.padEnd(widths[i])).join("  ")}\n`);
  for (const row of body) {
    process.stdout.write(`${row.map((v, i) => v.padEnd(widths[i])).join("  ")}\n`);
  }
}

/** 分页响应：取 itemsKey 列表渲染；JSON 模式透传整包（保留 nextPageToken）。 */
export function emitItems(payload, { itemsKey, columns, jsonOut = false } = {}) {
  if (jsonOut) {
    emitJson(payload);
    return;
  }
  emitTable((payload || {})[itemsKey] || [], columns, { jsonOut: false });
  const token = (payload || {}).nextPageToken;
  if (token) process.stdout.write(`\n(还有下一页：--page-token ${token})\n`);
}

export function writeBytes(data, { toStderr = false } = {}) {
  const stream = toStderr ? process.stderr : process.stdout;
  stream.write(Buffer.isBuffer(data) ? data : Buffer.from(data));
}

/** 人类可读的行（typer.echo 等价）；err=true 走 stderr。 */
export function echo(text = "", { err = false } = {}) {
  const stream = err ? process.stderr : process.stdout;
  stream.write(`${text}\n`);
}
