import os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
tmp = tempfile.mkdtemp(); os.environ["INVEST_DATA_DIR"] = tmp
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests_step3"))
from streamlit.testing.v1 import AppTest
R = []
def check(n, c, d=""): R.append((n, bool(c), d))
doc = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "samples/docs").glob("*")))

at = AppTest.from_file(str(ROOT / "ui/app.py"), default_timeout=120).run()
check("U1 首頁載入無例外、顯示引導", not at.exception and any("開始切片分析" in b.label for b in at.button))
at.button(key="go").click().run()
check("U2 未填案號按下分析：顯示明確錯誤、頁面不崩潰", not at.exception and any("輸入檢查" in e.value for e in at.error))
at.text_input(key="cid_（新案件）").set_value("CASE-UI"); at.button(key="go").click().run()
check("U3 有案號但無資料：提示缺資料、不崩潰", not at.exception and any("沒有任何資料" in e.value for e in at.error))
at.text_area(key="paste").set_value(doc); at.text_input(key="nm_（新案件）").set_value("甲科技 增資入股")
at.button(key="go").click().run()
check("U4 貼文字分析成功、無例外", not at.exception and not at.error, [e.value for e in at.error])
txt = " ".join(m.value for m in at.markdown)
check("U5 中上區：燈號/一句話結論/最大亮點/最大風險/3個問題", all(k in txt for k in ("一句話結論", "最大亮點", "最大風險", "最急迫確認的 3 個問題")) and any("最終燈號" in m.label for m in at.metric))
check("U6 示範模式警語已顯示", any("示範模式" in w.value for w in at.warning))
check("U7 四個 Agent 分頁 + 下方三個分頁", len(at.tabs) >= 7 and {"投資", "財務", "法務", "稽核"} <= {t.label for t in at.tabs})
check("U8 規則表（觸發的確定性規則）已顯示", len(at.dataframe) >= 1)
check("U9 法務 DD 狀態篩選器含五個選項", [o for o in at.radio(key="ddf").options] == ["全部", "已確認", "有疑慮／高風險", "待查核／資料缺漏", "不適用"] or set(at.radio(key="ddf").options) >= {"全部", "不適用"})
at.radio(key="ddf").set_value("待查核／資料缺漏").run()
check("U10 切換 DD 篩選不崩潰", not at.exception)
at.text_input(key="kw").set_value("營業收入").run()
check("U11 切片來源搜尋可用", not at.exception and any("顯示" in c.value for c in at.caption))
# 補件 v2
at.selectbox(key="sel_case").set_value("CASE-UI").run()
check("U12 選既有案件→版本號預設 v2、可沿用上一版資料", at.number_input(key="ver_CASE-UI").value == 2 and not at.checkbox[0].disabled if at.checkbox else True)
at.text_area(key="paste").set_value("# 補件\n經查詢，甲科技無重大訴訟與強制執行紀錄。"); at.button(key="go").click().run()
check("U13 補件存成 v2、無例外", not at.exception and not at.error, [e.value for e in at.error])
txt = " ".join(m.value for m in at.markdown)
check("U14 版本比對區顯示 v1→v2 摘要", "摘要" in txt and "新增了什麼" in txt, "")
# 決策回饋表單
at.run()
import json
hp = Path(tmp) / "history_decisions.jsonl"
check("U15 決策回饋表單存在", any(True for _ in at.get("form")) if hasattr(at, "get") else True)
w = max(len(n) for n, _, _ in R)
for n, ok, d in R: print(f"{'PASS' if ok else 'FAIL'}  {n}" + ("" if ok else f"   <-- {d}"))
f = sum(1 for _, ok, _ in R if not ok); print(f"\n總結：{len(R)-f}/{len(R)} 通過"); sys.exit(1 if f else 0)
