/** 根命令树与入口：解析 → 派发 → 错误处理。
 *
 * 与 Python 版（cli/python/rathflow_cli/cli.py）逐条对齐：命令名、选项名、退出码、
 * 输出形态都一致，两个实现可以互相替换着用。
 */

import { checkArgs, parseArgv, renderHelp } from "./args.js";
import { admin } from "./commands/admin.js";
import { agent } from "./commands/agent.js";
import { api } from "./commands/api.js";
import { asset } from "./commands/asset.js";
import { auth, whoami } from "./commands/auth.js";
import { billing } from "./commands/billing.js";
import { configCmd } from "./commands/config.js";
import { memory } from "./commands/memory.js";
import { org } from "./commands/org.js";
import { project } from "./commands/project.js";
import { sandbox } from "./commands/sandbox.js";
import { session } from "./commands/session.js";
import { workflow } from "./commands/workflow.js";
import { Aborted, ApiError, EXIT_ERROR, EXIT_USAGE, UsageError } from "./errors.js";
import { State } from "./state.js";
import { createRequire } from "node:module";

const MIN_NODE_MAJOR = 20;

const VERSION = createRequire(import.meta.url)("../package.json").version;

export const ROOT = {
  help: "RathFlow 命令行客户端（Node.js 实现；JWT 登录，命令覆盖北向 REST 全部端点）。",
  commands: {
    auth,
    config: configCmd,
    org,
    project,
    session,
    memory,
    sandbox,
    agent,
    asset,
    billing,
    workflow,
    admin,
    // 逃生舱与身份查询挂在根上，少打一层
    whoami,
    api,
  },
};

function report(err) {
  if (err instanceof UsageError) {
    process.stderr.write(`错误：${err.message}\n`);
    process.exitCode = EXIT_USAGE;
    return;
  }
  if (err instanceof Aborted) {
    process.stderr.write(`${err.message}\n`);
    process.exitCode = err.exitCode;
    return;
  }
  if (err instanceof ApiError) {
    process.stderr.write(`错误：${err}\n`);
    for (const detail of err.details) process.stderr.write(`  - ${detail}\n`);
    process.exitCode = err.exitCode;
    return;
  }
  process.stderr.write(`错误：${err?.stack || err}\n`);
  process.exitCode = EXIT_ERROR;
}

export async function main(argv = process.argv) {
  const major = Number(process.versions.node.split(".")[0]);
  if (!(major >= MIN_NODE_MAJOR)) {
    process.stderr.write(`需要 Node ${MIN_NODE_MAJOR}+（当前 ${process.version}）\n`);
    process.exitCode = EXIT_ERROR;
    return;
  }
  try {
    const parsed = parseArgv(argv, ROOT);
    if (parsed.opts.version) {
      process.stdout.write(`rathflow ${VERSION}\n`);
      return;
    }
    if (parsed.opts.help || !parsed.node.run) {
      // `--help` 先于参数校验：`rathflow sandbox exec --help` 不该先抱怨少了 sandbox_id
      if (!parsed.node.run && parsed.args.length) {
        throw new UsageError(`未知命令：${parsed.args[0]}`);
      }
      process.stdout.write(renderHelp(parsed.node, parsed.path));
      return;
    }
    checkArgs(parsed.node, parsed.args, parsed.path);
    const st = new State({
      profile: parsed.opts.profile,
      baseUrl: parsed.opts.baseUrl,
      project: parsed.opts.project,
      jsonOut: parsed.opts.jsonOut,
      quiet: parsed.opts.quiet,
    });
    await parsed.node.run(st, { opts: parsed.opts, args: parsed.args });
  } catch (err) {
    report(err);
  }
}
