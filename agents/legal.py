from .common import S, REFS, system_prompt, select_for, compact
KEY, NAME, DOMAIN = "legal", "法務", "法務"
SPECIFIC_SCHEMA = {"type": "object", "required": ["risk_overview", "structure_review", "related_party", "background_integrity_dd",
                   "core_contract_asset_ip_qualification", "dd_checklist"],
    "properties": {"risk_overview": S(80), "structure_review": S(80),
        "related_party": {"type": "object", "required": ["status", "evidence", "note", "next_step"],
            "properties": {"status": {"enum": ["明確涉及", "有疑似線索", "資料載明非關係人", "資料未載明"]}, "evidence": {"type": "array"}, "note": S(10), "next_step": S(10)}},
        "background_integrity_dd": S(60), "core_contract_asset_ip_qualification": S(80),
        "dd_checklist": {"type": "array", "items": {"type": "object", "required": ["item_id", "status"],
            "properties": {"item_id": {"type": "string"}, "status": {"enum": ["已確認", "有疑慮／高風險", "待查核／資料缺漏", "不適用"]},
                           "finding": {"type": "string"}, "chunk_refs": REFS, "next_step": {"type": "string"}}}}}}
ROLE = """【職責與深度要求】
1) 法務風險總評與交易架構檢視（risk_overview、structure_review）：交易型態（見 deal_profile）、對價與控制權安排、對寶碩的實質影響。
2) 關係人／實質關係人與利益衝突初判（related_party）：status 必須與輸入 related_party_assessment.status 完全一致（不得更動）；若你有不同看法，寫在 note。資料未載明時，只寫「待確認交易對象是否為關係人或實質關係人」及應向誰取得名冊/聲明，不要展開過多條文。永遠註明：僅限現有資料範圍，仍須與寶碩內部關係人名冊比對，不得宣稱絕對無關聯。
3) 背景/誠信與不良紀錄 DD 評估（background_integrity_dd）：訴訟、強制執行、票據、裁罰、輿情、智財爭議；沒有查到不等於沒有，資料未提供時一律列為待查核，不得假設無不良紀錄。
4) 核心合約/資產權屬/智財與營運資格分析（core_contract_asset_ip_qualification）：引用合約切片條號。
5) dd_checklist：對輸入 dd_template 中 applicable=true 的每一項逐項回答（item_id 必須沿用），status 只能是 已確認｜有疑慮／高風險｜待查核／資料缺漏｜不適用；每項附 finding、chunk_refs、next_step（下一步查核/談判建議）。已確認必須附正式/一般文件切片；有疑慮或待查核的項目，必須同步出現在 top_risks 或 missing_info（可在描述中寫 [DD-<item_id>]）。applicable=false 的項目請不要回答（系統會標不適用）。
6) 針對 engine_precheck.tw_obligations 逐項說明適用原因、證據與尚缺事項，寫進 structure_review 或 risk_overview。
specific 欄位：risk_overview, structure_review, related_party{status,evidence,note,next_step}, background_integrity_dd, core_contract_asset_ip_qualification, dd_checklist[{item_id,status,finding,chunk_refs,next_step}]"""
SYSTEM = system_prompt(KEY, NAME, ROLE)
def select(chunks): return [compact(c) for c in select_for(DOMAIN, chunks)]
