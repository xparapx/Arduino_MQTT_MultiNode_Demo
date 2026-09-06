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
    tpl = (HERE.parent / "assets" / "template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = tpl.replace("/*__DATA__*/{}", payload).replace("__TITLE__", data.get("title", "프로젝트 지도"))
    pathlib.Path(dst).write_text(html, encoding="utf-8")
    print(f"ok → {dst}  nodes={len(nodes)} edges={len(data.get('edges',[]))} dbs={len(data.get('dbs',[]))}")
if __name__ == "__main__":
    if len(sys.argv) != 3: sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
