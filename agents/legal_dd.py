"""法務盡職調查清單（Legal DD Checklist）：通用底盤＋依案型動態調整。五大構面、逐項狀態與切片出處。
確定性部分：案型辨識、適用性判斷、狀態/證據守門（不得跳過、已確認須有可靠出處、有疑慮/待查須同步進風險與缺漏）。"""
import re

STATUSES = ["已確認", "有疑慮／高風險", "待查核／資料缺漏", "不適用"]
DIMENSIONS = {
    "a": "交易主體、股權與控制權",
    "b": "背景、誠信與不良紀錄查核",
    "c": "核心資產、智財與營運資格",
    "d": "合約條款、交易條件與風險分攤",
    "e": "法規遵循與內控審議程序",
}
# applies: 適用的案型集合（equity 股權投資/增資、asset 資產收購、jv 合資合作、reg 特許或重監管）；"all"＝通用
ITEMS = [
    ("a1", "a", "公司登記與存續狀態（設立、營業中、有無解散/撤銷登記）", "all"),
    ("a2", "a", "交易型態與交易架構（直接/間接、SPV、分期、對價形式）", "all"),
    ("a3", "a", "股權結構與實質控制人穿透（至自然人）", {"equity", "jv"}),
    ("a4", "a", "關係人／實質關係人四態初判與利益衝突檢視", "all"),
    ("b1", "b", "民事、刑事訴訟與行政爭訟紀錄", "all"),
    ("b2", "b", "強制執行、假扣押、支付命令紀錄", "all"),
    ("b3", "b", "破產、重整、清算與票據信用（退票/拒往）", "all"),
    ("b4", "b", "主管機關裁罰、檢查缺失與改善情形", "all"),
    ("b5", "b", "履約信用與輿情（供應商/客戶/媒體負面）", "all"),
    ("b6", "b", "智財侵權或素材挪用疑慮", {"equity", "jv", "reg"}),
    ("b7", "b", "核心人物過往任職背景與離職爭議", {"equity", "jv"}),
    ("c1", "c", "標的權屬與負擔（抵押/質權/查封）及優先承買權", "all"),
    ("c2", "c", "專利/商標/著作權或核心技術權屬，及與業務契合度", {"equity", "jv", "reg"}),
    ("c3", "c", "營業登記、特許執照、專案許可是否齊備有效", "all"),
    ("c4", "c", "法定專戶/信託/資金專用等資格", {"reg"}),
    ("d1", "d", "核心合約條款完整性與不利條款", "all"),
    ("d2", "d", "對價與付款條件（分期、價格調整、託管）", "all"),
    ("d3", "d", "交割先決條件（CP）", "all"),
    ("d4", "d", "聲明與保證（R&W）及揭露附表", "all"),
    ("d5", "d", "違約責任與賠償上限（含補償/解除權）", "all"),
    ("d6", "d", "競業禁止與保密義務", {"equity", "jv", "asset"}),
    ("d7", "d", "僵局處理與決策機制", {"jv"}),
    ("d8", "d", "股份買回/退出機制與資金流動性（卡死風險）", {"equity", "jv"}),
    ("e1", "e", "審計委員會/董事會/股東會審議與利害關係人迴避", "all"),
    ("e2", "e", "取處準則程序與申報/公告門檻（對應規則引擎清單）", "all"),
    ("e3", "e", "其他法規申報（公平法結合、外資/投審、證交法大量持股等）", {"reg", "equity", "jv"}),
]
NA_REASON = {
    "a3": "本案為資產收購，不涉及標的公司股權穿透", "b6": "本案型態/標的與智財素材無關", "b7": "資產交易不涉及核心人物任職背景",
    "c2": "本案標的為不動產/設備等實體資產，不涉及專利商標著作權", "c4": "非特許/重監管產業，無法定專戶或信託資格要求",
    "d6": "本案型態無競業/保密核心安排", "d7": "非合資/共同控制型態，無僵局處理需求", "d8": "非股權/合資型態，無股份買回或退出機制",
    "e3": "非重監管、非股權/合資型態，無其他特別申報",
}
TYPE_KW = {"equity": r"增資|入股|股權|股份|認購|受讓|私募|特別股", "asset": r"資產|不動產|土地|廠房|設備|房地|購入|收購資產",
           "jv": r"合資|合作|聯盟|共同投資|JV|合營"}
REG_KW = r"金融|銀行|保險|證券|醫療|醫藥|藥品|電信|博弈|能源|電力|特許|許可|執照|信託|教育|食品安全|無人機|網路平台"


def identify_deal_profile(basic, facts, chunks):
    text = (basic.get("deal_type") or "") + " " + (basic.get("name") or "")
    types = {t for t, kw in TYPE_KW.items() if re.search(kw, text)}
    at = (facts.get("tw.asset_type") or {}).get("value")
    if at in ("不動產", "設備", "使用權資產"): types.add("asset")
    if at in ("有價證券", "併購"): types.add("equity")
    reg_ev = [c["chunk_id"] for c in chunks if re.search(REG_KW, c["text"])][:5]
    if not types: types = {"equity"}   # 保守預設：用最完整的股權投資清單
    return {"types": sorted(types), "regulated": bool(reg_ev), "regulated_evidence": reg_ev,
            "note": "依案名/交易型態與標的資料辨識；與本案型態無關的細項標示『不適用』並說明原因"}


def template(profile):
    """回傳本案適用性：[{item_id, dimension, name, applicable, na_reason}]"""
    active = set(profile["types"]) | ({"reg"} if profile["regulated"] else set())
    out = []
    for iid, dim, name, ap in ITEMS:
        ok = True if ap == "all" else bool(set(ap) & active)
        out.append({"item_id": iid, "dimension": dim, "dimension_name": DIMENSIONS[dim], "name": name, "applicable": ok,
                    "na_reason": None if ok else NA_REASON.get(iid, "與本案型態/標的無關")})
    return out


def normalize(output, tmpl, chunks):
    """守門：補齊遺漏項、強制不適用項、已確認須有可靠出處、有疑慮/待查必須同步進風險與缺漏。回傳 (output, notes)。"""
    notes, grade = [], {c["chunk_id"]: c["evidence_grade"] for c in chunks}
    spec = output.setdefault("specific", {})
    got = {d.get("item_id"): d for d in (spec.get("dd_checklist") or []) if isinstance(d, dict)}
    final = []
    for t in tmpl:
        d = dict(got.get(t["item_id"]) or {})
        d.update(item_id=t["item_id"], dimension=t["dimension"], name=t["name"])
        d.setdefault("chunk_refs", []); d.setdefault("finding", ""); d.setdefault("next_step", "")
        if not t["applicable"]:
            d.update(status="不適用", finding=d.get("finding") or t["na_reason"], na_reason=t["na_reason"])
        elif d.get("status") not in STATUSES or d.get("status") == "不適用":
            if t["item_id"] not in got: notes.append(f"{t['item_id']} 法務未回答 → 自動列為待查核")
            else: notes.append(f"{t['item_id']} 狀態不合法/誤標不適用 → 改列待查核")
            d.update(status="待查核／資料缺漏", finding=d.get("finding") or "法務 Agent 未提供此項檢核結果", next_step=d.get("next_step") or "補充資料後查核")
        if d["status"] == "已確認":
            refs = [r for r in d["chunk_refs"] if r in grade]
            reliable = [r for r in refs if grade[r] in ("正式文件", "一般文件")]
            if not reliable:
                notes.append(f"{t['item_id']} 標『已確認』但無正式/一般文件切片佐證 → 降為待查核（簡報/口頭宣稱不得當已確認）")
                d.update(status="待查核／資料缺漏", next_step=d.get("next_step") or "取得正式文件佐證")
        final.append(d)
    spec["dd_checklist"] = final
    # 風險／缺漏同步
    risks, missing = output.setdefault("top_risks", []), output.setdefault("missing_info", [])
    txt_r = " ".join(r.get("description", "") + r.get("concern_id", "") for r in risks)
    txt_m = " ".join(m.get("item", "") for m in missing)
    for d in final:
        tag = f"[DD-{d['item_id']}]"
        if d["status"] == "有疑慮／高風險" and tag not in txt_r:
            risks.append({"concern_id": f"legal-DD-{d['item_id']}", "description": f"{tag} {d['name']}：{d['finding'] or '法務清單標示有疑慮/高風險'}",
                          "severity": "高", "category": "合規" if d["dimension"] == "e" else "治理", "evidence_refs": d["chunk_refs"] or []})
        if d["status"] == "待查核／資料缺漏" and tag not in txt_m:
            missing.append({"item": f"{tag} {d['name']}", "why_critical": d["finding"] or "資料缺漏，無法確認", "affects": "法務盡職調查結論",
                            "ask_who": d["next_step"] or "交易對方/法務"})
    output["specific"]["dd_summary"] = {s: sum(1 for d in final if d["status"] == s) for s in STATUSES}
    return output, notes
