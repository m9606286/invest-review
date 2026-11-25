"""關係人／實質關係人初判（確定性、只看切片）。四態：明確涉及｜有疑似線索｜資料載明非關係人｜資料未載明。
僅限現有資料範圍；任何狀態都不得宣稱「絕對無關聯」，仍須與寶碩內部關係人名冊比對。"""
import re

POS = re.compile(r"(?:寶碩|投資方)[^。；\n]{0,20}?(?:關係人|實質關係人|關係企業|母公司|子公司|聯屬公司)|(?<![非不無])(?:為|係|屬於?)[^，。；\n]{0,15}(?:寶碩|投資方)[^，。；\n]{0,6}(?:關係人|關係企業|聯屬公司)|同一(?:集團|控制人|實質控制人)[^。；\n]{0,15}寶碩|寶碩[^。；\n]{0,15}同一(?:集團|控制人)")
SUSPECT = re.compile(r"關係人交易|(?:董事|監察人|經理人|負責人|大股東|股東)[^。；\n]{0,15}(?:相同|重疊|兼任|共同|同一)|配偶|二親等|三親等|親屬|姻親|兄弟|姊妹|父子|母子|共同(?:董事|股東|投資人)|(?:地址|住址|電話)[^。；\n]{0,8}(?:相同|一致)|(?:實質控制|實際控制)[^。；\n]{0,10}(?:同一|相同|相關)|關係[^。；\n]{0,6}(?:待確認|不明|尚不明確)")
NEG = re.compile(r"非(?:屬)?(?:本公司|寶碩)?(?:之)?(?:實質)?關係人|無(?:任何)?(?:實質)?關係人|與[^，。；\n]{0,12}(?:無|不具)(?:任何)?(?:關係|關聯)|不具(?:實質)?關係人身分|非關係企業")
OK_GRADES = ("正式文件", "一般文件")
STATUS_NOTE = "此判斷僅限於現有資料範圍，仍須與寶碩內部關係人名冊比對確認，不可據此宣稱與寶碩絕對無關聯。"


def _sents(text):
    return [s.strip() for s in re.split(r"(?<=[。！？!?；;])|\n", text) if s and s.strip()]


def assess(chunks):
    pos, sus, neg, neg_weak = [], [], [], []
    for c in chunks:
        for s in _sents(c["text"]):
            ev = {"chunk_id": c["chunk_id"], "snippet": s[:90], "grade": c["evidence_grade"]}
            if POS.search(s) and not NEG.search(s): pos.append(ev)
            elif NEG.search(s): (neg if c["evidence_grade"] in OK_GRADES else neg_weak).append(ev)
            elif SUSPECT.search(s): sus.append(ev)
    contradiction = bool(pos and neg)
    if pos:
        status, ev, note = "明確涉及", pos, "資料中已有明確的關係人/關係企業敘述。"
    elif sus:
        status, ev, note = "有疑似線索", sus, "資料出現疑似關聯線索，待確認交易對象是否為關係人或實質關係人。"
    elif neg:
        status, ev, note = "資料載明非關係人", neg, "正式/一般文件載明非關係人。"
    else:
        status, ev = "資料未載明", neg_weak
        note = "資料未載明；待確認交易對象是否為關係人或實質關係人。" + ("（僅有簡報/口頭宣稱為非關係人，不予採信）" if neg_weak else "")
    if contradiction:
        note += "【注意：不同切片對關係人身分敘述互相矛盾，需優先釐清】"
    return {"status": status, "evidence": ev[:6], "contradiction": contradiction, "note": note + STATUS_NOTE}


def to_facts(res, roster_result=None):
    """轉成登記表用的 legal.related_party_disclosure 與 tw.counterparty。
    roster_result：使用者與寶碩內部關係人名冊比對後的結果 None(尚未比對)｜"是"｜"否"。
    只有比對過(非None)才會把 substantive_checked 設為 True；資料判斷與名冊結果衝突時，從嚴採「是關係人」。"""
    st = res["status"]
    related = True if (st == "明確涉及" or roster_result == "是") else (False if (st == "資料載明非關係人" or roster_result == "否") else None)
    note = res["note"] + ("【名冊比對結果與資料判斷衝突，從嚴視為關係人】" if st == "明確涉及" and roster_result == "否" else "")
    disclosure = {"status": st, "roster_result": roster_result, "exists": related, "disclosed": None, "procedure_ok": None,
                  "evidence": res["evidence"], "note": note}
    cp = {"is_related": related, "substantive_checked": roster_result is not None, "is_domestic_gov": False,
          "is_group_internal": False, "status": st}
    return disclosure, cp
