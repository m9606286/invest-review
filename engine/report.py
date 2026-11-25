"""投委會正式報告：一頁式決策摘要（30秒）＋ 四 Agent 深度報告 ＋ 規則引擎說明 ＋ 切片清單。"""
import json
from .rule_info import INFO
from agents.legal_dd import DIMENSIONS

EMOJI = {"綠": "🟢", "黃": "🟡", "紅": "🔴"}
ACTION = {"綠": "推進（仍須人工核准）", "黃": "有條件推進", "紅": "暫緩／退回（需補件或人工覆核）"}
NAMES = {"investment": "投資", "finance": "財務", "legal": "法務", "audit": "稽核"}
SEV = {"高": 0, "中": 1, "低": 2}


def _valid(out, k):
    o = out["agents"].get(k)
    return o if o and o["status"] != "失敗" else None


def _top_risk(out):
    ev = out["evaluation"]
    reds = [h for h in ev["triggered"] if h["light"] == "紅"]
    if reds:
        return f"【規則引擎 {reds[0]['rule']}】{reds[0]['detail']}"
    rs = [(SEV[r["severity"]], NAMES[k], r) for k in out["agents"] if _valid(out, k) for r in out["agents"][k]["top_risks"]]
    if rs:
        _, who, r = sorted(rs, key=lambda x: x[0])[0]
        return f"【{who}】{r['description']}（{r['severity']}）"
    return "未發現重大風險"


def _questions(out, case):
    ev, qs = out["evaluation"], []
    if ev["missing_fields"]:
        qs.append("請補齊關鍵欄位：" + "、".join(ev["missing_fields"]))
    rp = case["facts_provided"].get("legal.related_party_disclosure", {}).get("value") or {}
    if rp.get("roster_result") is None:
        qs.append(f"待與寶碩內部關係人名冊比對確認交易對象是否為關係人/實質關係人（資料初判：{rp.get('status', '—')}）")
    for o in ev["tw_obligations"]:
        if o["status"] == "未規劃":
            qs.append(f"取處準則{o['article']}：{o['requirement']}——目前未規劃，請確認或補辦")
    for h in ev["triggered"]:
        if h["rule"] in ("R4", "R5", "R2", "R8", "R3"):
            qs.append(f"{h['rule']}：{h['detail']}")
    for k in ("audit", "legal", "finance", "investment"):
        if _valid(out, k): qs += _valid(out, k)["questions_for_human"]
    for h in ev["triggered"]:
        if h["rule"] in ("Y6", "Y8", "Y7", "Y9", "Y2", "Y4"):
            qs.append(f"{h['rule']}：{h['detail']}")
    seen, uniq = set(), []
    for q in qs:
        if q not in seen: seen.add(q); uniq.append(q)
    return uniq[:3]


def _risks_md(o):
    return [f"- **[{r['severity']}／{r['category']}]** {r['description']}（{r['concern_id']}；出處：{', '.join(r['evidence_refs']) or '無'}）" for r in o["top_risks"]] or ["- （無）"]


def _claims_md(o):
    return [f"- 〔{c['label']}〕{c['claim']}（{', '.join(c['evidence_refs']) or c.get('inferred_by') or '—'}）" for c in o["claims"]] or ["- （無）"]


def _missing_md(o):
    return [f"- {m['item']}：{m['why_critical']}（影響：{m['affects']}；向誰索取：{m['ask_who']}）" for m in o["missing_info"]] or ["- （無）"]


def _common(o, md):
    cj = o["core_judgement"]
    md += [f"- 狀態：{o['status']}｜立場：**{cj['stance']}**｜信心：{cj['confidence']}", f"- 核心判斷：{cj['summary']}", ""]


def _tail(o, md):
    md += ["", "**最大風險／疑點**", *_risks_md(o), "", "**結論與依據（事實／推論／缺漏）**", *_claims_md(o), "", "**缺漏資訊**", *_missing_md(o)]
    if o["conditions_proposed"]: md += ["", "**建議條件／下一步**", *[f"- {c}" for c in o["conditions_proposed"]]]


def _sec(md, title, text):
    if text: md += ["", f"**{title}**", str(text)]


def render_report(case, out, chunks, return_sections=False):
    ev, ag = out["evaluation"], out["agents"]
    L = ev["final_light"]; audit = _valid(out, "audit"); inv = _valid(out, "investment")
    rp = case["facts_provided"].get("legal.related_party_disclosure", {}).get("value") or {}
    highlight = ((audit and (audit.get("specific") or {}).get("highlight")) or (inv and inv["core_judgement"]["summary"]) or "（無）")
    one = audit["core_judgement"]["summary"] if audit else "稽核 Agent 未完成，無法彙整結論"
    if ev["ai_override_blocked"]: one += "（注意：稽核建議較寬鬆，但規則引擎強制維持較嚴燈號）"
    md = [f"# 投委會評估報告｜{case['basic']['name']}（{case['case_id']} v{case['version']}）", "",
          "## 一頁式決策摘要（30 秒版）", "",
          f"**最終燈號**：{EMOJI[L]} {L}燈 → {ACTION[L]}（規則引擎：{ev['rule_light']}；稽核建議：{ev['ai_light'] or '無'}）", "",
          f"**觸發規則**：{'、'.join(ev['triggered_rules']) or '無'}", "",
          f"**一句話結論**：{one}", "",
          f"**關係人初判**：{rp.get('status', '資料未載明')}（僅限現有資料；仍須與內部關係人名冊比對）", "",
          f"**最大亮點**：{highlight}", "", f"**最大風險**：{_top_risk(out)}", "", "**最急迫確認的 3 個問題**："]
    md += [f"{i}. {q}" for i, q in enumerate(_questions(out, case), 1)] or ["1. （無）"]
    conds = [h["detail"] for h in ev["triggered"] if h["rule"] in ("Y3", "Y7", "Y8", "Y9", "Y6")]
    if L == "黃" and conds: md += ["", "**有條件推進之條件**：", *[f"- {c}" for c in conds]]
    md += ["", "---"]

    sections = {}

    def failed(k, title):
        md.extend(["", f"## {title}", f"> ⚠ {NAMES[k]} Agent 執行失敗：{ag[k]['core_judgement']['summary']}"])

    # ---- 投資 ----
    _m = len(md)
    o = ag["investment"]
    if o["status"] == "失敗": failed("investment", "一、投資 Agent 深度報告")
    else:
        sp = o["specific"]; md += ["", "## 一、投資 Agent 深度報告"]; _common(o, md)
        _sec(md, "投資核心定調與立場", sp.get("stance_rationale")); _sec(md, "商業模式與獲利邏輯", sp.get("business_model_analysis"))
        _sec(md, "市場空間與競爭壁壘", sp.get("market_and_moat"))
        md += ["", "**核心亮點 vs. 致命弱點**", "| 類型 | 要點 | 成立機制 | 出處 |", "|---|---|---|---|"]
        md += [f"| {x['kind']} | {x['point']} | {x['mechanism']} | {', '.join(x['chunk_refs'])} |" for x in sp.get("strengths_vs_weaknesses", [])]
        _sec(md, "交易條件與談判建議", sp.get("deal_terms_and_negotiation")); _sec(md, "退場／流動性機制檢視", sp.get("exit_and_liquidity_review"))
        md += ["", "**核心假設**", *[f"- [{x['verifiability']}] {x['assumption']}（{', '.join(x['chunk_refs'])}）" for x in sp.get("core_assumptions", [])]]
        _tail(o, md)
    sections["investment"] = md[_m:]
    # ---- 財務 ----
    _m = len(md)
    o = ag["finance"]
    if o["status"] == "失敗": failed("finance", "二、財務 Agent 深度報告")
    else:
        sp = o["specific"]; md += ["", "## 二、財務 Agent 深度報告"]; _common(o, md)
        _sec(md, "財務體質總評", sp.get("health_overview"))
        md += ["", "**關鍵指標解讀**", "| 指標 | 數值 | 解讀 | 出處 |", "|---|---|---|---|"]
        md += [f"| {x['metric']} | {x['value_text']} | {x['reading']} | {', '.join(x['refs'])} |" for x in sp.get("key_metrics", [])]
        _sec(md, "資本結構與資產真實性檢核", sp.get("capital_structure_and_asset_authenticity")); _sec(md, "交易對價與資金調度影響", sp.get("consideration_and_funding_impact"))
        md += ["", "**樂觀／基準／保守三情境**", "| 情境 | 假設 | 回報 | 依據 | 出處 |", "|---|---|---|---|---|"]
        for k, n in (("optimistic", "樂觀"), ("base", "基準"), ("conservative", "保守")):
            x = sp.get("scenarios", {}).get(k)
            if x: md.append(f"| {n} | {x['assumptions']} | {x['return_text']} | {x['basis']} | {', '.join(x['refs'])} |")
        md += ["", "**財務矛盾與缺漏**", *([f"- {x}" for x in sp.get("contradictions_and_gaps", [])] or ["- （無）"])]
        _tail(o, md)
    sections["finance"] = md[_m:]
    # ---- 法務 ----
    _m = len(md)
    o = ag["legal"]
    if o["status"] == "失敗": failed("legal", "三、法務 Agent 深度報告")
    else:
        sp = o["specific"]; md += ["", "## 三、法務 Agent 深度報告"]; _common(o, md)
        _sec(md, "法務風險總評", sp.get("risk_overview")); _sec(md, "交易架構檢視", sp.get("structure_review"))
        r = sp.get("related_party", {})
        md += ["", f"**關係人／實質關係人初判**：{r.get('status')}", f"- 說明：{r.get('note')}", f"- 下一步：{r.get('next_step')}",
               *[f"- 出處 {e.get('chunk_id')}：{e.get('snippet')}" for e in r.get("evidence", [])]]
        _sec(md, "背景／誠信與不良紀錄 DD", sp.get("background_integrity_dd")); _sec(md, "核心合約／資產權屬／智財與營運資格", sp.get("core_contract_asset_ip_qualification"))
        pf = out["deal_profile"]
        md += ["", f"**法務 DD 審查清單檢核表**（案型：{'、'.join(pf['types'])}{'＋特許/重監管' if pf['regulated'] else ''}；統計：{sp.get('dd_summary')}）"]
        for dk, dn in DIMENSIONS.items():
            items = [d for d in sp.get("dd_checklist", []) if d["dimension"] == dk]
            md += ["", f"*({dk}) {dn}*", "| 項目 | 狀態 | 發現 | 出處 | 下一步 |", "|---|---|---|---|---|"]
            md += [f"| {d['item_id']} {d['name']} | {d['status']} | {d.get('finding', '')} | {', '.join(d.get('chunk_refs', []))} | {d.get('next_step', '')} |" for d in items]
        _tail(o, md)
    sections["legal"] = md[_m:]
    # ---- 稽核 ----
    _m = len(md)
    o = ag["audit"]
    if o["status"] == "失敗": failed("audit", "四、稽核 Agent 深度報告")
    else:
        sp = o["specific"]; md += ["", "## 四、稽核 Agent 深度報告"]; _common(o, md)
        for key, label in (("cross_contradictions", "跨角色矛盾點交叉對帳"), ("number_mismatches", "數字前後不一"), ("optimistic_assumptions", "假設過度樂觀")):
            md += ["", f"**{label}**", *([f"- {json.dumps(i, ensure_ascii=False) if not isinstance(i, str) else i}" for i in sp.get(key, [])] or ["- （未發現）"])]
        md += ["", "**關鍵樂觀假設壓力測試**", *[f"- 假設：{x['assumption']}；測試：{x['test']}；結果：{x['result']}" for x in sp.get("stress_tests", [])]]
        ec = sp.get("evidence_chain", {})
        md += ["", "**事實／推論／缺漏證據鏈**"] + [f"- {t}：{json.dumps(ec.get(k, []), ensure_ascii=False)}" for k, t in (("facts", "事實"), ("inferences", "推論"), ("gaps", "缺漏"))]
        md += ["", f"**歷史相似模式／前案警訊**：{sp.get('historical_commentary')}", f"- 三方結論一致性評分：{sp.get('reconciliation_score')}"]
        _tail(o, md)
    sections["audit"] = md[_m:]
    # ---- 規則引擎 ----
    md += ["", "## 五、確定性規則引擎：觸發原因與解除條件", ""]
    for h in ev["triggered"]:
        why, rel = INFO.get(h["rule"], ("", ""))
        md += [f"- {EMOJI[h['light']]} **{h['rule']}**：{h['detail']}", f"  - 規則說明：{why}", f"  - 解除條件：{rel}"]
    if not ev["triggered"]: md += ["- 無觸發"]
    md += ["", "## 六、取處準則：簽約／付款前須完成事項", "", "| 狀態 | 條文 | 要求 |", "|---|---|---|"]
    md += [f"| {x['status']} | {x['article']} | {x['requirement']} |" for x in ev["tw_obligations"]] or ["| — | — | 本案未觸發前置程序 |"]
    md += ["", "**事實發生日後義務**", *[f"- {x['article']}：{x['requirement']}" for x in ev["post_decision_obligations"]]]
    md += ["", "## 七、補件清單"]
    miss = [f"- 關鍵欄位：{m}" for m in ev["missing_fields"]] + [f"- 待補（人工）：{g}" for g in out["review_state"]["open_gaps"]] + [f"- 關鍵缺口：{g}" for g in out["review_state"]["unresolved_critical_gaps"]]
    md += miss or ["- （無）"]
    md += ["", "## 八、補問輪紀錄", *([f"- 第{r['round']}輪：重跑 {', '.join(NAMES[a] for a in r['reran'])}；已解除 {r['resolved'] or '無'}；仍在 {r['still_open'] or '無'}；新增 {r['new'] or '無'}" for r in out["rounds_log"]] or ["- 未啟動補問輪"])]
    notes = ev["notes"] + out.get("pipeline_notes", [])
    if notes: md += ["", "## 系統備註", *[f"- {n}" for n in notes]]
    md += ["", "## 九、資料切片清單（來源與可信度）", "", "| 編號 | 檔名 | 位置 | 證據等級 | 性質 | 低可信 | 警示 |", "|---|---|---|---|---|---|---|"]
    md += [f"| {c['chunk_id']} | {c['source_file']} | {c['location']} | {c['evidence_grade']} | {c['nature']} | {'⚠' if c['low_confidence'] else ''} | {'；'.join(c['warnings'])} |" for c in chunks]
    md += ["", "---", "*本報告僅為決策輔助，最終決策須經人工核准；取處準則判定為前置條件檢查，不構成法律意見。關係人初判僅限現有資料，須與內部關係人名冊比對。*"]
    full = "\n".join(md)
    return (full, sections) if return_sections else full
