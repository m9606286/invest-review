"""案件版本存檔（data/cases/<case_id>/v<n>/）、v1→v2 差異對照、決策回饋（data/history_decisions.jsonl）與相似歷史案件檢索。"""
import json, os, re
from datetime import datetime
from pathlib import Path

DATA = Path(os.environ.get("INVEST_DATA_DIR") or (Path(__file__).resolve().parent.parent / "data"))
LIGHT = {"綠": 0, "黃": 1, "紅": 2}


def _dir(case_id, version, root=None):
    return (Path(root) if root else DATA) / "cases" / re.sub(r"[^\w\-]+", "_", case_id) / f"v{version}"


def save_version(case, chunks, out, root=None):
    d = _dir(case["case_id"], case["version"], root); d.mkdir(parents=True, exist_ok=True)
    (d / "case.json").write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    if out:
        (d / "result.json").write_text(json.dumps({k: v for k, v in out.items() if k != "report_md"}, ensure_ascii=False, indent=2), encoding="utf-8")
        (d / "report.md").write_text(out["report_md"], encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({"saved_at": datetime.now().isoformat(timespec="seconds"), "final_light": out and out["evaluation"]["final_light"]}, ensure_ascii=False), encoding="utf-8")
    return d


def save_sources(case_id, version, sources, root=None):
    """保存原始上傳檔，v2 補件時可沿用 v1 的全部原始資料重新切片。sources: [(檔名, bytes|str)]"""
    d = _dir(case_id, version, root) / "sources"; d.mkdir(parents=True, exist_ok=True)
    for name, data in sources:
        (d / Path(name).name).write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


def load_sources(case_id, version, root=None):
    d = _dir(case_id, version, root) / "sources"
    return [(p.name, p.read_bytes()) for p in sorted(d.glob("*"))] if d.exists() else []


def list_cases(root=None):
    base = (Path(root) if root else DATA) / "cases"
    return sorted(p.name for p in base.glob("*") if p.is_dir()) if base.exists() else []


def list_versions(case_id, root=None):
    base = (Path(root) if root else DATA) / "cases" / re.sub(r"[^\w\-]+", "_", case_id)
    return sorted((int(p.name[1:]) for p in base.glob("v*") if p.is_dir()), key=int) if base.exists() else []


def load_version(case_id, version, root=None):
    d = _dir(case_id, version, root)
    g = lambda n: json.loads((d / n).read_text(encoding="utf-8")) if (d / n).exists() else None
    return {"case": g("case.json"), "chunks": g("chunks.json"), "result": g("result.json"),
            "report": (d / "report.md").read_text(encoding="utf-8") if (d / "report.md").exists() else None}


def _concerns(result):
    out = {}
    for k, o in (result or {}).get("agents", {}).items():
        for r in o.get("top_risks", []):
            out[r["concern_id"]] = {"agent": k, "description": r["description"], "severity": r["severity"]}
    return out


def diff_versions(old, new):
    """old/new = load_version() 的結果。回傳：新增了什麼、解除了哪些疑慮、出現哪些新問題、數字變動、燈號變化。"""
    fo, fn = (old["case"] or {}).get("facts_provided", {}), (new["case"] or {}).get("facts_provided", {})
    present = lambda f: bool(f) and f.get("label") != "缺漏" and f.get("value") not in (None, "", [], {})
    added = [k for k in fn if present(fn[k]) and not present(fo.get(k))]
    changed = [{"key": k, "old": fo[k]["value"], "new": fn[k]["value"]} for k in fn if present(fn[k]) and present(fo.get(k)) and fn[k]["value"] != fo[k]["value"]]
    removed = [k for k in fo if present(fo[k]) and not present(fn.get(k))]
    docs_old = {d["filename"] for d in (old["case"] or {}).get("documents", [])}
    new_docs = [d["filename"] for d in (new["case"] or {}).get("documents", []) if d["filename"] not in docs_old]
    co, cn = _concerns(old["result"]), _concerns(new["result"])
    ro = set((old["result"] or {}).get("evaluation", {}).get("triggered_rules", [])); rn = set((new["result"] or {}).get("evaluation", {}).get("triggered_rules", []))
    lo = (old["result"] or {}).get("evaluation", {}).get("final_light"); ln = (new["result"] or {}).get("evaluation", {}).get("final_light")
    return {"new_documents": new_docs, "facts_added": added, "facts_changed": changed, "facts_removed": removed,
            "concerns_resolved": [{"concern_id": k, **co[k]} for k in co if k not in cn],
            "concerns_new": [{"concern_id": k, **cn[k]} for k in cn if k not in co],
            "concerns_persisting": [k for k in cn if k in co],
            "rules_cleared": sorted(ro - rn), "rules_new": sorted(rn - ro), "light_old": lo, "light_new": ln,
            "light_change": None if lo == ln else f"{lo} → {ln}"}


def diff_summary_line(d):
    return (f"燈號 {d['light_old']}→{d['light_new']}；新增資料 {len(d['new_documents'])} 份/事實 {len(d['facts_added'])} 項；"
            f"解除疑慮 {len(d['concerns_resolved'])}、新增疑慮 {len(d['concerns_new'])}；解除規則 {','.join(d['rules_cleared']) or '無'}、新觸發 {','.join(d['rules_new']) or '無'}")


# ---------------- 決策回饋與歷史 ----------------
def history_path(root=None):
    return (Path(root) if root else DATA) / "history_decisions.jsonl"


def record_decision(rec, root=None):
    """rec: {case_id, version, ai_recommendation, final_light, human_decision, decision_date, diff_reason, postmortem_tags[], notes}"""
    need = ("case_id", "version", "human_decision")
    miss = [k for k in need if rec.get(k) in (None, "")]
    if miss: raise ValueError("缺少欄位：" + "、".join(miss))
    p = history_path(root); p.parent.mkdir(parents=True, exist_ok=True)
    rec = {**rec, "recorded_at": datetime.now().isoformat(timespec="seconds")}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def load_history(root=None):
    p = history_path(root)
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def disagreements(root=None):
    """AI 建議與人工最終決策不一致的歷史案件。"""
    norm = {"推進": "推進", "綠": "推進", "有條件推進": "有條件推進", "黃": "有條件推進", "暫緩": "暫緩", "紅": "暫緩"}
    return [h for h in load_history(root) if norm.get(h.get("ai_recommendation"), h.get("ai_recommendation")) != norm.get(h.get("human_decision"), h.get("human_decision"))]


def similar_cases(deal_type, triggered_rules, tags=None, root=None, limit=3, exclude_case=None):
    """相似前案（只當參考提醒，不是證據）：依交易型態、觸發規則重疊、踩坑標籤計分。"""
    scored = []
    for h in load_history(root):
        if h.get("case_id") == exclude_case: continue
        s = (2 if deal_type and h.get("deal_type") == deal_type else 0) + len(set(h.get("triggered_rules", [])) & set(triggered_rules)) + len(set(h.get("postmortem_tags", [])) & set(tags or []))
        if s > 0: scored.append((s, h))
    scored.sort(key=lambda x: -x[0])
    return [{"case_id": h["case_id"], "version": h["version"], "deal_type": h.get("deal_type"), "ai_recommendation": h.get("ai_recommendation"),
             "human_decision": h["human_decision"], "diff_reason": h.get("diff_reason"), "postmortem_tags": h.get("postmortem_tags", []),
             "note": "僅供參考提醒，不得當作證據"} for _, h in scored[:limit]]
