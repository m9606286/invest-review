import io, json, sys, tempfile, copy
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests_step3"))
from jsonschema import Draft202012Validator
from engine.chunker import chunk_sources
from engine.extract import extract, build_case_package
from engine import related_party as RP, store
from engine.pipeline import run_case
from engine.rules import load_yaml, LIGHT_ORDER
from agents import legal_dd as DD
from mock import ScriptedLLM, behavior_default, build

R = []
def check(name, cond, detail=""): R.append((name, bool(cond), detail))
CS = Draft202012Validator(json.load(open(ROOT / "schemas/chunk.schema.json", encoding="utf-8")))
DOCS = {p.name: p.read_bytes() for p in sorted((ROOT / "samples/docs").glob("*"))}
COMPANY = {**load_yaml("company_profile.yaml"), "total_assets_basis": "個體"}
OKP = {k: "已具備" for k in ["target_fs_reviewed", "board_approval", "audit_committee_approval", "independent_director_minutes"]}
BASIC = {"name": "甲科技 增資入股", "deal_type": "股權投資/增資", "asset_type": "有價證券", "direction": "取得", "concentration_pct": 10, "submitted_at": "2026-11-24"}

def make(basic=None, sources=None, roster=None, procs=None, version=1, cid="CASE-T"):
    b = {**BASIC, **(basic or {})}
    if procs is not None: b["procedures"] = procs
    ch, _ = chunk_sources(list((sources or DOCS).items()))
    ex = extract(ch, b, roster_result=roster)
    return build_case_package(cid, version, b, ch, ex), ch, ex

def run(case, ch, beh, company=COMPANY, **kw):
    llm = ScriptedLLM(beh); return run_case(case, ch, llm, company=company, **kw), llm

# ================= 1. 切片 =================
ch, notes = chunk_sources(list(DOCS.items()))
check("1.1 所有切片符合 chunk.schema", all(not list(CS.iter_errors(c)) for c in ch))
tbl = [c for c in ch if c["is_table"]]
check("1.2 財報表格完整保留於單一切片（含首列到末列）", len(tbl) == 1 and "營業收入" in tbl[0]["text"] and "有息借款" in tbl[0]["text"] and "單位：新臺幣仟元" in tbl[0]["text"])
check("1.3 數字不被拆散（8,000萬元完整出現）", any("8,000萬元" in c["text"] for c in ch))
g = {c["source_file"]: c["evidence_grade"] for c in ch}
check("1.4 證據等級：財報/合約＝正式文件、簡報＝簡報/宣稱", g["甲科技_財務報告_會計師核閱.md"] == "正式文件" and g["甲科技_投資協議草案_v3.md"] == "正式文件" and g["甲科技_公司簡報.txt"] == "簡報/宣稱")
deck = [c for c in ch if c["source_file"].endswith("簡報.txt")][0]
check("1.5 簡報切片：低可信度＋警示（宣稱/未經證實/模糊用語）", deck["low_confidence"] and any("未經證實" in w for w in deck["warnings"]) and any("模糊" in w for w in deck["warnings"]))
long = "".join(f"第{i}項重點是營收成長1,234.5萬元，毛利率12.5%。" for i in range(1, 120))
lc, _ = chunk_sources([("長文.txt", long)])
check("1.6 長段落只在句界切：每塊皆以句號結尾、小數與千分位完整", len(lc) >= 2 and all(c["text"].endswith("。") for c in lc) and all("1,234.5萬元" in c["text"] for c in lc[:1]))
rows = "\n".join(f"| 項目{i} | {i*1000} | {i*2000} |" for i in range(500))
bt, _ = chunk_sources([("大表.md", "單位：元\n| 項目 | 甲 | 乙 |\n|---|---|---|\n" + rows)])
check("1.7 超大表格才分段，且每段重複表頭並警示", len(bt) >= 2 and all(c["text"].lstrip().startswith(("單位", "| 項目")) or "| 項目 | 甲 | 乙 |" in c["text"] for c in bt) and all(any("分段" in w for w in c["warnings"]) for c in bt))
import csv, openpyxl, docx
cb = "項目,2025\n營業收入,1000\n淨利,100\n".encode("utf-8")
wb = openpyxl.Workbook(); ws = wb.active; ws.title = "損益表"; ws.append(["項目", "2025"]); ws.append(["營業收入", 1000]); bio = io.BytesIO(); wb.save(bio)
d = docx.Document(); d.add_heading("財務概況", 1); d.add_paragraph("本公司營收穩定成長。"); t = d.add_table(rows=2, cols=2); t.cell(0, 0).text = "項目"; t.cell(0, 1).text = "金額"; t.cell(1, 0).text = "營業收入"; t.cell(1, 1).text = "1000"; dio = io.BytesIO(); d.save(dio)
mc, mn = chunk_sources([("a.csv", cb), ("b_財報.xlsx", bio.getvalue()), ("c_契約.docx", dio.getvalue())])
check("1.8 csv/xlsx/docx 可解析且表格為單一切片", not mn and sum(c["is_table"] for c in mc) == 3 and any("sheet:損益表" in c["location"] for c in mc))
pc, pn = chunk_sources([("壞檔.pdf", b"not a pdf")])
check("1.9 壞檔不會讓整體崩潰：回報錯誤並繼續", pc == [] and pn and "error" in pn[0])

# ================= 2. 事實抽取 =================
case, ch, ex = make(); F = ex["facts"]
check("2.1 投資金額=8,000萬（不誤抓『賠償上限20%』）", F["financial.investment_amount"]["value"] == 80_000_000 and F["financial.investment_amount"]["label"] == "明載")
check("2.2 財報表格數字依『仟元』單位換算為元", F["financial.total_assets"]["value"] == 3_000_000_000 and F["financial.revenue_history"]["value"][0] == 1_000_000_000)
check("2.3 簡報來源的回報/退出一律標『推論』（不當事實）", all(F[k]["label"] == "推論" for k in ("financial.return_base", "financial.return_conservative", "investment.exit_path")))
check("2.4 抓不到的欄位明確標『缺漏』且 value=None（不腦補）", F["tw.procedures"]["value"] == {} and Draft202012Validator({"type": "object"}).is_valid(F) and sum(1 for f in F.values() if f["label"] == "缺漏") >= 0)
c2, ch2, ex2 = make(sources={"只有簡報.txt": DOCS["甲科技_公司簡報.txt"]})
check("2.5 只有簡報時：財務/法務關鍵欄位為缺漏、報酬欄位標推論", ex2["facts"]["financial.total_assets"]["label"] == "缺漏" and ex2["facts"]["financial.total_assets"]["value"] is None and ex2["facts"]["legal.main_contract_draft"]["label"] == "缺漏")
check("2.6 組出的 case_package 通過 schema", not __import__("engine.rules", fromlist=["x"]).validate_case(case))
src3 = dict(DOCS); src3["甲科技_補充說明.md"] = "# 補充\n寶碩擬投資金額為新臺幣9,500萬元。".encode("utf-8")
c3, ch3, ex3 = make(sources=src3)
check("2.7 跨文件金額衝突：保留最高等級值並記錄 alt_values", ex3["facts"]["financial.investment_amount"].get("alt_values"))
r3, _ = run(c3, ch3, behavior_default)
check("2.8 跨文件金額衝突 → 規則引擎 R2 紅燈", r3["evaluation"]["final_light"] == "紅" and "R2" in r3["evaluation"]["triggered_rules"])

# ================= 3. 關係人初判 =================
def rp(txt, name="一般說明.md"):
    c, _ = chunk_sources([(name, txt)]); return RP.assess(c)
check("3.1 明確涉及（附切片出處）", (lambda r: r["status"] == "明確涉及" and r["evidence"][0]["chunk_id"].startswith("C"))(rp("甲科技為寶碩之關係人。")))
check("3.2 有疑似線索", rp("甲科技董事長與寶碩董事為二親等親屬。")["status"] == "有疑似線索")
check("3.3 資料載明非關係人（正式文件）", rp("甲科技聲明與寶碩間非屬關係人。", "投資協議_契約.md")["status"] == "資料載明非關係人")
check("3.4 資料未載明", rp("甲科技成立於2010年，主要產品為感測器。")["status"] == "資料未載明")
w = rp("我們與寶碩非關係人，請放心。", "公司簡報.txt")
check("3.5 僅簡報宣稱非關係人 → 不採信，視為資料未載明", w["status"] == "資料未載明" and "不予採信" in w["note"])
cc, _ = chunk_sources([("a_契約.md", "甲科技聲明與寶碩非屬關係人。"), ("b_說明.md", "甲科技為寶碩之關係人。")])
check("3.6 切片間矛盾 → 明確涉及並標記矛盾", (lambda r: r["status"] == "明確涉及" and r["contradiction"])(RP.assess(cc)))
check("3.7 財報『歸屬於母公司業主』不誤判為關係人", rp("歸屬於母公司業主之淨利為1,000仟元。", "財報.md")["status"] == "資料未載明")
res = rp("甲科技成立於2010年。"); d0, cp0 = RP.to_facts(res, None); d1, cp1 = RP.to_facts(res, "否"); d2, cp2 = RP.to_facts(rp("甲科技為寶碩之關係人。"), "否")
check("3.8 名冊比對：未比對→substantive_checked=False；比對否→True；與資料衝突從嚴", cp0["substantive_checked"] is False and cp1["substantive_checked"] is True and cp1["is_related"] is False and cp2["is_related"] is True)
check("3.9 初判備註永遠聲明僅限現有資料、須與名冊比對", all("名冊比對" in x["note"] for x in (rp("a"), rp("甲科技為寶碩之關係人。"))))

# ================= 4. 法務DD清單 =================
p_eq = DD.identify_deal_profile({"deal_type": "股權投資/增資", "name": "x"}, {"tw.asset_type": {"value": "有價證券"}}, [])
p_as = DD.identify_deal_profile({"deal_type": "資產收購", "name": "不動產"}, {"tw.asset_type": {"value": "不動產"}}, [])
na_as = {t["item_id"] for t in DD.template(p_as) if not t["applicable"]}
check("4.1 依案型動態調整：資產收購標不適用（a3/c2/d7/d8…）並附原因", {"a3", "c2", "d7", "d8"} <= na_as and all(t["na_reason"] for t in DD.template(p_as) if not t["applicable"]))
check("4.2 五大構面皆有項目", {t["dimension"] for t in DD.template(p_eq)} == set("abcde"))

# ================= 5. 管線端到端 =================
case, ch, ex = make(roster="否", procs=OKP)
out, llm = run(case, ch, behavior_default); ev = out["evaluation"]; L = out["agents"]["legal"]
check("5.1 四Agent皆完成、各呼叫1次、補問輪未啟動", all(a["status"] == "完成" for a in out["agents"].values()) and out["agent_calls"] == {"investment": 1, "finance": 1, "legal": 1, "audit": 1}, out["agent_calls"])
check("5.2 簡報宣稱支撐關鍵欄位 → Y6，最終黃燈（不會綠燈）", ev["final_light"] == "黃" and "Y6" in ev["triggered_rules"], ev["triggered_rules"])
dd = L["specific"]["dd_checklist"]
check("5.3 DD 清單涵蓋全部項目、狀態合法、不適用有原因", len(dd) == len(DD.ITEMS) and all(d["status"] in DD.STATUSES for d in dd) and all(d.get("na_reason") for d in dd if d["status"] == "不適用"))
check("5.4 待查核項目同步進『缺漏資訊』並帶下一步", all(any(f"[DD-{d['item_id']}]" in m["item"] for m in L["missing_info"]) for d in dd if d["status"] == "待查核／資料缺漏"))
for h in ("一頁式決策摘要", "最終燈號", "觸發規則", "一句話結論", "最大亮點", "最大風險", "最急迫確認的 3 個問題", "關係人初判", "核心亮點 vs. 致命弱點", "三情境", "法務 DD 審查清單檢核表", "壓力測試", "解除條件", "資料切片清單"):
    check(f"5.5 報告含「{h}」", h in out["report_md"])
check("5.6 切片清單列出每個切片來源與可信度", all(c["chunk_id"] in out["report_md"] for c in ch))
d_def = ScriptedLLM(behavior_default); case0, ch0, _ = make()   # 預設：未比對名冊、程序未規劃
o0 = run_case(case0, ch0, d_def, company=COMPANY)
check("5.7 預設（名冊未比對、程序未規劃）→ 紅燈 R9，不放行", o0["evaluation"]["final_light"] == "紅" and "R9" in o0["evaluation"]["triggered_rules"])
check("5.8 AI建議推進仍不能放寬紅燈（不變式）", all(LIGHT_ORDER[run_case(case0, ch0, ScriptedLLM(lambda a, c, m, n, rec=rec: behavior_default(a, c, m, n, ai=rec)), company=COMPANY)["evaluation"]["final_light"]] == 2 for rec in ("推進", "有條件推進", "暫緩")))

# ---- 不得把宣稱當事實 ----
def b_claim(agent, ctx, model, n):
    o = behavior_default(agent, ctx, model, n)
    if agent == "finance":
        dk = [c["chunk_id"] for c in ctx["chunks"] if c["evidence_grade"] == "簡報/宣稱"][0]
        o["claims"].append({"claim": "客戶續約率95%已確認", "label": "明載", "evidence_refs": [dk]})
    return o
o, _ = run(case, ch, b_claim)
check("5.9 『明載』僅憑簡報出處 → 自動降為推論並註記", any("已降為推論" in n for n in o["pipeline_notes"]) and any(c["claim"].startswith("【僅憑簡報") and c["label"] == "推論" for c in o["agents"]["finance"]["claims"]))
o, _ = run(case, ch, lambda a, c, m, n: behavior_default(a, c, m, n, fake_confirm={"b1"}, fake_ref=[x["chunk_id"] for x in ch if x["evidence_grade"] == "簡報/宣稱"][0]) if a == "legal" else behavior_default(a, c, m, n))
b1 = [d for d in o["agents"]["legal"]["specific"]["dd_checklist"] if d["item_id"] == "b1"][0]
check("5.10 DD『已確認』僅憑簡報 → 降為待查核", b1["status"] == "待查核／資料缺漏" and any("b1" in n for n in o["pipeline_notes"]))
o, _ = run(case, ch, lambda a, c, m, n: behavior_default(a, c, m, n, doubt={"d5"}, confirm=set()) if a == "legal" else behavior_default(a, c, m, n))
check("5.11 DD『有疑慮／高風險』同步進風險清單", any("[DD-d5]" in r["description"] for r in o["agents"]["legal"]["top_risks"]))
o, _ = run(case, ch, lambda a, c, m, n: behavior_default(a, c, m, n, skip={"a1", "a2"}) if a == "legal" else behavior_default(a, c, m, n))
check("5.12 法務遺漏的DD項目被補列為待查核（不得跳過）", {d["item_id"]: d["status"] for d in o["agents"]["legal"]["specific"]["dd_checklist"]}["a1"] == "待查核／資料缺漏")

# ================= 6. 品質守門與重試 =================
def b_fluff(agent, ctx, model, n):
    o = behavior_default(agent, ctx, model, n)
    if agent == "investment" and n == 0: o["top_risks"][0]["description"] = "一般營運風險"
    return o
o, llm = run(case, ch, b_fluff)
check("6.1 空泛套話（一般營運風險）被擋，重試後通過", o["agent_calls"]["investment"] == 2 and any("25字" in t.get("error", "") or "空泛" in t.get("error", "") for t in o["trace"]))
def b_ref(agent, ctx, model, n):
    o = behavior_default(agent, ctx, model, n)
    if agent == "finance" and n == 0: o["claims"][0]["evidence_refs"] = ["C999"]
    return o
o, _ = run(case, ch, b_ref)
check("6.2 引用不存在的切片編號被擋，重試後通過", o["agent_calls"]["finance"] == 2 and any("C999" in t.get("error", "") for t in o["trace"]))
o, _ = run(case, ch, lambda a, c, m, n: behavior_default(a, c, m, n, rp_status="明確涉及") if (a == "legal" and n == 0) else behavior_default(a, c, m, n))
check("6.3 法務擅改關係人初判狀態被擋", o["agent_calls"]["legal"] == 2 and any("related_party.status" in t.get("error", "") for t in o["trace"]))
def b_down(agent, ctx, model, n):
    if agent == "finance": raise RuntimeError("503")
    return behavior_default(agent, ctx, model, n)
o, _ = run(case, ch, b_down)
check("6.4 Agent當機：嘗試3次後標失敗 → R7紅燈", o["agent_calls"]["finance"] == 3 and "R7" in o["evaluation"]["triggered_rules"] and o["evaluation"]["final_light"] == "紅" and "執行失敗" in o["report_md"])
o, _ = run(case, ch, lambda a, c, m, n: (_ for _ in ()).throw(RuntimeError("x")) if (a == "finance" and m == "mock-primary") else behavior_default(a, c, m, n))
check("6.5 主模型失敗、備援成功 → 『降級』並記備註", o["agents"]["finance"]["status"] == "降級" and any("降級" in x for x in o["evaluation"]["notes"]))

# ================= 7. 補問輪（預設上限1） =================
gap = [{"gap_id": "G1", "description": "合約違約責任條款未說明", "target_agent": "legal", "fillable_from": "attachments", "critical": True}]
check("7.1 預設 max_follow_up_rounds = 1", load_yaml("rules.yaml")["max_follow_up_rounds"] == 1)
o, _ = run(case, ch, lambda a, c, m, n: behavior_default(a, c, m, n, gaps=gap) if a == "audit" else behavior_default(a, c, m, n))
check("7.2 缺口反覆出現：只補問1輪（法務共2次、稽核共2次），列缺口並出報告，R8紅燈", o["review_state"]["rounds_used"] == 1 and o["agent_calls"]["legal"] == 2 and o["agent_calls"]["audit"] == 2 and "R8" in o["evaluation"]["triggered_rules"] and "補件清單" in o["report_md"])
o, _ = run(case, ch, lambda a, c, m, n: behavior_default(a, c, m, n, gaps=(gap if n == 0 else [])) if a == "audit" else behavior_default(a, c, m, n))
check("7.3 補問成功：只重跑受影響Agent（法務+稽核），缺口解除", o["agent_calls"] == {"investment": 1, "finance": 1, "legal": 2, "audit": 2} and o["rounds_log"][0]["resolved"] == ["G1"] and "R8" not in o["evaluation"]["triggered_rules"])
hg = [{"gap_id": "G2", "description": "估價缺少第三方估價報告佐證", "target_agent": "finance", "fillable_from": "human", "critical": False}]
o, _ = run(case, ch, lambda a, c, m, n: behavior_default(a, c, m, n, gaps=hg) if a == "audit" else behavior_default(a, c, m, n))
check("7.4 需人工補件的非關鍵缺口：不重跑、列入補件清單、Y9", o["review_state"]["rounds_used"] == 0 and "Y9" in o["evaluation"]["triggered_rules"])
bad = copy.deepcopy(case); del bad["basic"]
check("7.5 輸入結構不合：拒收且不呼叫LLM", run_case(bad, ch, ScriptedLLM(behavior_default), company=COMPANY)["status"] == "INVALID_INPUT")

# ================= 8. 版本、差異、歷史 =================
with tempfile.TemporaryDirectory() as tmp:
    c1, ch1, _ = make(roster=None, procs={}); o1 = run_case(c1, ch1, ScriptedLLM(behavior_default), company=COMPANY); store.save_version(c1, ch1, o1, root=tmp)
    s2 = dict(DOCS); s2["甲科技_補件_法律意見書.md"] = "# 法律意見書\n經查詢，甲科技無重大訴訟與強制執行紀錄。".encode("utf-8")
    c2, ch2, _ = make(sources=s2, roster="否", procs=OKP, version=2); o2 = run_case(c2, ch2, ScriptedLLM(behavior_default), company=COMPANY); store.save_version(c2, ch2, o2, root=tmp)
    check("8.1 版本存檔與列出（v1,v2）", store.list_versions("CASE-T", tmp) == [1, 2] and c2["prev_version_ref"] == "CASE-T/v1")
    df = store.diff_versions(store.load_version("CASE-T", 1, tmp), store.load_version("CASE-T", 2, tmp))
    check("8.2 v1→v2 差異：新增文件、解除規則(R9)、燈號 紅→黃", "甲科技_補件_法律意見書.md" in df["new_documents"] and "R9" in df["rules_cleared"] and df["light_change"] == "紅 → 黃", df["light_change"])
    check("8.3 v2缺prev_version_ref會被schema擋", bool(__import__("engine.rules", fromlist=["x"]).validate_case({**c1, "version": 2})))
    store.record_decision({"case_id": "CASE-T", "version": 2, "deal_type": "股權投資/增資", "ai_recommendation": "有條件推進", "final_light": "黃", "human_decision": "暫緩", "decision_date": "2026-11-30", "diff_reason": "董事會要求先完成名冊比對與個體總資產確認", "postmortem_tags": ["簡報宣稱未驗證"], "triggered_rules": ["Y6"]}, root=tmp)
    store.record_decision({"case_id": "CASE-U", "version": 1, "ai_recommendation": "暫緩", "human_decision": "暫緩", "decision_date": "2026-12-01"}, root=tmp)
    check("8.4 『AI建議 vs 最終決策』可查不一致案件", [h["case_id"] for h in store.disagreements(tmp)] == ["CASE-T"])
    try: store.record_decision({"case_id": "X"}, root=tmp); ok = False
    except ValueError: ok = True
    check("8.5 決策回饋缺必填欄位會被擋", ok)
    sim = store.similar_cases("股權投資/增資", ["Y6"], root=tmp, exclude_case="CASE-NEW")
    o3 = run_case(c2, ch2, ScriptedLLM(behavior_default), company=COMPANY, history=sim)
    check("8.6 相似前案只進稽核參考欄（historical_commentary），不影響燈號", sim and "CASE-T" in o3["agents"]["audit"]["specific"]["historical_commentary"] and o3["evaluation"]["final_light"] == o2["evaluation"]["final_light"])

w = max(len(n) for n, _, _ in R)
for n, ok, d in R: print(f"{'PASS' if ok else 'FAIL'}  {n}" + ("" if ok else f"   <-- {d}"))
fails = sum(1 for _, ok, _ in R if not ok); print(f"\n總結：{len(R)-fails}/{len(R)} 通過"); sys.exit(1 if fails else 0)
