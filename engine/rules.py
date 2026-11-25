"""確定性規則引擎 (Step 1)。不呼叫任何 LLM。

evaluate() 回傳 rule_light（規則引擎燈號）與 final_light（與稽核 Agent 建議取較嚴者）。
設計重點：final_light >= rule_light，AI 只能把燈號調嚴，不能放寬。
"""
import json
from collections import defaultdict
from pathlib import Path

import yaml
from .tw_compliance import check_tw
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
LIGHT_ORDER = {"綠": 0, "黃": 1, "紅": 2}
AI_REC_TO_LIGHT = {"推進": "綠", "有條件推進": "黃", "暫緩": "紅"}
STANCE_ORDER = {"支持": 0, "有條件": 1, "保留": 2, "反對": 3}
AGENT_KEYS = ["investment", "finance", "legal", "audit"]
AGENT_NAMES = {"investment": "投資", "finance": "財務", "legal": "法務", "audit": "稽核"}


def load_yaml(name):
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))


def load_schema(name):
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def max_light(*lights):
    lights = [l for l in lights if l]
    return max(lights, key=lambda l: LIGHT_ORDER[l]) if lights else "綠"


def _isnum(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _present(fact):
    return (fact is not None and fact.get("label") != "缺漏"
            and fact.get("value") not in (None, "", [], {}))


def _val(facts, key):
    f = facts.get(key)
    return f["value"] if _present(f) and _isnum(f["value"]) else None


def validate_case(case):
    errs = sorted(Draft202012Validator(load_schema("case_package.schema.json")).iter_errors(case),
                  key=lambda e: list(e.path))
    return [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in errs]


def evaluate(case, agents, review_state=None, authority=None, rules=None, company=None):
    authority = authority or load_yaml("authority.yaml")
    rules = rules or load_yaml("rules.yaml")
    review_state = review_state or {"rounds_used": 0, "unresolved_critical_gaps": []}

    errs = validate_case(case)
    if errs:
        return {"status": "INVALID_INPUT", "errors": errs}

    facts = case["facts_provided"]
    hits, notes = [], []

    def hit(rule, light, detail):
        hits.append({"rule": rule, "light": light, "detail": detail})

    # ---------- R7：Agent 輸出缺失 / 失敗 / schema 不合 ----------
    agent_validator = Draft202012Validator(load_schema("agent_output.schema.json"))
    valid_agents = {}
    for k in AGENT_KEYS:
        out = (agents or {}).get(k)
        if out is None:
            hit("R7", "紅", f"{AGENT_NAMES[k]} Agent 無輸出")
            continue
        errs = [e.message for e in agent_validator.iter_errors(out)]
        if errs:
            hit("R7", "紅", f"{AGENT_NAMES[k]} Agent 輸出未通過 Schema：{errs[0]}")
            continue
        if out["agent"] != k or out["case_id"] != case["case_id"] or out["version"] != case["version"]:
            hit("R7", "紅", f"{AGENT_NAMES[k]} Agent 輸出的 agent/case_id/version 與本案不符")
            continue
        if out["status"] == "失敗":
            hit("R7", "紅", f"{AGENT_NAMES[k]} Agent 重試與備援後仍失敗")
            continue
        if out["status"] == "降級":
            notes.append(f"{AGENT_NAMES[k]} Agent 使用備援模型產出（降級），建議人工留意")
        valid_agents[k] = out

    # ---------- R1：關鍵欄位缺漏 ----------
    crit = [k for grp in rules["critical_fields"].values() for k in grp]
    missing = [k for k in crit if not _present(facts.get(k))]
    if missing:
        hit("R1", "紅", "關鍵欄位缺漏：" + "、".join(missing))
    only_inferred = [k for k in crit if _present(facts.get(k)) and facts[k]["label"] == "推論"]
    if only_inferred:
        hit("Y6", "黃", "關鍵欄位僅為推論、無附件明載：" + "、".join(only_inferred))

    # ---------- R2：數字矛盾 ----------
    vals = defaultdict(list)
    for key, f in facts.items():
        if _present(f) and _isnum(f["value"]):
            vals[key].append(("登記表", f["value"]))
            for alt in f.get("alt_values", []):          # 切片抽取時發現的跨文件衝突值
                if _isnum(alt.get("value")):
                    vals[key].append((f"衝突值({alt.get('source','')})", alt["value"]))
    for k, out in valid_agents.items():
        for c in out["claims"]:
            for n in c.get("numbers_used", []):
                if _isnum(n["value"]):
                    vals[n["key"]].append((AGENT_NAMES[k], n["value"]))
    tol = rules["number_tolerance_pct"]
    for key, lst in vals.items():
        nums = [v for _, v in lst]
        hi, lo = max(nums), min(nums)
        denom = max(abs(hi), abs(lo))
        if denom > 0 and (hi - lo) / denom * 100 > tol:
            hit("R2", "紅", f"{key} 數字不一致（容忍 {tol}%）：" + "；".join(f"{s}={v}" for s, v in lst))

    # ---------- R3：重大合規疑慮 ----------
    for k, out in valid_agents.items():
        for r in out["top_risks"]:
            if r["severity"] == "高" and r["category"] == "合規":
                hit("R3", "紅", f"{AGENT_NAMES[k]} Agent 標示重大合規疑慮：{r['concern_id']}")

    # ---------- R4：授權/風控門檻 ----------
    if case["authority_ref"] != authority["version"]:
        hit("R4", "紅", f"案件授權版本 {case['authority_ref']} 與現行設定 {authority['version']} 不符")
    if case["basic"]["currency"] != authority["currency"]:
        hit("R4", "紅", f"幣別 {case['basic']['currency']} 與授權幣別 {authority['currency']} 不符，無法比對門檻")
    amt = _val(facts, "financial.investment_amount")
    if amt is not None and amt > authority["max_single_amount"]:
        hit("R4", "紅", f"出資金額 {amt} 超過單案上限 {authority['max_single_amount']}")
    debt, assets = _val(facts, "financial.total_debt"), _val(facts, "financial.total_assets")
    if debt is not None and assets:
        ratio = debt / assets
        if ratio > authority["max_debt_ratio"]:
            hit("R4", "紅", f"負債比 {ratio:.2f} 超過上限 {authority['max_debt_ratio']}")
    conc = _val(facts, "portfolio.concentration_pct")
    if conc is not None and conc > authority["max_concentration_pct"]:
        hit("R4", "紅", f"集中度 {conc}% 超過上限 {authority['max_concentration_pct']}%")
    base = _val(facts, "financial.return_base")
    if base is not None and base < authority["min_base_return_pct"]:
        hit("R4", "紅", f"基準情境回報 {base}% 低於最低要求 {authority['min_base_return_pct']}%")

    # ---------- R5：關係人交易 ----------
    rp = facts.get("legal.related_party_disclosure")
    if _present(rp) and isinstance(rp["value"], dict):
        v = rp["value"]
        if v.get("exists") and not (v.get("disclosed") and v.get("procedure_ok")):
            hit("R5", "紅", "存在關係人交易但未完整揭露或未經適當程序")

    # ---------- R9 / Y7：取處準則（寶碩）合規前置條件 ----------
    company = company if company is not None else load_yaml("company_profile.yaml")
    tw_hits, tw_obs, tw_post = check_tw(facts, company, authority)
    hits.extend(tw_hits)

    # ---------- R6：無憑據結論 / 標籤違規 / 數字無登記依據 ----------
    fact_ids = {f["fact_id"] for f in facts.values()}
    for k, out in valid_agents.items():
        name = AGENT_NAMES[k]
        if not any(c["evidence_refs"] for c in out["claims"]):
            hit("R6", "紅", f"{name} Agent 沒有任何附證據出處的結論")
        for c in out["claims"]:
            if c["label"] == "明載" and not c["evidence_refs"]:
                hit("R6", "紅", f"{name} Agent 標示『明載』卻無出處：{c['claim'][:20]}")
            if c["label"] == "推論" and not c.get("inferred_by"):
                hit("R6", "紅", f"{name} Agent 的推論未標註推論者：{c['claim'][:20]}")
            for n in c.get("numbers_used", []):
                if n["fact_id"] not in fact_ids:
                    hit("R6", "紅", f"{name} Agent 引用不存在的 fact_id {n['fact_id']}（疑似腦補數字）")

    # ---------- R8：補問輪後缺口未補齊 ----------
    rounds = review_state.get("rounds_used", 0)
    gaps = review_state.get("unresolved_critical_gaps", [])
    if rounds > rules.get("max_follow_up_rounds", rules.get("max_rounds", 1)):
        hit("R8", "紅", f"補問輪次 {rounds} 超過上限 {rules.get('max_follow_up_rounds', rules.get('max_rounds', 1))}（流程錯誤）")
    elif gaps and (rounds >= rules.get("max_follow_up_rounds", rules.get("max_rounds", 1)) or review_state.get("closed")):
        hit("R8", "紅", f"補問流程結束（{rounds} 輪）後仍有關鍵缺口：" + "；".join(gaps))
    open_gaps = review_state.get("open_gaps", [])
    if open_gaps:
        hit("Y9", "黃", "稽核標示之非關鍵缺口待補件：" + "；".join(open_gaps))

    # ---------- 黃燈 ----------
    absent_nc = [k for k in rules["noncritical_fields"] if not _present(facts.get(k))]
    if absent_nc:
        hit("Y1", "黃", "非關鍵欄位缺漏：" + "、".join(absent_nc))
    bench = _val(facts, "market.peer_benchmark_return")
    if base is not None and bench is not None and base > bench + authority["base_over_benchmark_margin_pct"]:
        hit("Y2", "黃", f"基準回報 {base}% 明顯高於同業基準 {bench}%（疑似過度樂觀）")
    pending = [f"{AGENT_NAMES[k]}：{c}" for k, o in valid_agents.items() for c in o["conditions_proposed"]]
    if pending:
        hit("Y3", "黃", "待談妥/補齊條件：" + "；".join(pending))
    cons = _val(facts, "financial.return_conservative")
    if cons is not None and cons < authority["min_conservative_return_pct"]:
        hit("Y4", "黃", f"保守情境回報 {cons}% 低於 {authority['min_conservative_return_pct']}%")
    ranks = [STANCE_ORDER[valid_agents[k]["core_judgement"]["stance"]]
             for k in ("investment", "finance", "legal") if k in valid_agents]
    if len(ranks) >= 2 and max(ranks) - min(ranks) >= rules["stance_divergence_gap"]:
        hit("Y5", "黃", "投資/財務/法務結論分歧過大")

    rule_light = max_light(*[h["light"] for h in hits])
    audit = valid_agents.get("audit")
    ai_light = AI_REC_TO_LIGHT[audit["ai_recommendation"]] if audit else None
    final = max_light(rule_light, ai_light)
    return {
        "status": "OK",
        "rule_light": rule_light,
        "ai_light": ai_light,
        "final_light": final,
        "ai_override_blocked": bool(ai_light) and LIGHT_ORDER[ai_light] < LIGHT_ORDER[rule_light],
        "triggered": hits,
        "triggered_rules": sorted({h["rule"] for h in hits}),
        "missing_fields": missing,
        "notes": notes,
        "tw_obligations": tw_obs,
        "post_decision_obligations": tw_post,
    }
