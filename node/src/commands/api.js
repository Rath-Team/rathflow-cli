/** api：端点表逃生舱 —— 表里没有的调用（或想自己拼参数时）走这里。
 *
 * 设计取舍：**不留未覆盖端点**。新 proto 先于 CLI 发布时，用 `rathflow api <Key>`
 * 即可调通；CLI 补上具名命令后再切回来。端点 key 见 `rathflow api --list`。
 *
 * 本模块暴露一个根命令（不是子组）：这样 `rathflow api <Key>` 才是最短形态，
 * 不必多打一层 `call`。
 */

import { opt } from "../args.js";
import * as endpoints from "../endpoints.js";
import { UsageError } from "../errors.js";
import * as output from "../output.js";
import { BODY_FILE_OPT, BODY_OPT, PATH_OPT, QUERY_OPT, bodyOf, pairs } from "./_common.js";

/** 列出全部端点 key（含是否流式）。本函数不是命令，由 run 调用。 */
function listEndpoints(st, filter) {
  const rows = Object.entries(endpoints.ENDPOINTS)
    .filter(([key]) => !filter || key.toLowerCase().includes(filter.toLowerCase()))
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([key, spec]) => ({
      key,
      method: spec[0],
      path: spec[1],
      stream: endpoints.isStreaming(key) ? "stream" : "",
    }));
  output.emitTable(
    rows,
    [
      ["KEY", "key"],
      ["方法", "method"],
      ["路径", "path"],
      ["流", "stream"],
    ],
    { jsonOut: st.jsonOut },
  );
}

export const api = {
  help: "任意端点调用（`rathflow api --list` 看全部）",
  args: [{ name: "key", help: "端点 key，如 sandbox.RunCommand" }],
  opts: [
    opt("list", ["--list", "-l"], { help: "列端点而不调用" }),
    opt("filter", ["--filter", "-f"], { take: true, help: "配合 --list：按子串过滤 key" }),
    PATH_OPT,
    QUERY_OPT,
    BODY_OPT,
    BODY_FILE_OPT,
    opt("stream", ["--stream"], { negate: ["--no-stream"], help: "强制流式；缺省按端点表判定" }),
    opt("url", ["--url"], { take: true, help: "直接给路径，配合 --method（绕过端点表）" }),
    opt("method", ["--method", "-X"], { take: true, help: "配合 --url 用" }),
  ],
  run: async (st, { opts, args }) => {
    if (opts.list) {
      listEndpoints(st, opts.filter);
      return;
    }
    const key = args[0];
    if (!key && !opts.url) {
      throw new UsageError("给端点 key，或 --url/--method；列端点用 `rathflow api --list`");
    }
    const body = await bodyOf(opts);
    const common = { body, query: pairs(opts.query) };

    let target;
    let isStream;
    if (opts.url) {
      isStream = Boolean(opts.stream);
      target = { ...common, method: opts.method || "GET", path: opts.url };
    } else {
      if (opts.stream === false && endpoints.isStreaming(key)) {
        throw new UsageError(`${key} 是流式端点，不能 --no-stream（其响应体是逐行 JSON）`);
      }
      isStream = opts.stream === undefined ? endpoints.isStreaming(key) : opts.stream;
      target = { ...common, key, pathParams: pairs(opts.path) };
    }

    if (isStream) {
      for await (const frame of st.client().stream(target.key, target)) {
        output.emitJson(frame);
      }
      return;
    }
    output.emitJson(await st.client().call(target.key, target));
  },
};
