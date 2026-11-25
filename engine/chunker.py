"""自動資料切片：依結構（標題/表格/段落）切片，完整保留表格、不拆散數字、不硬切斷句。
支援：.txt .md .csv .xlsx .docx .pdf 與貼上文字。每塊帶來源、位置、領域標籤、證據等級、事實/假設標記與低可信度警示。"""
import io, re, csv
from pathlib import Path

PROSE_TARGET = 1000      # 敘述段落每塊目標字數（只在句界切，單句超過就整句保留）
TABLE_HARD = 6000        # 表格超過此字數才依列分段，且每段重複表頭

KW = {
    "財務": "營收 營業收入 銷貨 淨利 稅後 現金流 現金流量 負債 資產 權益 毛利 EBITDA 估值 本益比 融資 借款 現金 應收 存貨 折舊 財報 損益 資產負債 出資 分期 回報 IRR ROI 對價 淨值 股利 資本額".split(),
    "法務": "合約 契約 條款 股權 表決權 董事 關係人 訴訟 判決 裁定 違約 賠償 聲明與保證 章程 登記 專利 商標 著作 許可 執照 法規 競業 保密 質押 抵押 強制執行 假扣押 裁罰 優先承買 先決條件 交割 僵局".split(),
    "投資": "商業模式 市場 競爭 競品 產業 客戶 策略 綜效 退出 IPO 成長 產品 技術 團隊 通路 品牌 市占 護城河 動機 合作 營運".split(),
    "稽核": "授權 內控 稽核 異常 重述 矛盾 簽核 董事會 審計委員會 股東會 迴避 申報 公告 門檻".split(),
}
FORMAL = ["財報", "財務報告", "財務報表", "查核", "核閱", "會計師", "合約", "契約", "協議", "章程", "登記", "公示", "判決", "裁定", "股東名簿", "SPA", "公告", "年報", "估價報告", "法律意見"]
DECK = ["簡報", "pitch", "deck", "ppt", "提案", "公司簡介", "說明會", "介紹"]
ORAL = ["口頭", "訪談", "電話", "會議紀錄", "line", "微信", "聽說", "傳聞", "口述", "對話"]
HYP = re.compile(r"預計|預估|預期|預測|目標|假設|有望|可望|規劃|若.{0,12}(?:則|將)|推估|估計將")
CLAIM = re.compile(r"據稱|聲稱|號稱|宣稱|聽說|傳聞|口頭(?:表示|承諾|說明)|對方表示|管理層表示")
VAGUE = re.compile(r"約|大約|左右|大概|可能|應該|初步|尚未|據說|待確認|暫定|估計|或許|不排除")
SENT_END = re.compile(r"(?<=[。！？!?])\s*")


def _grade(name, text):
    n = name.lower()
    head = text[:600]
    if any(k.lower() in n for k in DECK):
        return "簡報/宣稱"
    if any(k.lower() in n for k in ORAL):
        return "口頭/未證實"
    if any(k.lower() in n for k in FORMAL):
        return "正式文件"
    if CLAIM.search(head) and not any(k in head for k in FORMAL):
        return "口頭/未證實"
    return "一般文件"


def _tags(text):
    scores = {d: sum(text.count(k) for k in ks) for d, ks in KW.items()}
    tags = [d for d, s in scores.items() if s >= 2 or (s >= 1 and len(text) < 120)]
    return tags or ["投資"]


def _md_table(rows):
    rows = [[("" if c is None else str(c).replace("\n", " ").strip()) for c in r] for r in rows if any(c not in (None, "") for c in r)]
    if not rows:
        return ""
    w = max(len(r) for r in rows)
    rows = [r + [""] * (w - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * w]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


# ------------------------------ 解析：檔案 → 區塊 ------------------------------
def _blocks_text(text):
    """文字/Markdown → 區塊：heading / table(含前導說明行) / para"""
    blocks, buf, heading, caption = [], [], None, None
    lines = text.replace("\r\n", "\n").split("\n")
    i = 0
    def flush():
        nonlocal buf
        if buf:
            blocks.append({"kind": "para", "text": "\n".join(buf).strip(), "heading": heading}); buf = []
    while i < len(lines):
        ln = lines[i]
        if re.match(r"^\s*\|.*\|\s*$", ln):
            cap = None
            if buf and len(buf[-1]) <= 60:
                cap = buf.pop()
            flush()
            tl = []
            while i < len(lines) and re.match(r"^\s*\|.*\|\s*$", lines[i]):
                tl.append(lines[i].strip()); i += 1
            blocks.append({"kind": "table", "text": ((cap + "\n") if cap else "") + "\n".join(tl), "heading": heading})
            continue
        if re.match(r"^\s{0,3}#{1,6}\s+\S", ln) or re.match(r"^\s*(?:第[一二三四五六七八九十\d]+[章節條]|[一二三四五六七八九十]+、)\s*\S{1,30}\s*$", ln):
            flush(); heading = re.sub(r"^\s*#+\s*", "", ln).strip(); i += 1; continue
        if not ln.strip():
            flush(); i += 1; continue
        buf.append(ln.strip()); i += 1
    flush()
    return blocks


def _read(name, data):
    ext = Path(name).suffix.lower()
    if isinstance(data, str):
        return [dict(b, loc=None) for b in _blocks_text(data)], None
    if ext in (".txt", ".md", ".markdown"):
        return _blocks_text(data.decode("utf-8", errors="replace")), None
    if ext == ".csv":
        txt = data.decode("utf-8-sig", errors="replace")
        return [{"kind": "table", "text": _md_table(list(csv.reader(io.StringIO(txt)))), "heading": None, "loc": "csv"}], None
    if ext in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        return [{"kind": "table", "text": _md_table([list(r) for r in ws.iter_rows(values_only=True)]), "heading": ws.title, "loc": f"sheet:{ws.title}"}
                for ws in wb.worksheets], None
    if ext == ".docx":
        import docx
        d = docx.Document(io.BytesIO(data)); blocks = []
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        heading = None; buf = []
        for el in d.element.body.iterchildren():
            if el.tag.endswith("}p"):
                p = Paragraph(el, d)
                if p.style is not None and p.style.name.lower().startswith(("heading", "標題")) and p.text.strip():
                    if buf: blocks.append({"kind": "para", "text": "\n".join(buf), "heading": heading}); buf = []
                    heading = p.text.strip()
                elif p.text.strip():
                    buf.append(p.text.strip())
                elif buf:
                    blocks.append({"kind": "para", "text": "\n".join(buf), "heading": heading}); buf = []
            elif el.tag.endswith("}tbl"):
                if buf: blocks.append({"kind": "para", "text": "\n".join(buf), "heading": heading}); buf = []
                t = Table(el, d)
                blocks.append({"kind": "table", "text": _md_table([[c.text for c in r.cells] for r in t.rows]), "heading": heading})
        if buf: blocks.append({"kind": "para", "text": "\n".join(buf), "heading": heading})
        return blocks, None
    if ext == ".pdf":
        import pdfplumber
        blocks, warn = [], None
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for pn, page in enumerate(pdf.pages, 1):
                try:
                    tbls = page.find_tables()
                except Exception:
                    tbls = []
                pg = page
                for t in tbls:
                    try: pg = pg.outside_bbox(t.bbox)
                    except Exception: pass
                txt = (pg.extract_text() or "").strip()
                for b in _blocks_text(txt): b["loc"] = f"p{pn}"; blocks.append(b)
                for t in tbls:
                    md = _md_table(t.extract())
                    if md: blocks.append({"kind": "table", "text": md, "heading": None, "loc": f"p{pn}"})
        if not blocks:
            warn = "PDF 未擷取到文字（可能是掃描檔，需 OCR）"
        return blocks, warn
    raise ValueError(f"不支援的檔案類型：{ext}")


# ------------------------------ 打包：區塊 → 切片 ------------------------------
def _sentences(text):
    out = []
    for para in text.split("\n"):
        out += [s for s in SENT_END.split(para) if s and s.strip()]
    return out


def _pack_prose(blocks_text):
    """把同一標題下的段落依句界打包；單句過長就整句保留，不切數字、不切斷句。"""
    chunks, cur = [], ""
    for s in _sentences(blocks_text):
        if cur and len(cur) + len(s) > PROSE_TARGET:
            chunks.append(cur.strip()); cur = ""
        cur += s
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def _split_table(text):
    if len(text) <= TABLE_HARD:
        return [text], False
    lines = text.split("\n")
    hdr_i = next((i for i, l in enumerate(lines) if l.strip().startswith("|")), 0)
    head, rows = lines[:hdr_i + 2], lines[hdr_i + 2:]
    parts, cur = [], []
    for r in rows:
        if sum(len(x) for x in cur) + len(r) > TABLE_HARD and cur:
            parts.append("\n".join(head + cur)); cur = []
        cur.append(r)
    if cur: parts.append("\n".join(head + cur))
    return parts, True


def chunk_sources(sources):
    """sources: [(檔名, bytes|str)]；回傳 (chunks, notes)。貼上文字請用 ('貼上文字_1', '內容')"""
    chunks, notes, n = [], [], 0
    for di, (name, data) in enumerate(sources, 1):
        try:
            blocks, warn = _read(name, data)
        except Exception as e:
            notes.append({"file": name, "error": f"{type(e).__name__}: {e}"}); continue
        if warn: notes.append({"file": name, "warning": warn})
        full = "\n".join(b["text"] for b in blocks)
        grade_doc = _grade(name, full)
        doc_id = f"D{di}"
        i = 0
        while i < len(blocks):
            b = blocks[i]
            if b["kind"] == "para":     # 合併同標題連續段落再依句界打包
                group = [b]
                while i + 1 < len(blocks) and blocks[i + 1]["kind"] == "para" and blocks[i + 1]["heading"] == b["heading"]:
                    i += 1; group.append(blocks[i])
                pieces = [(p, False, False) for p in _pack_prose("\n".join(g["text"] for g in group))]
            else:
                parts, split = _split_table(b["text"])
                pieces = [(p, True, split) for p in parts]
            for pi, (txt, is_tbl, tsplit) in enumerate(pieces, 1):
                n += 1
                loc = [x for x in (b.get("loc"), f"§{b['heading']}" if b.get("heading") else None) if x]
                loc.append(("表格" if is_tbl else "段落") + (f"（分段{pi}/{len(pieces)}）" if tsplit else ""))
                warnings, nature = [], "事實"
                grade = grade_doc
                if grade_doc == "一般文件" and CLAIM.search(txt):
                    grade = "口頭/未證實"
                sents = _sentences(txt) if not is_tbl else []
                hyp_n = sum(1 for x in sents if HYP.search(x))
                if sents and hyp_n * 2 >= len(sents):
                    nature = "假設/預測"
                elif CLAIM.search(txt) or grade in ("簡報/宣稱", "口頭/未證實"):
                    nature = "宣稱"
                elif hyp_n:
                    warnings.append(f"含 {hyp_n} 句預測/假設用語（事實抽取以句為單位判斷）")
                if grade == "簡報/宣稱": warnings.append("簡報來源，屬宣稱，未經證實，不得當作已落實事實")
                if grade == "口頭/未證實": warnings.append("口頭/未經證實說法，不得當作已落實事實")
                if nature == "假設/預測": warnings.append("本塊以預測/假設為主，非已發生事實")
                v = len(VAGUE.findall(txt))
                if v >= 2: warnings.append(f"含 {v} 處模糊用語（約/可能/初步/尚未…），數字與結論需再確認")
                if tsplit: warnings.append("表格過大已分段，表頭已重複，跨段加總需謹慎")
                if len(txt) < 25: warnings.append("內容過短，語意可能不完整")
                chunks.append({"chunk_id": f"C{n:03d}", "doc_id": doc_id, "source_file": name, "location": "｜".join(loc),
                               "heading": b.get("heading"), "text": txt, "is_table": is_tbl, "char_count": len(txt),
                               "domain_tags": _tags(txt), "evidence_grade": grade, "nature": nature,
                               "low_confidence": grade in ("簡報/宣稱", "口頭/未證實") or nature != "事實" or v >= 2, "warnings": warnings})
            i += 1
    return chunks, notes
