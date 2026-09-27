#!/usr/bin/env node
// rathflow —— Node.js 实现的 RathFlow CLI（与 Python 版同界面同退出码）。
//
// 无构建步骤：本文件与 src/ 下的 .js/.mjs 都是直接可跑的源码（P1：快速开发）。
import { main } from "../src/cli.js";

// `rathflow api --list | head` 这类用法会被下游提前关管道：Node 默认把 EPIPE
// 抛成未处理错误并打一坨栈。这里按 Unix 惯例安静收场（同 SIGPIPE 的效果）。
process.stdout.on("error", (err) => {
  if (err.code === "EPIPE") process.exit(0);
  throw err;
});
process.stderr.on("error", () => {});

main();
