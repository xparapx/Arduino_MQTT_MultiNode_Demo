// Edge headless + CDP: 로컬 HTML을 지정 크기·배율로 캡처하고, 열(.col)별 넘침을 보고한다.
// usage: node shot.mjs <file.html> <cssW> <cssH> <scale> <out.png>
import { spawn } from "node:child_process";
import { writeFileSync, rmSync, mkdirSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";
const [file, W, H, S, out] = process.argv.slice(2);
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PROF = path.join(path.dirname(path.resolve(out)), "cdp_prof_" + Date.now());
mkdirSync(PROF, { recursive: true });
const DBG = 9400 + Math.floor(Math.random() * 400);
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars", "--allow-file-access-from-files",
  `--user-data-dir=${PROF}`, `--window-size=${W},${H}`, `--remote-debugging-port=${DBG}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let targets = null;
for (let i = 0; i < 40 && !targets; i++) { await sleep(500); try { targets = await (await fetch(`http://127.0.0.1:${DBG}/json`)).json(); } catch (e) {} }
if (!targets) { console.error("no debugger"); edge.kill(); process.exit(1); }
const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0; const pending = new Map();
ws.addEventListener("message", (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const evalJS = async (expr) => (await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value;
await send("Page.enable"); await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", { width: +W, height: +H, deviceScaleFactor: +S, mobile: false });
await send("Page.navigate", { url: pathToFileURL(path.resolve(file)).href });
await sleep(2500);
await evalJS(`document.fonts.ready.then(() => "ok")`);
await sleep(1200);
const rep = await evalJS(`JSON.stringify({page:[document.documentElement.scrollWidth, document.documentElement.scrollHeight],
  cols:[...document.querySelectorAll("[data-fit]")].map(c => ({id:c.dataset.fit, need:c.scrollHeight, have:c.clientHeight})),
  fonts:[...document.fonts].filter(f=>f.status==="loaded").map(f=>f.family).filter((v,i,a)=>a.indexOf(v)===i)})`);
console.log(rep);
const shot = await send("Page.captureScreenshot", { format: "png", clip: { x: 0, y: 0, width: +W, height: +H, scale: 1 } });
writeFileSync(out, Buffer.from(shot.result.data, "base64"));
console.log("saved", out);
ws.close(); edge.kill(); await sleep(2500);
try { rmSync(PROF, { recursive: true, force: true }); } catch (e) {}
