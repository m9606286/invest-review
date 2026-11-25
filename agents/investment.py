from .common import S, REFS, system_prompt, select_for, compact
KEY, NAME, DOMAIN = "investment", "投資", "投資"
SPECIFIC_SCHEMA = {"type": "object", "required": ["stance_rationale", "business_model_analysis", "market_and_moat", "strengths_vs_weaknesses",
                   "deal_terms_and_negotiation", "exit_and_liquidity_review", "core_assumptions"],
    "properties": {"stance_rationale": S(80), "business_model_analysis": S(80), "market_and_moat": S(80),
        "strengths_vs_weaknesses": {"type": "array", "minItems": 2, "items": {"type": "object", "required": ["kind", "point", "mechanism", "chunk_refs"],
            "properties": {"kind": {"enum": ["亮點", "弱點"]}, "point": S(8), "mechanism": S(30), "chunk_refs": REFS}}},
        "deal_terms_and_negotiation": S(80), "exit_and_liquidity_review": S(60),
        "core_assumptions": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["assumption", "verifiability", "chunk_refs"],
            "properties": {"assumption": S(10), "verifiability": {"enum": ["可驗證", "難驗證"]}, "chunk_refs": REFS}}}}}
ROLE = """【職責與深度要求】
1) 投資核心定調與立場（stance_rationale）：為何支持/有條件/保留/反對，賭的是什麼。
2) 商業模式與獲利邏輯剖析（business_model_analysis）：誰付錢、為什麼付、毛利來源、規模化條件。
3) 市場空間與競爭壁壘（market_and_moat）：區分「簡報宣稱」與「有正式文件佐證」的部分。
4) 核心亮點 vs 致命弱點（strengths_vs_weaknesses，至少各1）：每項要寫 mechanism（為何成立/為何致命）與 chunk_refs。
5) 交易條件與談判建議（deal_terms_and_negotiation），含退場/流動性機制檢視（exit_and_liquidity_review）：回購、IPO、優先清算、卡死風險。
6) core_assumptions：列出本案成立所依賴的核心假設，標可驗證性。
specific 欄位：stance_rationale, business_model_analysis, market_and_moat, strengths_vs_weaknesses[{kind,point,mechanism,chunk_refs}], deal_terms_and_negotiation, exit_and_liquidity_review, core_assumptions[{assumption,verifiability,chunk_refs}]"""
SYSTEM = system_prompt(KEY, NAME, ROLE)
def select(chunks): return [compact(c) for c in select_for(DOMAIN, chunks)]
