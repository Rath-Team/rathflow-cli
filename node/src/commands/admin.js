/** admin：平台管理（用户、上下文令牌签名密钥）。 */

import { opt } from "../args.js";
import { UsageError } from "../errors.js";
import * as output from "../output.js";
import { PAGE_SIZE_OPT, PAGE_TOKEN_OPT, pagination } from "./_common.js";

export const admin = {
  help: "平台管理（需平台管理员）",
  commands: {
    users: {
      help: "列平台用户。",
      opts: [PAGE_SIZE_OPT, PAGE_TOKEN_OPT],
      run: async (st, { opts }) => {
        const payload = await st.client().call("admin.ListUsers", {
          query: pagination(opts.pageSize || 50, opts.pageToken),
        });
        output.emitItems(payload, {
          itemsKey: "users",
          columns: [
            ["USER ID", "userId"],
            ["邮箱", "email"],
            ["名称", "displayName"],
            ["状态", "status"],
            ["管理员", "isPlatformAdmin"],
            ["注册时间", "createdAt"],
          ],
          jsonOut: st.jsonOut,
        });
      },
    },

    promote: {
      help: "授予/收回平台管理员。",
      args: [{ name: "user_id", required: true }],
      opts: [
        opt("admin", ["--admin"], { negate: ["--demote"], default: true, help: "授予（--demote 收回）" }),
      ],
      run: async (st, { opts, args }) => {
        const payload = await st.client().call("admin.PromoteUser", {
          pathParams: { user_id: args[0] },
          body: { isPlatformAdmin: opts.admin },
        });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(`${args[0]} → ${opts.admin ? "平台管理员" : "普通用户"}`);
      },
    },

    "set-status": {
      help: "启用/停用账号。",
      args: [{ name: "user_id", required: true }],
      opts: [opt("status", ["--status"], { take: true, help: "active | disabled" })],
      run: async (st, { opts, args }) => {
        if (!opts.status) throw new UsageError("需要 --status（active | disabled）");
        const payload = await st.client().call("admin.SetUserStatus", {
          pathParams: { user_id: args[0] },
          body: { status: `USER_STATUS_${opts.status.toUpperCase()}` },
        });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(`${args[0]} → ${opts.status}`);
      },
    },

    "rotate-context-key": {
      help: "轮换上下文令牌签名密钥（reason 走 query，该接口无 body）。",
      opts: [opt("reason", ["--reason"], { take: true, help: "轮换原因（记入审计）" })],
      run: async (st, { opts }) => {
        const payload = await st.client().call("admin.RotateContextTokenKey", {
          query: opts.reason ? { reason: opts.reason } : undefined,
        });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(`新密钥 ${payload.keyId} 生效于 ${payload.effectiveAt}`);
      },
    },
  },
};
