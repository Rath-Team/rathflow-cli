/** workflow：工作流定义与删除。 */

import { opt } from "../args.js";
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

const COLUMNS = [
  ["WORKFLOW ID", "workflowId"],
  ["标题", "title"],
  ["状态", "status"],
  ["更新时间", "updatedAt"],
];

export const workflow = {
  help: "工作流",
  commands: {
    list: {
      help: "列工作流。",
      opts: [PAGE_SIZE_OPT, PAGE_TOKEN_OPT],
      run: async (st, { opts }) => {
        const payload = await st.client().call("workflow.ListWorkflows", {
          query: pagination(opts.pageSize || 50, opts.pageToken),
        });
        output.emitItems(payload, { itemsKey: "workflows", columns: COLUMNS, jsonOut: st.jsonOut });
      },
    },

    get: {
      help: "工作流详情。",
      args: [{ name: "workflow_id", required: true }],
      run: async (st, { args }) => {
        const payload = await st.client().call("workflow.GetWorkflow", {
          pathParams: { workflow_id: args[0] },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    counts: {
      help: "每个 project 的存活工作流数（服务端不返回 0 的行 = 没有）。",
      run: async (st) => {
        const payload = await st.client().call("workflow.CountWorkflowsByProject");
        output.emitItems(payload, {
          itemsKey: "counts",
          columns: [
            ["PROJECT ID", "projectId"],
            ["数量", "count"],
          ],
          jsonOut: st.jsonOut,
        });
      },
    },

    create: {
      help: "建工作流（图定义用 --body 传）。",
      opts: [opt("title", ["--title", "-t"], { take: true, help: "标题" }), BODY_OPT, BODY_FILE_OPT],
      run: async (st, { opts }) => {
        const body = (await bodyOf(opts)) || {};
        if (opts.title) body.title ??= opts.title;
        const payload = await st.client().call("workflow.CreateWorkflow", { body });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(payload.workflowId || "");
      },
    },

    delete: {
      help: "删工作流（连同其会话与沙箱；响应会报删了多少）。",
      args: [{ name: "workflow_id", required: true }],
      opts: [YES_OPT],
      run: async (st, { opts, args }) => {
        if (!opts.yes) await confirm(`确认删除工作流 ${args[0]}？其下会话与沙箱一并清理`);
        const payload = await st.client().call("workflow.DeleteWorkflow", {
          pathParams: { workflow_id: args[0] },
        });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(
          `已删除；清理会话 ${payload.sessionsDeleted || 0} 个、` +
            `沙箱 ${payload.sandboxesTerminated || 0} 个`,
        );
      },
    },
  },
};
