"""命令列版（與 UI 同一條管線）。
  python3 run_pipeline.py samples/docs --case-id CASE-1 --name "甲科技 增資入股" --asset-type 有價證券 --roster 否 --mock
  python3 run_pipeline.py 檔案或資料夾 ... --case-id CASE-1 --version 2 --reuse --live      # 補件 v2，沿用 v1 全部原始資料
程序狀態：--procs '{"board_approval":"已具備","audit_committee_approval":"已具備"}'（未列出者視為未規劃）"""
import argparse, json, sys
from datetime import date
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests_step3"))
from engine.chunker import chunk_sources
from engine.extract import extract, build_case_package
from engine.pipeline import run_case
from engine import store

ap = argparse.ArgumentParser(); ap.add_argument("paths", nargs="+"); ap.add_argument("--case-id", required=True); ap.add_argument("--version", type=int, default=1)
ap.add_argument("--name"); ap.add_argument("--deal-type", default="股權投資/增資"); ap.add_argument("--asset-type"); ap.add_argument("--direction", default="取得")
ap.add_argument("--concentration", type=float); ap.add_argument("--roster", choices=["是", "否"]); ap.add_argument("--procs", default="{}")
ap.add_argument("--reuse", action="store_true"); ap.add_argument("--mock", action="store_true"); ap.add_argument("--live", action="store_true"); a = ap.parse_args()
sources = store.load_sources(a.case_id, a.version - 1) if (a.reuse and a.version > 1) else []
for p in map(Path, a.paths):
    for f in ([p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file())):
        sources.append((f.name, f.read_bytes()))
chunks, notes = chunk_sources(sources)
for n in notes: print("⚠", n)
basic = {"name": a.name or a.case_id, "deal_type": a.deal_type, "asset_type": a.asset_type, "direction": a.direction, "concentration_pct": a.concentration,
         "submitted_at": date.today().isoformat(), "procedures": json.loads(a.procs)}
ex = extract(chunks, basic, roster_result=a.roster)
case = build_case_package(a.case_id, a.version, basic, chunks, ex)
if a.live:
    from engine.llm import AnthropicLLM; llm = AnthropicLLM()
elif a.mock:
    from mock import ScriptedLLM, behavior_default; llm = ScriptedLLM(behavior_default)
else: sys.exit("請指定 --live 或 --mock")
out = run_case(case, chunks, llm, history=store.similar_cases(a.deal_type, [], exclude_case=a.case_id))
if out["status"] != "OK": sys.exit(f"案件資料不合：{out['errors']}")
store.save_sources(a.case_id, a.version, sources); d = store.save_version(case, chunks, out)
ev = out["evaluation"]; print(f"{a.case_id} v{a.version} → 最終燈號 {ev['final_light']}（規則 {ev['rule_light']}／稽核 {ev['ai_light']}）觸發 {ev['triggered_rules']}\n報告：{d / 'report.md'}")
