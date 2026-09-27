/** billing：订阅、用量与发票（只读）。 */

import { opt } from "../args.js";
import * as output from "../output.js";
import { PAGE_SIZE_OPT, PAGE_TOKEN_OPT, pagination } from "./_common.js";

export const billing = {
  help: "订阅 / 用量 / 发票",
  commands: {
    subscription: {
      help: "当前订阅。",
      opts: [opt("projectId", ["--project-id"], { take: true, help: "缺省用当前作用域项目" })],
      run: async (st, { opts }) => {
        const payload = await st.client().call("billing.GetSubscription", {
          query: { project_id: opts.projectId || st.project },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    usage: {
      help: "用量汇总。",
      opts: [
        opt("projectId", ["--project-id"], { take: true, help: "缺省用当前作用域项目" }),
        opt("start", ["--start"], { take: true, help: "RFC3339，如 2026-09-01T00:00:00Z" }),
        opt("end", ["--end"], { take: true, help: "RFC3339" }),
        opt("metrics", ["--metrics"], { take: true, help: "逗号分隔的指标名" }),
      ],
      run: async (st, { opts }) => {
        const payload = await st.client().call("billing.GetUsage", {
          query: {
            project_id: opts.projectId || st.project,
            start_time: opts.start,
            end_time: opts.end,
            metrics: opts.metrics,
          },
        });
        output.emitTable(
          payload.usages || [],
          [
            ["指标", "metric"],
            ["用量", "units"],
          ],
          { jsonOut: st.jsonOut },
        );
      },
    },

    invoices: {
      help: "发票列表。",
      opts: [
        opt("projectId", ["--project-id"], { take: true, help: "缺省用当前作用域项目" }),
        PAGE_SIZE_OPT,
        PAGE_TOKEN_OPT,
      ],
      run: async (st, { opts }) => {
        const query = pagination(opts.pageSize || 20, opts.pageToken, {
          project_id: opts.projectId || st.project,
        });
        const payload = await st.client().call("billing.ListInvoices", { query });
        output.emitItems(payload, {
          itemsKey: "invoices",
          columns: [
            ["INVOICE ID", "invoiceId"],
            ["编号", "number"],
            ["周期", "periodStart"],
            ["金额", "amountMinor"],
            ["币种", "currency"],
            ["状态", "status"],
          ],
          jsonOut: st.jsonOut,
        });
      },
    },
  },
};
