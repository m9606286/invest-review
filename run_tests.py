import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from engine.rules import evaluate, LIGHT_ORDER, validate_case, load_yaml
AUTH = load_yaml("authority.yaml")
def run(t, ag=None):
    return evaluate(t["case"], ag if ag is not None else t["agents"], t["review_state"], authority={**AUTH, **t.get("authority_override", {})}, company=t.get("company"))

files = sorted((Path(__file__).parent / "tests/cases").glob("*.json"))
fails, rows = 0, []
for f in files:
    t = json.loads(f.read_text(encoding="utf-8"))
    r = run(t)
    e = t["expect"]
    unmet = sorted(o["id"] for o in r["tw_obligations"] if o["status"] == "未規劃")
    post = [o["id"] for o in r["post_decision_obligations"]]
    ok = (r["rule_light"] == e["rule_light"] and r["final_light"] == e["final_light"]
          and r["triggered_rules"] == sorted(e["rules"]) and sorted(r["missing_fields"]) == sorted(e["missing"])
          and (("override_blocked" not in e) or r["ai_override_blocked"] == e["override_blocked"])
          and (("tw_unmet" not in e) or unmet == e["tw_unmet"])
          and (("post" not in e) or post == e["post"]))
    if not ok: print("  >> unmet:", unmet, "post:", post)
    fails += (not ok)
    rows.append((t["name"], e["final_light"], r["final_light"], ",".join(r["triggered_rules"]) or "-", "PASS" if ok else "FAIL"))
    if not ok:
        print("FAIL detail:", t["name"], json.dumps(r, ensure_ascii=False, indent=1))

print(f"{'case':32}{'預期':4}{'實際':4}  觸發規則        結果")
for n, ex, ac, rl, st in rows:
    print(f"{n:32}{ex:4}{ac:4}  {rl:14}{st}")

# 驗收 2：不變式 —— 對每個案件、每種 AI 建議，final 都不得低於 rule_light；規則紅燈則永遠紅燈
viol = 0
for f in files:
    t = json.loads(f.read_text(encoding="utf-8"))
    for rec in ("推進", "有條件推進", "暫緩"):
        ag = json.loads(json.dumps(t["agents"]))
        if ag.get("audit"): ag["audit"]["ai_recommendation"] = rec
        r = run(t, ag)
        if LIGHT_ORDER[r["final_light"]] < LIGHT_ORDER[r["rule_light"]]: viol += 1
        if r["rule_light"] == "紅" and r["final_light"] != "紅": viol += 1
print(f"\n不變式檢查：{len(files)*3} 組(案件×AI建議)，違規 {viol} 組")

# 基準案的 schema 結構自檢
base = json.loads(files[0].read_text(encoding="utf-8"))["case"]
assert validate_case(base) == [], validate_case(base)
bad = json.loads(json.dumps(base)); bad["version"] = 2   # v2 必須有 prev_version_ref
print("v2 缺 prev_version_ref 被擋：", bool(validate_case(bad)))
print(f"\n總結：{len(files)-fails}/{len(files)} 通過，不變式違規 {viol}")
sys.exit(1 if fails or viol else 0)
