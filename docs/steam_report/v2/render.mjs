// v2 그림 렌더러 — figs/*.html 을 실제 크기(mm)로 Edge 헤드리스에서 캡처한다.
//   <html data-kind="r|p" data-w="159" data-h="60" [data-scale="3.2"]>
//   usage: node render.mjs [figs/d_cycle.html ...]   (인수 없으면 figs/*.html 전부)
//   out:   out/<name>.png  + 콘솔에 넘침 보고(page scroll 크기 vs 목표, [data-fit] 요소 need/have)
import { spawn } from "node:child_process";
import { writeFileSync, rmSync, mkdirSync, readFileSync, readdirSync } from "node:fs";
import { pathToFileURL, fileURLToPath } from "node:url";
import path from "node:path";
import os from "node:os";
import { execSync } from "node:child_process";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIGS = path.join(HERE, "figs"), OUT = path.join(HERE, "out");
mkdirSync(OUT, { recursive: true });
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PX = 96 / 25.4;                                   // CSS px per mm
let files = process.argv.slice(2).map((f) => path.resolve(f));
if (!files.length) files = readdirSync(FIGS).filter((f) => f.endsWith(".html")).map((f) => path.join(FIGS, f));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const PROF = path.join(os.tmpdir(), "aq_cdp_prof_" + Date.now()); mkdirSync(PROF, { recursive: true });
const DBG = 9400 + Math.floor(Math.random() * 400);
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars", "--allow-file-access-from-files",
  `--user-data-dir=${PROF}`, "--window-size=1200,900", `--remote-debugging-port=${DBG}`, "about:blank"], { stdio: "ignore" });
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

let bad = 0;
for (const file of files) {
  const html = readFileSync(file, "utf-8");
  const attr = (k, d) => { const m = html.match(new RegExp(`<html[^>]*\\sdata-${k}="([^"]+)"`)); return m ? m[1] : d; };
  const kind = attr("kind", "r"), wmm = +attr("w", 159), hmm = +attr("h", 60);
  const scale = +attr("scale", kind === "r" ? 3.2 : kind === "m" ? 4.5 : 2.4);   // r ~307 dpi, p ~230 dpi, m(한마당, 확대 인쇄) ~430 dpi
  const W = Math.round(wmm * PX), H = Math.round(hmm * PX);
  await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: scale, mobile: false });
  await send("Page.navigate", { url: pathToFileURL(file).href });
  await sleep(1500);
  await evalJS(`document.fonts.ready.then(() => "ok")`);
  await sleep(600);
  const rep = JSON.parse(await evalJS(`JSON.stringify({page:[document.documentElement.scrollWidth, document.documentElement.scrollHeight],
    body:[document.body.scrollWidth, document.body.scrollHeight],
    fits:[...document.querySelectorAll("[data-fit]")].map(c => ({id:c.dataset.fit, need:c.scrollHeight, have:c.clientHeight, needW:c.scrollWidth, haveW:c.clientWidth})),
    fonts:[...document.fonts].filter(f=>f.status==="loaded").map(f=>f.family).filter((v,i,a)=>a.indexOf(v)===i)})`));
  const name = path.basename(file, ".html");
  const over = rep.body[0] > W + 1 || rep.body[1] > H + 1;
  const fitBad = rep.fits.filter((c) => c.need > c.have + 1 || c.needW > c.haveW + 1);
  if (over || fitBad.length) bad++;
  console.log(`${over || fitBad.length ? "OVERFLOW " : "ok       "}${name}  target ${W}x${H}px (${wmm}x${hmm}mm) body ${rep.body}` +
    (fitBad.length ? `  fit:${JSON.stringify(fitBad)}` : "") + `  fonts:${rep.fonts.join(",")}`);
  const shot = await send("Page.captureScreenshot", { format: "png", clip: { x: 0, y: 0, width: W, height: H, scale: 1 } });
  writeFileSync(path.join(OUT, name + ".png"), Buffer.from(shot.result.data, "base64"));
}
ws.close(); try { execSync(`taskkill /PID ${edge.pid} /T /F`, { stdio: "ignore" }); } catch (e) {} await sleep(1200);
try { rmSync(PROF, { recursive: true, force: true }); } catch (e) {}
console.log(bad ? `${bad} figure(s) overflow` : "all figures fit");
