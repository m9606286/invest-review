"""ScriptedLLM：腳本化模擬 LLM，產出符合深度報告 Schema 的輸出，並可注入各種故障。
這驗證的是『管線、守門、規則閘門』，不是真實 LLM 的判斷品質（真實命中率請用 run_anchor_test.py 搭配 API key）。"""
import json

LONG = "（依切片出處分析，說明成因、機制與影響，並區分事實、推論與缺漏。）"
def pad(t, n=90): return t if len(t) >= n else t + LONG * ((n - len(t)) // len(LONG) + 1)


class ScriptedLLM:
    models = ["mock-primary", "mock-backup"]

    def __init__(self, behavior):
        self.behavior, self.calls = behavior, []

    def complete(self, system, user, model):
        ctx = json.loads(user.split("\n\n[上次")[0])
        agent = ctx["agent"]; n = sum(1 for c in self.calls if c["agent"] == agent)
        self.calls.append({"agent": agent, "model": model, "followup": bool(ctx.get("followup_questions"))})
        out = self.behavior(agent, ctx, model, n)
        return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)


def _ids(ctx, grade=None, tag=None):
    return [c["chunk_id"] for c in ctx["chunks"] if (grade is None or c["evidence_grade"] in grade) and (tag is None or True)]


def _amount_claim(ctx, ref, value=None):
    f = ctx["facts_registry"]["financial.investment_amount"]
    return {"claim": "擬投資金額如登記表所載（來源切片），已回頭對照登記表驗證", "label": "明載", "evidence_refs": [ref], "numbers_used": [
        {"fact_id": f["fact_id"], "key": "financial.investment_amount", "value": f["value"] if value is None else value}]}


def build(agent, ctx, stance="有條件", ai="有條件推進", **o):
    formal = _ids(ctx, ("正式文件", "一般文件")) or _ids(ctx); deck = [c["chunk_id"] for c in ctx["chunks"] if c["evidence_grade"] in ("簡報/宣稱", "口頭/未證實")]
    r0 = formal[0]; rd = (deck or formal)[0]
    base = {"agent": agent, "case_id": ctx["case_id"], "version": ctx["version"], "status": "完成",
            "core_judgement": {"stance": stance, "summary": pad(f"{agent} 審查結論：條件式支持，成立前提為正式文件佐證與程序完成；主要疑慮在簡報宣稱尚未驗證。", 60), "confidence": "中"},
            "top_risks": [{"concern_id": f"{agent}-證據-1", "description": pad(f"關鍵假設僅由簡報宣稱支撐（{rd}），尚未被正式文件驗證，若不成立將直接影響回報與談判籌碼。", 40), "severity": "中", "category": "財務", "evidence_refs": [rd]}],
            "missing_info": [], "claims": [_amount_claim(ctx, r0), {"claim": "簡報宣稱之成長與客戶續約數字，屬對方宣稱，尚未被正式文件驗證", "label": "推論", "inferred_by": {"investment": "投資", "finance": "財務", "legal": "法務", "audit": "稽核"}[agent], "evidence_refs": [rd]}],
            "conditions_proposed": [], "questions_for_human": [], "specific": {}}
    sp = {}
    if agent == "investment":
        sp = {"stance_rationale": pad("有條件支持：標的有正式財報佐證的成長與現金流，但市占與續約率只來自簡報。"), "business_model_analysis": pad("以產品銷售與服務續約為主，獲利取決於規模化與客戶留存。"),
              "market_and_moat": pad("市場地位僅有簡報宣稱，需以第三方資料驗證；財報顯示營收年增雙位數。"),
              "strengths_vs_weaknesses": [{"kind": "亮點", "point": "營收與現金流同步成長", "mechanism": pad("財報顯示淨利與營業現金流同向成長，獲利品質較佳。", 40), "chunk_refs": [r0]},
                                          {"kind": "弱點", "point": "成長假設過度依賴簡報", "mechanism": pad("三年成長率30%僅見簡報，若達不到，三情境回報將下修。", 40), "chunk_refs": [rd]}],
              "deal_terms_and_negotiation": pad("建議談判：分期付款綁定里程碑、取得董事會否決權、約定回購條款。"), "exit_and_liquidity_review": pad("退出依賴IPO宣稱，需約定回購與優先清算以降低卡死風險。"),
              "core_assumptions": [{"assumption": "營收年增率維持高成長且客戶續約穩定", "verifiability": "難驗證", "chunk_refs": [rd]}]}
    elif agent == "finance":
        sp = {"health_overview": pad("營收、淨利、營業現金流皆連年成長；負債比約47%，有息負債佔比偏高，需觀察利息保障。"),
              "key_metrics": [{"metric": "營收成長", "value_text": "見財報表格", "reading": pad("連續成長，但需排除一次性因素", 40), "refs": [r0]},
                              {"metric": "營業現金流/淨利", "value_text": "見財報表格", "reading": pad("現金流略低於淨利，獲利品質尚可但需看應收帳款", 40), "refs": [r0]},
                              {"metric": "負債比", "value_text": "見財報表格", "reading": pad("負債總額佔資產近半，需檢視還款壓力", 40), "refs": [r0]}],
              "capital_structure_and_asset_authenticity": pad("現金水位與應收、存貨明細未提供，無法排除虛增；列為缺漏，不假設沒問題。"),
              "consideration_and_funding_impact": pad("寶碩自有資金分兩期支付，對現金部位有壓力；若退出延後，回收期拉長，有資金卡死風險。"),
              "scenarios": {"optimistic": {"assumptions": pad("簡報宣稱之樂觀成長與續約率達成", 40), "return_text": "簡報宣稱約20%", "basis": "推論", "refs": [rd]},
                            "base": {"assumptions": pad("成長低於簡報宣稱，依基準假設估算", 40), "return_text": "簡報宣稱約12%", "basis": "推論", "refs": [rd]},
                            "conservative": {"assumptions": pad("成長減半且回收期延後一年", 40), "return_text": "簡報宣稱約5%", "basis": "推論", "refs": [rd]}},
              "contradictions_and_gaps": ["資金來源與付款節奏需與寶碩現金預測對齊"]}
    elif agent == "legal":
        rp = ctx["related_party_assessment"]
        tmpl = [t for t in ctx["dd_template"] if t["applicable"]]
        confirm = o.get("confirm", {"a2", "d1", "d5"})
        dd = []
        for t in tmpl:
            if t["item_id"] in o.get("doubt", set()): dd.append({"item_id": t["item_id"], "status": "有疑慮／高風險", "finding": "條款對寶碩不利，需談判調整", "chunk_refs": [r0], "next_step": "要求修改條款"})
            elif t["item_id"] in confirm: dd.append({"item_id": t["item_id"], "status": "已確認", "finding": "契約草案已有對應條款", "chunk_refs": [r0], "next_step": "定稿前再核對"})
            elif t["item_id"] in o.get("fake_confirm", set()): dd.append({"item_id": t["item_id"], "status": "已確認", "finding": "簡報稱已無問題", "chunk_refs": [o.get("fake_ref", rd)], "next_step": ""})
            elif t["item_id"] in o.get("skip", set()): continue
            else: dd.append({"item_id": t["item_id"], "status": "待查核／資料缺漏", "finding": "現有資料未涵蓋", "chunk_refs": [], "next_step": "向交易對方索取並查核"})
        sp = {"risk_overview": pad("法務面主要風險在關係人身分尚待名冊確認、DD多項資料缺漏與取處準則程序尚未完成。"), "structure_review": pad("為股權投資型態，寶碩持股20%、董事1席並享重大事項否決權；取處準則程序見規則引擎清單。"),
              "related_party": {"status": o.get("rp_status", rp["status"]), "evidence": rp["evidence"], "note": "僅限現有資料範圍，仍須與寶碩內部關係人名冊比對。", "next_step": "取得寶碩關係人名冊並比對交易對象與其實質控制人"},
              "background_integrity_dd": pad("訴訟、強制執行、票據、裁罰與輿情查詢結果未提供，一律列為待查核，不假設無不良紀錄。"),
              "core_contract_asset_ip_qualification": pad("協議草案載有董事會與否決權及違約賠償上限；權屬、智財與許可資料缺漏。"), "dd_checklist": dd}
        base["conditions_proposed"] = ["完成取處準則所列程序後始得簽約付款"]
    else:
        sp = {"cross_contradictions": o.get("contradictions", []), "optimistic_assumptions": [{"description": "簡報宣稱之成長率與IRR尚無正式文件佐證", "agent": "finance"}],
              "number_mismatches": o.get("mismatches", []), "missing_critical": [], "authority_check": {"result": "通過", "notes": "金額未超過單案上限，詳見規則引擎。"},
              "stress_tests": [{"assumption": "營收年增率30%", "test": pad("將成長率減半並延後回收一年重算三情境回報", 40), "result": pad("保守情境回報將明顯下降，需以保守情境作為授權依據", 40)}],
              "evidence_chain": {"facts": ["財報表格數字"], "inferences": ["簡報成長假設"], "gaps": ["DD查核資料"]},
              "historical_commentary": ("參考前案：" + "; ".join(h["case_id"] for h in ctx.get("historical_cases", []))) if ctx.get("historical_cases") else "無歷史紀錄可比對",
              "reconciliation_score": 82, "highlight": "財報顯示營收、淨利與營業現金流連續成長", "gaps": o.get("gaps", [])}
        base["ai_recommendation"] = ai
    base["specific"] = sp
    base.update({k: v for k, v in o.items() if k in ("top_risks", "claims", "core_judgement", "conditions_proposed", "questions_for_human", "missing_info")})
    return base


def behavior_default(agent, ctx, model, n, **kw):
    return build(agent, ctx, "支持" if agent == "investment" else "有條件", **{**kw})
