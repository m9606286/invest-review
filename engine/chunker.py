"""資料切片模組：支援一般文件、表格，並在 PDF 無文字層時自動以 Gemini 辨識掃描內容。"""
import csv
import io
import os
import re
from pathlib import Path

import pandas as pd
import pdfplumber
from google import genai
from google.genai import types

LOW_CONF_KEYWORDS = ("據稱", "口頭", "預計", "尚未確認", "初估", "草案", "擬", "待確認")
DEFAULT_OCR_MODEL = os.environ.get("GEMINI_OCR_MODEL", "gemini-3-flash-preview")


def _detect_domain(text: str) -> list[str]:
    tags = []
    if any(k in text for k in ("估值", "市占", "市場", "成長率", "商業模式", "競爭", "投資", "投報", "IRR", "ROI")):
        tags.append("投資")
    if any(k in text for k in ("財報", "營收", "毛利", "淨利", "現金流", "負債", "資產", "估價", "會計師", "CPA", "每股")):
        tags.append("財務")
    if any(k in text for k in ("合約", "契約", "法務", "訴訟", "智財", "專利", "商標", "關係人", "董事會", "股東會", "合規", "法規", "擔保")):
        tags.append("法務")
    if any(k in text for k in ("稽核", "內控", "授權", "憑證", "核決", "異常", "紀錄", "留存", "覆核")):
        tags.append("稽核")
    return tags or ["投資"]


def _assess_confidence(text: str, source_file: str, is_ocr: bool = False) -> tuple[bool, list[str], str]:
    warnings = []
    low = False
    matched = [w for w in LOW_CONF_KEYWORDS if w in text]
    if matched:
        low = True
        warnings.append(f"含不確定/口頭用語：{ '、'.join(matched[:4]) }")
    if "貼上文字" in source_file:
        warnings.append("來源為直接貼上文字，屬一般文件")
    if is_ocr:
        warnings.append("由 Gemini 辨識掃描 PDF 取得，建議核對關鍵數字與印章條款")
    grade = "C級（OCR/一般文件）" if (is_ocr or low or "貼上文字" in source_file) else "B級（結構化/文字檔）"
    return low, warnings, grade


def _ocr_pdf_with_gemini(pdf_bytes: bytes, filename: str) -> str:
    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("未設定 GEMINI_API_KEY，無法進行掃描 PDF OCR")
    client = genai.Client(api_key=api_key)
    prompt = (
        f"請完整辨識並轉錄這份掃描 PDF（檔名：{filename}）的所有文字、標題、表格與數字。"
        "請逐頁輸出，保留公司名稱、日期、金額、百分比、條款與印章/簽署備註；"
        "看不清楚的字請標示 [字跡模糊]，不要自行捏造。"
    )
    resp = client.models.generate_content(
        model=DEFAULT_OCR_MODEL,
        contents=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            prompt,
        ],
        config=types.GenerateContentConfig(temperature=0),
    )
    return (resp.text or "").strip()


def _extract_pdf_pages(raw_bytes: bytes, filename: str) -> tuple[list[tuple[str, str, bool]], str | None]:
    pages: list[tuple[str, str, bool]] = []
    has_any_text = False
    with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
        for idx, page in enumerate(pdf.pages, 1):
            txt = (page.extract_text() or "").strip()
            tables = page.extract_tables() or []
            table_lines = []
            for tbl in tables:
                for row in tbl:
                    cells = [(c or "").strip().replace("\n", " ") for c in row]
                    if any(cells):
                        table_lines.append(" | ".join(cells))
            merged = txt
            if table_lines:
                merged = (merged + "\n[表格]\n" + "\n".join(table_lines)).strip()
            if merged:
                has_any_text = True
            pages.append((f"第 {idx} 頁", merged, False))

    if has_any_text:
        return [(loc, txt, ocr) for loc, txt, ocr in pages if txt], None

    try:
        ocr_text = _ocr_pdf_with_gemini(raw_bytes, filename)
    except Exception as e:
        return [], f"PDF 未擷取到文字且 OCR 失敗：{e}"

    if not ocr_text:
        return [], "PDF 未擷取到文字（可能是空白頁或掃描檔 OCR 無輸出）"

    return [("全檔 OCR", ocr_text, True)], None


def _split_text_blocks(text: str, source_file: str, base_loc: str, is_ocr: bool, start_idx: int) -> list[dict]:
    blocks = [b.strip() for b in re.split(r"\n\s*\n+", text.strip()) if b.strip()]
    if not blocks and text.strip():
        blocks = [text.strip()]

    chunks = []
    cur_idx = start_idx
    for i, blk in enumerate(blocks, 1):
        low, warns, grade = _assess_confidence(blk, source_file, is_ocr=is_ocr)
        chunks.append({
            "chunk_id": f"C{cur_idx:03d}",
            "source_file": source_file,
            "location": f"{base_loc}・段落 {i}" if len(blocks) > 1 else base_loc,
            "evidence_grade": grade,
            "nature": "掃描辨識摘錄" if is_ocr else ("一般文字" if "貼上文字" in source_file else "文件段落"),
            "low_confidence": low,
            "warnings": warns,
            "domain_tags": _detect_domain(blk),
            "text": blk,
        })
        cur_idx += 1
    return chunks


def chunk_sources(sources: list[tuple[str, bytes | str]]) -> tuple[list[dict], list[dict]]:
    all_chunks: list[dict] = []
    notes: list[dict] = []
    seq = 1

    for fname, content in sources:
        ext = Path(fname).suffix.lower()
        try:
            if isinstance(content, str):
                text = content.strip()
                if not text:
                    notes.append({"file": fname, "warning": "內容為空"})
                    continue
                new_c = _split_text_blocks(text, fname, "貼上內容", is_ocr=False, start_idx=seq)
                all_chunks.extend(new_c)
                seq += len(new_c)
                continue

            raw = bytes(content)
            if ext in (".txt", ".md"):
                text = raw.decode("utf-8", errors="replace").strip()
                if not text:
                    notes.append({"file": fname, "warning": "檔案內容為空"})
                    continue
                new_c = _split_text_blocks(text, fname, "全文", is_ocr=False, start_idx=seq)
                all_chunks.extend(new_c)
                seq += len(new_c)

            elif ext == ".csv":
                text = raw.decode("utf-8-sig", errors="replace")
                rows = list(csv.reader(io.StringIO(text)))
                if not rows:
                    notes.append({"file": fname, "warning": "CSV 無資料"})
                    continue
                joined = "\n".join(" | ".join(c.strip() for c in r) for r in rows if any(c.strip() for c in r))
                new_c = _split_text_blocks(joined, fname, "CSV 表格", is_ocr=False, start_idx=seq)
                all_chunks.extend(new_c)
                seq += len(new_c)

            elif ext == ".xlsx":
                xl = pd.ExcelFile(io.BytesIO(raw), engine="openpyxl")
                added = 0
                for sheet in xl.sheet_names:
                    df = xl.parse(sheet).dropna(how="all")
                    if df.empty:
                        continue
                    txt = df.to_csv(sep="|", index=False).strip()
                    new_c = _split_text_blocks(txt, fname, f"工作表：{sheet}", is_ocr=False, start_idx=seq)
                    all_chunks.extend(new_c)
                    seq += len(new_c)
                    added += len(new_c)
                if added == 0:
                    notes.append({"file": fname, "warning": "Excel 工作表皆為空"})

            elif ext == ".pdf":
                pages, err = _extract_pdf_pages(raw, fname)
                if err:
                    notes.append({"file": fname, "error": err})
                    continue
                added = 0
                for loc, p_txt, is_ocr in pages:
                    new_c = _split_text_blocks(p_txt, fname, loc, is_ocr=is_ocr, start_idx=seq)
                    all_chunks.extend(new_c)
                    seq += len(new_c)
                    added += len(new_c)
                if added == 0:
                    notes.append({"file": fname, "warning": "PDF 無可用文字內容"})

            else:
                raise ValueError(f"不支援的檔案類型：{ext or '無副檔名'}")

        except Exception as e:
            notes.append({"file": fname, "error": f"{type(e).__name__}: {e}"})

    return all_chunks, notes
