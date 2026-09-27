/** org：组织（团队空间）成员身份与邀请码。
 *
 * 注册时创建的 org 就是 web 的「个人空间」（`is_primary`），其余为团队空间。
 * 邀请码一次性：接受即作废，明文只在签发那一次出现。
 */

import { opt } from "../args.js";
import { UsageError } from "../errors.js";
import * as output from "../output.js";

const COLUMNS = [
  ["ORG ID", "orgId"],
  ["名称", "name"],
  ["slug", "slug"],
  ["角色", "role"],
  ["个人空间", "isPrimary"],
];

export const org = {
  help: "组织成员身份 / 邀请码",
  commands: {
    list: {
      help: "我加入的 org。",
      run: async (st) => {
        const payload = await st.client().call("tenant.ListMyOrgs");
        output.emitItems(payload, { itemsKey: "orgs", columns: COLUMNS, jsonOut: st.jsonOut });
      },
    },

    create: {
      help: "新建组织（自己是 OWNER，且会附带一个默认 project）。",
      opts: [opt("name", ["--name", "-n"], { take: true, help: "展示名（1..60 字符；slug 服务端派生）" })],
      run: async (st, { opts }) => {
        if (!opts.name) throw new UsageError("需要 --name");
        const payload = await st.client().call("tenant.CreateOrg", { body: { name: opts.name } });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        const created = payload.org || {};
        output.echo(`已创建 ${created.orgId || "?"}  ${created.name || opts.name}`);
        if (payload.defaultProjectId) {
          output.echo(`切过去：rathflow project use ${payload.defaultProjectId}`);
        }
      },
    },

    invite: {
      help: "签发成员邀请码（**明文只打印这一次**；OWNER 不发）。",
      args: [{ name: "org_id", help: "组织 id", required: true }],
      opts: [
        opt("ttl", ["--ttl"], { take: true, int: true, help: "有效期秒数；<=0 用服务端默认（7 天）" }),
        opt("role", ["--role"], { take: true, help: "加入后的角色：MEMBER（默认）或 ADMIN" }),
      ],
      run: async (st, { opts, args }) => {
        const orgId = args[0];
        const body = {};
        if (opts.ttl !== undefined) body.ttlSeconds = opts.ttl;
        if (opts.role) body.role = opts.role;
        const payload = await st.client().call("tenant.CreateOrgInvitation", {
          pathParams: { org_id: orgId },
          body,
        });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(payload.code || "", { err: true });
        const expires = payload.expiresAt;
        output.echo(
          `org=${payload.orgId || orgId}${expires ? `  到期 ${expires}` : ""}（明文只此一次）`,
          { err: true },
        );
      },
    },

    accept: {
      help: "接受邀请加入 org（org 由码反查，不用手填）。",
      args: [{ name: "code", help: "邀请码（一次性，接受即作废）", required: true }],
      run: async (st, { args }) => {
        const payload = await st.client().call("tenant.AcceptOrgInvitation", {
          body: { code: args[0] },
        });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(`已加入 ${payload.orgId || "?"}  ${payload.name || ""}`);
      },
    },
  },
};
