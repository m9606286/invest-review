"""由切片抽取 facts_provided（事實登記表）。規則式、保守：抓不到就標「缺漏」，不推算、不腦補。
來源等級為簡報/口頭或句子含預測用語者，標籤一律降為「推論」（不得當成已落實事實）。
跨切片同一欄位出現不同數字，保留最高等級者並把其他值放進 alt_values（規則引擎 R2 會據此紅燈）。"""
import re
from . import related_party as RP

HYP = ("據稱", "口頭", "預計", "尚未確認", "初估", "草案", "擬", "待確認")

HYP_RE = re.compile("|".join(map(re.escape, HYP)))

GRADE_RANK = {
    "正式文件": 0,
    "一般文件": 1,
    "B級（結構化/文字檔）": 1,
    "C級（OCR/一般文件）": 1,
    "簡報/宣稱": 2,
    "口頭/未證實": 3,
}
UNIT_MULT = {"億": 1e8, "百萬": 1e6, "萬": 1e4, "千": 1e3, "仟": 1e3, "": 1}
NUM = r"-?\d[\d,]*\.?\d*"

# (key, 型態, 列標籤/關鍵字 regex)
TABLE_HISTORY = [
    ("financial.revenue_history", r"^(?:營業收入|營收|銷貨收入|營業收入合計|營業收入淨額)"),
    ("financial.net_income_history", r"^(?:稅後淨利|本期淨利|淨利|稅後純益|本期稅後淨利)"),
    ("financial.operating_cash_flow_history", r"^(?:營業活動之?淨?現金流入?(?:\(出\))?|營業活動現金流量|營運現金流)"),
]
SCALARS = [
    ("financial.interest_bearing_debt", r"(?:有息負債|有息借款|借款合計|銀行借款合計|借款總額)"),
    ("financial.total_debt", r"(?:負債總額|負債總計|總負債)"),
    ("financial.total_assets", r"(?:資產總額|資產總計|總資產)"),
    ("financial.investment_amount", r"(?:擬投資金額|投資金額|出資金額|擬出資(?:金額)?|增資金額|交易金額)"),
]
RETURNS = [("financial.return_optimistic", "樂觀"), ("financial.return_base", "基準"), ("financial.return_conservative", "保守")]
TEXT_FACTS = [
    ("financial.installment_structure", r"分期|分[一二兩三四五六七八九十\d]+期|首期款|簽約時.{0,12}(?:支付|付)|交割時.{0,12}(?:支付|付)"),
    ("financial.funding_source", r"資金來源|自有資金|自籌|增資支應|以自有"),
    ("financial.valuation_basis", r"估值|評價|本益比|P/E|EV/EBITDA|淨值比|DCF|現金流量折現|認購價格|每股.{0,6}元"),
    ("legal.shareholding_structure", r"股權結構|持股比|持有.{0,12}%|股東名冊|持股"),
    ("legal.control_voting_arrangement", r"表決權|董事席次|董事會.{0,6}席|控制權|否決權|優先股|一致決"),
    ("market.competitive_landscape", r"競爭|競品|市占|市佔|同業"),
    ("investment.exit_path", r"退出|IPO|上市櫃|股份買回|回購|出場"),
]
CLAUSE_KEYS = {"investment.exit_path", "market.competitive_landscape"}
ALL_KEYS = (
    [k for k, _ in TABLE_HISTORY]
    + [k for k, _ in SCALARS]
    + [k for k, _ in RETURNS]
    + [k for k, _ in TEXT_FACTS]
    + [
        "legal.main_contract_draft",
        "legal.related_party_disclosure",
        "market.peer_benchmark_return",
        "portfolio.concentration_pct",
        "tw.asset_type",
        "tw.direction",
        "tw.counterparty",
        "tw.procedures",
    ]
)


def _unit_mult(text):
    m = re.search(r"單位[:：]\s*(?:新?[臺台]幣|NT\$?)?\s*(百萬|仟|千|萬|億)?\s*元", text)
    return UNIT_MULT.get(m.group(1) or "", 1) if m else 1


def _amount(s, default_mult=1):
    """'8,000萬元' → 8e7；無單位則套用表格單位。"""
    m = re.search(rf"({NUM})\s*(億|百萬|萬|千|仟)?\s*(?:元|圓)?", s)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return v * (UNIT_MULT[m.group(2)] if m.group(2) else default_mult)


def _sents(text):
    return [s.strip() for s in re.split(r"(?<=[。！？!?])|\n", text) if s and s.strip()]


def _clauses(sent):
    return [c.strip() for c in re.split(r"[，,；;]", sent) if c.strip()]


def _table_rows(text):
    rows = []
    for ln in text.split("\n"):
        if ln.strip().startswith("|") and not re.match(r"^\s*\|[\s\-:|]+\|\s*$", ln):
            rows.append([c.strip() for c in ln.strip().strip("|").split("|")])
    return rows


def extract(chunks, basic=None, roster_result=None, user_facts=None):
    """回傳 {facts, log, related}。user_facts：使用者在介面直接填的欄位 {key: value}，標「明載(使用者輸入)」。"""
    basic = basic or {}
    cands = {k: [] for k in ALL_KEYS}
    for c in chunks:
        grade = c.get("evidence_grade", "一般文件")
        rank = GRADE_RANK.get(grade, 1)
        is_table = bool(c.get("is_table", False))
        heading = c.get("heading") or ""
        source_file = c.get("source_file", "")

        if is_table:
            mult = _unit_mult(c["text"])
            rows = _table_rows(c["text"])
            for r in rows:
                if len(r) < 2:
                    continue
                for key, pat in TABLE_HISTORY:
                    if re.match(pat, r[0]):
                        nums = [_amount(x, mult) for x in r[1:] if re.search(r"\d", x)]
                        if nums and all(n is not None for n in nums):
                            cands[key].append({"value": nums, "chunk": c, "hyp": False, "rank": rank})
                for key, pat in SCALARS:
                    if re.search(pat, r[0]):
                        nums = [_amount(x, mult) for x in r[1:] if re.search(r"\d", x)]
                        if nums and nums[-1] is not None:
                            cands[key].append({"value": nums[-1], "chunk": c, "hyp": False, "rank": rank, "period": "最近期欄"})

        for s in _sents(c["text"]):
            if is_table:
                continue
            hyp = bool(HYP_RE.search(s))
            for key, pat in SCALARS:
                m = re.search(pat + rf"[^\d\-]{{0,14}}({NUM}\s*(?:億|百萬|萬|千|仟)\s*(?:元|圓)?|{NUM}\s*(?:元|圓))(?!\s*%)", s)
                if m:
                    v = _amount(m.group(1))
                    if v is not None:
                        cands[key].append({"value": v, "chunk": c, "hyp": hyp, "rank": rank})
            for key, tag in RETURNS:
                m = re.search(rf"{tag}(?:情境)?[^。；\n]{{0,15}}?(?:回報|報酬|IRR)[^\d%]{{0,8}}({NUM})\s*%", s)
                if m:
                    cands[key].append({"value": float(m.group(1)), "chunk": c, "hyp": False, "rank": rank})
            m = re.search(rf"同業[^。；\n]{{0,15}}?(?:回報|報酬|IRR)[^\d%]{{0,8}}({NUM})\s*%", s)
            if m:
                cands["market.peer_benchmark_return"].append({"value": float(m.group(1)), "chunk": c, "hyp": False, "rank": rank})
            for key, pat in TEXT_FACTS:
                if re.search(pat, s):
                    if key in CLAUSE_KEYS:
                        val = "，".join(x for x in _clauses(s) if re.search(pat, x))[:200]
                        h = bool(HYP_RE.search(val))
                    else:
                        val, h = s[:240], hyp
                    cands[key].append({"value": val, "chunk": c, "hyp": h, "rank": rank})

        if re.search(r"合約|契約|協議書|SPA|投資協議", source_file + heading) and grade in (
            "正式文件",
            "一般文件",
            "B級（結構化/文字檔）",
            "C級（OCR/一般文件）",
        ):
            cands["legal.main_contract_draft"].append({"value": f"契約文件：{source_file}", "chunk": c, "hyp": False, "rank": rank})

    facts, log, n = {}, [], 0

    def fid():
        nonlocal n
        n += 1
        return f"F{n:03d}"

    for key in ALL_KEYS:
        if key in (
            "legal.related_party_disclosure",
            "tw.counterparty",
            "tw.asset_type",
            "tw.direction",
            "tw.procedures",
            "portfolio.concentration_pct",
        ):
            continue
        cs = sorted(cands[key], key=lambda x: (x["rank"], x["hyp"]))
        if not cs:
            facts[key] = {"fact_id": fid(), "value": None, "label": "缺漏", "source": None}
            log.append({"key": key, "status": "缺漏"})
            continue
        best = cs[0]
        c = best["chunk"]
        c_grade = c.get("evidence_grade", "一般文件")
        c_id = c.get("chunk_id", "")
        c_src = c.get("source_file", "")
        c_loc = c.get("location", "")
        is_ret = key.startswith("financial.return_")
        unverified = best["rank"] >= 2 or (best["hyp"] and not is_ret)
        f = {
            "fact_id": fid(),
            "value": best["value"],
            "unit": "%"
            if (is_ret or key == "market.peer_benchmark_return")
            else ("元" if isinstance(best["value"], (int, float)) or key.endswith("_history") else None),
            "source": f"{c_id}｜{c_src} {c_loc}".strip(),
            "source_chunk": c_id,
            "evidence_grade": c_grade,
            "label": "推論" if unverified else "明載",
        }
        if unverified:
            f["inferred_by"] = "切片器（來源為簡報/口頭宣稱或預測用語，未經證實）"
        alts = []
        for o in cs[1:]:
            if isinstance(best["value"], (int, float)) and isinstance(o["value"], (int, float)) and o["value"] != best["value"]:
                oc = o["chunk"]
                alts.append(
                    {
                        "value": o["value"],
                        "source": f"{oc.get('chunk_id', '')}｜{oc.get('source_file', '')}",
                        "grade": oc.get("evidence_grade", "一般文件"),
                    }
                )
        if alts:
            f["alt_values"] = alts
        facts[key] = f
        log.append({"key": key, "status": f["label"], "chunk": c_id, "conflicts": len(alts)})

    rp = RP.assess(chunks)
    disc, cp = RP.to_facts(rp, roster_result)
    ev_src = ",".join(sorted({e["chunk_id"] for e in rp["evidence"] if "chunk_id" in e})) or "（無對應切片）"
    facts["legal.related_party_disclosure"] = {
        "fact_id": fid(),
        "value": disc,
        "label": "推論" if rp["status"] != "資料載明非關係人" else "明載",
        "source": f"關係人初判｜{ev_src}",
        "inferred_by": "切片器（關係人初判）",
    }
    facts["tw.counterparty"] = {
        "fact_id": fid(),
        "value": cp,
        "label": "推論",
        "source": f"關係人初判｜{ev_src}",
        "inferred_by": "切片器（關係人初判）",
    }
    ub = "使用者輸入（基本資料）"
    for key, bk in (("tw.asset_type", "asset_type"), ("tw.direction", "direction"), ("portfolio.concentration_pct", "concentration_pct")):
        v = basic.get(bk)
        facts[key] = {"fact_id": fid(), "value": v, "label": "明載", "source": ub} if v not in (None, "") else {"fact_id": fid(), "value": None, "label": "缺漏", "source": None}
    facts["tw.procedures"] = {"fact_id": fid(), "value": basic.get("procedures") or {}, "label": "明載", "source": "使用者輸入（取處準則程序狀態）"}
    for key, v in (user_facts or {}).items():
        old = facts.get(key, {}).get("fact_id") or fid()
        facts[key] = {"fact_id": old, "value": v, "label": "明載", "source": "使用者補件輸入"}
    return {"facts": facts, "log": log, "related": rp}


def build_case_package(case_id, version, basic, chunks, extraction, submitted_by="ui", authority_ref="PLACEHOLDER-0", prev_version_ref=None):
    docs, seen = [], set()
    for c in chunks:
        src = c.get("source_file", "")
        doc_id = c.get("doc_id") or src
        if doc_id not in seen:
            seen.add(doc_id)
            docs.append({"doc_id": doc_id, "doc_type": c.get("evidence_grade", "一般文件"), "filename": src})
    amt = (extraction["facts"].get("financial.investment_amount") or {}).get("value")
    case = {
        "case_id": case_id,
        "version": version,
        "submitted_by": submitted_by,
        "submitted_at": basic.get("submitted_at", ""),
        "authority_ref": authority_ref,
        "basic": {
            "name": basic.get("name", case_id),
            "deal_type": basic.get("deal_type", "未填"),
            "amount": float(basic.get("amount") or amt or 0),
            "currency": basic.get("currency", "TWD"),
        },
        "documents": docs,
        "facts_provided": extraction["facts"],
    }
    if version > 1:
        case["prev_version_ref"] = prev_version_ref or f"{case_id}/v{version-1}"
    return case
