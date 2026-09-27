/** auth 与 whoami。 */

import { opt } from "../args.js";
import { UsageError } from "../errors.js";
import * as output from "../output.js";
import { promptHidden, promptLine } from "../prompt.js";
import { YES_OPT, confirm, readBinary, readStdin } from "./_common.js";

export const auth = {
  help: "登录 / 登出 / 注册 / 身份",
  commands: {
    login: {
      help: "用邮箱密码换取 JWT（响应体令牌交给 CLI，见 gateway cookiepost.go）。",
      opts: [
        opt("email", ["--email", "-e"], { take: true, help: "邮箱（缺省交互输入）" }),
        opt("password", ["--password"], { take: true, help: "密码（缺省交互输入，不回显）" }),
      ],
      run: async (st, { opts }) => {
        const email = opts.email || (await promptLine("邮箱 "));
        const password = opts.password || (await promptHidden("密码 "));
        const payload = await st.client().login(email, password);
        st.rememberIdentity(payload);
        st.profile.user = { ...(st.profile.user || {}), email };
        st.save();
        const role = payload.isPlatformAdmin ? "平台管理员" : "普通用户";
        output.echo(`已登录 ${email}（${role}）`);
        if (payload.defaultProjectId) output.echo(`默认项目：${payload.defaultProjectId}`);
      },
    },

    logout: {
      help: "清本地令牌并通知服务端（幂等）。",
      run: async (st) => {
        await st.client().logout();
        delete st.profile.user;
        st.save();
        output.echo("已登出");
      },
    },

    register: {
      help: "注册新账号（成功后自动登录）。",
      opts: [
        opt("email", ["--email", "-e"], { take: true, help: "邮箱" }),
        opt("password", ["--password"], { take: true, help: "密码（缺省交互输入）" }),
        opt("displayName", ["--display-name"], { take: true, help: "显示名" }),
      ],
      run: async (st, { opts }) => {
        const email = opts.email;
        if (!email) throw new UsageError("需要 --email");
        const password = opts.password || (await promptHidden("密码 "));
        const body = { email, password };
        if (opts.displayName) body.display_name = opts.displayName;
        const payload = await st.client().call("auth.Register", { body, auth: false });
        if (st.jsonOut) {
          output.emitJson(payload);
        } else {
          output.echo(`注册成功：user=${payload.userId} org=${payload.orgId}`);
          output.echo(`默认项目：${payload.projectId}`);
        }
        // 注册响应里没有令牌，接着登录一次；两边的身份信息一起落盘
        st.rememberIdentity(await st.client().login(email, password));
        st.profile.user = { ...(st.profile.user || {}), email };
        st.save();
        output.echo("已自动登录。");
      },
    },

    // ---------------------------------------------------------------- API key
    // 注意：签发/吊销都走 JWT（IssueAPIKey 的认证是 jwt），所以必须先用邮箱登录。
    // 密钥只在签发那一次出现，之后服务端只留摘要 —— 落盘责任在调用方。

    keys: {
      help: "列本账号的 API key（不含密钥本体）。",
      run: async (st) => {
        const payload = await st.client().call("auth.ListAPIKeys", { query: { page_size: 100 } });
        output.emitTable(
          payload.keys || [],
          [
            ["KEY ID", "keyId"],
            ["名称", "name"],
            ["项目", "projectIds"],
            ["创建时间", "createdAt"],
            ["最后使用", "lastUsedAt"],
            ["已吊销", "revokedAt"],
          ],
          { jsonOut: st.jsonOut },
        );
      },
    },

    "key-create": {
      help: "签发 API key（**明文只打印这一次**）。",
      opts: [
        opt("name", ["--name", "-n"], { take: true, help: "用途备注，便于日后吊销" }),
        opt("projectIds", ["--project-id"], {
          take: true,
          list: true,
          help: "限定项目，可重复；缺省不限定",
        }),
      ],
      run: async (st, { opts }) => {
        if (!opts.name) throw new UsageError("需要 --name");
        const body = { name: opts.name };
        if (opts.projectIds?.length) body.projectIds = opts.projectIds.join(",");
        const payload = await st.client().call("auth.IssueAPIKey", { body });
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        output.echo(payload.apiKey || "", { err: true });
        output.echo(`key_id=${payload.keyId}（明文只此一次，请立即存好）`, { err: true });
      },
    },

    "key-revoke": {
      help: "吊销 API key。",
      args: [{ name: "key_id", help: "密钥 id", required: true }],
      opts: [YES_OPT],
      run: async (st, { opts, args }) => {
        const keyId = args[0];
        if (!opts.yes) await confirm(`确认吊销 ${keyId}？`);
        await st.client().call("auth.RevokeAPIKey", { pathParams: { key_id: keyId } });
        output.echo(`已吊销 ${keyId}`);
      },
    },

    // ---------------------------------------------------------------- 个人资料

    profile: {
      help: "看当前账号资料（头像以 base64 内联，这里只显示「有/类型」，字节走 --json）。",
      run: async (st) => {
        const payload = await st.client().call("auth.GetProfile");
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        const { avatarBytes, ...view } = payload;
        if (avatarBytes) view.avatar = payload.avatarMediaType || "有（--json 取字节）";
        output.emitObject(view);
      },
    },

    "profile-update": {
      help: "改资料；只发显式给出的字段（都不给 = 用法错，避免空 PATCH）。",
      opts: [
        opt("displayName", ["--display-name"], { take: true, help: "显示名" }),
        opt("username", ["--username"], { take: true }),
        opt("phone", ["--phone"], { take: true }),
      ],
      run: async (st, { opts }) => {
        const body = {};
        if (opts.displayName !== undefined) body.displayName = opts.displayName;
        if (opts.username !== undefined) body.username = opts.username;
        if (opts.phone !== undefined) body.phone = opts.phone;
        if (Object.keys(body).length === 0) {
          throw new UsageError("至少给一个：--display-name / --username / --phone");
        }
        output.emitObject(await st.client().call("auth.UpdateProfile", { body }), {
          jsonOut: st.jsonOut,
        });
      },
    },

    "change-password": {
      help: "改密码（旧密码证明是本人）。",
      opts: [
        opt("currentPassword", ["--current-password"], { take: true, help: "缺省交互输入，不进 shell 历史" }),
        opt("newPassword", ["--new-password"], { take: true, help: "缺省交互输入；>=8 位且含大小写" }),
      ],
      run: async (st, { opts }) => {
        const currentPassword = opts.currentPassword || (await promptHidden("当前密码 "));
        let newPassword = opts.newPassword;
        if (!newPassword) {
          newPassword = await promptHidden("新密码 ");
          const again = await promptHidden("再输一次 ");
          if (again !== newPassword) throw new UsageError("两次输入的新密码不一致");
        }
        await st.client().call("auth.ChangePassword", {
          body: { currentPassword, newPassword },
        });
        output.echo("密码已更新");
      },
    },

    "set-email": {
      help: "换登录邮箱（要当前密码，防止被盗会话直接改）。",
      opts: [
        opt("newEmail", ["--email", "-e"], { take: true, help: "新登录邮箱" }),
        opt("currentPassword", ["--current-password"], { take: true, help: "缺省交互输入" }),
      ],
      run: async (st, { opts }) => {
        if (!opts.newEmail) throw new UsageError("需要 --email");
        const currentPassword = opts.currentPassword || (await promptHidden("当前密码 "));
        output.emitObject(
          await st.client().call("auth.UpdateEmail", {
            body: { newEmail: opts.newEmail, currentPassword },
          }),
          { jsonOut: st.jsonOut },
        );
      },
    },

    "set-avatar": {
      help: "换/清头像（base64 内联，服务端限 64KB 方图）。",
      opts: [
        opt("file", ["--file", "-f"], { take: true, help: "图片文件；传 - 读 stdin" }),
        opt("mediaType", ["--media-type"], { take: true, help: "缺省按扩展名猜" }),
        opt("clear", ["--clear"], { help: "清除头像" }),
      ],
      run: async (st, { opts }) => {
        if (opts.clear && opts.file) throw new UsageError("--clear 与 --file 互斥");
        if (!opts.clear && !opts.file) {
          throw new UsageError("给 --file <图片>，或用 --clear 清除头像");
        }
        let body;
        if (opts.clear) {
          body = { data: "", mediaType: "" };
        } else {
          const raw = opts.file === "-" ? await readStdin() : readBinary(opts.file);
          const mediaType = opts.mediaType || guessImageType(opts.file);
          if (!AVATAR_TYPES.has(mediaType)) {
            throw new UsageError(
              `媒体类型 ${mediaType || "(未知)"} 不在白名单：${[...AVATAR_TYPES].sort().join(", ")}（用 --media-type 指定）`,
            );
          }
          body = { data: raw.toString("base64"), mediaType };
        }
        output.emitObject(await st.client().call("auth.UpdateAvatar", { body }), {
          jsonOut: st.jsonOut,
        });
      },
    },
  },
};

const AVATAR_TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);

/** 按扩展名猜头像媒体类型（Python 版走 mimetypes，这里只需要这四种栅格）。 */
function guessImageType(file) {
  const ext = String(file || "").toLowerCase().split(".").pop();
  return { png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", webp: "image/webp", gif: "image/gif" }[ext];
}

/** 根命令：显示登录身份 + 作用域 + 可访问项目（后者顺带证明令牌有效）。 */
export const whoami = {
  help: "显示登录身份、作用域与可访问项目",
  run: async (st) => {
    const profUser = st.profile.user || {};
    const payload = await st.client().call("tenant.ListProjects", { query: { page_size: 50 } });
    const projects = payload.projects || [];
    if (st.jsonOut) {
      output.emitJson({
        baseUrl: st.baseUrl,
        profile: st.profileName,
        user: profUser,
        // Python 版这里发 null；JSON.stringify 会把 undefined 整个丢掉，
        // 键没了脚本读到 undefined 与 null 是两回事，故显式补 null。
        project: st.project ?? null,
        projects,
      });
      return;
    }
    output.echo(`地址      ${st.baseUrl}`);
    output.echo(`配置档    ${st.profileName}`);
    if (profUser.email) output.echo(`用户      ${profUser.email}`);
    if (profUser.user_id) output.echo(`用户 id   ${profUser.user_id}`);
    if (profUser.org_id) output.echo(`组织 id   ${profUser.org_id}`);
    output.echo(`平台管理员 ${profUser.is_platform_admin ? "是" : "否"}`);
    output.echo(`当前项目  ${st.project || "(未设置 —— 用 rathflow project use <id>)"}`);
    output.echo("");
    output.emitTable(
      projects,
      [
        ["PROJECT ID", "projectId"],
        ["名称", "name"],
        ["创建时间", "createdAt"],
      ],
      { jsonOut: false },
    );
  },
};
