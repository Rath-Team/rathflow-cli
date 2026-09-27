/** asset：资产（skill / mcp_server / plugin）、版本、可见性与装配。
 *
 * 管理面（/admin/...）与消费面（/api/v1/...）同放一组命令：
 * 能不能跑通由服务端权限决定，CLI 不预先拦（403 会带原因回来）。
 */

import fs from "node:fs";

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

const KINDS = "skill | mcp_server | plugin";
const TIERS = "core | optional";
const LIFECYCLES = "active | retired";
const SCOPES = "global | plan | org";
const POLICIES = "immediate | on_idle | manual";

const COLUMNS = [
  ["ASSET ID", "assetId"],
  ["类型", "kind"],
  ["层级", "tier"],
  ["名称", "name"],
  ["启用", "enabled"],
  ["生效版本", "effectiveVersion"],
];

const ENUM_PREFIX = {
  ASSET_KIND: "ASSET_KIND_",
  ASSET_TIER: "ASSET_TIER_",
  ASSET_LIFECYCLE: "ASSET_LIFECYCLE_",
  VISIBILITY_SCOPE: "VISIBILITY_SCOPE_",
  RESTART_POLICY: "RESTART_POLICY_",
};
// CLI 上写的短名 → 枚举全名（protojson 认全名，也认短名，但只认大写）
const ENUM_ALIAS = { global: "GLOBAL", plan: "PLAN", org: "ORG" };

/** 'mcp_server' → 'ASSET_KIND_MCP_SERVER'；已是大写全名则原样。 */
function enumOf(prefix, value) {
  if (!value) return undefined;
  const text = ENUM_ALIAS[value.toLowerCase()] || value.toUpperCase();
  const full = ENUM_PREFIX[prefix];
  return text.startsWith(full) ? text : full + text;
}

async function setEnabled(st, assetId, enabled) {
  const payload = await st.client().call("assets.SetAssetEnabled", {
    pathParams: { asset_id: assetId },
    body: { enabled },
  });
  if (st.jsonOut) {
    output.emitJson(payload);
    return;
  }
  output.echo(`已${enabled ? "启用" : "停用"} ${assetId}`);
}

async function versionAction(st, key, assetId, versionId, done) {
  const payload = await st.client().call(key, {
    pathParams: { asset_id: assetId, version_id: versionId },
    body: {},
  });
  if (st.jsonOut) {
    output.emitJson(payload);
    return;
  }
  output.echo(`${done} ${assetId}/${versionId}`);
}

const VERSION_ID_OPT = opt("versionId", ["--version-id"], { take: true, help: "版本 id" });

export const asset = {
  help: "资产 / 版本 / 装配",
  commands: {
    // ---------------------------------------------------------------- 消费面

    list: {
      help: `列资产（含未启用）。kind：${KINDS}；tier：${TIERS}`,
      opts: [
        opt("kind", ["--kind"], { take: true, help: KINDS }),
        opt("tier", ["--tier"], { take: true, help: TIERS }),
        PAGE_SIZE_OPT,
        PAGE_TOKEN_OPT,
      ],
      run: async (st, { opts }) => {
        const query = pagination(opts.pageSize || 50, opts.pageToken, {
          kind: enumOf("ASSET_KIND", opts.kind),
          tier: enumOf("ASSET_TIER", opts.tier),
        });
        const payload = await st.client().call("assets.ListAssets", { query });
        output.emitItems(payload, { itemsKey: "assets", columns: COLUMNS, jsonOut: st.jsonOut });
      },
    },

    enabled: {
      help: "只看本项目已启用的资产。",
      opts: [PAGE_SIZE_OPT, PAGE_TOKEN_OPT],
      run: async (st, { opts }) => {
        const payload = await st.client().call("assets.ListEnabledAssets", {
          query: pagination(opts.pageSize || 50, opts.pageToken),
        });
        output.emitItems(payload, { itemsKey: "assets", columns: COLUMNS, jsonOut: st.jsonOut });
      },
    },

    get: {
      help: "资产详情。",
      args: [{ name: "asset_id", required: true }],
      run: async (st, { args }) => {
        const payload = await st.client().call("assets.GetAsset", {
          pathParams: { asset_id: args[0] },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    pin: {
      help: "把资产钉到指定版本。",
      args: [{ name: "asset_id", required: true }],
      opts: [VERSION_ID_OPT],
      run: async (st, { opts, args }) => {
        if (!opts.versionId) throw new UsageError("需要 --version-id");
        const payload = await st.client().call("assets.PinAssetVersion", {
          pathParams: { asset_id: args[0] },
          body: { versionId: opts.versionId },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    "set-config": {
      help: "写资产配置（Struct，用 --body 传）。",
      args: [{ name: "asset_id", required: true }],
      opts: [BODY_OPT, BODY_FILE_OPT],
      run: async (st, { opts, args }) => {
        const config = await bodyOf(opts);
        if (config === undefined) throw new UsageError('需要 --body \'{"...":...}\' 或 --body-file');
        const payload = await st.client().call("assets.SetAssetConfig", {
          pathParams: { asset_id: args[0] },
          body: { config },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    enable: {
      help: "在本项目启用资产。",
      args: [{ name: "asset_id", required: true }],
      run: (st, { args }) => setEnabled(st, args[0], true),
    },

    disable: {
      help: "在本项目停用资产。",
      args: [{ name: "asset_id", required: true }],
      run: (st, { args }) => setEnabled(st, args[0], false),
    },

    "set-credential": {
      help: "绑定凭据引用（**只填引用名，不传密钥本体**）。",
      args: [{ name: "asset_id", required: true }],
      opts: [
        opt("credRef", ["--cred-ref"], { take: true, help: "凭据引用（服务端密钥库里的键）" }),
        opt("injectAs", ["--inject-as"], { take: true, help: "注入方式" }),
        opt("injectKey", ["--inject-key"], { take: true, help: "注入键名" }),
      ],
      run: async (st, { opts, args }) => {
        if (!opts.credRef) throw new UsageError("需要 --cred-ref");
        const body = { credRef: opts.credRef };
        if (opts.injectAs) body.injectAs = opts.injectAs;
        if (opts.injectKey) body.injectKey = opts.injectKey;
        const payload = await st.client().call("assets.SetCredential", {
          pathParams: { asset_id: args[0] },
          body,
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    // ---------------------------------------------------------------- 管理面

    create: {
      help: `建资产（payload 用 --body 传）。kind：${KINDS}；tier：${TIERS}`,
      opts: [
        opt("kind", ["--kind"], { take: true, help: KINDS }),
        opt("tier", ["--tier"], { take: true, help: TIERS }),
        opt("name", ["--name", "-n"], { take: true, help: "名称" }),
        opt("description", ["--description", "-d"], { take: true, help: "描述" }),
        BODY_OPT,
        BODY_FILE_OPT,
      ],
      run: async (st, { opts }) => {
        if (!opts.kind || !opts.tier || !opts.name) {
          throw new UsageError("需要 --kind、--tier、--name");
        }
        const body = {
          kind: enumOf("ASSET_KIND", opts.kind),
          tier: enumOf("ASSET_TIER", opts.tier),
          name: opts.name,
        };
        if (opts.description) body.description = opts.description;
        const payload = await bodyOf(opts);
        if (payload) body.payload = payload;
        const out = await st.client().call("assets.CreateAsset", { body });
        if (st.jsonOut) {
          output.emitJson(out);
          return;
        }
        output.echo(out.assetId || "");
      },
    },

    "create-version": {
      help: "建版本（contribution_spec 用 --body 传）。",
      args: [{ name: "asset_id", required: true }],
      opts: [
        opt("version", ["--version", "-v"], { take: true, help: "版本号（语义化字符串）" }),
        opt("engineCompat", ["--engine-compat"], { take: true, help: "引擎兼容范围" }),
        opt("contentDigest", ["--content-digest"], { take: true, help: "内容摘要" }),
        BODY_OPT,
        BODY_FILE_OPT,
      ],
      run: async (st, { opts, args }) => {
        if (!opts.version) throw new UsageError("需要 --version");
        const body = { version: opts.version };
        if (opts.engineCompat) body.engineCompat = opts.engineCompat;
        if (opts.contentDigest) body.contentDigest = opts.contentDigest;
        const spec = await bodyOf(opts);
        if (spec) body.contributionSpec = spec;
        const out = await st.client().call("assets.CreateAssetVersion", {
          pathParams: { asset_id: args[0] },
          body,
        });
        if (st.jsonOut) {
          output.emitJson(out);
          return;
        }
        output.echo(out.versionId || "");
      },
    },

    update: {
      help: "改资产元信息（PATCH）。",
      args: [{ name: "asset_id", required: true }],
      opts: [BODY_OPT, BODY_FILE_OPT],
      run: async (st, { opts, args }) => {
        const body = await bodyOf(opts);
        if (!body) throw new UsageError("需要 --body（name/description/payload 中至少一项）");
        const payload = await st.client().call("assets.UpdateAsset", {
          pathParams: { asset_id: args[0] },
          body,
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    "put-content": {
      help: "上传版本内容（本地文件 → bytes；base64 编码由 CLI 负责）。",
      args: [{ name: "asset_id", required: true }],
      opts: [
        VERSION_ID_OPT,
        opt("file", ["--file", "-f"], { take: true, help: "本地文件路径（- = 读 stdin）" }),
        opt("contentType", ["--content-type"], { take: true, help: "内容类型" }),
      ],
      run: async (st, { opts, args }) => {
        if (!opts.versionId) throw new UsageError("需要 --version-id");
        if (!opts.file) throw new UsageError("需要 --file <路径|->");
        const data = opts.file === "-" ? await readStdin() : readBinary(opts.file);
        const body = { content: data.toString("base64") };
        if (opts.contentType) body.contentType = opts.contentType;
        const payload = await st.client().call("assets.PutAssetContent", {
          pathParams: { asset_id: args[0], version_id: opts.versionId },
          body,
        });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(`已上传 ${data.length} 字节 → ${args[0]}/${opts.versionId}`);
      },
    },

    publish: {
      help: "发布版本。",
      args: [{ name: "asset_id", required: true }],
      opts: [VERSION_ID_OPT],
      run: async (st, { opts, args }) => {
        if (!opts.versionId) throw new UsageError("需要 --version-id");
        await versionAction(st, "assets.PublishVersion", args[0], opts.versionId, "已发布");
      },
    },

    yank: {
      help: "撤回版本。",
      args: [{ name: "asset_id", required: true }],
      opts: [VERSION_ID_OPT],
      run: async (st, { opts, args }) => {
        if (!opts.versionId) throw new UsageError("需要 --version-id");
        await versionAction(st, "assets.YankVersion", args[0], opts.versionId, "已撤回");
      },
    },

    "set-lifecycle": {
      help: `改资产生命周期（${LIFECYCLES}）。`,
      args: [{ name: "asset_id", required: true }],
      opts: [opt("lifecycle", ["--lifecycle"], { take: true, help: LIFECYCLES })],
      run: async (st, { opts, args }) => {
        if (!opts.lifecycle) throw new UsageError("需要 --lifecycle");
        const payload = await st.client().call("assets.SetAssetLifecycle", {
          pathParams: { asset_id: args[0] },
          body: { lifecycle: enumOf("ASSET_LIFECYCLE", opts.lifecycle) },
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    "set-visibility": {
      help: `改可见性（${SCOPES}）。`,
      args: [{ name: "asset_id", required: true }],
      opts: [
        opt("scope", ["--scope"], { take: true, help: SCOPES }),
        opt("scopeRef", ["--scope-ref"], { take: true, help: "plan/org 作用域的目标 id" }),
        opt("visible", ["--visible"], { negate: ["--hidden"], default: true, help: "可见（--hidden 隐藏）" }),
      ],
      run: async (st, { opts, args }) => {
        if (!opts.scope) throw new UsageError("需要 --scope");
        const body = { scope: enumOf("VISIBILITY_SCOPE", opts.scope), visible: opts.visible };
        if (opts.scopeRef) body.scopeRef = opts.scopeRef;
        const payload = await st.client().call("assets.SetVisibility", {
          pathParams: { asset_id: args[0] },
          body,
        });
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    "sync-core": {
      help: "把内置 core 资产同步进库。",
      run: async (st) => {
        const payload = await st.client().call("assets.SyncCoreAssets", { body: {} });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(`新增 ${payload.added || 0}，更新 ${payload.updated || 0}`);
      },
    },

    // ---------------------------------------------------------------- 装配

    "assembly-status": {
      help: "看装配状态（desired/applied revision）。",
      run: async (st) => {
        const payload = await st.client().call("assets.GetAssemblyStatus");
        output.emitObject(payload, { jsonOut: st.jsonOut });
      },
    },

    "assembly-dispatch": {
      help: `触发一次装配下发（restart policy：${POLICIES}）。`,
      opts: [
        opt("projectId", ["--project-id"], { take: true, help: "缺省用当前作用域项目" }),
        opt("orgId", ["--org-id"], { take: true, help: "组织 id" }),
        opt("reason", ["--reason"], { take: true, help: "下发原因" }),
        opt("restartPolicy", ["--restart-policy"], { take: true, help: POLICIES }),
      ],
      run: async (st, { opts }) => {
        const body = {};
        const pid = opts.projectId || st.project;
        if (pid) body.projectId = pid;
        if (opts.orgId) body.orgId = opts.orgId;
        if (opts.reason) body.reason = opts.reason;
        if (opts.restartPolicy) body.restartPolicy = enumOf("RESTART_POLICY", opts.restartPolicy);
        const payload = await st.client().call("assets.TriggerAssemblyDispatch", { body });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        const dispatch = payload.dispatch || {};
        output.echo(`已触发：revision=${dispatch.revision} state=${dispatch.state}`);
      },
    },

    "assembly-revisions": {
      help: "列装配 revision 历史。",
      opts: [
        opt("projectId", ["--project-id"], { take: true, help: "缺省用当前作用域项目" }),
        opt("orgId", ["--org-id"], { take: true, help: "组织 id" }),
        PAGE_SIZE_OPT,
        PAGE_TOKEN_OPT,
      ],
      run: async (st, { opts }) => {
        const query = pagination(opts.pageSize || 20, opts.pageToken, {
          project_id: opts.projectId || st.project,
          org_id: opts.orgId,
        });
        const payload = await st.client().call("assets.ListAssemblyRevisions", { query });
        output.emitItems(payload, {
          itemsKey: "revisions",
          columns: [
            ["REV", "revision"],
            ["状态", "state"],
            ["需重启", "restartRequired"],
            ["原因", "reason"],
            ["创建时间", "createdAt"],
          ],
          jsonOut: st.jsonOut,
        });
      },
    },

    "assembly-artifact": {
      help: "取装配产物（patch_content 是 bytes）。",
      args: [
        { name: "project_id", required: true },
        { name: "revision", help: "revision 号", required: true },
      ],
      opts: [
        opt("out", ["--out", "-o"], { take: true, help: "写入文件；缺省 stdout" }),
        opt("meta", ["--meta"], { help: "只打印元信息，不吐 patch_content" }),
      ],
      run: async (st, { opts, args }) => {
        const revision = Number(args[1]);
        if (!Number.isInteger(revision)) throw new UsageError(`revision 需要整数，收到 ${args[1]}`);
        const payload = await st.client().call("assets.GetAssemblyArtifact", {
          pathParams: { project_id: args[0], revision },
        });
        if (st.jsonOut && !opts.meta) {
          output.emitJson(payload);
          return;
        }
        const info = { ...payload };
        delete info.patchContent;
        output.emitObject(info, { jsonOut: st.jsonOut });
        if (opts.meta || !payload.patchContent) return;
        const data = bytesOf(payload.patchContent);
        if (opts.out) {
          fs.writeFileSync(opts.out, data);
          output.echo(`已写入 ${opts.out}（${data.length} 字节）`, { err: true });
        } else {
          output.writeBytes(data);
        }
      },
    },
  },
};
