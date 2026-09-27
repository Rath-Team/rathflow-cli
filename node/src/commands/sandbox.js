/** sandbox：沙箱生命周期、执行（流式）、文件读取与日志。 */

import { opt } from "../args.js";
import { ApiError, UsageError } from "../errors.js";
import * as output from "../output.js";
import {
  BODY_FILE_OPT,
  BODY_OPT,
  PAGE_SIZE_OPT,
  PAGE_TOKEN_OPT,
  YES_OPT,
  bodyOf,
  bytesOf,
  confirm,
  pagination,
  pairs,
  readStdin,
  readText,
} from "./_common.js";

const SANDBOX_COLUMNS = [
  ["SANDBOX ID", "sandboxId"],
  ["名称", "name"],
  ["状态", "status"],
  ["隔离级别", "effectiveIsolation"],
  ["到期", "expiresAt"],
];

/** 流式抽干一个执行流：stdout→stdout，stderr→stderr，返回远端退出码。 */
async function pump(st, key, sandboxId, body) {
  let exitCode = 0;
  for await (const chunk of st.client().stream(key, {
    pathParams: { sandbox_id: sandboxId },
    body,
  })) {
    const stdout = bytesOf(chunk.stdout);
    const stderr = bytesOf(chunk.stderr);
    if (stdout.length) output.writeBytes(stdout);
    if (stderr.length) output.writeBytes(stderr, { toStderr: true });
    if (chunk.errorCode) {
      throw new ApiError(0, chunk.errorCode, chunk.errorMessage || "执行失败");
    }
    if (chunk.truncated) output.echo("[截断：输出达服务端上限]", { err: true });
    if (chunk.exitCode !== undefined && chunk.exitCode !== null) exitCode = Number(chunk.exitCode);
  }
  return exitCode;
}

async function streamJson(st, key, sandboxId, body) {
  for await (const chunk of st.client().stream(key, {
    pathParams: { sandbox_id: sandboxId },
    body,
  })) {
    output.emitJson(chunk);
  }
}

export const sandbox = {
  help: "沙箱 / 执行 / 文件 / 日志",
  commands: {
    list: {
      help: "列本项目沙箱（含已终止）。",
      opts: [PAGE_SIZE_OPT, PAGE_TOKEN_OPT],
      run: async (st, { opts }) => {
        const payload = await st.client().call("sandbox.List", {
          query: pagination(opts.pageSize || 50, opts.pageToken),
        });
        output.emitItems(payload, {
          itemsKey: "sandboxes",
          columns: SANDBOX_COLUMNS,
          jsonOut: st.jsonOut,
        });
      },
    },

    get: {
      help: "沙箱详情。",
      args: [{ name: "sandbox_id", required: true }],
      run: async (st, { args }) => {
        const payload = await st.client().call("sandbox.Get", {
          pathParams: { sandbox_id: args[0] },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    create: {
      help: "建沙箱（隔离级别等用 --body 传）。",
      opts: [opt("name", ["--name", "-n"], { take: true, help: "沙箱名" }), BODY_OPT, BODY_FILE_OPT],
      run: async (st, { opts }) => {
        const body = (await bodyOf(opts)) || {};
        if (opts.name) body.name ??= opts.name;
        const payload = await st.client().call("sandbox.Create", { body });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(payload.sandboxId || "");
      },
    },

    terminate: {
      help: "终止沙箱。",
      args: [{ name: "sandbox_id", required: true }],
      opts: [YES_OPT],
      run: async (st, { opts, args }) => {
        if (!opts.yes) await confirm(`确认终止沙箱 ${args[0]}？`);
        await st.client().call("sandbox.Terminate", { pathParams: { sandbox_id: args[0] } });
        output.echo(`已终止 ${args[0]}`);
      },
    },

    renew: {
      help: "续期沙箱。",
      args: [{ name: "sandbox_id", required: true }],
      opts: [BODY_OPT, BODY_FILE_OPT],
      run: async (st, { opts, args }) => {
        const payload = await st.client().call("sandbox.Renew", {
          pathParams: { sandbox_id: args[0] },
          body: (await bodyOf(opts)) || {},
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    "expose-port": {
      help: "暴露端口，打印可达地址。",
      args: [
        { name: "sandbox_id", required: true },
        { name: "port", help: "沙箱内端口", required: true },
      ],
      opts: [opt("protocol", ["--protocol"], { take: true, help: "协议（如 http）" })],
      run: async (st, { opts, args }) => {
        const body = { port: Number(args[1]) };
        if (!Number.isInteger(body.port)) throw new UsageError(`port 需要整数，收到 ${args[1]}`);
        if (opts.protocol) body.protocol = opts.protocol;
        const payload = await st.client().call("sandbox.ExposePort", {
          pathParams: { sandbox_id: args[0] },
          body,
        });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(
          payload.url || `(backend 未上报地址；assigned_port=${payload.assignedPort})`,
        );
      },
    },

    // ---------------------------------------------------------------- 执行

    exec: {
      help: "在沙箱里执行命令（流式；远端非零退出码原样透传为 CLI 退出码）。",
      args: [
        { name: "sandbox_id", required: true },
        { name: "command", help: "要执行的命令（经 shell 解释）", required: true },
      ],
      opts: [
        opt("workdir", ["--workdir", "-w"], { take: true, help: "工作目录" }),
        opt("env", ["--env", "-e"], { take: true, list: true, help: "环境变量 k=v，可重复" }),
      ],
      run: async (st, { opts, args }) => {
        const body = { command: args[1] };
        if (opts.workdir) body.workdir = opts.workdir;
        if (opts.env?.length) body.env = pairs(opts.env);
        if (st.jsonOut) {
          await streamJson(st, "sandbox.RunCommand", args[0], body);
          return;
        }
        const code = await pump(st, "sandbox.RunCommand", args[0], body);
        if (code) process.exitCode = code;
      },
    },

    code: {
      help: "在沙箱里跑一段源码（流式）。",
      args: [
        { name: "sandbox_id", required: true },
        { name: "file", help: "源码文件；缺省或 - 读 stdin" },
      ],
      opts: [opt("language", ["--language", "-l"], { take: true, help: "python / bash / ..." })],
      run: async (st, { opts, args }) => {
        if (!opts.language) throw new UsageError("需要 --language（如 -l python）");
        const file = args[1];
        const source =
          file && file !== "-" ? readText(file) : (await readStdin()).toString("utf8");
        const body = { language: opts.language, code: source };
        if (st.jsonOut) {
          await streamJson(st, "sandbox.RunCode", args[0], body);
          return;
        }
        const exitCode = await pump(st, "sandbox.RunCode", args[0], body);
        if (exitCode) process.exitCode = exitCode;
      },
    },

    logs: {
      help: "沙箱日志（流式；stderr 分流到 stderr），Ctrl-C 退出。当前 backend 未实现沙箱级日志面（返回 CODE_UNIMPLEMENTED），要取实时输出请用 `sandbox exec` 的流帧。",
      args: [{ name: "sandbox_id", required: true }],
      opts: [opt("tail", ["--tail"], { take: true, int: true, help: "回看行数（服务端支持时生效）" })],
      run: async (st, { opts, args }) => {
        const query = opts.tail !== undefined ? { tail: opts.tail } : undefined;
        for await (const chunk of st.client().stream("sandbox.StreamLogs", {
          pathParams: { sandbox_id: args[0] },
          query,
        })) {
          if (st.jsonOut) {
            output.emitJson(chunk);
            continue;
          }
          const data = bytesOf(chunk.data);
          if (!data.length) continue;
          if (chunk.stderr) output.writeBytes(data, { toStderr: true });
          else output.writeBytes(data);
          if (chunk.truncated) output.echo("\n[截断：输出达服务端上限]", { err: true });
        }
      },
    },

    // ---------------------------------------------------------------- 文件

    ls: {
      help: "列目录。",
      args: [{ name: "sandbox_id", required: true }],
      opts: [
        opt("path", ["--path", "-p"], { take: true, default: "/", help: "相对沙箱根；缺省根目录" }),
      ],
      run: async (st, { opts, args }) => {
        // 该 backend 要求 path 必填（传空报 CODE_INVALID_ARGUMENT），故缺省给根
        const payload = await st.client().call("sandbox.ListDir", {
          pathParams: { sandbox_id: args[0] },
          query: { path: opts.path },
        });
        output.emitTable(
          payload.entries || [],
          [
            ["类型", "type"],
            ["大小", "sizeBytes"],
            ["时间", "modifiedAt"],
            ["名称", "name"],
          ],
          { jsonOut: st.jsonOut },
        );
      },
    },

    stat: {
      help: "看单个路径的元信息（须为单文件路径，见 StatRequest 注释）。",
      args: [{ name: "sandbox_id", required: true }],
      opts: [opt("path", ["--path", "-p"], { take: true, help: "沙箱内相对路径" })],
      run: async (st, { opts, args }) => {
        if (!opts.path) throw new UsageError("需要 --path <沙箱内路径>");
        const payload = await st.client().call("sandbox.Stat", {
          pathParams: { sandbox_id: args[0] },
          query: { path: opts.path },
        });
        output.emitObject(payload.entry || payload, { jsonOut: st.jsonOut });
      },
    },

    cat: {
      help: "读文件到 stdout（流式分片直写，不整包缓冲）。",
      args: [{ name: "sandbox_id", required: true }],
      opts: [opt("path", ["--path", "-p"], { take: true, help: "沙箱内相对路径" })],
      run: async (st, { opts, args }) => {
        if (!opts.path) throw new UsageError("需要 --path <沙箱内路径>");
        for await (const chunk of st.client().stream("sandbox.ReadFile", {
          pathParams: { sandbox_id: args[0], path: opts.path },
        })) {
          if (st.jsonOut) {
            output.emitJson(chunk);
            continue;
          }
          const data = bytesOf(chunk.data);
          if (data.length) output.writeBytes(data);
        }
      },
    },
  },
};
