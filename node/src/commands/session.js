/** session：会话、block、事件流与 block 分享。 */

import { opt } from "../args.js";
import { UsageError } from "../errors.js";
import * as output from "../output.js";
import {
  BODY_FILE_OPT,
  BODY_OPT,
  PAGE_SIZE_OPT,
  PAGE_TOKEN_OPT,
  YES_OPT,
  bodyOf,
  confirm,
  pagination,
} from "./_common.js";

export const SESSION_COLUMNS = [
  ["SESSION ID", "sessionId"],
  ["状态", "status"],
  ["标题", "title"],
  ["AGENT", "agentDefId"],
  ["创建时间", "createdAt"],
];
export const BLOCK_COLUMNS = [
  ["BLOCK ID", "blockId"],
  ["标题", "title"],
  ["事件区间", "fromSeq"],
  ["到", "toSeq"],
  ["创建时间", "createdAt"],
];

export const session = {
  help: "会话 / block / 事件流",
  commands: {
    list: {
      help: "列出本项目会话。",
      opts: [
        PAGE_SIZE_OPT,
        PAGE_TOKEN_OPT,
        opt("status", ["--status"], { take: true, help: "按状态过滤" }),
      ],
      run: async (st, { opts }) => {
        const payload = await st.client().call("session.ListSessions", {
          query: pagination(opts.pageSize || 50, opts.pageToken, { status: opts.status }),
        });
        output.emitItems(payload, {
          itemsKey: "sessions",
          columns: SESSION_COLUMNS,
          jsonOut: st.jsonOut,
        });
      },
    },

    get: {
      help: "会话详情。",
      args: [{ name: "session_id", required: true }],
      run: async (st, { args }) => {
        const payload = await st.client().call("session.GetSession", {
          pathParams: { session_id: args[0] },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    create: {
      help: "建会话。",
      opts: [
        BODY_OPT,
        BODY_FILE_OPT,
        opt("title", ["--title"], { take: true, help: "标题（等价于 --body 里给 title）" }),
      ],
      run: async (st, { opts }) => {
        let body = await bodyOf(opts);
        if (body === undefined) body = opts.title ? { title: opts.title } : {};
        const payload = await st.client().call("session.CreateSession", { body });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(payload.sessionId || "");
      },
    },

    delete: {
      help: "删会话。",
      args: [{ name: "session_id", required: true }],
      opts: [YES_OPT],
      run: async (st, { opts, args }) => {
        if (!opts.yes) await confirm(`确认删除会话 ${args[0]}？`);
        await st.client().call("session.DeleteSession", { pathParams: { session_id: args[0] } });
        output.echo(`已删除 ${args[0]}`);
      },
    },

    archive: {
      help: "归档会话。",
      args: [{ name: "session_id", required: true }],
      run: async (st, { args }) => {
        const payload = await st.client().call("session.ArchiveSession", {
          pathParams: { session_id: args[0] },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    lineage: {
      help: "血统（fork/派生关系）。",
      args: [{ name: "session_id", required: true }],
      run: async (st, { args }) => {
        const payload = await st.client().call("session.GetSessionLineage", {
          pathParams: { session_id: args[0] },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    interrupt: {
      help: "打断正在跑的 run（agent.Interrupt）。",
      args: [{ name: "session_id", required: true }],
      run: async (st, { args }) => {
        const payload = await st.client().call("agent.Interrupt", {
          pathParams: { session_id: args[0] },
          body: {},
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    // ---------------------------------------------------------------- block

    blocks: {
      help: "列会话下的 block。",
      args: [{ name: "session_id", required: true }],
      opts: [PAGE_SIZE_OPT, PAGE_TOKEN_OPT],
      run: async (st, { opts, args }) => {
        const payload = await st.client().call("session.ListBlocks", {
          pathParams: { session_id: args[0] },
          query: pagination(opts.pageSize || 50, opts.pageToken),
        });
        output.emitItems(payload, {
          itemsKey: "blocks",
          columns: BLOCK_COLUMNS,
          jsonOut: st.jsonOut,
        });
      },
    },

    block: {
      help: "看单个 block。",
      args: [{ name: "block_id", required: true }],
      run: async (st, { args }) => {
        const payload = await st.client().call("session.GetBlock", {
          pathParams: { block_id: args[0] },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    "block-create": {
      help: "给会话加 block（内容用 --body/--body-file 传）。",
      args: [{ name: "session_id", required: true }],
      opts: [BODY_OPT, BODY_FILE_OPT],
      run: async (st, { opts, args }) => {
        const body = await bodyOf(opts);
        if (body === undefined) {
          throw new UsageError('需要 --body \'{"type":...,...}\' 或 --body-file <路径|->');
        }
        const payload = await st.client().call("session.CreateBlock", {
          pathParams: { session_id: args[0] },
          body,
        });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(payload.blockId || "");
      },
    },

    "block-delete": {
      help: "删 block。",
      args: [{ name: "block_id", required: true }],
      opts: [YES_OPT],
      run: async (st, { opts, args }) => {
        if (!opts.yes) await confirm(`确认删除 block ${args[0]}？`);
        await st.client().call("session.DeleteBlock", { pathParams: { block_id: args[0] } });
        output.echo(`已删除 ${args[0]}`);
      },
    },

    share: {
      help: "把 block 分享给别人（scope 用 --body 传）。",
      args: [{ name: "block_id", required: true }],
      opts: [BODY_OPT, BODY_FILE_OPT],
      run: async (st, { opts, args }) => {
        const payload = await st.client().call("session.ShareBlock", {
          pathParams: { block_id: args[0] },
          body: (await bodyOf(opts)) || {},
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    unshare: {
      help: "撤销 block 分享。",
      args: [{ name: "share_id", required: true }],
      run: async (st, { args }) => {
        await st.client().call("session.RevokeBlockShare", { pathParams: { share_id: args[0] } });
        output.echo(`已撤销 ${args[0]}`);
      },
    },

    // ---------------------------------------------------------------- 事件

    events: {
      help: "拉历史事件（一次性）。",
      args: [{ name: "session_id", required: true }],
      opts: [PAGE_SIZE_OPT, PAGE_TOKEN_OPT],
      run: async (st, { opts, args }) => {
        const payload = await st.client().call("session.GetSessionEvents", {
          pathParams: { session_id: args[0] },
          query: pagination(opts.pageSize || 100, opts.pageToken),
        });
        output.emitItems(payload, {
          itemsKey: "events",
          columns: [
            ["SEQ", "seq"],
            ["数据", "payloadJson"],
            ["时间", "createdAt"],
          ],
          jsonOut: st.jsonOut,
        });
      },
    },

    watch: {
      help: "跟事件流（:stream，长连，Ctrl-C 退出）。",
      args: [{ name: "session_id", required: true }],
      opts: [
        opt("raw", ["--raw"], { help: "逐帧原样打印 JSON，不渲染" }),
        opt("fromSeq", ["--from-seq"], { take: true, int: true, help: "从该 seq 续传（断线重连用）" }),
      ],
      run: async (st, { opts, args }) => {
        const query = opts.fromSeq !== undefined ? { from_seq: opts.fromSeq } : undefined;
        for await (const frame of st.client().stream("session.StreamSessionEvents", {
          pathParams: { session_id: args[0] },
          query,
        })) {
          if (st.jsonOut || opts.raw) {
            output.emitJson(frame);
            continue;
          }
          const seq = frame.seq;
          const prefix = seq !== undefined ? `${String(seq).padStart(6)}  ` : "";
          output.echo(prefix + output.cell(frame.payloadJson ?? frame));
        }
      },
    },
  },
};
