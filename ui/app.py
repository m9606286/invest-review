"""寶碩｜多 Agent 投資決策輔助 — 單頁工作台（Streamlit）。啟動：streamlit run ui/app.py"""
import json, os, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "tests_step3"):
    if str(p) not in sys.path: sys.path.insert(0, str(p))
import pandas as pd
import streamlit as st

from engine.chunker import chunk_sources
from engine.extract import extract, build_case_package
from engine.pipeline import run_case
from engine.report import render_report, _top_risk, _questions, EMOJI, ACTION
from engine.rule_info import INFO
from engine.rules import load_yaml, validate_case
from engine import store
from agents.legal_dd import DIMENSIONS, STATUSES

st.set_page_config(page_title="寶碩 投資決策輔助", page_icon="🧭", layout="wide")
ASSETS = ["有價證券", "不動產", "設備", "使用權資產", "無形資產", "會員證", "併購", "其他（規則庫未涵蓋）"]
PROCS = {"target_fs_reviewed": "標的最近期會計師查核/核閱財報", "appraisal_report": "專業估價報告", "cpa_price_opinion": "會計師價格合理性意見",
         "board_approval": "董事會決議", "audit_committee_approval": "審計委員會同意", "independent_director_minutes": "獨立董事意見載明議事錄",
         "chairman_approval": "董事長簽核（未達董事會門檻）", "expert_independence": "專家獨立性確認", "related_pack": "關係人交易資料包(第15條)",
         "related_valuation_or_cpa": "關係人交易估價/會計師意見(第14條)", "related_cost_cpa_review": "關係人不動產成本合理性會計師複核(第16條)",
         "shareholder_approval": "股東會同意", "cpa_opinion_appraisal_gap": "估價差距之會計師意見", "merger_expert_opinion": "併購合理性專家意見"}
LIGHT_COLOR = {"綠": "green", "黃": "orange", "紅": "red"}

st.title("🧭 寶碩｜多 Agent 投資決策輔助工作台")
st.caption("投資 → 財務 → 法務 → 稽核，層層審核；燈號由確定性規則引擎決定，AI 只能把燈號調得更嚴。僅為決策輔助，須人工核准。")

# =============================== 上方：案件、補件與資料投入 ===============================
with st.container(border=True):
    st.subheader("① 案件、補件與資料投入")
    c1, c2, c3 = st.columns([2, 2, 1])
    cases = store.list_cases()
    sel = c1.selectbox("選取既有案件（補件）或建立新案件", ["（新案件）"] + cases, key="sel_case")
    existing = sel != "（新案件）"
    vers = store.list_versions(sel) if existing else []
    case_id = c2.text_input("案件編號／案名", value=(sel if existing else ""), key=f"cid_{sel}", placeholder="例如 APEX-2026-017")
    version = c3.number_input("版本號 v", min_value=1, value=(max(vers) + 1 if vers else 1), step=1, key=f"ver_{sel}")
    prev = store.load_version(sel, max(vers)) if existing and vers else None
    pb = (prev["case"]["basic"] if prev and prev.get("case") else {})

    b1, b2, b3, b4 = st.columns(4)
    name = b1.text_input("交易名稱", value=pb.get("name", ""), key=f"nm_{sel}")
    deal_type = b2.text_input("交易型態", value=pb.get("deal_type", "股權投資/增資"), key=f"dt_{sel}", help="例：股權投資/增資、資產收購、合資合作；會決定法務DD清單的適用項目")
    asset_type = b3.selectbox("標的資產類型（取處準則）", ASSETS, key=f"at_{sel}")
    direction = b4.selectbox("交易方向", ["取得", "處分"], key=f"dr_{sel}")
    d1, d2 = st.columns(2)
    conc = d1.number_input("本案占投資組合比重 %（授權檢核用）", min_value=0.0, max_value=100.0, value=10.0, key=f"cc_{sel}")
    roster = d2.radio("與寶碩內部關係人名冊比對", ["尚未比對", "比對結果：是關係人/實質關係人", "比對結果：非關係人"], horizontal=True, key=f"ro_{sel}")
    with st.expander("取處準則／內控程序狀態（簽約付款前須完成；未填視為『未規劃』會觸發紅燈）"):
        pc = st.columns(3); procs = {}
        for i, (k, label) in enumerate(PROCS.items()):
            procs[k] = pc[i % 3].selectbox(label, ["未規劃", "待辦", "已具備"], key=f"pr_{k}_{sel}")
    u1, u2 = st.columns(2)
    files = u1.file_uploader("上傳檔案（可多檔：.txt .md .csv .xlsx .docx .pdf）", accept_multiple_files=True, key="files")
    pasted = u2.text_area("或直接貼上文字（簡報重點、會議紀錄、條款摘錄…）", height=120, key="paste", placeholder="貼上的文字會被視為『一般文件』，含『據稱/口頭/預計』等用語者會自動降低可信度")
    reuse = st.checkbox("沿用上一版的全部原始資料（補件時勾選，v2 = v1 資料 + 本次新增）", value=existing and bool(vers), disabled=not (existing and vers))

    m1, m2 = st.columns([2, 3])
    mode = m1.radio(
        "分析引擎",
        ["示範模式（腳本模擬）", "Gemini 免費額度", "OpenAI 相容免費 API", "Anthropic（需付費）"],
        horizontal=False,
        key="mode",
    )
    with m2:
        if mode == "Gemini 免費額度":
            api_key = st.text_input("GEMINI_API_KEY（留空則讀環境變數）", type="password", key="gemini_key")
            gemini_model = st.text_input("Gemini 模型", value="gemini-3-flash-preview", key="gemini_model")
        elif mode == "OpenAI 相容免費 API":
            compat_url = st.text_input("Base URL", value="https://openrouter.ai/api/v1", key="compat_url")
            api_key = st.text_input("API Key（留空則讀環境變數）", type="password", key="compat_key")
            compat_model = st.text_input("模型名稱", value="openrouter/free", key="compat_model")
        elif mode == "Anthropic（需付費）":
            api_key = st.text_input("ANTHROPIC_API_KEY（留空則讀環境變數）", type="password", key="anthropic_key")
        else:
            api_key = ""
            st.caption("示範模式不需要 API Key，可直接按「開始切片分析」測試流程。")

    go = st.button("開始切片分析", type="primary", width="stretch", key="go")


def pick_llm():
    if mode.startswith("示範"):
        from mock import ScriptedLLM, behavior_default
        return ScriptedLLM(behavior_default)
    if mode.startswith("Gemini"):
        from engine.llm import GeminiLLM
        m_name = (gemini_model or "gemini-3-flash-preview").strip()
        return GeminiLLM(api_key=api_key or None, models=[m_name, m_name])
    if mode.startswith("OpenAI"):
        from engine.llm import OpenAICompatLLM
        return OpenAICompatLLM(api_key=api_key or None, base_url=compat_url or None, model=compat_model or None)
    from engine.llm import AnthropicLLM
    return AnthropicLLM(api_key=api_key or None)


if go:
    stage = "輸入檢查"
    try:
        if not case_id.strip():
            st.error("【輸入檢查】請填案件編號／案名。")
        else:
            sources = []
            if reuse and vers: sources += store.load_sources(sel, max(vers))
            sources += [(f.name, f.getvalue()) for f in (files or [])]
            if pasted.strip(): sources.append((f"貼上文字_v{int(version)}.txt", pasted))
            if not sources:
                st.error("【輸入檢查】沒有任何資料：請上傳檔案或貼上文字。")
            else:
                with st.status("分析進行中…", expanded=True) as status:
                    stage = "資料切片"; st.write("① 資料切片（依結構/表格/段落，保留完整表格與數字）")
                    chunks, notes = chunk_sources(sources)
                    for n in notes:
                        st.warning(f"【資料切片】{n['file']}：{n.get('error') or n.get('warning')}（此檔未納入分析，其他檔案不受影響）")
                    if not chunks: raise RuntimeError("所有資料都無法切片，請檢查檔案格式")
                    stage = "事實抽取"; st.write(f"② 抽取事實登記表（{len(chunks)} 個切片）")
                    basic = {"name": name or case_id, "deal_type": deal_type, "asset_type": None if asset_type.startswith("其他") else asset_type,
                             "direction": direction, "concentration_pct": conc, "submitted_at": date.today().isoformat(),
                             "procedures": {k: v for k, v in procs.items() if v != "未規劃"}}
                    if asset_type.startswith("其他"): basic["asset_type"] = "其他"
                    rr = {"尚未比對": None, "比對結果：是關係人/實質關係人": "是", "比對結果：非關係人": "否"}[roster]
                    ex = extract(chunks, basic, roster_result=rr)
                    case = build_case_package(case_id.strip(), int(version), basic, chunks, ex, prev_version_ref=(f"{sel}/v{max(vers)}" if existing and vers else None))
                    errs = validate_case(case)
                    if errs: raise RuntimeError("案件資料不合格式：" + "；".join(errs[:3]))
                    stage = "歷史比對"; hist = store.similar_cases(deal_type, [], root=None, exclude_case=case["case_id"])
                    stage = "Agent 審核"; st.write("③ 投資 → 財務 → 法務 → 稽核（含補問輪、規則閘門）")
                    out = run_case(case, chunks, pick_llm(), history=hist)
                    if out["status"] != "OK": raise RuntimeError("案件未通過驗證：" + "；".join(out["errors"][:3]))
                    stage = "存檔"; store.save_sources(case["case_id"], case["version"], sources); store.save_version(case, chunks, out)
                    st.session_state["res"] = {"case": case, "chunks": chunks, "out": out, "extraction": ex, "mode": mode}
                    status.update(label="分析完成", state="complete")
    except Exception as e:
        st.error(f"【{stage}】發生錯誤：{type(e).__name__}: {e} — 受影響環節：{stage}；其餘頁面功能不受影響，可修正後重試。")

res = st.session_state.get("res")
if not res:
    st.info("請在上方投入資料並按「開始切片分析」。")
else:
    case, chunks, out, ex = res["case"], res["chunks"], res["out"], res["extraction"]
    ev = out["evaluation"]; L = ev["final_light"]
    full, sections = render_report(case, out, chunks, return_sections=True)
    if res["mode"].startswith("示範"): st.warning("目前為『示範模式』：Agent 輸出由腳本產生，僅用來展示流程與規則閘門，不是真實分析。")

    # =============================== 中上：燈號與一頁式摘要 ===============================
    with st.container(border=True):
        st.subheader(f"② 決策燈號與一頁式摘要｜{case['basic']['name']}（{case['case_id']} v{case['version']}）")
        k1, k2, k3, k4 = st.columns([1, 1, 1, 2])
        k1.metric("最終燈號", f"{EMOJI[L]} {L}燈"); k2.metric("規則引擎", ev["rule_light"]); k3.metric("稽核建議", ev["ai_light"] or "無")
        rpv = case["facts_provided"]["legal.related_party_disclosure"]["value"]
        k4.metric("關係人初判", rpv["status"], help="僅限現有資料；仍須與寶碩內部關係人名冊比對")
        st.markdown(f"**建議動作**：{ACTION[L]}")
        audit = out["agents"]["audit"]
        st.markdown(f"**一句話結論**：{audit['core_judgement']['summary'] if audit['status'] != '失敗' else '稽核 Agent 未完成'}")
        st.markdown(f"**最大亮點**：{(audit.get('specific') or {}).get('highlight', '（無）')}")
        st.markdown(f"**最大風險**：{_top_risk(out)}")
        st.markdown("**最急迫確認的 3 個問題**")
        for i, q in enumerate(_questions(out, case), 1): st.markdown(f"{i}. {q}")
        if ev["triggered"]:
            df = pd.DataFrame([{"規則": h["rule"], "燈": h["light"], "觸發原因": h["detail"], "規則說明": INFO.get(h["rule"], ("", ""))[0], "解除條件": INFO.get(h["rule"], ("", ""))[1]} for h in ev["triggered"]])
            st.markdown("**觸發的確定性規則**（R1–R9 紅燈／Y1–Y9 黃燈；AI 無法放寬）")
            st.dataframe(df, width="stretch", hide_index=True)
        else:
            st.success("確定性規則引擎未觸發任何紅/黃燈。")
        st.download_button("下載完整報告（Markdown）", full, file_name=f"{case['case_id']}_v{case['version']}_report.md", key="dl")

    # =============================== 中下：四 Agent 深度報告 ===============================
    with st.container(border=True):
        st.subheader("③ 四 Agent 深度報告與法務 DD 清單")
        t_inv, t_fin, t_leg, t_aud = st.tabs(["投資", "財務", "法務", "稽核"])
        t_inv.markdown("\n".join(sections["investment"])); t_fin.markdown("\n".join(sections["finance"])); t_aud.markdown("\n".join(sections["audit"]))
        with t_leg:
            lg = out["agents"]["legal"]
            if lg["status"] == "失敗":
                st.error(lg["core_judgement"]["summary"])
            else:
                txt = sections["legal"]
                i0 = next(i for i, l in enumerate(txt) if l.startswith("**法務 DD 審查清單檢核表**")); i1 = next(i for i, l in enumerate(txt) if l.startswith("**最大風險／疑點**"))
                st.markdown("\n".join(txt[:i0]))
                st.markdown("\n".join(txt[i0:i0 + 1]))
                flt = st.radio("DD 清單狀態篩選", ["全部"] + STATUSES, horizontal=True, key="ddf")
                items = lg["specific"]["dd_checklist"]
                for dk, dn in DIMENSIONS.items():
                    rows = [d for d in items if d["dimension"] == dk and (flt == "全部" or d["status"] == flt)]
                    with st.expander(f"({dk}) {dn}｜顯示 {len(rows)} / {sum(1 for d in items if d['dimension'] == dk)} 項", expanded=bool(rows) and flt != "全部"):
                        if rows:
                            st.dataframe(pd.DataFrame([{"項目": f"{d['item_id']} {d['name']}", "狀態": d["status"], "發現": d.get("finding", ""), "出處": ", ".join(d.get("chunk_refs", [])), "下一步查核／談判建議": d.get("next_step", "")} for d in rows]), width="stretch", hide_index=True)
                        else: st.caption("（此篩選下無項目）")
                linked = [d for d in items if d["status"] in ("有疑慮／高風險", "待查核／資料缺漏") and (flt in ("全部", d["status"]))]
                if linked:
                    st.markdown("**連動建議（已同步帶入法務風險／缺漏資訊）**")
                    for d in linked: st.markdown(f"- [{d['status']}] {d['item_id']} {d['name']} → {d.get('next_step') or '補充資料後查核'}")
                st.markdown("\n".join(txt[i1:]))

    # =============================== 下方：版本比對、決策回饋、切片來源 ===============================
    with st.container(border=True):
        st.subheader("④ 版本比對、決策回饋與切片來源")
        tv, tf, ts = st.tabs(["版本比對 v1 → v2", "AI 建議 vs. 最終決策", "切片來源檢視器"])
        with tv:
            vs = store.list_versions(case["case_id"])
            if len(vs) < 2: st.info("此案件目前只有一個版本。補件後以新版本號（v2…）再次分析，即可在此對照差異。")
            else:
                a, b = st.columns(2); va = a.selectbox("舊版", vs, index=len(vs) - 2, key="va"); vb = b.selectbox("新版", vs, index=len(vs) - 1, key="vb")
                if va != vb:
                    d = store.diff_versions(store.load_version(case["case_id"], va), store.load_version(case["case_id"], vb))
                    st.markdown(f"**摘要**：{store.diff_summary_line(d)}")
                    c_a, c_b, c_c = st.columns(3)
                    c_a.markdown("**新增了什麼**"); c_a.write(d["new_documents"] or ["（無新文件）"]); c_a.write([f"事實：{k}" for k in d["facts_added"]] or ["（無新事實）"])
                    c_b.markdown("**解除了哪些疑慮／規則**"); c_b.write([f"{x['concern_id']}｜{x['description'][:40]}" for x in d["concerns_resolved"]] or ["（無）"]); c_b.write([f"規則 {r} 已解除" for r in d["rules_cleared"]])
                    c_c.markdown("**新出現的問題**"); c_c.write([f"{x['concern_id']}｜{x['description'][:40]}" for x in d["concerns_new"]] or ["（無）"]); c_c.write([f"規則 {r} 新觸發" for r in d["rules_new"]])
                    if d["facts_changed"]: st.markdown("**數字/內容變動**"); st.dataframe(pd.DataFrame([{"欄位": x["key"], "舊值": str(x["old"])[:60], "新值": str(x["new"])[:60]} for x in d["facts_changed"]]), hide_index=True)
        with tf:
            with st.form("fb"):
                f1, f2, f3 = st.columns(3)
                ai_rec = audit.get("ai_recommendation", "暫緩") if audit["status"] != "失敗" else "暫緩"
                f1.text_input("AI 建議（稽核）", value=ai_rec, disabled=True); f2.text_input("最終燈號", value=L, disabled=True)
                human = f3.selectbox("人工最終決策", ["推進", "有條件推進", "暫緩"], index=2)
                f4, f5 = st.columns(2); ddate = f4.date_input("決策日期", value=date.today()); tags = f5.text_input("踩坑／後續標籤（逗號分隔）")
                reason = st.text_area("與 AI 建議差異的原因／備註")
                sub = st.form_submit_button("儲存決策紀錄")
            if sub:
                try:
                    store.record_decision({"case_id": case["case_id"], "version": case["version"], "deal_type": case["basic"]["deal_type"], "ai_recommendation": ai_rec,
                                           "final_light": L, "human_decision": human, "decision_date": ddate.isoformat(), "diff_reason": reason,
                                           "postmortem_tags": [t.strip() for t in tags.split(",") if t.strip()], "triggered_rules": ev["triggered_rules"]})
                    st.success("已儲存至 data/history_decisions.jsonl")
                except Exception as e:
                    st.error(f"【決策回饋】儲存失敗：{e}")
            hist = store.load_history()
            if hist:
                only = st.checkbox("只看『AI 建議與人工決策不一致』", key="onlydis")
                rows = store.disagreements() if only else hist
                st.dataframe(pd.DataFrame([{k: (", ".join(v) if isinstance(v, list) else v) for k, v in h.items()} for h in rows]), width="stretch", hide_index=True)
        with ts:
            q1, q2 = st.columns([2, 2]); kw = q1.text_input("搜尋切片內容/檔名", key="kw"); dom = q2.multiselect("依領域篩選", ["投資", "財務", "法務", "稽核"], key="dom")
            shown = [c for c in chunks if (not kw or kw in c["text"] or kw in c["source_file"]) and (not dom or set(dom) & set(c["domain_tags"]))]
            st.caption(f"共 {len(chunks)} 個切片，顯示 {len(shown)} 個")
            for c in shown:
                flag = "⚠ " if c["low_confidence"] else ""
                with st.expander(f"{flag}{c['chunk_id']}｜{c['source_file']}｜{c['location']}｜{c['evidence_grade']}｜{'/'.join(c['domain_tags'])}"):
                    st.caption(f"性質：{c['nature']} 低可信度：{'是' if c['low_confidence'] else '否'} 警示：{'；'.join(c['warnings']) or '無'}")
                    st.text(c["text"])
