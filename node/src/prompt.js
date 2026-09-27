/** 交互输入（typer.prompt 的等价物，零依赖）。
 *
 * 提示文字一律走 **stderr**：stdout 只放命令结果，管道里不掺提示语。
 */

import { Aborted } from "./errors.js";

const CTRL_C = 3;
const BACKSPACE = 8;
const DELETE = 127;
const LF = 10;
const CR = 13;

async function readAllStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

/** 明文提示（邮箱之类）。 */
export async function promptLine(question) {
  if (!process.stdin.isTTY) {
    // 管道：把 stdin 的第一行当答案（`echo you@example.com | rathflow auth login`）
    return (await readAllStdin()).split("\n")[0].trim();
  }
  const { createInterface } = await import("node:readline/promises");
  const rl = createInterface({ input: process.stdin, output: process.stderr });
  try {
    return (await rl.question(question)).trim();
  } finally {
    rl.close();
  }
}

/** 不回显提示（密码）：TTY 上进原始模式逐字符读，管道上读第一行。 */
export async function promptHidden(question) {
  if (!process.stdin.isTTY) {
    return (await readAllStdin()).split("\n")[0].trim();
  }
  process.stderr.write(question);
  process.stdin.setRawMode(true);
  process.stdin.resume();
  process.stdin.setEncoding("utf8");
  return await new Promise((resolve, reject) => {
    let buf = "";
    const done = () => {
      process.stdin.removeListener("data", onData);
      process.stdin.setRawMode(false);
      process.stdin.pause();
    };
    const onData = (chunk) => {
      for (const ch of chunk) {
        const code = ch.codePointAt(0);
        if (code === CR || code === LF) {
          done();
          process.stderr.write("\n");
          resolve(buf);
          return;
        }
        if (code === CTRL_C) {
          done();
          process.stderr.write("\n");
          reject(new Aborted());
          return;
        }
        if (code === BACKSPACE || code === DELETE) {
          buf = buf.slice(0, -1);
          continue;
        }
        if (code >= 32) buf += ch;
      }
    };
    process.stdin.on("data", onData);
  });
}
