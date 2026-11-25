"""埋雷測試（樣本 samples/docs_B）。
Part A（不需 API，確定性）：切片/抽取/規則引擎必抓的埋雷。
Part B（需 ANTHROPIC_API_KEY）：真實 LLM 稽核命中率——本環境無 key，尚未實測；有 key 時執行：ANTHROPIC_API_KEY=... python3 run_anchor_test.py"""
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests_step3"))
from engine.chunker import chunk_sources
from engine.extract import extract, build_case_package
from engine.pipeline import run_case
from engine.rules import load_yaml
src = [(p.name, p.read_bytes()) for p in sorted((ROOT / "samples/docs_B").glob("*"))]
chunks, _ = chunk_sources(src)
basic = {"name": "乙地產 入股", "deal_type": "股權投資/增資", "asset_type": "有價證券", "direction": "取得", "concentration_pct": 10, "submitted_at": "2026-12-01"}
ex = extract(chunks, basic); case = build_case_package("ANCHOR-B", 1, basic, chunks, ex)
company = {**load_yaml("company_profile.yaml"), "total_assets_basis": "個體"}
F = ex["facts"]
A = {"P3 跨文件金額衝突(8,000萬 vs 9,500萬) 被切片器標出": bool(F["financial.investment_amount"].get("alt_values")),
     "P4 關係人疑似線索(二親等親屬)被初判抓到": ex["related"]["status"] in ("有疑似線索", "明確涉及"),
     "P2 簡報IRR(22%)只標推論、不當事實": F["financial.return_base"]["label"] == "推論",
     "P5 簡報『無須審議程序』被標為宣稱/口頭，低可信": any(c["low_confidence"] and "審議" in c["text"] for c in chunks)}
from mock import ScriptedLLM, behavior_default
o = run_case(case, chunks, ScriptedLLM(behavior_default), company=company)
A["規則引擎對上述組合給出紅燈(R2/R9)，AI無法放寬"] = o["evaluation"]["final_light"] == "紅" and {"R2", "R9"} <= set(o["evaluation"]["triggered_rules"])
print("Part A（確定性）"); [print(("PASS " if v else "FAIL ") + k) for k, v in A.items()]
if not os.environ.get("ANTHROPIC_API_KEY"):
    print("\nPart B：未設定 ANTHROPIC_API_KEY，真實稽核命中率尚未實測。"); sys.exit(0 if all(A.values()) else 1)
from engine.llm import AnthropicLLM
r = run_case(case, chunks, AnthropicLLM(), company=company)
txt = json.dumps(r["agents"]["audit"].get("specific", {}), ensure_ascii=False) + json.dumps(r["agents"]["audit"]["top_risks"], ensure_ascii=False)
planted = {"P1 簡報稱無有息負債 vs 財報有息借款": ["有息"], "P2 IRR 22% 遠高於同業10%": ["22", "樂觀"], "P3 投資金額 8,000萬 vs 9,500萬": ["9,500", "9500", "95000000", "金額"],
           "P5 簡報稱無須審議程序": ["審議"], "P6 營業現金流為負/獲利品質": ["現金流"]}
hits = {k: any(w in txt for w in ws) for k, ws in planted.items()}
print("\nPart B（真實LLM稽核命中）"); [print(("HIT  " if v else "MISS ") + k) for k, v in hits.items()]; print(f"命中 {sum(hits.values())}/{len(hits)}；最終燈號 {r['evaluation']['final_light']}")
