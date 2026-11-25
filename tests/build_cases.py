"""產生測試 Case（以一份『乾淨基準案』為底，每案只改動一處，確保一案只觸發預期規則）。"""
import copy, json
from pathlib import Path

OUT = Path(__file__).parent / "cases"
AMT = 80_000_000

def fact(fid, value, label="明載", source="doc1#p3", **kw):
    d = {"fact_id": fid, "value": value, "label": label, "source": source}
    d.update(kw); return d

def base_case():
    return {
        "case_id": "CASE-T", "version": 1, "submitted_by": "tester", "submitted_at": "2026-11-24",
        "authority_ref": "PLACEHOLDER-0",
        "basic": {"name": "測試案", "deal_type": "入股", "amount": AMT, "currency": "TWD"},
        "documents": [{"doc_id": "doc1", "doc_type": "財報", "filename": "fs.pdf"}],
        "facts_provided": {
            "financial.revenue_history": fact("F01", [100, 120, 150]),
            "financial.net_income_history": fact("F02", [10, 14, 20]),
            "financial.operating_cash_flow_history": fact("F03", [8, 12, 18]),
            "financial.interest_bearing_debt": fact("F04", 200_000_000),
            "financial.total_debt": fact("F05", 300_000_000),
            "financial.total_assets": fact("F06", 1_000_000_000),
            "financial.investment_amount": fact("F07", AMT),
            "financial.installment_structure": fact("F08", "分兩期，簽約30%/交割70%"),
            "financial.funding_source": fact("F09", "自有資金"),
            "financial.valuation_basis": fact("F10", "EV/EBITDA 8x"),
            "financial.return_base": fact("F11", 12),
            "financial.return_conservative": fact("F12", 5),
            "financial.return_optimistic": fact("F13", 18),
            "legal.shareholding_structure": fact("F14", "創辦人60%/本公司20%/其他20%"),
            "legal.control_voting_arrangement": fact("F15", "董事會5席，本公司1席"),
            "legal.related_party_disclosure": fact("F16", {"exists": False, "disclosed": True, "procedure_ok": True}),
            "legal.main_contract_draft": fact("F17", "SPA 草案 v3"),
            "portfolio.concentration_pct": fact("F18", 10),
            "market.competitive_landscape": fact("F19", "前三大占55%"),
            "market.peer_benchmark_return": fact("F20", 10),
            "investment.exit_path": fact("F21", "5年後IPO或回購"),
            "tw.asset_type": fact("T01", "有價證券"),
            "tw.direction": fact("T02", "取得"),
            "tw.counterparty": fact("T03", {"is_related": False, "substantive_checked": True, "is_domestic_gov": False, "is_group_internal": False}),
            "tw.procedures": fact("T04", {"target_fs_reviewed": "已具備", "board_approval": "已具備", "audit_committee_approval": "已具備", "independent_director_minutes": "已具備"}),
        },
    }

def agent(key, stance="有條件", ai=None, amt=AMT):
    a = {
        "agent": key, "case_id": "CASE-T", "version": 1, "status": "完成",
        "core_judgement": {"stance": stance, "summary": f"{key} 結論摘要", "confidence": "中"},
        "top_risks": [{"concern_id": f"{key}-R1", "description": "一般營運風險", "severity": "中",
                       "category": "營運", "evidence_refs": ["doc1#p5"]}],
        "missing_info": [],
        "claims": [{"claim": "出資金額如附件所載", "label": "明載", "evidence_refs": ["doc1#p3"],
                    "numbers_used": [{"fact_id": "F07", "key": "financial.investment_amount", "value": amt}]}],
        "conditions_proposed": [], "questions_for_human": [],
    }
    if key == "audit":
        a["ai_recommendation"] = ai or "推進"
    return a

def agents(ai="推進", stance="支持", amt=AMT):
    return {k: agent(k, stance, ai, amt) for k in ("investment", "finance", "legal", "audit")}

TEST_COMPANY = {"name": "寶碩(測試用假資料，非真實數字)", "is_public_offering": True, "paid_in_capital": 1_000_000_000,
                "par_value": 10, "parent_equity": 2_000_000_000, "total_assets": 3_000_000_000,
                "has_audit_committee": True, "has_independent_directors": True, "is_professional_investor": False, "total_assets_basis": "個體"}
CLEAN_STATE = {"rounds_used": 0, "unresolved_critical_gaps": []}
cases = []
def add(name, desc, case, ag, expect, state=None, company=None, auth=None):
    cases.append({"name": name, "description": desc, "case": case, "agents": ag,
                  "review_state": state or CLEAN_STATE, "company": company or TEST_COMPANY,
                  "authority_override": auth or {}, "expect": expect})

# 01 乾淨綠燈
add("01_clean_green", "全部齊全、無觸發、稽核同意推進", base_case(), agents(),
    {"rule_light": "綠", "final_light": "綠", "rules": [], "missing": []})

# 02 缺關鍵財務欄位，但 AI 說推進 → 必須紅燈且 AI 被擋
c = base_case(); del c["facts_provided"]["financial.operating_cash_flow_history"]
add("02_missing_ocf_ai_says_go", "缺營業現金流；稽核仍建議推進，不得放行", c, agents("推進"),
    {"rule_light": "紅", "final_light": "紅", "rules": ["R1"],
     "missing": ["financial.operating_cash_flow_history"], "override_blocked": True})

# 03 數字矛盾（稽核引用 8,400 萬 vs 登記表 8,000 萬，差 4.8%）
ag = agents(); ag["audit"]["claims"][0]["numbers_used"][0]["value"] = 84_000_000
add("03_number_mismatch", "稽核引用金額與登記表差>1%", base_case(), ag, {"rule_light": "紅", "final_light": "紅", "rules": ["R2"], "missing": []})

# 04 超過單案金額上限
c = base_case(); c["facts_provided"]["financial.investment_amount"]["value"] = 120_000_000
add("04_over_amount_limit", "出資1.2億 > 上限1億", c, agents(amt=120_000_000),
    {"rule_light": "紅", "final_light": "紅", "rules": ["R4"], "missing": []})

# 05 重大合規疑慮
ag = agents(); ag["legal"]["top_risks"].append({"concern_id": "L-COMP-1", "description": "疑似違反外資持股限制",
    "severity": "高", "category": "合規", "evidence_refs": ["doc2#p9"]})
add("05_major_compliance", "法務標示高嚴重度合規疑慮", base_case(), ag, {"rule_light": "紅", "final_light": "紅", "rules": ["R3"], "missing": []})

# 06 關係人交易未揭露
c = base_case(); c["facts_provided"]["legal.related_party_disclosure"]["value"] = {"exists": True, "disclosed": False, "procedure_ok": False}
add("06_related_party_undisclosed", "存在關係人交易但未揭露", c, agents(), {"rule_light": "紅", "final_light": "紅", "rules": ["R5"], "missing": []})

# 07 無憑據結論
ag = agents(); ag["finance"]["claims"][0]["evidence_refs"] = []
add("07_no_evidence", "財務 Agent 的結論全無出處", base_case(), ag, {"rule_light": "紅", "final_light": "紅", "rules": ["R6"], "missing": []})

# 08 Agent 失敗
ag = agents(); ag["finance"]["status"] = "失敗"
add("08_agent_failed", "財務 Agent 重試+備援後仍失敗", base_case(), ag, {"rule_light": "紅", "final_light": "紅", "rules": ["R7"], "missing": []})

# 09 補問兩輪仍有缺口
add("09_rounds_exhausted", "補問2輪後關鍵缺口仍在", base_case(), agents(),
    {"rule_light": "紅", "final_light": "紅", "rules": ["R8"], "missing": []},
    {"rounds_used": 2, "unresolved_critical_gaps": ["估值依據仍無第三方報告"]})

# 10 黃燈：過度樂觀 + 非關鍵缺漏 + 待談條件
c = base_case(); c["facts_provided"]["financial.return_base"]["value"] = 16
del c["facts_provided"]["market.competitive_landscape"]
ag = agents("有條件推進"); ag["investment"]["conditions_proposed"] = ["取得董事會觀察員席位"]
add("10_yellow_mix", "基準回報16%>同業10%+5；缺競爭格局；有待談條件", c, ag,
    {"rule_light": "黃", "final_light": "黃", "rules": ["Y1", "Y2", "Y3"], "missing": []})

# 11 規則黃、稽核暫緩 → 最終紅（取較嚴）
c = base_case(); c["facts_provided"]["financial.return_conservative"]["value"] = 2
add("11_yellow_ai_stricter", "規則僅黃燈，稽核建議暫緩 → 最終紅", c, agents("暫緩"),
    {"rule_light": "黃", "final_light": "紅", "rules": ["Y4"], "missing": []})

# 12 規則綠、稽核有條件 → 最終黃
add("12_green_ai_conditional", "規則綠燈，稽核有條件推進 → 最終黃", base_case(), agents("有條件推進"),
    {"rule_light": "綠", "final_light": "黃", "rules": [], "missing": []})

# 13 結論分歧
ag = agents("有條件推進"); ag["investment"]["core_judgement"]["stance"] = "支持"; ag["legal"]["core_judgement"]["stance"] = "保留"
add("13_stance_divergence", "投資支持、法務保留（差2級）", base_case(), ag, {"rule_light": "黃", "final_light": "黃", "rules": ["Y5"], "missing": []})

# 14 授權版本/幣別不符
c = base_case(); c["authority_ref"] = "OLD-2025"; c["basic"]["currency"] = "USD"
add("14_authority_mismatch", "授權版本與幣別皆不符", c, agents(), {"rule_light": "紅", "final_light": "紅", "rules": ["R4"], "missing": []})

# 15 多欄位缺漏，需精準列出欄位名
c = base_case(); c["facts_provided"]["legal.main_contract_draft"] = fact("F17", None, label="缺漏", source=None)
c["facts_provided"]["financial.funding_source"]["value"] = ""
add("15_multi_missing", "合約草案標缺漏、資金來源為空", c, agents(),
    {"rule_light": "紅", "final_light": "紅", "rules": ["R1"],
     "missing": ["financial.funding_source", "legal.main_contract_draft"]})

# 16 關鍵欄位僅為推論
c = base_case(); c["facts_provided"]["financial.valuation_basis"] = fact("F10", "同業倍數推估", label="推論", source=None, inferred_by="財務")
add("16_critical_only_inferred", "估值依據只是推論", c, agents("有條件推進"), {"rule_light": "黃", "final_light": "黃", "rules": ["Y6"], "missing": []})

# ================= 取處準則（寶碩）測試 =================
BIG = {"max_single_amount": 5_000_000_000}
ALL_OK = {k: "已具備" for k in ["target_fs_reviewed", "cpa_price_opinion", "appraisal_report", "expert_independence",
          "board_approval", "audit_committee_approval", "independent_director_minutes", "related_pack",
          "related_valuation_or_cpa", "shareholder_approval", "related_cost_cpa_review", "merger_expert_opinion",
          "cpa_opinion_appraisal_gap"]}

def tw_case(amount, asset="有價證券", direction="取得", procs=None, cp=None, flags=None, ap=None):
    c = base_case(); f = c["facts_provided"]
    f["financial.investment_amount"]["value"] = amount
    f["tw.asset_type"]["value"] = asset; f["tw.direction"]["value"] = direction
    f["tw.procedures"]["value"] = procs if procs is not None else {}
    if cp: f["tw.counterparty"]["value"].update(cp)
    if flags: f["tw.asset_flags"] = fact("T05", flags)
    if ap: f["tw.appraisals"] = fact("T06", ap)
    return c

def exp(light, rules, unmet=None, post=None, final=None):
    e = {"rule_light": light, "final_light": final or light, "rules": rules, "missing": []}
    if unmet is not None: e["tw_unmet"] = sorted(unmet)
    if post is not None: e["post"] = post
    return e

# 17 不動產 2.5億（≥門檻2億）完全沒規劃
add("17_tw_realestate_nothing_planned", "不動產2.5億≥實收資本20%(2億)：估價/獨立性/董事會等皆未規劃",
    tw_case(250_000_000, "不動產"), agents(amt=250_000_000),
    exp("紅", ["R9"], ["appraisal_report", "audit_committee_approval", "board_approval", "expert_independence", "independent_director_minutes"]), auth=BIG)

# 18 同案全部「待辦」→ 黃燈（有條件推進）
pend = {k: "待辦" for k in ["appraisal_report", "expert_independence", "board_approval", "audit_committee_approval", "independent_director_minutes"]}
add("18_tw_realestate_all_pending", "同案但程序皆已排程待辦 → 黃燈，條件=簽約付款前完成",
    tw_case(250_000_000, "不動產", procs=pend), agents("有條件推進", amt=250_000_000), exp("黃", ["Y7"], []), auth=BIG)

# 19 估價差距≥20%且無會計師意見
okp = dict(ALL_OK); okp.pop("cpa_opinion_appraisal_gap")
add("19_tw_appraisal_gap_no_cpa", "估價18億/20億 vs 交易2.5億 差距≥20%，缺會計師意見",
    tw_case(250_000_000, "不動產", procs=okp, ap={"values": [180_000_000, 200_000_000], "report_date": "2026-10-01", "contract_date": "2026-11-20"}),
    agents(amt=250_000_000), exp("紅", ["R9"], ["cpa_opinion_appraisal_gap"]), auth=BIG)

# 20 估價報告逾三個月
add("20_tw_appraisal_stale", "估價報告6/1、契約11/20，逾三個月",
    tw_case(250_000_000, "不動產", procs=ALL_OK, ap={"values": [240_000_000, 260_000_000], "report_date": "2026-06-01", "contract_date": "2026-11-20"}),
    agents(amt=250_000_000), exp("紅", ["R9"], ["appraisal_date_validity"]), auth=BIG)

# 21 ≥10億只有一家估價
add("21_tw_need_two_appraisers", "交易12億僅一家估價",
    tw_case(1_200_000_000, "不動產", procs=ALL_OK, ap={"values": [1_200_000_000], "report_date": "2026-10-01", "contract_date": "2026-11-20"}),
    agents(amt=1_200_000_000), exp("紅", ["R9"], ["second_appraisal"]), auth=BIG)

# 22 有價證券≥門檻缺會計師意見
p22 = dict(ALL_OK); p22.pop("cpa_price_opinion")
add("22_tw_securities_no_cpa", "有價證券2.5億≥門檻，缺會計師價格合理性意見",
    tw_case(250_000_000, "有價證券", procs=p22), agents(amt=250_000_000), exp("紅", ["R9"], ["cpa_price_opinion"]), auth=BIG)

# 23 活絡市場報價例外 → 不需 FS/CPA，其餘程序齊備 → 綠，並列公告義務
add("23_tw_active_quote_green", "有價證券具活絡報價，免FS/CPA；董事會/審計委員會齊備 → 綠；列第31條第8款公告",
    tw_case(250_000_000, "有價證券", procs=ALL_OK, flags={"active_quote": True}), agents(amt=250_000_000),
    exp("綠", [], [], post=["disclosure", "retention"]), auth=BIG)

# 24 關係人交易缺七項資料
p24 = dict(ALL_OK); p24.pop("related_pack")
add("24_tw_related_no_pack", "關係人交易2.5億缺第15條資料包",
    tw_case(250_000_000, "有價證券", procs=p24, cp={"is_related": True}), agents(amt=250_000_000),
    exp("紅", ["R9"], ["related_pack"]), auth=BIG)

# 25 關係人≥總資產10%（3億）缺估價/會計師與股東會
p25 = dict(ALL_OK); [p25.pop(k) for k in ("related_valuation_or_cpa", "shareholder_approval")]
add("25_tw_related_over_10pct_assets", "關係人交易3.5億≥總資產10%：缺第14條意見與股東會同意",
    tw_case(350_000_000, "有價證券", procs=p25, cp={"is_related": True}), agents(amt=350_000_000),
    exp("紅", ["R9"], ["related_valuation_or_cpa", "shareholder_approval"]), auth=BIG)

# 26 未完成實質關係人判斷
add("26_tw_substantive_unchecked", "未做實質關係人判斷", tw_case(80_000_000, procs=ALL_OK, cp={"substantive_checked": False}), agents(),
    exp("紅", ["R9"], []))

# 27 寶碩資料缺漏（真實設定檔預設狀態）
add("27_tw_company_profile_missing", "寶碩實收資本額未填 → 鎖紅", base_case(), agents(),
    exp("紅", ["R9"], []), company={"name": "寶碩", "is_public_offering": True, "paid_in_capital": None, "par_value": 10,
        "total_assets": 3_000_000_000, "has_audit_committee": True, "has_independent_directors": True, "is_professional_investor": False})

# 28 超出 v1 範圍
add("28_tw_unsupported_asset", "衍生性商品：規則庫v1不涵蓋 → 人工覆核", tw_case(80_000_000, "衍生性商品"), agents(), exp("紅", ["R9"], []))

# 29 併購缺專家意見
p29 = dict(ALL_OK); p29.pop("merger_expert_opinion")
add("29_tw_merger_no_expert", "收購/股份受讓缺會計師/律師/承銷商合理性意見",
    tw_case(80_000_000, "併購", procs=p29), agents(), exp("紅", ["R9"], ["merger_expert_opinion"], post=["disclosure", "retention"]))

# 30 面額非10元：以權益換算（權益10% = 實收資本20%）
add("30_tw_par_not_10", "面額5元，母公司權益2億→門檻2000萬；金額3000萬需CPA，未規劃→紅",
    tw_case(30_000_000, "無形資產", procs={}), agents(amt=30_000_000),
    exp("紅", ["R9"], ["audit_committee_approval", "board_approval", "cpa_price_opinion", "expert_independence", "independent_director_minutes"]),
    company={"name": "寶碩(測試)", "is_public_offering": True, "paid_in_capital": 400_000_000, "par_value": 5, "parent_equity": 200_000_000,
             "total_assets": 3_000_000_000, "has_audit_committee": True, "has_independent_directors": True, "is_professional_investor": False}, auth=BIG)

# 31/32 未達3000萬 → 上簽董事長
add("31_tw_chairman_path_green", "有價證券2000萬<3000萬：FS已具備、董事長核准已具備 → 綠",
    tw_case(20_000_000, procs={"target_fs_reviewed": "已具備", "chairman_approval": "已具備"}), agents(amt=20_000_000), exp("綠", [], []))
add("32_tw_chairman_missing", "有價證券2000萬缺董事長核准", tw_case(20_000_000, procs={"target_fs_reviewed": "已具備"}), agents(amt=20_000_000),
    exp("紅", ["R9"], ["chairman_approval"]))
# 33 總資產採合併數暫代 → 黃燈
add("33_tw_assets_basis_consolidated", "寶碩總資產採合併數暫代 → Y8 黃燈", base_case(), agents("有條件推進"),
    exp("黃", ["Y8"], []), company={**TEST_COMPANY, "total_assets_basis": "合併(暫代)"})

for t in cases:
    (OUT / f"{t['name']}.json").write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"generated {len(cases)} cases")

