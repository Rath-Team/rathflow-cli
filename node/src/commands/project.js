/** project：项目（租户单元）的增删改查与作用域切换。 */

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
  requireProject,
} from "./_common.js";

const COLUMNS = [
  ["PROJECT ID", "projectId"],
  ["名称", "name"],
  ["创建时间", "createdAt"],
];

export const project = {
  help: "项目管理与作用域切换",
  commands: {
    list: {
      help: "列出当前账号可访问的项目。",
      opts: [PAGE_SIZE_OPT, PAGE_TOKEN_OPT],
      run: async (st, { opts }) => {
        const payload = await st.client().call("tenant.ListProjects", {
          query: pagination(opts.pageSize || 50, opts.pageToken),
        });
        output.emitItems(payload, { itemsKey: "projects", columns: COLUMNS, jsonOut: st.jsonOut });
      },
    },

    get: {
      help: "查看项目详情。",
      args: [{ name: "project_id", help: "缺省用当前作用域项目" }],
      run: async (st, { args }) => {
        const pid = args[0] || requireProject(st.project);
        const payload = await st.client().call("tenant.GetProject", {
          pathParams: { project_id: pid },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    create: {
      help: "建项目（创建者自动成为 owner）。",
      opts: [opt("name", ["--name", "-n"], { take: true, help: "项目名" })],
      run: async (st, { opts }) => {
        if (!opts.name) throw new UsageError("需要 --name");
        const payload = await st.client().call("tenant.CreateProject", { body: { name: opts.name } });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(`已创建 ${payload.projectId}  ${payload.name || opts.name}`);
        output.echo(`切过去：rathflow project use ${payload.projectId}`);
      },
    },

    update: {
      help: "改项目名（或用 --body 传整包）。",
      args: [{ name: "project_id", help: "缺省用当前作用域项目" }],
      opts: [
        opt("name", ["--name", "-n"], { take: true, help: "新项目名" }),
        BODY_OPT,
        BODY_FILE_OPT,
      ],
      run: async (st, { opts, args }) => {
        const pid = args[0] || requireProject(st.project);
        let body = await bodyOf(opts);
        if (body === undefined) {
          if (!opts.name) throw new UsageError("至少给 --name，或用 --body 传整包");
          body = { name: opts.name };
        }
        const payload = await st.client().call("tenant.UpdateProject", {
          body,
          pathParams: { project_id: pid },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    delete: {
      help: "删项目（不可逆）。",
      args: [{ name: "project_id", help: "缺省用当前作用域项目" }],
      opts: [YES_OPT],
      run: async (st, { opts, args }) => {
        const pid = args[0] || requireProject(st.project);
        if (!opts.yes) await confirm(`确认删除项目 ${pid}？此操作不可逆`);
        await st.client().call("tenant.DeleteProject", { pathParams: { project_id: pid } });
        output.echo(`已删除 ${pid}`);
      },
    },

    use: {
      help: "把项目设为默认作用域（此后所有命令都带它）。",
      args: [{ name: "project_id", help: "写入配置档的默认作用域", required: true }],
      run: async (st, { args }) => {
        st.profile.project = args[0];
        st.save();
        output.echo(`当前项目 → ${args[0]}`);
      },
    },

    "config-get": {
      help: "读项目配置（模型、限额等）。",
      args: [{ name: "project_id", help: "缺省用当前作用域项目" }],
      run: async (st, { args }) => {
        const pid = args[0] || requireProject(st.project);
        const payload = await st.client().call("tenant.GetProjectConfig", {
          pathParams: { project_id: pid },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    "config-set": {
      help: "改项目配置（PATCH 语义，只传要改的字段）。",
      args: [{ name: "project_id", help: "缺省用当前作用域项目" }],
      opts: [BODY_OPT, BODY_FILE_OPT],
      run: async (st, { opts, args }) => {
        const pid = args[0] || requireProject(st.project);
        const body = await bodyOf(opts);
        if (!body) throw new UsageError('需要 --body \'{"...":...}\'（只传要改的字段）');
        const payload = await st.client().call("tenant.UpdateProjectConfig", {
          body,
          pathParams: { project_id: pid },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    // ------------------------------------------------------------ 分享链接
    // 链接 = 能力凭证：明文 `link` 只在**创建/轮换那一次**的响应里出现，服务端只
    // 存摘要（同 API key 的「只显示一次」纪律）。撤销/过期后 `project shared` 里
    // 也不再出现。

    "share-set": {
      help: "建/改本项目的分享链接（PATCH 语义，只传要改的字段；换有效期得用 --rotate 重发）。",
      args: [{ name: "project_id", help: "缺省用当前作用域项目" }],
      opts: [
        opt("permission", ["--permission"], { take: true, help: "SharePermission 枚举，如 VIEW/EDIT" }),
        opt("password", ["--password"], {
          take: true,
          help: "设密码；给空串=清除（不给=保留原值）",
        }),
        opt("ttl", ["--ttl"], { take: true, int: true, help: "有效期秒数；<=0 永不过期（仅创建时生效）" }),
        opt("rotate", ["--rotate"], { help: "重发令牌，旧链接立即失效" }),
      ],
      run: async (st, { opts, args }) => {
        const pid = args[0] || requireProject(st.project);
        const body = {};
        if (opts.permission) body.permission = opts.permission;
        // password 是三态（保留/清除/覆盖），故判 undefined 而非真假
        if (opts.password !== undefined) body.password = opts.password;
        if (opts.ttl !== undefined) body.ttlSeconds = opts.ttl;
        if (opts.rotate) body.rotate = true;
        if (Object.keys(body).length === 0) {
          throw new UsageError("至少给一项要改的字段（--permission/--password/--ttl/--rotate）");
        }
        const payload = await st.client().call("tenant.UpdateProjectShare", {
          pathParams: { project_id: pid },
          body,
        });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        if (payload.link) {
          output.echo(payload.link, { err: true });
          output.echo("（明文只此一次，请立即存好）", { err: true });
        }
        const rest = { ...payload };
        delete rest.link;
        output.emitObject(rest, { jsonOut: false });
      },
    },

    "share-revoke": {
      help: "撤销分享（已在用的人立即失去入口）。",
      args: [{ name: "project_id", help: "缺省用当前作用域项目" }],
      opts: [YES_OPT],
      run: async (st, { opts, args }) => {
        const pid = args[0] || requireProject(st.project);
        if (!opts.yes) await confirm(`确认撤销项目 ${pid} 的分享链接？`);
        await st.client().call("tenant.RevokeProjectShare", { pathParams: { project_id: pid } });
        output.echo(`已撤销 ${pid} 的分享`);
      },
    },

    shared: {
      help: "我认领过的共享 project（分享被撤销/过期后不再出现）。",
      opts: [PAGE_SIZE_OPT, PAGE_TOKEN_OPT],
      run: async (st, { opts }) => {
        const payload = await st.client().call("tenant.ListSharedProjects", {
          query: pagination(opts.pageSize || 50, opts.pageToken),
        });
        output.emitItems(payload, { itemsKey: "projects", columns: COLUMNS, jsonOut: st.jsonOut });
      },
    },

    claim: {
      help: "认领一个共享 project（认领后进入 `project list`）。",
      args: [{ name: "token", help: "分享链接里的不透明令牌（整条链接也行）", required: true }],
      opts: [opt("password", ["--password"], { take: true, help: "链接设了密码时必填" })],
      run: async (st, { opts, args }) => {
        const body = { token: args[0].replace(/\/+$/, "").split("/").pop() };
        if (opts.password !== undefined) body.password = opts.password;
        const payload = await st.client().call("tenant.JoinSharedProject", { body });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        const claimed = payload.project || {};
        output.echo(`已认领 ${claimed.projectId || "?"}  ${claimed.name || ""}`);
        if (claimed.projectId) output.echo(`切过去：rathflow project use ${claimed.projectId}`);
      },
    },
  },
};
