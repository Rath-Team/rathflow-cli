/** agent：Agent 定义、版本、运行与 Agent 目录。 */

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
  readStdin,
  readText,
  bytesOf,
} from "./_common.js";
import fs from "node:fs";

const DEF_COLUMNS = [
  ["AGENT DEF ID", "agentDefId"],
  ["名称", "name"],
  ["版本", "version"],
  ["状态", "status"],
  ["更新时间", "updatedAt"],
];
const RUN_COLUMNS = [
  ["RUN ID", "runId"],
  ["状态", "status"],
  ["提示词", "promptText"],
  ["创建时间", "createdAt"],
];

/** config_json 是自由 JSON 文本：字面量或文件（- 读 stdin）。 */
async function textOf(text, file) {
  if (text && file) throw new UsageError("--config 与 --config-file 不能同时用");
  if (!file) return text;
  if (file === "-") return (await readStdin()).toString("utf8");
  return readText(file);
}

const NAME_OPT = opt("name", ["--name", "-n"], { take: true, help: "名称" });
const DESCRIPTION_OPT = opt("description", ["--description", "-d"], { take: true, help: "描述" });
const CONFIG_OPT = opt("config", ["--config"], { take: true, help: "config_json 字面量（自由 JSON 文本）" });
const CONFIG_FILE_OPT = opt("configFile", ["--config-file"], {
  take: true,
  help: "从文件读 config_json（- 读 stdin）",
});
const MEMORY_BINDING_OPT = opt("memoryBinding", ["--memory-binding"], {
  take: true,
  help: "记忆绑定，如 memories/agents",
});

export const agent = {
  help: "Agent 定义 / 版本 / 运行 / 目录",
  commands: {
    // ---------------------------------------------------------------- 定义

    defs: {
      help: "列 Agent 定义。",
      opts: [PAGE_SIZE_OPT, PAGE_TOKEN_OPT],
      run: async (st, { opts }) => {
        const payload = await st.client().call("agent.ListAgentDefs", {
          query: pagination(opts.pageSize || 50, opts.pageToken),
        });
        output.emitItems(payload, { itemsKey: "agentDefs", columns: DEF_COLUMNS, jsonOut: st.jsonOut });
      },
    },

    def: {
      help: "看定义详情。",
      args: [{ name: "agent_def_id", required: true }],
      run: async (st, { args }) => {
        const payload = await st.client().call("agent.GetAgentDef", {
          pathParams: { agent_def_id: args[0] },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    "def-create": {
      help: "建 Agent 定义。",
      opts: [
        NAME_OPT,
        DESCRIPTION_OPT,
        CONFIG_OPT,
        CONFIG_FILE_OPT,
        MEMORY_BINDING_OPT,
        BODY_OPT,
        BODY_FILE_OPT,
      ],
      run: async (st, { opts }) => {
        if (!opts.name) throw new UsageError("需要 --name");
        const body = (await bodyOf(opts)) || {};
        body.name ??= opts.name;
        if (opts.description) body.description ??= opts.description;
        if (opts.memoryBinding) body.memoryBinding ??= opts.memoryBinding;
        const text = await textOf(opts.config, opts.configFile);
        if (text !== undefined) body.configJson ??= text;
        const payload = await st.client().call("agent.CreateAgentDef", { body });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(payload.agentDefId || "");
      },
    },

    "def-update": {
      help: "改定义（PATCH 语义；改完通常产生新版本）。",
      args: [{ name: "agent_def_id", required: true }],
      opts: [
        NAME_OPT,
        DESCRIPTION_OPT,
        CONFIG_OPT,
        CONFIG_FILE_OPT,
        MEMORY_BINDING_OPT,
        opt("status", ["--status"], { take: true, help: "AgentDefStatus 枚举" }),
        BODY_OPT,
        BODY_FILE_OPT,
      ],
      run: async (st, { opts, args }) => {
        const body = (await bodyOf(opts)) || {};
        for (const [key, value] of [
          ["name", opts.name],
          ["description", opts.description],
          ["memoryBinding", opts.memoryBinding],
          ["status", opts.status],
        ]) {
          if (value) body[key] ??= value;
        }
        const text = await textOf(opts.config, opts.configFile);
        if (text !== undefined) body.configJson ??= text;
        if (Object.keys(body).length === 0) {
          throw new UsageError(
            "至少给一项要改的字段（--name/--description/--config/--memory-binding/--status）",
          );
        }
        const payload = await st.client().call("agent.UpdateAgentDef", {
          pathParams: { agent_def_id: args[0] },
          body,
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    "def-delete": {
      help: "删定义。",
      args: [{ name: "agent_def_id", required: true }],
      opts: [YES_OPT],
      run: async (st, { opts, args }) => {
        if (!opts.yes) await confirm(`确认删除 Agent 定义 ${args[0]}？`);
        await st.client().call("agent.DeleteAgentDef", { pathParams: { agent_def_id: args[0] } });
        output.echo(`已删除 ${args[0]}`);
      },
    },

    versions: {
      help: "列定义的版本。",
      args: [{ name: "agent_def_id", required: true }],
      opts: [PAGE_SIZE_OPT, PAGE_TOKEN_OPT],
      run: async (st, { opts, args }) => {
        const payload = await st.client().call("agent.ListAgentDefVersions", {
          pathParams: { agent_def_id: args[0] },
          query: pagination(opts.pageSize || 50, opts.pageToken),
        });
        output.emitItems(payload, {
          itemsKey: "versions",
          columns: [
            ["版本", "version"],
            ["创建人", "createdBy"],
            ["创建时间", "createdAt"],
          ],
          jsonOut: st.jsonOut,
        });
      },
    },

    version: {
      help: "看某个版本。",
      args: [
        { name: "agent_def_id", required: true },
        { name: "version", help: "版本号", required: true },
      ],
      run: async (st, { args }) => {
        const version = Number(args[1]);
        if (!Number.isInteger(version)) throw new UsageError(`version 需要整数，收到 ${args[1]}`);
        const payload = await st.client().call("agent.GetAgentDefVersion", {
          pathParams: { agent_def_id: args[0], version },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    // ---------------------------------------------------------------- 运行

    prompt: {
      help: "给会话发提示词，起一个 run（返回 runId；进度用 `session watch` 跟）。",
      args: [
        { name: "session_id", required: true },
        { name: "text", help: "提示词；缺省或 - 读 stdin" },
      ],
      opts: [BODY_OPT, BODY_FILE_OPT],
      run: async (st, { opts, args }) => {
        let body = await bodyOf(opts);
        if (body === undefined) {
          const text = args[1] === undefined || args[1] === "-" ? (await readStdin()).toString("utf8") : args[1];
          body = { text };
        }
        const payload = await st.client().call("agent.Prompt", {
          pathParams: { session_id: args[0] },
          body,
        });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(payload.runId || "");
      },
    },

    runs: {
      help: "列会话下的 run。",
      args: [{ name: "session_id", required: true }],
      opts: [PAGE_SIZE_OPT, PAGE_TOKEN_OPT],
      run: async (st, { opts, args }) => {
        const payload = await st.client().call("agent.ListRuns", {
          pathParams: { session_id: args[0] },
          query: pagination(opts.pageSize || 50, opts.pageToken),
        });
        output.emitItems(payload, { itemsKey: "runs", columns: RUN_COLUMNS, jsonOut: st.jsonOut });
      },
    },

    run: {
      help: "看单个 run。",
      args: [{ name: "run_id", required: true }],
      run: async (st, { args }) => {
        const payload = await st.client().call("agent.GetRun", { pathParams: { run_id: args[0] } });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    // ---------------------------------------------------------------- 目录

    directory: {
      help: "列 Agent 目录（跨 project 可见的 agent 地址）。",
      opts: [PAGE_SIZE_OPT, PAGE_TOKEN_OPT],
      run: async (st, { opts }) => {
        const payload = await st.client().call("agent.ListAgentDirectory", {
          query: pagination(opts.pageSize || 50, opts.pageToken),
        });
        output.emitItems(payload, {
          itemsKey: "entries",
          columns: [
            ["AGENT ID", "agentId"],
            ["地址", "address"],
            ["状态", "status"],
          ],
          jsonOut: st.jsonOut,
        });
      },
    },

    resolve: {
      help: "把 agent id 解析成地址。",
      args: [{ name: "agent_id", required: true }],
      run: async (st, { args }) => {
        const payload = await st.client().call("agent.ResolveAgentAddress", {
          pathParams: { agent_id: args[0] },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    messages: {
      help: "看某个 agent 的消息记录。",
      args: [{ name: "agent_id", required: true }],
      opts: [PAGE_SIZE_OPT, PAGE_TOKEN_OPT],
      run: async (st, { opts, args }) => {
        const payload = await st.client().call("agent.ListAgentMessages", {
          pathParams: { agent_id: args[0] },
          query: pagination(opts.pageSize || 50, opts.pageToken),
        });
        output.emitItems(payload, {
          itemsKey: "messages", // 见 ListAgentMessagesResponse
          columns: [
            ["MESSAGE ID", "messageId"],
            ["方向", "direction"],
            ["对端", "peerAgentId"],
            ["负载", "payloadJson"],
          ],
          jsonOut: st.jsonOut,
        });
      },
    },

    attachment: {
      help: "读附件字节（流式，分片直写，不整包缓冲）。",
      args: [{ name: "attachment_id", help: "sha256:<hex>，取自事件里的 attachmentRef", required: true }],
      opts: [opt("out", ["--out", "-o"], { take: true, help: "写文件；缺省写 stdout" })],
      run: async (st, { opts, args }) => {
        let fd = null;
        try {
          if (opts.out) {
            try {
              fd = fs.openSync(opts.out, "w");
            } catch (err) {
              throw new UsageError(`写入失败：${err.message}`);
            }
          }
          for await (const chunk of st.client().stream("agent.ReadAttachment", {
            pathParams: { attachment_id: args[0] },
          })) {
            if (st.jsonOut) {
              output.emitJson(chunk);
              continue;
            }
            const data = bytesOf(chunk.data);
            if (!data.length) continue;
            if (fd !== null) fs.writeSync(fd, data);
            else output.writeBytes(data);
          }
        } finally {
          if (fd !== null) fs.closeSync(fd);
        }
      },
    },
  },
};
