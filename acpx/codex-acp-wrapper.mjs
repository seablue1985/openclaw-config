#!/usr/bin/env node
import { existsSync } from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const codexHome = fileURLToPath(new URL("./codex-home/", import.meta.url));
const env = {
  ...process.env,
  CODEX_HOME: codexHome,
};
const configuredArgs = process.argv.slice(2);

function resolveNpmCliPath() {
  const candidate = path.resolve(
    path.dirname(process.execPath),
    "..",
    "lib",
    "node_modules",
    "npm",
    "bin",
    "npm-cli.js",
  );
  return existsSync(candidate) ? candidate : undefined;
}

const npmCliPath = resolveNpmCliPath();
const defaultCommand = npmCliPath ? process.execPath : process.platform === "win32" ? "npx.cmd" : "npx";
const defaultArgs = npmCliPath
  ? [npmCliPath, "exec", "--yes", "--package", "@zed-industries/codex-acp@^0.11.1", "--", "codex-acp"]
  : ["--yes", "--package", "@zed-industries/codex-acp@^0.11.1", "--", "codex-acp"];
const command = configuredArgs[0] ?? defaultCommand;
const args = configuredArgs.length > 0 ? configuredArgs.slice(1) : defaultArgs;

const child = spawn(command, args, {
  env,
  stdio: "inherit",
  windowsHide: true,
});

for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) {
  process.once(signal, () => {
    child.kill(signal);
  });
}

child.on("error", (error) => {
  console.error(`[openclaw] failed to launch isolated Codex ACP wrapper: ${error.message}`);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (code !== null) {
    process.exit(code);
  }
  process.exit(signal ? 1 : 0);
});
