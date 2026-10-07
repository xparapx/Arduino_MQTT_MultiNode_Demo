// 보드 /kiosk 슬라이드 캡처 (ssh 터널 18502). usage: node capture_kiosk.mjs <port> s1,s2,s3,s5
import { spawn } from "node:child_process";
import { writeFileSync, rmSync, mkdirSync } from "node:fs";
import path from "node:path"; import os from "node:os";
import { fileURLToPath } from "node:url";
const [port, list] = process.argv.slice(2);
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "shots");
const PROF = path.join(os.tmpdir(), "aq_kiosk_prof_" + Date.now()); mkdirSync(PROF, { recursive: true });
const DBG = 9800 + Math.floor(Math.random() * 300);
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars", `--user-data-dir=${PROF}`, "--window-size=1920,1080", `--remote-debugging-port=${DBG}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let targets = null; for (let i = 0; i < 40 && !targets; i++) { await sleep(500); try { targets = await (await fetch(`http://127.0.0.1:${DBG}/json`)).json(); } catch (e) {} }
const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0; const pending = new Map();
ws.addEventListener("message", (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const evalJS = async (expr) => (await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value;
await send("Page.enable"); await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
for (const s of list.split(",")) {
  await send("Page.navigate", { url: `http://127.0.0.1:${port}/kiosk?slides=${s}&anim=0&interval=300` });
  await sleep(9000);
  const sid = await evalJS(`document.querySelector('#k-stage, .k-stage, [data-sid]')?.dataset?.sid || document.body.innerText.slice(0,80)`);
  const shot = await send("Page.captureScreenshot", { format: "png", clip: { x: 0, y: 0, width: 1920, height: 1080, scale: 1 } });
  writeFileSync(path.join(DIR, `kiosk-${s}.png`), Buffer.from(shot.result.data, "base64"));
  console.log(s, "->", sid);
}
ws.close(); edge.kill(); await sleep(1500); try { rmSync(PROF, { recursive: true, force: true }); } catch (e) {}
