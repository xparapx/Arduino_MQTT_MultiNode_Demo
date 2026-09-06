#!/usr/bin/env python3
"""project-map 데이터 JSON → 단일 HTML.
사용: python render.py data.json out.html
"""
import json, sys, pathlib
HERE = pathlib.Path(__file__).resolve().parent
def main(src, dst):
    data = json.loads(pathlib.Path(src).read_text(encoding="utf-8"))
    # 최소 검증: edge 양끝이 nodes 에 있는지, rels 양끝이 dbs.tables 에 있는지
    nodes = data.get("nodes", {}); bad = [e for e in data.get("edges", []) if e[0] not in nodes or e[1] not in nodes]
    tabs = {f"{d['id']}.{t['n']}" for d in data.get("dbs", []) for t in d["tables"]}
    badr = [r for r in data.get("rels", []) if r[0] not in tabs or r[1] not in tabs]
    if bad: print("경고: nodes 에 없는 edge", bad, file=sys.stderr)
    if badr: print("경고: 테이블이 없는 rel", badr, file=sys.stderr)
    # embeds: 외부 HTML(예: archify 다이어그램)을 iframe srcdoc 탭으로 내장 → 산출물은 파일 하나로 유지
    src_dir = pathlib.Path(src).resolve().parent
    for e in data.get("embeds", []):
        if "html" in e: continue
        p = (src_dir / e.pop("file")).resolve()
        if p.exists(): e["html"] = p.read_text(encoding="utf-8")
        else: print(f"경고: embed 파일 없음 {p}", file=sys.stderr); e["html"] = ""
        # 내장 시에만 적용할 조정 — hide: 요소 제거(display:none), css: 자유 CSS
        # (레이아웃 자리를 지켜야 하면 hide 대신 css 로 visibility:hidden 을 쓴다)
        extra = ""
        if e.get("hide"): extra += f'{e.pop("hide")}{{display:none!important}}'
        if e.get("css"): extra += e.pop("css")
        if extra and e["html"]:
            css = f"<style>{extra}</style>"
            e["html"] = e["html"].replace("</body>", css + "</body>", 1) if "</body>" in e["html"] else e["html"] + css
    tpl = (HERE.parent / "assets" / "template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = tpl.replace("/*__DATA__*/{}", payload).replace("__TITLE__", data.get("title", "프로젝트 지도"))
    pathlib.Path(dst).write_text(html, encoding="utf-8")
    print(f"ok → {dst}  nodes={len(nodes)} edges={len(data.get('edges',[]))} dbs={len(data.get('dbs',[]))} embeds={len(data.get('embeds',[]))}")
if __name__ == "__main__":
    if len(sys.argv) != 3: sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
