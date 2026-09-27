/** config：本地配置档（base_url / project / 令牌存放）。 */

import * as config from "../config.js";
import { UsageError } from "../errors.js";
import * as output from "../output.js";

const KEYS = ["base_url", "project"];

export const configCmd = {
  help: "本地配置档管理",
  commands: {
    list: {
      help: "列出全部配置档。",
      run: async (st) => {
        const profiles = st.data.profiles || {};
        const rows = Object.entries(profiles).map(([name, prof]) => ({
          name,
          current: name === st.profileName ? "*" : "",
          base_url: prof.base_url || config.DEFAULT_BASE_URL,
          project: prof.project || "",
          email: (prof.user || {}).email || "",
          token: config.mask(prof.access_token),
        }));
        output.emitTable(
          rows,
          [
            ["", "current"],
            ["配置档", "name"],
            ["地址", "base_url"],
            ["项目", "project"],
            ["邮箱", "email"],
            ["令牌", "token"],
          ],
          { jsonOut: st.jsonOut },
        );
      },
    },

    show: {
      help: "显示当前生效配置（flag/env 覆盖后的结果）。",
      run: async (st) => {
        // 只回显真实存在的环境变量；未设时明确写「(未设置)」，
        // 否则会把 profile/默认值伪装成 env 覆盖，误导用户与模型。
        const envView = {
          [config.ENV_BASE_URL]: st.envBaseUrl || "(未设置)",
          [config.ENV_PROJECT]: st.envProject || "(未设置)",
          [config.ENV_TOKEN]: config.mask(st.tokenOverride),
        };
        const payload = {
          profile: st.profileName,
          base_url: st.baseUrl,
          project: st.project || "(未设置)",
          token: config.mask(st.profile.access_token),
          config_file: config.configPath(),
          env: envView,
        };
        if (st.jsonOut) {
          output.emitJson(payload);
          return;
        }
        // 人类可读模式把 env 摊平到顶层：嵌套对象会被截断到 48 列，
        // 只看得到第一个变量，等于看不出来到底有没有 env 覆盖。
        const { env: _nested, ...rest } = payload;
        output.emitObject({ ...rest, ...envView }, { jsonOut: false });
      },
    },

    set: {
      help: "写当前配置档的一项。",
      args: [
        { name: "key", help: `可设的键：${KEYS.join(" | ")}`, required: true },
        { name: "value", help: "值；project 传 - 表示清空", required: true },
      ],
      run: async (st, { args }) => {
        const [key, value] = args;
        if (!KEYS.includes(key)) throw new UsageError(`可设的键：${KEYS.join(", ")}`);
        const prof = st.profile;
        if (key === "project" && value === "-") {
          delete prof.project;
          // 清掉登录时记下的默认项目，否则下次仍会回填
          delete prof.default_project_id;
          output.echo("已清空 project");
        } else {
          prof[key] = value;
          output.echo(`${key} = ${value}`);
        }
        st.save();
      },
    },

    use: {
      help: "切换当前配置档。",
      args: [{ name: "profile", help: "配置档名；不存在则新建", required: true }],
      run: async (st, { args }) => {
        const name = args[0];
        st.data.profiles ??= {};
        st.data.profiles[name] ??= {};
        st.data.current = name;
        st.save();
        output.echo(`已切到配置档 ${name}（首次使用需在该档下 auth login）`);
      },
    },
  },
};
