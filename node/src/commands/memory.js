/** memory：记忆文件读写、检索、树与 commit 任务。
 *
 * 路径规律（engine-memory/internal/engine/path.go）：`memory_path` 的**首段**必须是
 * `memories`（项目私有）或 `resources`（共享资源）之一，其余自由。路径是 `{path=**}`
 * 多段通配，逐段 encode 由 endpoints.js 负责。
 */

import { opt } from "../args.js";
import { UsageError } from "../errors.js";
import * as output from "../output.js";
import {
  BODY_FILE_OPT,
  BODY_OPT,
  PAGE_SIZE_OPT,
  PAGE_TOKEN_OPT,
  bodyOf,
  bytesOf,
  pagination,
  readBinary,
  readStdin,
} from "./_common.js";

const ROOTS = ["memories", "resources"];

const PATH_ARG = {
  name: "memory_path",
  help: `记忆路径，首段须是 ${ROOTS.join("/")}（如 memories/notes/a.md）`,
  required: true,
};
const FILE_ARG = { name: "file", help: "内容文件；缺省或 - 读 stdin" };

/** 首段校验：服务端只认 memories/resources，早点报错比往返一趟强。 */
function checked(memoryPath, { allowEmpty = false } = {}) {
  if (!memoryPath) {
    if (allowEmpty) return undefined;
    throw new UsageError(`需要记忆路径（首段须是 ${ROOTS.join("/")}）`);
  }
  const head = memoryPath.replace(/^\/+|\/+$/g, "").split("/")[0];
  if (!ROOTS.includes(head)) {
    throw new UsageError(
      `路径首段 ${JSON.stringify(head)} 不在域内（只允许 ${ROOTS.join("、")}）` +
        `—— 试 ${ROOTS[0]}/${memoryPath.replace(/^\/+/, "")}`,
    );
  }
  return memoryPath;
}

async function sourceOf(file) {
  if (!file || file === "-") return await readStdin();
  return readBinary(file);
}

function printTree(nodes, indent = 0) {
  for (const node of nodes || []) {
    const name = node.memoryPath || "?";
    const size = node.sizeBytes;
    const mark = node.isDir ? "/ " : "  ";
    const extra = size ? `  (${size}B)` : "";
    output.echo(`${"  ".repeat(indent)}${mark}${name}${extra}`);
    if (node.children) printTree(node.children, indent + 1);
  }
}

export const memory = {
  help: "记忆库 / 任务",
  commands: {
    list: {
      help: "列记忆条目（当前缀为空时服务端通常返回空，建议 --prefix memories）。",
      opts: [
        opt("prefix", ["--prefix"], { take: true, help: "路径前缀，如 memories/notes" }),
        opt("recursive", ["--recursive", "-r"], { help: "递归列" }),
        PAGE_SIZE_OPT,
        PAGE_TOKEN_OPT,
      ],
      run: async (st, { opts }) => {
        const query = pagination(opts.pageSize || 100, opts.pageToken, {
          prefix: checked(opts.prefix, { allowEmpty: true }),
          recursive: opts.recursive || undefined,
        });
        const payload = await st.client().call("memory.List", { query });
        output.emitItems(payload, {
          itemsKey: "entries",
          columns: [
            ["路径", "memoryPath"],
            ["大小", "sizeBytes"],
            ["更新时间", "updatedAt"],
          ],
          jsonOut: st.jsonOut,
        });
      },
    },

    read: {
      help: "读记忆内容（原始字节写 stdout，可直接重定向）。",
      args: [PATH_ARG],
      opts: [opt("level", ["--level"], { take: true, help: "读层级（ReadLevel 枚举，如 L0/L1）" })],
      run: async (st, { opts, args }) => {
        const payload = await st.client().call("memory.Read", {
          pathParams: { memory_path: checked(args[0]) },
          query: opts.level ? { level: opts.level } : undefined,
        });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        if (payload.content === undefined || payload.content === null) {
          output.emitObject(payload, { jsonOut: false });
          return;
        }
        output.writeBytes(bytesOf(payload.content));
      },
    },

    write: {
      help: "写记忆内容（`-` 或省略 = 读 stdin；content 是 bytes，编码由 CLI 负责）。",
      args: [PATH_ARG, FILE_ARG],
      opts: [
        opt("contentType", ["--content-type"], { take: true, help: "如 text/markdown" }),
        opt("ttl", ["--ttl"], { take: true, int: true, help: "存活秒数" }),
      ],
      run: async (st, { opts, args }) => {
        const data = await sourceOf(args[1]);
        const body = { content: data.toString("base64") };
        if (opts.contentType) body.contentType = opts.contentType;
        if (opts.ttl !== undefined) body.ttlSeconds = opts.ttl;
        const payload = await st.client().call("memory.Write", {
          pathParams: { memory_path: checked(args[0]) },
          body,
        });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(`已写入 ${args[0]}（${payload.bytesWritten ?? data.length} 字节）`);
      },
    },

    search: {
      help: "语义检索（流式：命中逐条到，不必等全量）。",
      args: [{ name: "query", help: "语义检索词", required: true }],
      opts: [
        opt("topK", ["--top-k"], { take: true, int: true, help: "返回条数（服务端要求 > 0）" }),
        opt("minScore", ["--min-score"], { take: true, help: "最低分" }),
        opt("scope", ["--scope"], { take: true, help: "限定路径前缀" }),
        opt("mode", ["--mode"], { take: true, help: "SearchMode 枚举" }),
        opt("paths", ["--paths"], { help: "只列命中路径（喂给 xargs）" }),
        BODY_OPT,
        BODY_FILE_OPT,
      ],
      run: async (st, { opts, args }) => {
        const body = (await bodyOf(opts)) || {};
        body.query ??= args[0];
        if (opts.topK !== undefined) body.topK ??= opts.topK;
        if (opts.minScore !== undefined) body.minScore ??= opts.minScore;
        if (opts.scope) body.scope ??= opts.scope;
        if (opts.mode) body.mode ??= opts.mode;

        const rows = [];
        let empty = true;
        for await (const hit of st.client().stream("memory.Search", { body })) {
          empty = false;
          if (st.jsonOut) {
            output.emitJson(hit);
            continue;
          }
          if (opts.paths) {
            output.echo(hit.memoryPath || "");
            continue;
          }
          rows.push(hit);
        }
        if (!empty && rows.length && !st.jsonOut) {
          output.emitTable(
            rows,
            [
              ["路径", "memoryPath"],
              ["得分", "score"],
              ["片段", "snippet"],
            ],
            { jsonOut: false },
          );
        } else if (empty && !st.jsonOut && !opts.paths) {
          output.echo("(无命中)");
        }
      },
    },

    tree: {
      help: "目录树。",
      opts: [
        opt("root", ["--root"], { take: true, help: `子树根，如 ${ROOTS.join(" 或 ")}` }),
        opt("depth", ["--depth"], { take: true, int: true, help: "深度上限" }),
      ],
      run: async (st, { opts }) => {
        const body = {};
        if (opts.root !== undefined) body.root = opts.root;
        if (opts.depth !== undefined) body.depthLimit = opts.depth;
        const payload = await st.client().call("memory.Tree", { body });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        printTree(payload.nodes || []);
      },
    },

    commit: {
      help: "把会话提交成记忆（异步，返回 taskId）。",
      opts: [
        opt("session", ["--session", "-s"], { take: true, help: "源会话 id" }),
        opt("note", ["--note"], { take: true, help: "备注（写进提交说明）" }),
      ],
      run: async (st, { opts }) => {
        if (!opts.session) throw new UsageError("需要 --session <会话 id>");
        const body = { sessionId: opts.session };
        if (opts.note) body.note = opts.note;
        const payload = await st.client().call("memory.CommitSession", { body });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(`任务 ${payload.taskId}；进度：rathflow memory watch-task ${payload.taskId}`);
      },
    },

    tasks: {
      help: "列 commit/索引任务。",
      opts: [
        opt("session", ["--session", "-s"], { take: true, help: "只看某会话的任务" }),
        PAGE_SIZE_OPT,
        PAGE_TOKEN_OPT,
      ],
      run: async (st, { opts }) => {
        const query = pagination(opts.pageSize || 50, opts.pageToken, { session_id: opts.session });
        const payload = await st.client().call("memory.ListTasks", { query });
        output.emitItems(payload, {
          itemsKey: "tasks",
          columns: [
            ["TASK ID", "taskId"],
            ["状态", "status"],
            ["创建", "createdAt"],
            ["完成", "finishedAt"],
          ],
          jsonOut: st.jsonOut,
        });
      },
    },

    task: {
      help: "看单个任务。",
      args: [{ name: "task_id", required: true }],
      run: async (st, { args }) => {
        const payload = await st.client().call("memory.GetTask", {
          pathParams: { task_id: args[0] },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    "watch-task": {
      help: "跟任务进度流（Ctrl-C 退出）。",
      args: [{ name: "task_id", required: true }],
      opts: [opt("wait", ["--wait"], { help: "阻塞到终态；失败时非零退出" })],
      run: async (st, { opts, args }) => {
        let final = null;
        for await (const frame of st.client().stream("memory.WatchTask", {
          pathParams: { task_id: args[0] },
        })) {
          final = frame;
          const status = frame.status || "?";
          if (st.jsonOut) output.emitJson(frame);
          else output.echo(status);
          if (opts.wait && /(SUCCEEDED|FAILED|CANCELED)$/.test(status)) break;
        }
        if (opts.wait && final && /(FAILED|CANCELED)$/.test(final.status || "")) {
          throw new UsageError(final.error || "任务失败");
        }
      },
    },
  },
};
