import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { once } from "node:events";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const desktopOut = join(repositoryRoot, "apps", "desktop", "out");
const expectedBridgeMethods = [
  "exportArtifact",
  "getServerConfig",
  "getVersion",
  "openExternal",
  "setServerConfig",
];

const delay = (milliseconds) => new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));

async function findArtifact(filename) {
  const pending = [desktopOut];
  while (pending.length > 0) {
    const directory = pending.pop();
    let entries;
    try {
      entries = await readdir(directory, { withFileTypes: true });
    } catch (error) {
      if (error?.code === "ENOENT") return null;
      throw error;
    }
    for (const entry of entries) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) pending.push(path);
      if (entry.isFile() && entry.name === filename) return path;
    }
  }
  return null;
}

async function reservePort() {
  const server = createServer();
  server.unref();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.equal(typeof address, "object");
  const port = address.port;
  server.close();
  await once(server, "close");
  return port;
}

async function waitForPage(port, process, diagnostics) {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    assert.equal(process.exitCode, null, `packaged app exited early: ${diagnostics()}`);
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      if (response.ok) {
        const pages = await response.json();
        const page = pages.find((candidate) => candidate.type === "page");
        if (page?.webSocketDebuggerUrl) return page;
      }
    } catch {
      // The debugging endpoint is not listening yet; keep polling the observable condition.
    }
    await delay(100);
  }
  throw new Error(`packaged app did not expose a page before timeout: ${diagnostics()}`);
}

async function evaluate(webSocketDebuggerUrl, expression) {
  return new Promise((resolveEvaluation, rejectEvaluation) => {
    const socket = new WebSocket(webSocketDebuggerUrl);
    const timeout = setTimeout(() => {
      socket.close();
      rejectEvaluation(new Error("CDP evaluation timed out"));
    }, 5_000);
    socket.addEventListener("error", () => {
      clearTimeout(timeout);
      rejectEvaluation(new Error("CDP WebSocket failed"));
    });
    socket.addEventListener("open", () => {
      socket.send(
        JSON.stringify({
          id: 1,
          method: "Runtime.evaluate",
          params: { expression, awaitPromise: true, returnByValue: true },
        }),
      );
    });
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data));
      if (message.id !== 1) return;
      clearTimeout(timeout);
      socket.close();
      if (message.result?.exceptionDetails) {
        rejectEvaluation(new Error(message.result.exceptionDetails.text));
        return;
      }
      resolveEvaluation(message.result?.result?.value);
    });
  });
}

const observationExpression = `(async () => JSON.stringify({
  readyState: document.readyState,
  title: document.title,
  url: location.href,
  methods: window.desktop ? Object.keys(window.desktop).sort() : null,
  version: window.desktop ? await window.desktop.getVersion() : null,
  initialConfig: window.desktop ? await window.desktop.getServerConfig() : null,
  processType: typeof process,
  requireType: typeof require,
  csp: document.querySelector('meta[http-equiv="Content-Security-Policy"]')?.content ?? null
}))()`;

const configTransitionExpression = `(async () => JSON.stringify({
  savedConfig: await window.desktop.setServerConfig({ baseUrl: "https://api-2.example.edu" }),
  finalConfig: await window.desktop.getServerConfig()
}))()`;

async function waitForObservation(page, process, diagnostics) {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    assert.equal(process.exitCode, null, `packaged app exited early: ${diagnostics()}`);
    try {
      const raw = await evaluate(page.webSocketDebuggerUrl, observationExpression);
      const observation = JSON.parse(raw);
      if (
        observation.readyState === "complete" &&
        observation.title === "PyMentor Lab" &&
        observation.url === "pymentor://app/index.html" &&
        observation.methods !== null
      ) {
        return observation;
      }
    } catch {
      // Navigation may replace the execution context; retry against the same page target.
    }
    await delay(100);
  }
  throw new Error(`packaged page did not become ready before timeout: ${diagnostics()}`);
}

async function terminate(process) {
  if (process.exitCode !== null) return;
  process.kill();
  await Promise.race([
    once(process, "exit"),
    delay(5_000).then(() => {
      throw new Error("packaged app did not terminate cleanly");
    }),
  ]);
}

test("Windows package artifacts exist and have a SHA-256 checksum", { skip: process.platform !== "win32" }, async () => {
  const executable = await findArtifact("PyMentorLab.exe");
  const setup = await findArtifact("PyMentorLab-Setup.exe");

  assert.ok(executable, "run the Windows package task before packaged smoke");
  assert.ok(setup, "run the Windows make task before installer smoke");
  const checksum = createHash("sha256").update(await readFile(setup)).digest("hex");
  assert.match(checksum, /^[a-f0-9]{64}$/);
});

test("packaged app loads trusted content with the bounded preload bridge", { skip: process.platform !== "win32" }, async () => {
  const executable = await findArtifact("PyMentorLab.exe");
  assert.ok(executable, "run the Windows package task before packaged smoke");

  const userData = await mkdtemp(join(tmpdir(), "pymentor-int006-"));
  await writeFile(
    join(userData, "server-config.json"),
    JSON.stringify({ baseUrl: "https://api.example.edu" }),
    { encoding: "utf8", mode: 0o600 },
  );
  const port = await reservePort();
  const environment = { ...process.env };
  delete environment.PYMENTOR_DESKTOP_WEB_URL;
  const child = spawn(
    executable,
    [
      `--user-data-dir=${userData}`,
      `--remote-debugging-port=${port}`,
      "--remote-allow-origins=*",
      "--disable-gpu",
    ],
    { env: environment, stdio: ["ignore", "pipe", "pipe"], windowsHide: true },
  );
  let output = "";
  child.stdout.on("data", (chunk) => {
    output += String(chunk);
  });
  child.stderr.on("data", (chunk) => {
    output += String(chunk);
  });

  try {
    const page = await waitForPage(port, child, () => output.slice(-2_000));
    const observation = await waitForObservation(page, child, () => output.slice(-2_000));
    assert.equal(observation.title, "PyMentor Lab");
    assert.equal(observation.url, "pymentor://app/index.html");
    assert.deepEqual(observation.methods, expectedBridgeMethods);
    assert.deepEqual(observation.version, { version: "0.1.0" });
    assert.deepEqual(observation.initialConfig, { baseUrl: "https://api.example.edu" });
    const transition = JSON.parse(
      await evaluate(page.webSocketDebuggerUrl, configTransitionExpression),
    );
    assert.deepEqual(transition.savedConfig, { baseUrl: "https://api-2.example.edu" });
    assert.deepEqual(transition.finalConfig, { baseUrl: "https://api-2.example.edu" });
    assert.deepEqual(JSON.parse(await readFile(join(userData, "server-config.json"), "utf8")), {
      baseUrl: "https://api-2.example.edu",
    });
    assert.equal(observation.processType, "undefined");
    assert.equal(observation.requireType, "undefined");
    assert.match(observation.csp, /object-src 'none'/u);
  } finally {
    await terminate(child);
    await rm(userData, { recursive: true, force: true });
  }
});
