#!/usr/bin/env python3
"""저장소를 훑어 project-map 데이터 JSON 초안을 만든다 (Python + systemd + SQLite + FastAPI 기준).
사용: python scan.py <repo_root> draft.json
초안에는 d(설명)·overview·rels 가 비어 있다 — 이 부분은 Claude 가 코드를 읽고 채운다.
"""
import ast, json, re, sys, pathlib
SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", "tests", "test", "docs", "build", "dist"}
def files(root, exts):
    for p in root.rglob("*"):
        if any(s in p.parts for s in SKIP): continue
        if p.suffix in exts and p.is_file(): yield p
def modname(root, p):
    rel = p.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__": parts = parts[:-1]
    return ".".join(parts)
def main(root, out):
    root = pathlib.Path(root).resolve()
    nodes, edges, dbs = {}, [], []
    mods = {}
    # 1) Python 모듈
    for p in files(root, {".py"}):
        m = modname(root, p); mods[m] = p
        src = p.read_text(encoding="utf-8", errors="ignore")
        try: tree = ast.parse(src)
        except SyntaxError: continue
        doc = (ast.get_docstring(tree) or "").strip().splitlines()
        routes = re.findall(r'@\w+\.(get|post|put|delete)\("([^"]+)"', src)
        has_main = "__main__" in src or "argparse" in src
        col = "api" if routes else ("job" if has_main else "lib")
        if p.name in ("main.py",) and "FastAPI(" in src: col = "job"
        nodes[m] = {"c": col, "n": str(p.relative_to(root)), "s": " ".join(f"{a.upper()} {b}" for a, b in routes)[:60] or (doc[0][:60] if doc else ""), "d": ""}
        # import 간선 (저장소 내부 모듈만)
        for n in ast.walk(tree):
            names = []
            if isinstance(n, ast.Import): names = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module:
                base = n.module
                if n.level:  # 상대 import → 패키지 기준으로 복원
                    pkg = m.split(".")[:-n.level] if not p.name == "__init__.py" else m.split(".")[: len(m.split(".")) - n.level + 1]
                    base = ".".join(pkg + [n.module])
                names = [base] + [base + "." + a.name for a in n.names]
            for nm in names: edges.append([m, nm, "imp", ""])
        # 파일 쓰기/읽기 힌트
        for w in re.findall(r'(?:open|Path)\(([^)]*?)\)', src):
            pass
        for fn in set(re.findall(r'["\']([\w./-]+\.(?:db|json|sqlite|csv))["\']', src)):
            ty = "wr" if re.search(r'(INSERT|write_text|json\.dump|os\.replace|executemany)', src) else "rd"
            edges.append([m, "file:" + fn, ty, ""])
        # SQLite 스키마
        for name, body in re.findall(r'CREATE TABLE(?: IF NOT EXISTS)? (\w+)\s*\(([^;]*?)\)\s*;?', src, re.S):
            cols = [re.sub(r'\s+', ' ', c.strip()) for c in body.split(",\n") if c.strip() and not c.strip().upper().startswith(("PRIMARY KEY", "FOREIGN", "UNIQUE"))]
            pk = re.search(r'PRIMARY KEY\s*\(([^)]*)\)', body)
            dbs.append({"file": m, "table": name, "pk": pk.group(1) if pk else next((c.split()[0] for c in cols if "PRIMARY KEY" in c.upper()), ""), "cols": [[c.split()[0], " ".join(c.split()[1:])] for c in cols]})
    # 내부 모듈로 해석되는 import 만 남기고, 파일 노드를 만든다
    def resolve(nm):
        while nm and nm not in mods: nm = nm.rpartition(".")[0]
        return nm or None
    clean = []
    for f, t, ty, lab in edges:
        if t.startswith("file:"):
            fid = t
            nodes.setdefault(fid, {"c": "data", "n": t[5:], "s": "", "d": ""}); clean.append([f, fid, ty, lab]); continue
        r = resolve(t)
        if r and r != f and [f, r, ty, lab] not in clean: clean.append([f, r, ty, lab])
    # 2) systemd 유닛
    for p in files(root, {".service", ".timer"}):
        txt = p.read_text(encoding="utf-8", errors="ignore")
        cal = re.search(r'OnCalendar=(.*)', txt); ex = re.search(r'ExecStart=(.*)', txt)
        nid = "unit:" + p.stem
        nodes[nid] = {"c": "timer", "n": p.name, "s": (cal.group(1) if cal else (ex.group(1)[-50:] if ex else "")), "d": ""}
        if ex:
            m = re.search(r'-m ([\w.]+)|uvicorn ([\w.]+):', ex.group(1))
            tgt = (m.group(1) or m.group(2)) if m else None
            if tgt and resolve(tgt): clean.append([nid, resolve(tgt), "call", ex.group(1)[:40]])
    # 3) 프론트 JS
    for p in files(root, {".js", ".html"}):
        src = p.read_text(encoding="utf-8", errors="ignore")
        nid = "web:" + str(p.relative_to(root)); nodes[nid] = {"c": "web", "n": str(p.relative_to(root)), "s": "", "d": ""}
        for url in set(re.findall(r'["\'`](/api/[\w/.-]+)', src)):
            for m, n in nodes.items():
                if n["c"] == "api" and url.split("?")[0] in n["s"]: clean.append([nid, m, "http", url])
    # DB 파일별로 테이블 묶기 (파일→DB 매핑은 사람이 확인)
    grouped = {}
    for t in dbs: grouped.setdefault(t["file"], []).append(t)
    out_dbs = [{"id": f.replace(".", "_"), "name": f + " (DB 파일명 확인 필요)", "writer": "확인 필요", "readers": [], "tables": [{"n": t["table"], "pk": t["pk"], "cols": t["cols"]} for t in ts]} for f, ts in grouped.items()]
    data = {"title": root.name + " 프로젝트 지도", "subtitle": "scan.py 초안 — 설명(d)·overview·rels·writer 는 코드를 읽고 채울 것",
            "overview": {"intro": "", "lanes": []},
            "columns": [{"id": "timer", "label": "실행 주체"}, {"id": "job", "label": "스크립트 / 프로세스"}, {"id": "lib", "label": "공용 모듈"}, {"id": "data", "label": "데이터 파일"}, {"id": "api", "label": "API 서버"}, {"id": "web", "label": "브라우저"}],
            "nodes": nodes, "edges": clean, "dbs": out_dbs, "rels": []}
    pathlib.Path(out).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"초안 → {out}: nodes={len(nodes)} edges={len(clean)} tables={len(dbs)}")
if __name__ == "__main__":
    if len(sys.argv) != 3: sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
