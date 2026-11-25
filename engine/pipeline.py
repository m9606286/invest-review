"""四 Agent 審核管線：切片 → 事實登記表 → 確定性預檢 → 投資→財務→法務→稽核 → 補問輪(預設1) → 規則閘門 → 報告。"""
import json
from jsonschema import Draft202012Validator

from agents import REGISTRY, ORDER
from agents import common as AC
from agents import legal_dd as DD
from .llm import extract_json
from .rules import evaluate, load_yaml, load_schema, AGENT_KEYS
from .report import render_report


def _stub(agent, case, reason):
    return {"agent": agent, "case_id": case["case_id"], "version": case["version"], "status": "失敗",
            "core_judgement": {"stance": "保留", "summary": f"Agent 執行失敗：{reason}"[:300], "confidence": "低"},
            "top_risks": [], "missing_info": [], "claims": [], "conditions_proposed": [], "questions_for_human": [], "specific": {},
            **({"ai_recommendation": "暫緩"} if agent == "audit" else {})}


def _summary(o, with_specific=True):
    keys = ["agent", "core_judgement", "top_risks", "claims", "missing_info", "conditions_proposed", "status"] + (["specific"] if with_specific else [])
    d = {k: o.get(k) for k in keys}
    if not with_specific: d["note"] = "細節已省略，須回頭對照切片"
    return d


def build_ctx(agent, case, chunks, pre, outputs, extra, followups=None):
    mod = REGISTRY[agent]
    sel_all = mod.select(chunks)
    keep_ids = {c["chunk_id"] for c in AC.fit_chunks([c for c in chunks if c["chunk_id"] in {x["chunk_id"] for x in sel_all}])[0]}
    sel = [c for c in sel_all if c["chunk_id"] in keep_ids]
    ctx = {"agent": agent, "case_id": case["case_id"], "version": case["version"], "basic": case["basic"],
           "facts_registry": case["facts_provided"], "chunks": sel, "chunks_omitted_for_length": sorted({c["chunk_id"] for c in sel_all} - keep_ids),
           "engine_precheck": {"missing_critical_fields": pre["missing_fields"], "tw_obligations": pre["tw_obligations"],
                               "post_decision_obligations": pre["post_decision_obligations"],
                               "deterministic_hits": [h for h in pre["triggered"] if h["rule"] != "R7"]}}
    ups = {"investment": [], "finance": ["investment"], "legal": ["investment", "finance"], "audit": ORDER}[agent]
    if ups:
        ctx["upstream_unverified"] = {k: _summary(outputs[k], with_specific=(agent == "audit")) for k in ups if k in outputs}
    if agent == "legal":
        ctx["deal_profile"] = extra["deal_profile"]; ctx["dd_template"] = extra["dd_template"]
        ctx["related_party_assessment"] = case["facts_provided"]["legal.related_party_disclosure"]["value"]
    if agent == "audit":
        ctx["historical_cases"] = extra.get("history", [])
    if followups:
        ctx["followup_questions"] = followups
    return ctx


def call_agent(agent, ctx, llm, case, chunks, extra, trace, pnotes):
    mod = REGISTRY[agent]; name = mod.NAME
    base_val = Draft202012Validator(load_schema("agent_output.schema.json"))
    known = {c["chunk_id"] for c in chunks} | {f["fact_id"] for f in case["facts_provided"].values()}
    base = json.dumps(ctx, ensure_ascii=False)
    primary, backup = llm.models[0], llm.models[-1]
    plan = [(primary, False), (primary, True)] + ([(backup, True)] if backup != primary else [])
    err = None
    for i, (model, with_err) in enumerate(plan, 1):
        user = base + (f"\n\n[上次輸出的錯誤，請修正後只輸出JSON]\n{err}" if with_err and err else "")
        try:
            obj = extract_json(llm.complete(mod.SYSTEM, user, model))
            obj.update(agent=agent, case_id=case["case_id"], version=case["version"], status="完成" if model == primary else "降級")
            errs = [e.message for e in base_val.iter_errors(obj)]
            if errs: raise ValueError("Schema：" + "；".join(errs[:4]))
            errs = AC.lint(obj, known, mod.SPECIFIC_SCHEMA, name)
            if agent == "legal":
                want = ctx["related_party_assessment"]["status"]; got = (obj["specific"].get("related_party") or {}).get("status")
                if got != want: errs.append(f"related_party.status 必須等於引擎初判『{want}』（你填『{got}』）；不同看法請寫在 note")
            if errs: raise ValueError("品質檢核：" + "；".join(errs[:6]))
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            trace.append({"agent": agent, "attempt": i, "model": model, "ok": False, "error": err[:200]}); continue
        pnotes += AC.downgrade_unverified(obj, chunks, name)
        if agent == "legal":
            obj, n = DD.normalize(obj, extra["dd_template"], chunks); pnotes += [f"法務DD：{x}" for x in n]
        trace.append({"agent": agent, "attempt": i, "model": model, "ok": True})
        return obj
    return _stub(agent, case, err or "未知錯誤")


def _gaps(audit):
    if not audit or audit.get("status") == "失敗": return []
    return [x for x in ((audit.get("specific") or {}).get("gaps") or []) if isinstance(x, dict) and x.get("gap_id") and x.get("description")]


def run_case(case, chunks, llm, company=None, authority=None, rules=None, max_rounds=None, history=None):
    authority = authority or load_yaml("authority.yaml"); rules = rules or load_yaml("rules.yaml")
    company = company if company is not None else load_yaml("company_profile.yaml")
    max_rounds = rules.get("max_follow_up_rounds", 1) if max_rounds is None else max_rounds
    ev = lambda ag, st: evaluate(case, ag, st, authority, rules, company)
    pre = ev({}, None)
    if pre["status"] != "OK":
        return {"status": "INVALID_INPUT", "errors": pre["errors"]}
    profile = DD.identify_deal_profile(case["basic"], case["facts_provided"], chunks)
    extra = {"deal_profile": profile, "dd_template": DD.template(profile), "history": history or []}
    trace, outputs, rounds_log, pnotes = [], {}, [], []
    for a in ORDER:
        outputs[a] = call_agent(a, build_ctx(a, case, chunks, pre, outputs, extra), llm, case, chunks, extra, trace, pnotes)
    outputs["audit"] = call_agent("audit", build_ctx("audit", case, chunks, pre, outputs, extra), llm, case, chunks, extra, trace, pnotes)

    rounds_used = 0
    while rounds_used < max_rounds:
        auto = [g for g in _gaps(outputs["audit"]) if g.get("fillable_from") == "attachments" and g.get("target_agent") in ORDER]
        if not auto: break
        rounds_used += 1
        before = {g["gap_id"] for g in _gaps(outputs["audit"])}
        targets = [a for a in ORDER if any(g["target_agent"] == a for g in auto)]
        for a in targets:
            fq = [f"[{g['gap_id']}] {g['description']}" for g in auto if g["target_agent"] == a]
            outputs[a] = call_agent(a, build_ctx(a, case, chunks, pre, outputs, extra, fq), llm, case, chunks, extra, trace, pnotes)
        outputs["audit"] = call_agent("audit", build_ctx("audit", case, chunks, pre, outputs, extra), llm, case, chunks, extra, trace, pnotes)
        after = {g["gap_id"] for g in _gaps(outputs["audit"])}
        rounds_log.append({"round": rounds_used, "reran": targets + ["audit"], "resolved": sorted(before - after), "still_open": sorted(before & after), "new": sorted(after - before)})

    fg = _gaps(outputs["audit"])
    crit = [f"{g['gap_id']} {g['description']}" for g in fg if g.get("critical")]
    openg = [f"{g['gap_id']} {g['description']}" for g in fg if not g.get("critical")]
    state = {"rounds_used": rounds_used, "unresolved_critical_gaps": crit, "open_gaps": openg, "closed": True}
    result = ev(outputs, state)
    out = {"status": "OK", "case_id": case["case_id"], "version": case["version"], "agents": outputs, "review_state": state,
           "rounds_log": rounds_log, "evaluation": result, "trace": trace, "pipeline_notes": pnotes, "deal_profile": profile,
           "agent_calls": {a: sum(1 for t in trace if t["agent"] == a) for a in AGENT_KEYS}, "chunk_index": [{k: c[k] for k in ("chunk_id", "source_file", "location", "evidence_grade", "nature", "low_confidence")} for c in chunks]}
    out["report_md"] = render_report(case, out, chunks)
    return out
