/** REST 端点表 —— 全 CLI 的路径唯一事实源（**禁止在命令实现里写 URL 字面量**）。
 *
 * 内容与 web/lib/api/generated/endpoints.ts 同源（proto → grpc-gateway 生成），
 * 也与 Python 版 cli/python/rathflow_cli/endpoints.py 逐行对应。契约变了改本文件；
 * `node src/selftest.js` 会挡住漂移。
 *
 * 值 = [HTTP 方法, 路径模板]。模板里的 `{name}` 是 proto 字段名（snake_case）。
 */

import { UsageError } from "./errors.js";

export const ENDPOINTS = {
  // ---- auth ----
  "auth.IssueAPIKey": ["POST", "/api/v1/api-keys"],
  "auth.ListAPIKeys": ["GET", "/api/v1/api-keys"],
  "auth.Login": ["POST", "/api/v1/auth/login"],
  "auth.Logout": ["POST", "/api/v1/auth/logout"],
  "auth.Refresh": ["POST", "/api/v1/auth/refresh"],
  "auth.Register": ["POST", "/api/v1/auth/register"],
  "auth.RevokeAPIKey": ["DELETE", "/api/v1/api-keys/{key_id}"],
  "auth.ChangePassword": ["POST", "/api/v1/profile/password"],
  "auth.GetProfile": ["GET", "/api/v1/profile"],
  "auth.UpdateAvatar": ["PUT", "/api/v1/profile/avatar"],
  "auth.UpdateEmail": ["POST", "/api/v1/profile/email"],
  "auth.UpdateProfile": ["PATCH", "/api/v1/profile"],
  // ---- tenant：分享链接（能力凭证，明文只在创建/轮换时出现一次）----
  "tenant.JoinSharedProject": ["POST", "/api/v1/shared-projects"],
  "tenant.ListSharedProjects": ["GET", "/api/v1/shared-projects"],
  "tenant.RevokeProjectShare": ["DELETE", "/api/v1/projects/{project_id}/share"],
  "tenant.UpdateProjectShare": ["PATCH", "/api/v1/projects/{project_id}/share"],
  // ---- tenant：org 成员身份 ----
  "tenant.AcceptOrgInvitation": ["POST", "/api/v1/orgs/join"],
  "tenant.CreateOrg": ["POST", "/api/v1/orgs"],
  "tenant.CreateOrgInvitation": ["POST", "/api/v1/orgs/{org_id}/invitations"],
  "tenant.ListMyOrgs": ["GET", "/api/v1/orgs"],
  // ---- tenant：project ----
  "tenant.CreateProject": ["POST", "/api/v1/projects"],
  "tenant.DeleteProject": ["DELETE", "/api/v1/projects/{project_id}"],
  "tenant.GetProject": ["GET", "/api/v1/projects/{project_id}"],
  "tenant.GetProjectConfig": ["GET", "/api/v1/projects/{project_id}/config"],
  "tenant.ListProjects": ["GET", "/api/v1/projects"],
  "tenant.UpdateProject": ["PATCH", "/api/v1/projects/{project_id}"],
  "tenant.UpdateProjectConfig": ["PATCH", "/api/v1/projects/{project_id}/config"],
  // ---- session ----
  "session.ArchiveSession": ["POST", "/api/v1/sessions/{session_id}:archive"],
  "session.CreateBlock": ["POST", "/api/v1/sessions/{session_id}/blocks"],
  "session.CreateSession": ["POST", "/api/v1/sessions"],
  "session.DeleteBlock": ["DELETE", "/api/v1/blocks/{block_id}"],
  "session.DeleteSession": ["DELETE", "/api/v1/sessions/{session_id}"],
  "session.GetBlock": ["GET", "/api/v1/blocks/{block_id}"],
  "session.GetSession": ["GET", "/api/v1/sessions/{session_id}"],
  "session.GetSessionEvents": ["GET", "/api/v1/sessions/{session_id}/events"],
  "session.GetSessionLineage": ["GET", "/api/v1/sessions/{session_id}/lineage"],
  "session.ListBlocks": ["GET", "/api/v1/sessions/{session_id}/blocks"],
  "session.ListSessions": ["GET", "/api/v1/sessions"],
  "session.RevokeBlockShare": ["DELETE", "/api/v1/block-shares/{share_id}"],
  "session.ShareBlock": ["POST", "/api/v1/blocks/{block_id}/shares"],
  "session.StreamSessionEvents": ["GET", "/api/v1/sessions/{session_id}/events:stream"],
  // ---- workflow ----
  "workflow.CountWorkflowsByProject": ["GET", "/api/v1/workflows:counts"],
  "workflow.CreateWorkflow": ["POST", "/api/v1/workflows"],
  "workflow.DeleteWorkflow": ["DELETE", "/api/v1/workflows/{workflow_id}"],
  "workflow.GetWorkflow": ["GET", "/api/v1/workflows/{workflow_id}"],
  "workflow.ListWorkflows": ["GET", "/api/v1/workflows"],
  "workflow.UpdateWorkflow": ["PATCH", "/api/v1/workflows/{workflow_id}"],
  // ---- agent ----
  "agent.CreateAgentDef": ["POST", "/api/v1/agents"],
  "agent.ReadAttachment": ["GET", "/api/v1/attachments/{attachment_id}"],
  "agent.DeleteAgentDef": ["DELETE", "/api/v1/agents/{agent_def_id}"],
  "agent.GetAgentDef": ["GET", "/api/v1/agents/{agent_def_id}"],
  "agent.GetAgentDefVersion": ["GET", "/api/v1/agents/{agent_def_id}/versions/{version}"],
  "agent.GetRun": ["GET", "/api/v1/runs/{run_id}"],
  "agent.Interrupt": ["POST", "/api/v1/sessions/{session_id}:interrupt"],
  "agent.ListAgentDefs": ["GET", "/api/v1/agents"],
  "agent.ListAgentDefVersions": ["GET", "/api/v1/agents/{agent_def_id}/versions"],
  "agent.ListAgentDirectory": ["GET", "/api/v1/agent-directory"],
  "agent.ListAgentMessages": ["GET", "/api/v1/agent-directory/{agent_id}/messages"],
  "agent.ListRuns": ["GET", "/api/v1/sessions/{session_id}/runs"],
  "agent.Prompt": ["POST", "/api/v1/sessions/{session_id}:prompt"],
  "agent.ResolveAgentAddress": ["GET", "/api/v1/agent-directory/{agent_id}"],
  "agent.UpdateAgentDef": ["PATCH", "/api/v1/agents/{agent_def_id}"],
  // ---- memory ----
  "memory.CommitSession": ["POST", "/api/v1/memories:commit"],
  "memory.Delete": ["DELETE", "/api/v1/memories/{memory_path}"],
  "memory.GetTask": ["GET", "/api/v1/memory-tasks/{task_id}"],
  "memory.List": ["GET", "/api/v1/memories"],
  "memory.ListTasks": ["GET", "/api/v1/memory-tasks"],
  "memory.Read": ["GET", "/api/v1/memories/{memory_path}"],
  "memory.Search": ["POST", "/api/v1/memories:search"],
  "memory.Tree": ["POST", "/api/v1/memories:tree"],
  "memory.WatchTask": ["GET", "/api/v1/memory-tasks/{task_id}:watch"],
  "memory.Write": ["PUT", "/api/v1/memories/{memory_path}"],
  // ---- sandbox ----
  "sandbox.Create": ["POST", "/api/v1/sandboxes"],
  "sandbox.ExposePort": ["POST", "/api/v1/sandboxes/{sandbox_id}/ports"],
  "sandbox.Get": ["GET", "/api/v1/sandboxes/{sandbox_id}"],
  "sandbox.List": ["GET", "/api/v1/sandboxes"],
  "sandbox.ListDir": ["GET", "/api/v1/sandboxes/{sandbox_id}/directory"],
  "sandbox.ReadFile": ["GET", "/api/v1/sandboxes/{sandbox_id}/files/{path}"],
  "sandbox.Renew": ["POST", "/api/v1/sandboxes/{sandbox_id}:renew"],
  "sandbox.RunCode": ["POST", "/api/v1/sandboxes/{sandbox_id}/code"],
  "sandbox.RunCommand": ["POST", "/api/v1/sandboxes/{sandbox_id}/exec"],
  "sandbox.Stat": ["GET", "/api/v1/sandboxes/{sandbox_id}/stat"],
  "sandbox.StreamLogs": ["GET", "/api/v1/sandboxes/{sandbox_id}/logs"],
  "sandbox.Terminate": ["DELETE", "/api/v1/sandboxes/{sandbox_id}"],
  // ---- assets ----
  "assets.CreateAsset": ["POST", "/admin/api/v1/assets"],
  "assets.CreateAssetVersion": ["POST", "/admin/api/v1/assets/{asset_id}/versions"],
  "assets.GetAssemblyArtifact": [
    "GET",
    "/admin/api/v1/assembly-artifacts/{project_id}/revisions/{revision}",
  ],
  "assets.GetAssemblyStatus": ["GET", "/api/v1/assembly-status"],
  "assets.GetAsset": ["GET", "/api/v1/assets/{asset_id}"],
  "assets.ListAssemblyRevisions": ["GET", "/admin/api/v1/assembly-revisions"],
  "assets.ListAssets": ["GET", "/api/v1/assets"],
  "assets.ListEnabledAssets": ["GET", "/api/v1/assets:enabled"],
  "assets.PinAssetVersion": ["POST", "/api/v1/assets/{asset_id}:pin-version"],
  "assets.PublishVersion": [
    "POST",
    "/admin/api/v1/assets/{asset_id}/versions/{version_id}:publish",
  ],
  "assets.PutAssetContent": [
    "PUT",
    "/admin/api/v1/assets/{asset_id}/versions/{version_id}/content",
  ],
  "assets.SetAssetConfig": ["POST", "/api/v1/assets/{asset_id}:set-config"],
  "assets.SetAssetEnabled": ["POST", "/api/v1/assets/{asset_id}:set-enabled"],
  "assets.SetAssetLifecycle": ["POST", "/admin/api/v1/assets/{asset_id}:set-lifecycle"],
  "assets.SetCredential": ["POST", "/api/v1/assets/{asset_id}:set-credential"],
  "assets.SetVisibility": ["POST", "/admin/api/v1/assets/{asset_id}:set-visibility"],
  "assets.SyncCoreAssets": ["POST", "/admin/api/v1/assets:sync-core"],
  "assets.TriggerAssemblyDispatch": ["POST", "/admin/api/v1/assembly-dispatch:trigger"],
  "assets.UpdateAsset": ["PATCH", "/admin/api/v1/assets/{asset_id}"],
  "assets.YankVersion": ["POST", "/admin/api/v1/assets/{asset_id}/versions/{version_id}:yank"],
  // ---- billing ----
  "billing.GetSubscription": ["GET", "/api/v1/billing/subscription"],
  "billing.GetUsage": ["GET", "/api/v1/billing/usage"],
  "billing.ListInvoices": ["GET", "/api/v1/billing/invoices"],
  // ---- admin ----
  "admin.ListUsers": ["GET", "/admin/api/v1/users"],
  "admin.PromoteUser": ["POST", "/admin/api/v1/users/{user_id}:promote"],
  "admin.RotateContextTokenKey": ["POST", "/admin/api/v1/context-token-keys:rotate"],
  "admin.SetUserStatus": ["PUT", "/admin/api/v1/users/{user_id}/status"],
};

/** 多段通配参数（模板里写作 {name=**}）：值含 `/`，须**逐段 encode 后以 `/` 连接**，
 * 不可整体 encodeURIComponent（否则 `notes/a.md` 会被压成单个 segment）。 */
export const MULTI_PARAMS = {
  "memory.Delete": new Set(["memory_path"]),
  "memory.Read": new Set(["memory_path"]),
  "memory.Write": new Set(["memory_path"]),
  "sandbox.ReadFile": new Set(["path"]),
};

/** 响应为流的端点（唯一事实源：contracts/gen/go-gateway 里 forward_*_0 =
 * runtime.ForwardResponseStream 的那几条）。流式端点必须走 Client.stream()：
 * 走 call() 会拿到逐行 JSON 的未解析正文。 */
export const STREAMING = new Set([
  "agent.ReadAttachment",
  "sandbox.RunCommand",
  "sandbox.RunCode",
  "sandbox.ReadFile",
  "sandbox.StreamLogs",
  "session.StreamSessionEvents",
  "memory.Search",
  "memory.WatchTask",
]);

export function isStreaming(key) {
  return STREAMING.has(key);
}

const TEMPLATE = /\{([A-Za-z_][A-Za-z0-9_]*)(=\*\*)?\}/g;

function spec(key) {
  const found = ENDPOINTS[key];
  if (!found) throw new UsageError(`未知端点 ${JSON.stringify(key)}（用 \`rathflow api --list\` 查看全部）`);
  return found;
}

/** 路径模板需要的参数名。 */
export function pathParams(key) {
  return [...spec(key)[1].matchAll(TEMPLATE)].map((m) => m[1]);
}

/** 把模板渲染成真实路径，逐参数 encode。缺参数 → UsageError。 */
export function renderPath(key, params = {}) {
  const [, template] = spec(key);
  const multi = MULTI_PARAMS[key] || new Set();
  return template.replace(TEMPLATE, (_all, name) => {
    const value = params[name];
    if (value === undefined || value === null || value === "") {
      throw new UsageError(`${key} 需要路径参数 --path ${name}=<值>`);
    }
    const text = String(value);
    if (multi.has(name)) {
      // `.` / `..` / 空段会被 HTTP 客户端按 URL 语义归一化（`a/b/../c` → `a/c`，
      // `//x` → `/x`），实际请求就跑到别的端点上，还绕过命令自己的域检查。
      // 逐段 encodeURIComponent 拦不住它们（`.` 不会被编码），故直接拒。
      const segments = text.split("/");
      for (const seg of segments) {
        if (seg === "" || seg === "." || seg === "..") {
          throw new UsageError(
            `${name} 不能含空段或 '.'/'..'：${JSON.stringify(text)}（要相对路径，如 memories/notes/a.md）`,
          );
        }
      }
      return segments.map(encodeURIComponent).join("/");
    }
    return encodeURIComponent(text);
  });
}

export function methodOf(key) {
  return spec(key)[0];
}
