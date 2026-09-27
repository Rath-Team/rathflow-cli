/** 轻量自检（不联服务端）：`node src/selftest.js`（或 `npm run selftest`）
 *
 * 只查三件事，但都是「装得上但会打错 URL」的那类毛病：
 * 1. **端点表是否与生成物一致**（最容易漂的那件）；
 * 2. **命令实现里不写 URL 字面量**；
 * 3. **多段路径参数拦住点段**（`..` 会被 URL 归一化，打到别的端点）。
 * `web/lib/api/generated/endpoints.ts` 由 proto 生成（scripts/gen-types.mjs），
 * 本 CLI 的 endpoints.js 手工同步 —— 两者一旦漂移，命令就会打错 URL。
 *
 * 为什么要这个：CLI 装不上、端点表过期，都不会在 `--help` 里露出来。
 *
 * 生成物在上游 monorepo 里，本仓库没有；用 `RATHFLOW_ENDPOINTS_TS=<path>` 指过去。
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import * as endpoints from "./endpoints.js";
import { UsageError } from "./errors.js";

const HERE = path.dirname(fileURLToPath(import.meta.url)); // cli/node/src
const REPO = path.resolve(HERE, "..", ".."); // node/src → node → 仓库根
const GENERATED =
  process.env.RATHFLOW_ENDPOINTS_TS || path.join(REPO, "web", "lib", "api", "generated", "endpoints.ts");
const COMMANDS = path.join(HERE, "commands");

const ROW =
  /\{ key: "([^"]+)", method: "(\w+)", path: "([^"]+)", pathParams: \[([^\]]*)\], multiParams: \[([^\]]*)\],.*?stream: (true|false),/;
const URL_LITERAL = /"(?:\/api\/|\/admin\/api\/)/;

function names(raw) {
  return new Set([...raw.matchAll(/"([^"]+)"/g)].map((m) => m[1]));
}

function checkGenerated() {
  // 生成物不在本仓库（它是上游 monorepo 的产物）：跳过比对，而不是报错。
  if (!fs.existsSync(GENERATED)) return [];
  const rows = {};
  for (const line of fs.readFileSync(GENERATED, "utf8").split("\n")) {
    const m = ROW.exec(line);
    if (!m) continue;
    rows[m[1]] = { method: m[2], path: m[3], multi: names(m[5]), stream: m[6] === "true" };
  }

  const problems = [];
  const have = new Set(Object.keys(endpoints.ENDPOINTS));
  const want = new Set(Object.keys(rows));
  const missing = [...want].filter((k) => !have.has(k)).sort();
  const extra = [...have].filter((k) => !want.has(k)).sort();
  if (missing.length) problems.push(`endpoints.js 缺 ${missing.length} 个端点：${missing.slice(0, 5)}…`);
  if (extra.length) problems.push(`endpoints.js 多出 ${extra.length} 个端点：${extra.slice(0, 5)}…`);

  for (const key of [...want].filter((k) => have.has(k)).sort()) {
    const w = rows[key];
    const g = endpoints.ENDPOINTS[key];
    if (g[0] !== w.method || g[1] !== w.path) {
      problems.push(`${key}: 路径/方法不一致 ${g} vs ${w.path}/${w.method}`);
    }
    const mine = endpoints.MULTI_PARAMS[key] || new Set();
    if (mine.size !== w.multi.size || [...mine].some((x) => !w.multi.has(x))) {
      problems.push(`${key}: multiParams 不一致 ${[...mine].sort()} vs ${[...w.multi].sort()}`);
    }
    if (endpoints.isStreaming(key) !== w.stream) {
      problems.push(`${key}: stream 标记不一致 ${endpoints.isStreaming(key)} vs ${w.stream}`);
    }
  }

  // 模板参数与 MULTI_PARAMS 声明必须对得上（多段参数一定出现在模板里）
  for (const key of Object.keys(endpoints.ENDPOINTS)) {
    const declared = endpoints.MULTI_PARAMS[key] || new Set();
    const unknown = [...declared].filter((p) => !endpoints.pathParams(key).includes(p));
    if (unknown.length) {
      problems.push(`${key}: MULTI_PARAMS 声明了模板里没有的参数 ${unknown.sort()}`);
    }
  }
  return problems;
}

function checkNoUrlLiterals() {
  const problems = [];
  for (const name of fs.readdirSync(COMMANDS).sort()) {
    if (!name.endsWith(".js")) continue;
    const lines = fs.readFileSync(path.join(COMMANDS, name), "utf8").split("\n");
    lines.forEach((line, i) => {
      if (URL_LITERAL.test(line) && !line.trimStart().startsWith("//")) {
        problems.push(`${name}:${i + 1} 出现 URL 字面量（该走端点 key）`);
      }
    });
  }
  return problems;
}

/** 多段路径里的 `.`/`..`/空段必须被拒，正常路径仍要能渲染。 */
function checkPathGuard() {
  const cases = { "memory.Read": "memory_path", "sandbox.ReadFile": "path" };
  const bad = ["a/../b", "../x", "/abs", "a//b", "a/./b"];
  const problems = [];
  for (const [key, name] of Object.entries(cases)) {
    const others = Object.fromEntries(endpoints.pathParams(key).filter((p) => p !== name).map((p) => [p, "X1"]));
    for (const value of bad) {
      let rendered;
      try {
        rendered = endpoints.renderPath(key, { [name]: value, ...others });
      } catch (err) {
        if (err instanceof UsageError) continue;
        problems.push(`${key}: ${name}=${JSON.stringify(value)} 抛了 ${err.name}，应抛 UsageError`);
        continue;
      }
      problems.push(
        `${key}: ${name}=${JSON.stringify(value)} 未被拒绝，会渲染成 ${rendered}（URL 归一化后打到别的端点）`,
      );
    }
    const good = endpoints.renderPath(key, { [name]: "a/b c.md", ...others });
    if (!good.endsWith("a/b%20c.md")) problems.push(`${key}: 正常路径渲染异常 ${good}`);
  }
  return problems;
}

export function run() {
  const problems = [...checkGenerated(), ...checkNoUrlLiterals(), ...checkPathGuard()];
  if (problems.length) {
    process.stderr.write(`自检未通过（${problems.length} 项）：\n`);
    for (const line of problems) process.stderr.write(`  - ${line}\n`);
    return 1;
  }
  const compared = fs.existsSync(GENERATED) ? "端点表与生成物一致" : "未找到生成物，跳过端点表比对";
  process.stdout.write(`自检通过：${compared}（${Object.keys(endpoints.ENDPOINTS).length} 个端点）\n`);
  return 0;
}

// 直接 `node src/selftest.js` 时跑；被 import 时只导出 run()。
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = run();
}
