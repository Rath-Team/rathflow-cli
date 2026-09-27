/** 参数解析与帮助渲染（零依赖，替代 Python 版的 typer）。
 *
 * 与 Python 版的行为差异：**全局选项写在命令前或命令后都认**——本解析器一次
 * 走完 argv，不需要 `_hoist_globals` 那种「把后面的全局选项挪到最前」的改写。
 *
 * 选项按**当前命令**解析，不做全树并集：短旗标在命令之间重名（`-e` 既是
 * `auth register --email` 又是 `sandbox exec --env`），并集会让 `auth register -e x`
 * 把 x 塞进 env。走到哪个命令就用哪个命令的选项表，祖先组与全局补在后面。
 */

import { UsageError } from "./errors.js";

const HELP_OPT = { key: "help", flags: ["--help", "-h"], help: "显示帮助" };

/** 全局选项（每个命令都认）。 */
export const GLOBAL_OPTS = [
  { key: "profile", flags: ["--profile", "-p"], take: true, help: "配置档名（缺省 default）" },
  { key: "baseUrl", flags: ["--base-url"], take: true, help: "gateway 地址（env RATHFLOW_BASE_URL）" },
  { key: "project", flags: ["--project"], take: true, help: "项目作用域（env RATHFLOW_PROJECT）" },
  { key: "jsonOut", flags: ["--json"], help: "以 JSON 输出（脚本消费的稳定形态）" },
  { key: "quiet", flags: ["--quiet", "-q"], help: "只输出主键（预留，暂未实现）" },
  { key: "version", flags: ["--version", "-V"], help: "显示版本并退出" },
  HELP_OPT,
];

const GLOBAL_FLAGS = new Map();
for (const o of GLOBAL_OPTS) {
  for (const f of o.flags) GLOBAL_FLAGS.set(f, o);
}

/** 选项描述：`opt("pageSize", ["--page-size"], {take: true, int: true, help: "…"})`。
 *
 * `take`   —— 该选项吃一个值（缺省是布尔旗标）
 * `int`    —— 值是整数
 * `list`   —— 可重复，收成数组
 * `negate` —— 取反写法（如 `--hidden` 之于 `--visible`）
 * `default`—— 缺省值（仅在该命令自己声明的选项上生效） */
export function opt(key, flags, extra = {}) {
  return { key, flags: Array.isArray(flags) ? flags : [flags], ...extra };
}

/** 每个节点自己的选项表（懒建，WeakMap 里存一份）。 */
const NODE_FLAGS = new WeakMap();

function flagsOf(node) {
  let map = NODE_FLAGS.get(node);
  if (!map) {
    map = new Map();
    for (const o of node.opts || []) {
      for (const f of o.flags) map.set(f, o);
      for (const f of o.negate || []) map.set(f, { ...o, negated: true });
    }
    NODE_FLAGS.set(node, map);
  }
  return map;
}

function assign(values, spec, value) {
  if (spec.list) {
    values[spec.key] ??= [];
    values[spec.key].push(value);
    return;
  }
  values[spec.key] = value;
}

function coerce(spec, flag, raw) {
  if (!spec.int) return raw;
  const n = Number(raw);
  if (!Number.isInteger(n)) {
    throw new UsageError(`选项 ${flag} 需要整数，收到 ${JSON.stringify(raw)}`);
  }
  return n;
}

/** 解析 argv（含 node 与脚本名）。返回 { node, path, opts, args }。 */
export function parseArgv(argv, root) {
  const tokens = argv.slice(2);
  const values = {};
  const args = [];
  const chain = [root];
  const path = [];
  let node = root;

  const find = (flag) => {
    for (let i = chain.length - 1; i >= 0; i -= 1) {
      const found = flagsOf(chain[i]).get(flag);
      if (found) return found;
    }
    return GLOBAL_FLAGS.get(flag);
  };
  const lookup = (flag) => {
    const found = find(flag);
    if (!found) throw new UsageError(`未知选项 ${flag}（用 --help 看该命令的选项）`);
    return found;
  };
  // 值可能长得像旗标（`--body --json`）：只有确定是旗标时才报错，`-` 与负数放行
  const valueOf = (spec, flag, inline, next) => {
    if (inline !== null) return inline;
    if (next === undefined || next === "") throw new UsageError(`选项 ${flag} 需要一个值`);
    if (next.startsWith("--") || (next.startsWith("-") && next !== "-" && find(next))) {
      throw new UsageError(`选项 ${flag} 需要一个值`);
    }
    return next;
  };
  const applyFlag = (spec, flag, inline, next) => {
    if (!spec.take) {
      assign(values, spec, spec.negated ? false : inline === null ? true : inline !== "false");
      return 0;
    }
    const value = valueOf(spec, flag, inline, next);
    assign(values, spec, coerce(spec, flag, value));
    return inline === null ? 1 : 0;
  };

  for (let i = 0; i < tokens.length; i += 1) {
    const tok = tokens[i];
    if (tok === "--") {
      args.push(...tokens.slice(i + 1));
      break;
    }
    if (tok === "-" || !tok.startsWith("-")) {
      if (node.commands && node.commands[tok]) {
        node = node.commands[tok];
        chain.push(node);
        path.push(tok);
      } else {
        args.push(tok);
      }
      continue;
    }

    const eq = tok.indexOf("=");
    const name = eq < 0 ? tok : tok.slice(0, eq);
    const inline = eq < 0 ? null : tok.slice(eq + 1);

    if (tok.startsWith("--")) {
      i += applyFlag(lookup(name), name, inline, tokens[i + 1]);
      continue;
    }
    const found = find(name);
    if (found) {
      i += applyFlag(found, name, inline, tokens[i + 1]);
      continue;
    }
    // 组合布尔短旗标：-rq
    const chars = tok.slice(1).split("");
    const specs = chars.map((c) => find(`-${c}`));
    if (chars.length > 1 && specs.every((s) => s && !s.take)) {
      specs.forEach((s) => assign(values, s, true));
      continue;
    }
    throw new UsageError(`未知选项 ${tok}（用 --help 看该命令的选项）`);
  }

  for (const spec of node.opts || []) {
    if (values[spec.key] === undefined && "default" in spec) values[spec.key] = spec.default;
  }

  return { node, path, opts: values, args };
}

/** 逐条校验位置参数（数量与必填），与 typer 的报错时机一致。 */
export function checkArgs(node, args, path) {
  const declared = node.args || [];
  if (args.length > declared.length) {
    throw new UsageError(`多余的参数：${args.slice(declared.length).join(" ")}`);
  }
  declared.forEach((spec, i) => {
    if (spec.required && (args[i] === undefined || args[i] === "")) {
      throw new UsageError(`缺少参数 <${spec.name}>（用法：rathflow ${path.join(" ")} …）`);
    }
  });
}

function optionsBlock(opts) {
  const rows = opts.map((o) => [o.flags.join(", "), o.help || ""]);
  const width = rows.reduce((max, [flags]) => Math.max(max, flags.length), 0);
  return rows.map(([flags, help]) => `  ${flags.padEnd(width)}  ${help}`);
}

export function renderHelp(node, path = []) {
  const name = ["rathflow", ...path].join(" ");
  const out = [node.help ? `${name} —— ${node.help}` : name, ""];
  const args = (node.args || []).map((a) => `<${a.name}>`);

  out.push("用法：");
  if (node.commands) {
    out.push(`  ${name} <命令> [选项]`, "", "命令：");
    const names = Object.keys(node.commands);
    const width = names.reduce((max, n) => Math.max(max, n.length), 0);
    for (const n of names) out.push(`  ${n.padEnd(width)}  ${node.commands[n].help || ""}`);
  } else {
    out.push(`  ${[name, ...args, "[选项]"].join(" ")}`);
  }

  if ((node.args || []).length) {
    out.push("", "参数：");
    const width = node.args.reduce((max, a) => Math.max(max, a.name.length + 2), 0);
    for (const a of node.args) out.push(`  ${`<${a.name}>`.padEnd(width)}  ${a.help || ""}`);
  }

  out.push("", "选项：", ...optionsBlock([...(node.opts || []), ...GLOBAL_OPTS]), "");
  return out.join("\n");
}
