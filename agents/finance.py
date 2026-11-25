from .common import S, REFS, system_prompt, select_for, compact
KEY, NAME, DOMAIN = "finance", "財務", "財務"
SC = {"type": "object", "required": ["assumptions", "return_text", "basis", "refs"],
      "properties": {"assumptions": S(20), "return_text": S(4), "basis": {"enum": ["明載", "推論"]}, "refs": REFS}}
SPECIFIC_SCHEMA = {"type": "object", "required": ["health_overview", "key_metrics", "capital_structure_and_asset_authenticity",
                   "consideration_and_funding_impact", "scenarios", "contradictions_and_gaps"],
    "properties": {"health_overview": S(80),
        "key_metrics": {"type": "array", "minItems": 3, "items": {"type": "object", "required": ["metric", "value_text", "reading", "refs"],
            "properties": {"metric": S(2), "value_text": S(1), "reading": S(20), "refs": REFS}}},
        "capital_structure_and_asset_authenticity": S(80), "consideration_and_funding_impact": S(80),
        "scenarios": {"type": "object", "required": ["optimistic", "base", "conservative"], "properties": {"optimistic": SC, "base": SC, "conservative": SC}},
        "contradictions_and_gaps": {"type": "array", "items": {"type": "string"}}}}
ROLE = """【職責與深度要求】
1) 財務體質總評與關鍵指標解讀（health_overview、key_metrics≥3）：成長性、獲利品質（淨利 vs 營業現金流）、槓桿。
2) 資本結構與資產真實性檢核（capital_structure_and_asset_authenticity）：現金水位是否合理、應收/存貨/商譽/關係人往來是否有灌水或虛增警訊；無資料就明說缺漏，不得假設沒問題。
3) 交易對價與資金調度影響（consideration_and_funding_impact）：對寶碩現金部位、分期付款節奏、資金卡死與回收期風險。
4) 樂觀/基準/保守三情境推演（scenarios）：每個情境寫出假設參數與回報；回報數字須對應 facts_registry 的 financial.return_*，若登記表沒有該情境，basis=推論並寫算式，不得當成事實。標示來源若為簡報宣稱。
5) 財務矛盾與缺漏清單（contradictions_and_gaps）：含不同切片的數字衝突（參考 facts_registry 的 alt_values）。
specific 欄位：health_overview, key_metrics[{metric,value_text,reading,refs}], capital_structure_and_asset_authenticity, consideration_and_funding_impact, scenarios{optimistic|base|conservative:{assumptions,return_text,basis,refs}}, contradictions_and_gaps[]"""
SYSTEM = system_prompt(KEY, NAME, ROLE)
def select(chunks): return [compact(c) for c in select_for(DOMAIN, chunks)]
