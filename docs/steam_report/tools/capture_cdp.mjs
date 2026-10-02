// Edge headless + CDP 캡처 — 라이트 테마(localStorage aq-theme=light) 적용 후 스크린샷.
// usage: node capture_cdp.mjs <port> <w> <h> <prefix> screen1,screen2,...
import { spawn } from "node:child_process";
import { writeFileSync, rmSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const [port, W, H, prefix, list] = process.argv.slice(2);
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "shots");
const PROF = DIR + "\\cdp_prof_" + prefix + port;
rmSync(PROF, { recursive: true, force: true }); mkdirSync(PROF, { recursive: true });
const DBG = 9333 + Math.floor(Math.random() * 500);
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
  `--user-data-dir=${PROF}`, `--window-size=${W},${H}`, `--remote-debugging-port=${DBG}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let targets = null;
for (let i = 0; i < 40 && !targets; i++) {
  await sleep(500);
  try { targets = await (await fetch(`http://127.0.0.1:${DBG}/json`)).json(); } catch (e) { /* not yet */ }
}
if (!targets) { console.error("no debugger"); edge.kill(); process.exit(1); }
const page = targets.find((t) => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0; const pending = new Map();
ws.addEventListener("message", (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const evalJS = async (expr) => (await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value;

await send("Page.enable"); await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", { width: +W, height: +H, deviceScaleFactor: 1, mobile: +W < 768 });
const base = `http://127.0.0.1:${port}/`;
await send("Page.navigate", { url: base + "#home" }); await sleep(2500);
await evalJS(`localStorage.setItem("aq-theme","light"); AQ.setTheme("light"); "ok"`);
for (const s of list.split(",")) {
  await evalJS(`location.hash = "#${s}"; "ok"`);
  await sleep(600);
  await evalJS(`AQ.setTheme("light"); window.scrollTo(0,0); "ok"`);
  await sleep(3200);   // 60 s 피드 첫 fetch + 렌더 대기
  const theme = await evalJS(`document.documentElement.getAttribute("data-theme")`);
  const shot = await send("Page.captureScreenshot", { format: "png", clip: { x: 0, y: 0, width: +W, height: +H, scale: 1 } });
  const out = `${DIR}\\${prefix}${s}.png`;
  writeFileSync(out, Buffer.from(shot.result.data, "base64"));
  console.log(`${s}: theme=${theme} -> ${out}`);
}
ws.close(); edge.kill();
await sleep(2500); try { rmSync(PROF, { recursive: true, force: true }); } catch (e) { /* profile still locked — harmless */ }
