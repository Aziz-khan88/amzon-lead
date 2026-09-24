// Dev server launcher: forwards CLI host/port args to Django's runserver.
// Usage: npm run dev -- --port 7100 --host 127.0.0.1
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const args = process.argv.slice(2);
let host = "127.0.0.1";
let port = "7100";
for (let i = 0; i < args.length; i++) {
  if ((args[i] === "--port" || args[i] === "-p") && args[i + 1]) port = args[++i];
  else if ((args[i] === "--host" || args[i] === "-h") && args[i + 1]) host = args[++i];
  else if (args[i].startsWith("--port=")) port = args[i].split("=")[1];
  else if (args[i].startsWith("--host=")) host = args[i].split("=")[1];
}

const root = __dirname ? path.resolve(__dirname, "..") : process.cwd();

// Prefer the project virtualenv Python if present.
const candidates = [
  path.join(root, "..", ".venv", "Scripts", "python.exe"),
  path.join(root, "..", ".venv", "bin", "python"),
  path.join(root, ".venv", "Scripts", "python.exe"),
  path.join(root, ".venv", "bin", "python"),
];
let python = "python";
for (const candidate of candidates) {
  if (fs.existsSync(candidate)) { python = candidate; break; }
}

const addr = `${host}:${port}`;
console.log(`Starting Django dev server at http://${addr}/`);
const child = spawn(python, [path.join(root, "manage.py"), "runserver", addr, "--noreload"], {
  cwd: root,
  stdio: "inherit",
});
child.on("exit", (code) => process.exit(code ?? 0));
process.on("SIGINT", () => child.kill("SIGINT"));
process.on("SIGTERM", () => child.kill("SIGTERM"));
