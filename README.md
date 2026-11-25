# 寶碩｜多 Agent 投資決策輔助系統

投資 → 財務 → 法務 → 稽核，層層審核；**燈號由確定性規則引擎決定，AI 只能把燈號調得更嚴**。符合《公開發行公司取得或處分資產處理準則》前置檢查。僅為決策輔助，須人工核准，不構成法律意見。

## 快速開始
```bash
pip install streamlit jsonschema pyyaml openpyxl python-docx pdfplumber pandas
streamlit run ui/app.py                      # 單頁工作台（預設「示範模式」，不需 API key）
export ANTHROPIC_API_KEY=...                 # 真實 LLM；模型可用 INVEST_PRIMARY_MODEL / INVEST_BACKUP_MODEL 覆寫
python3 run_pipeline.py samples/docs --case-id DEMO-1 --asset-type 有價證券 --roster 否 --mock   # 命令列
```
測試：`python3 run_tests.py`（規則引擎33）｜`python3 tests_step3/run_tests_step3.py`（切片/抽取/關係人/DD/管線/版本 69）｜`python3 tests_step3/run_tests_ui.py`（UI 15）｜`python3 run_anchor_test.py`（埋雷；有 API key 時多跑真實稽核命中率）

## 結構
| 路徑 | 內容 |
|---|---|
| engine/chunker.py、schemas/chunk.schema.json | 結構/表格/段落切片；來源、位置、領域標籤、證據等級、事實/假設/宣稱、低可信警示 |
| engine/extract.py | 由切片抽取 facts_provided；缺漏明確標「缺漏」；簡報/口頭/預測用語一律降為「推論」；跨文件衝突記 alt_values |
| engine/related_party.py | 關係人四態初判（明確涉及/有疑似線索/資料載明非關係人/資料未載明）＋切片出處＋名冊比對狀態 |
| agents/{investment,finance,legal,audit}.py、agents/common.py | 四 Agent 提示、深度報告 Schema、品質守門（空泛套話/不存在的出處/擅改關係人狀態會被擋並重試） |
| agents/legal_dd.py | 法務 DD 清單：5構面26項，依案型動態調整，不適用須附原因，遺漏/僅憑簡報的「已確認」會被降為待查核 |
| engine/pipeline.py | 切片→登記表→預檢→四Agent→補問輪(預設1輪，只重跑受影響Agent)→規則閘門→報告 |
| engine/rules.py、tw_compliance.py、rule_info.py | R1–R9、Y1–Y9、取處準則第5/8/9/10/11/14/15/16/23/31/35條、規則說明與解除條件 |
| engine/store.py | data/cases/<案>/v<n>/ 版本存檔、v1→v2 差異、data/history_decisions.jsonl、相似前案 |
| ui/app.py | 單頁工作台 |
| config/ | authority.yaml（授權門檻，部分仍為佔位值）、company_profile.yaml（寶碩）、rules.yaml |

## 已知限制（請務必知悉）
1. **真實 LLM 的分析品質尚未實測**（開發環境沒有 API key）。測試用的是腳本模擬，驗證的是管線、守門與規則閘門。請在你的環境用 `--live` 或 UI「真實 LLM」跑 `samples/docs_B` 驗證命中率。
2. 事實抽取為規則式：歷史數列只從表格列抽取；散文中的複雜敘述可能抓不到（會標缺漏，不會猜）。PDF 掃描檔需 OCR（目前會提示）。
3. 寶碩「總資產」目前為 115Q3 **合併**數暫代，第35條應用**個體**數；填入個體數並將 `total_assets_basis` 改為 `個體` 前，所有案件最好只能到黃燈（Y8）。
4. `authority.yaml` 的單案上限、負債比、集中度、回報門檻仍是佔位值。
5. 取處準則規則庫 v1 不含：衍生性商品、金融機構債權、大陸地區投資、營建業專案、其他重要資產（一律紅燈要求人工覆核）。條文詮釋（如第10條但書適用範圍）請由寶碩法務或簽證會計師確認。
6. 關係人初判只依現有切片，**必須**與寶碩內部關係人名冊比對；未比對前規則引擎維持 R9 紅燈。
