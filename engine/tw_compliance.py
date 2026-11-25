"""公開發行公司取得或處分資產處理準則（取處準則）確定性檢查。

依據：全國法規資料庫「公開發行公司取得或處分資產處理準則」（法規整編資料截至115/11/13，最近修正114/07/24）。
v1 涵蓋：第5、8、9、10、11、14、15、16、18(觸發判斷)、23、31、35 條。
v1 不涵蓋（遇到一律 R9 紅燈要求人工覆核）：衍生性商品、金融機構債權、大陸地區投資、營建業專案、其他重要資產。
※ 本模組是決策輔助的『前置條件檢查』，不構成法律意見；條文以主管機關公布為準。
"""
from datetime import date

OK, PENDING, NONE = "已具備", "待辦", "未規劃"
SUPPORTED = {"有價證券", "不動產", "設備", "使用權資產", "無形資產", "會員證", "併購"}
REAL_ESTATE_LIKE = {"不動產", "使用權資產"}
PROFILE_REQ = ["is_public_offering", "paid_in_capital", "par_value", "total_assets",
               "has_audit_committee", "has_independent_directors", "is_professional_investor"]


def _val(facts, key):
    f = facts.get(key)
    if f is None or f.get("label") == "缺漏" or f.get("value") in (None, "", [], {}):
        return None
    return f["value"]


def _isnum(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _months(d1, d2):
    return (d2.year - d1.year) * 12 + (d2.month - d1.month) - (1 if d2.day < d1.day else 0)


def thresholds(company):
    """第35條：面額非10元者，以歸屬母公司業主權益換算（權益10% ≙ 實收資本額20%）。"""
    eff_cap = company["paid_in_capital"] if company["par_value"] == 10 else company["parent_equity"] / 2
    return {
        "eff_cap": eff_cap,
        "t_gen": min(0.2 * eff_cap, 300_000_000),                       # 實收資本額20% 或 3億（取低者先到）
        "ta10": 0.1 * company["total_assets"],                          # 總資產10%
        "t_rel": min(0.2 * eff_cap, 0.1 * company["total_assets"], 300_000_000),
    }


def check_tw(facts, company, authority):
    hits, obs, post = [], [], []

    def hit(rule, light, detail):
        hits.append({"rule": rule, "light": light, "detail": detail})

    # ---- 寶碩基本資料 ----
    company = company or {}
    miss = [k for k in PROFILE_REQ if company.get(k) is None]
    if company.get("par_value") not in (None, 10) and company.get("parent_equity") is None:
        miss.append("parent_equity")
    if miss:
        hit("R9", "紅", "寶碩基本資料缺漏，無法判定取處準則門檻：" + "、".join(miss))
        return hits, obs, post
    if company["is_public_offering"] is not True:
        hit("R9", "紅", "寶碩資料顯示非公開發行公司，取處準則適用性需人工確認")
        return hits, obs, post

    if company.get("total_assets_basis", "個體") != "個體":
        hit("Y8", "黃", f"寶碩總資產目前採「{company['total_assets_basis']}」數；第35條規定應採最近期個體財報總資產，門檻（總資產10%）須以個體數覆核")

    # ---- 案件輸入 ----
    asset, direction, cp = _val(facts, "tw.asset_type"), _val(facts, "tw.direction"), _val(facts, "tw.counterparty")
    gaps = [k for k, v in (("tw.asset_type", asset), ("tw.direction", direction), ("tw.counterparty", cp)) if v is None]
    if gaps:
        hit("R9", "紅", "取處準則判定所需欄位缺漏：" + "、".join(gaps))
        return hits, obs, post
    flags = _val(facts, "tw.asset_flags") or {}
    procs = _val(facts, "tw.procedures") or {}
    if asset not in SUPPORTED or flags.get("is_mainland_investment") or flags.get("construction_industry"):
        hit("R9", "紅", f"資產類型/情境（{asset}）超出規則庫 v1 涵蓋範圍，須人工逐條覆核取處準則")
        return hits, obs, post
    nums = [x for x in [(_val(facts, "tw.amounts") or {}).get("single"),
                        (_val(facts, "tw.amounts") or {}).get("cum_same_counterparty_1y"),
                        (_val(facts, "tw.amounts") or {}).get("cum_same_asset_1y"),
                        _val(facts, "financial.investment_amount")] if _isnum(x)]
    if not nums:
        hit("R9", "紅", "缺交易金額，無法依第31條第2項計算取處準則交易金額")
        return hits, obs, post
    amount = max(nums)  # 單筆 / 一年內同一相對人同性質 / 同一標的累積，取最大者（輸入應已扣除「已公告部分」）
    t = thresholds(company)
    related = cp.get("is_related") is True
    if cp.get("substantive_checked") is not True:
        hit("R9", "紅", "尚未完成關係人『實質關係』判斷（第14條第3項），無法確認是否適用關係人交易規定")

    def need(oid, article, text, key=None):
        st = procs.get(key or oid, NONE)
        st = st if st in (OK, PENDING) else NONE
        obs.append({"id": oid, "article": article, "requirement": text, "status": st})
        if st == NONE:
            hit("R9", "紅", f"{article}：{text}（缺漏/未規劃）")
        elif st == PENDING:
            hit("Y7", "黃", f"{article}：{text}（待辦，須於簽約/付款前完成）")

    def derived(oid, article, text, ok):
        obs.append({"id": oid, "article": article, "requirement": text, "status": OK if ok else NONE})
        if not ok:
            hit("R9", "紅", f"{article}：{text}（不符）")

    expert = False
    is_gov = cp.get("is_domestic_gov") is True
    active = flags.get("active_quote") is True

    # ---- 第9條 不動產/設備/使用權資產：估價報告 ----
    if (asset in ("不動產", "設備", "使用權資產") and not is_gov and not flags.get("self_or_lease_build")
            and not (asset in ("設備", "使用權資產") and flags.get("for_business_use")) and amount >= t["t_gen"]):
        expert = True
        need("appraisal_report", "第9條", "事實發生日前須取得專業估價者出具之估價報告")
        ap = _val(facts, "tw.appraisals")
        if ap and ap.get("values"):
            vals = ap["values"]
            if amount >= 1_000_000_000:
                derived("second_appraisal", "第9條第2款", "交易金額達10億元以上須二家以上專業估價者", len(vals) >= 2)
            gap = any(abs(v - amount) / amount >= 0.2 for v in vals) or (len(vals) >= 2 and (max(vals) - min(vals)) / amount >= 0.1)
            one_sided = (direction == "取得" and all(v > amount for v in vals)) or (direction == "處分" and all(v < amount for v in vals))
            if gap and not one_sided:
                need("cpa_opinion_appraisal_gap", "第9條第3款", "估價與交易金額差距≥20%或估價間差距≥10%，須會計師就差異原因及價格允當性表示意見")
            if ap.get("report_date") and ap.get("contract_date"):
                m = _months(date.fromisoformat(ap["report_date"]), date.fromisoformat(ap["contract_date"]))
                if m <= 3:
                    derived("appraisal_date_validity", "第9條第4款", "估價報告日期與契約成立日不得逾三個月", True)
                elif ap.get("same_announced_value_6m") and m <= 6:
                    need("appraiser_opinion_letter", "第9條第4款", "逾三個月但適用同一期公告現值且未逾六個月，須由原估價者出具意見書")
                else:
                    derived("appraisal_date_validity", "第9條第4款", "估價報告日期與契約成立日不得逾三個月", False)
            if ap.get("special_price") or flags.get("special_price"):
                need("special_price_board_approval", "第9條第1款", "以限定/特定/特殊價格為參考依據須先經董事會決議")
        elif procs.get("appraisal_report") == OK:
            hit("Y7", "黃", "第9條：標示估價報告已具備，但未提供估價數據，無法驗證差距/期限/家數")

    # ---- 第10條 有價證券 ----
    if asset == "有價證券" and not active:
        expert = expert or amount >= t["t_gen"]
        need("target_fs_reviewed", "第10條", "須取具標的公司最近期經會計師查核簽證或核閱之財務報表作價格參考")
        if amount >= t["t_gen"]:
            need("cpa_price_opinion", "第10條", "交易金額達門檻，事實發生日前須洽請會計師就交易價格合理性表示意見")

    # ---- 第11條 無形資產/會員證 ----
    if asset in ("無形資產", "會員證") and not is_gov and amount >= t["t_gen"]:
        expert = True
        need("cpa_price_opinion", "第11條", "交易金額達門檻，事實發生日前須洽請會計師就交易價格合理性表示意見")

    # ---- 第23條 合併/分割/收購/股份受讓 ----
    if asset == "併購" and not flags.get("is_100pct_subsidiary_merger"):
        expert = True
        need("merger_expert_opinion", "第23條", "董事會決議前須委請會計師/律師/承銷商就換股比例或收購價格合理性表示意見")

    # ---- 第14~18條 關係人交易 ----
    exempt = flags.get("exempt_category") is True  # 國內公債/附買回賣回債券/國內貨幣市場基金
    trigger15 = False
    if related:
        re_like = asset in REAL_ESTATE_LIKE
        trigger15 = (not exempt) and (re_like or amount >= t["t_rel"])
        if amount >= t["ta10"]:
            expert = True
            need("related_valuation_or_cpa", "第14條", "關係人交易達總資產10%以上，須取得專業估價報告或會計師意見")
        if trigger15:
            need("related_pack", "第15條", "須備齊目的必要性、選定關係人原因、原取得資訊、現金收支預測、專家意見、限制條件等資料")
            if amount >= t["ta10"] and not cp.get("is_group_internal"):
                need("shareholder_approval", "第15條末項", "達總資產10%以上須提股東會同意後始得簽約付款")
        if re_like and direction == "取得":
            expert = True
            need("related_cost_cpa_review", "第16條", "向關係人取得不動產/使用權資產，成本合理性評估須洽請會計師複核")
            if flags.get("related_cost_eval_below_price") and not flags.get("related_exception_evidence"):
                hit("R9", "紅", "第17/18條：成本評估結果均低於交易價格且無客觀證據，將觸發特別盈餘公積/股東會程序，須人工覆核")

    # ---- 第5條 專家獨立性 ----
    if expert:
        need("expert_independence", "第5條", "估價師/會計師/律師/承銷商須與交易當事人無關係人或實質關係，且無相關前科")

    # ---- 第8條/第15條 董事會、審計委員會 ----
    material_thr = authority.get("material_transaction_threshold_ntd") or t["t_gen"]
    if asset == "併購" or amount >= material_thr or trigger15 or flags.get("special_price"):
        need("board_approval", "第8條", "重大資產交易須經董事會決議（關係人交易須於簽約及付款前）")
        if company["has_audit_committee"]:
            need("audit_committee_approval", "第8/15條", "須先經審計委員會全體成員1/2以上同意並提董事會決議")
        if company["has_independent_directors"]:
            need("independent_director_minutes", "第8條", "須充分考量獨立董事意見，反對/保留意見載明議事錄")
    else:
        need("chairman_approval", "寶碩處理程序", "未達董事會門檻之交易須上簽董事長核准")

    # ---- 第31條 事後公告申報（資訊型，不影響燈號） ----
    clause = None
    if related and not exempt and (asset in REAL_ESTATE_LIKE or amount >= t["t_rel"]):
        clause = "第31條第1項第1款（關係人交易）"
    elif asset == "併購":
        clause = "第31條第1項第2款（合併/分割/收購/股份受讓）"
    elif asset in ("設備", "使用權資產") and flags.get("for_business_use") and not related:
        c = t["eff_cap"]
        lim = 500_000_000 if c < 10_000_000_000 else (1_000_000_000 if c < 50_000_000_000 else 0.05 * c)
        if amount >= lim:
            clause = "第31條第1項第4款（供營業使用設備）"
    elif not (exempt or (company["is_professional_investor"] and asset == "有價證券" and active)) and amount >= t["t_gen"]:
        clause = "第31條第1項第8款（其他資產交易）"
    if clause:
        post.append({"id": "disclosure", "article": clause,
                     "requirement": "事實發生之即日起算二日內於主管機關指定網站公告申報；契約/內容變更或終止亦須二日內公告（第32條）"})
    post.append({"id": "retention", "article": "第31條末項",
                 "requirement": "相關契約、議事錄、備查簿、估價報告及專家意見書須備置於公司至少五年"})
    return hits, obs, post
