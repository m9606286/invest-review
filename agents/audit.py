from .common import S, REFS, system_prompt, compact
KEY, NAME, DOMAIN = "audit", "稽核", "稽核"
SPECIFIC_SCHEMA = {"type": "object", "required": ["cross_contradictions", "optimistic_assumptions", "number_mismatches", "missing_critical", "authority_check",
                   "stress_tests", "evidence_chain", "historical_commentary", "reconciliation_score", "highlight", "gaps"],
    "properties": {"cross_contradictions": {"type": "array"}, "optimistic_assumptions": {"type": "array"}, "number_mismatches": {"type": "array"},
        "missing_critical": {"type": "array", "items": {"type": "string"}},
        "authority_check": {"type": "object", "required": ["result", "notes"], "properties": {"result": {"enum": ["通過", "疑慮"]}, "notes": S(10)}},
        "stress_tests": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["assumption", "test", "result"],
            "properties": {"assumption": S(8), "test": S(20), "result": S(20)}}},
        "evidence_chain": {"type": "object", "required": ["facts", "inferences", "gaps"], "properties": {"facts": {"type": "array"}, "inferences": {"type": "array"}, "gaps": {"type": "array"}}},
        "historical_commentary": S(4), "reconciliation_score": {"type": "integer", "minimum": 0, "maximum": 100}, "highlight": S(10),
        "gaps": {"type": "array", "items": {"type": "object", "required": ["gap_id", "description", "target_agent", "fillable_from", "critical"],
            "properties": {"gap_id": S(2), "description": S(8), "target_agent": {"enum": ["investment", "finance", "legal"]},
                           "fillable_from": {"enum": ["attachments", "human"]}, "critical": {"type": "boolean"}}}}}}
ROLE = """【職責與深度要求】你是最後一道關卡：不得因為三方結論一致就略過檢查，須逐一對帳。
1) 跨角色矛盾點交叉對帳（cross_contradictions、number_mismatches）：比對各方 claims 與 facts_registry/切片；對照切片之間的衝突數字（facts 的 alt_values）。每筆寫出誰說了什麼、與哪個切片衝突、為何重要。
2) 關鍵樂觀假設壓力測試（stress_tests、optimistic_assumptions）：至少1項；寫出「若假設不成立（如成長率減半、延遲回收）結果如何」，優先檢驗只由簡報/宣稱支撐的假設。
3) 事實/推論/缺漏證據鏈評估（evidence_chain）：列出本案結論中，哪些靠正式文件、哪些靠推論或宣稱、哪些仍缺；指出被簡報宣稱「包裝成事實」的地方。
4) 歷史相似模式/前案警訊（historical_commentary）：若輸入 historical_cases 有資料，只能當參考提醒、不得當證據；沒有就寫「無歷史紀錄可比對」。
5) 守住內控與授權紅線（authority_check）；並說明確定性規則引擎觸發的紅/黃燈（輸入 engine_precheck.deterministic_hits）你是否同意、如何才能解除。
6) 你必須輸出 ai_recommendation（推進｜有條件推進｜暫緩），與你找到的問題一致。
7) gaps：可由既有附件補查者 fillable_from=attachments 並指定 target_agent（會自動請該 Agent 補答）；必須由人提供新資料者 fillable_from=human；critical=true 表示不補齊就不能做決策。
specific 欄位：cross_contradictions[], optimistic_assumptions[], number_mismatches[], missing_critical[], authority_check{result:通過|疑慮,notes}, stress_tests[{assumption,test,result}], evidence_chain{facts[],inferences[],gaps[]}, historical_commentary, reconciliation_score(0-100整數), highlight, gaps[{gap_id,description,target_agent,fillable_from,critical}]
另外頂層需有 "ai_recommendation"。"""
SYSTEM = system_prompt(KEY, NAME, ROLE)
def select(chunks): return [compact(c) for c in chunks]
