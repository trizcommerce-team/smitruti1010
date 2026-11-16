"""댓글 여론 '최종 연동': admin 에서 체크한 항목만 셀러 캘린더 opinion.json 에 넣는다.
- admin 검토 대기 초안: https://trizcommerce.github.io/admin/drafts/<저장소>/opinion.json
- 체크 목록: 조회 기록 Apps Script  ?action=opinion_sync&repo=<저장소>  (admin 의 '최종 연동' 버튼이 보냄)
- 체크 목록이 지금 초안(at 같은 것)에 대한 것이면, 셀러 opinion.json 을 '초안에서 체크한 항목만'으로 바꾼다.
  체크를 다 뺀 묶음은 셀러 화면에서 빠진다(2026-11-16 재열님: 체크 해제가 반영 안 된다고 해서 바꿈).
build_app.py 가 빌드 때 부른다(실패해도 빌드는 계속). 바뀌면 GitHub Actions 가 opinion.json 을 커밋해 남긴다."""
import json, os, re, urllib.request
from pathlib import Path

ADMIN = "https://trizcommerce.github.io/admin/"
META = ("from", "to", "at", "note", "moodNote")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "calendar-build"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


MONTHS = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}


def _day(v):
    """'2026-11-12', 'at:2026-11-12', 'Thu Nov 12 2026 00:00:00 GMT+0900'(시트가 날짜로 바꾼 것) → '2026-11-12'"""
    s = str(v or "").replace("at:", "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    m = re.match(r"\w{3} (\w{3}) (\d{1,2}) (\d{4})", s)
    if m and m.group(1) in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"
    return s


def merge(live, draft, keys):
    """keys: ["headline:0", "loves:2", "changes", ...]
    셀러 캘린더 = 초안에서 '체크한 항목만'. 체크를 다 뺀 묶음은 셀러 화면에서 빠진다.
    기간·정리 날짜·안내 문구 같은 기본 정보(목록·묶음이 아닌 값)는 초안 그대로."""
    keys = set(keys)
    out = {}
    for sec, val in draft.items():
        if isinstance(val, list):
            picked = [it for i, it in enumerate(val) if f"{sec}:{i}" in keys]
            if picked:
                out[sec] = picked
        elif isinstance(val, dict):
            if sec in keys:                 # 예전 방식: 묶음 통째로
                out[sec] = val
            elif sec == "changes":          # 낱개 체크: changes:new:0, changes:deeper:2
                new = [x for i, x in enumerate(val.get("new") or []) if f"changes:new:{i}" in keys]
                deeper = [x for i, x in enumerate(val.get("deeper") or []) if f"changes:deeper:{i}" in keys]
                if new or deeper:
                    out[sec] = {k: v for k, v in val.items() if k not in ("new", "deeper")} | {"new": new, "deeper": deeper}
            elif sec == "iq":               # 낱개 체크: iq:mood, iq:replies, iq:questions, iq:ex:3
                iq = {k: val[k] for k in ("from", "to", "posts", "comments") if k in val}
                if "iq:mood" in keys:
                    iq.update({k: val[k] for k in ("mood", "counted", "entries") if k in val})
                if "iq:replies" in keys and "replies" in val:
                    iq["replies"] = val["replies"]
                q = val.get("questions") or {}
                ex = [e for i, e in enumerate(q.get("examples") or []) if f"iq:ex:{i}" in keys]
                if "iq:questions" in keys or ex:
                    iq["questions"] = ({k: v for k, v in q.items() if k != "examples"} if "iq:questions" in keys else {}) | {"examples": ex}
                if any(k in iq for k in ("mood", "replies", "questions")):
                    out[sec] = iq
        else:
            out[sec] = val
    if out.get("posts"):
        out["count"] = len(out["posts"])
        out["read"] = sum(int(p.get("n") or 0) for p in out["posts"])
    return out, bool(keys)


def apply(here: Path):
    repo = (os.environ.get("GITHUB_REPOSITORY") or "").split("/")[-1]
    if not repo:
        return False
    tpl = (here / "template.html").read_text(encoding="utf-8")
    m = re.search(r'const LOG_URL = "([^"]+)"', tpl)
    if not m:
        return False
    try:
        sel = _get(f"{m.group(1)}?action=opinion_sync&repo={repo}")
        if not sel or not sel.get("keys"):
            return False
        draft = _get(f"{ADMIN}drafts/{repo}/opinion.json")
    except Exception as e:
        print("opinion sync: skip", e)
        return False
    if _day(draft.get("at")) != _day(sel.get("draftAt")):
        print("opinion sync: 체크 목록이 지금 초안과 달라서 건너뜀")
        return False
    p = here / "opinion.json"
    live = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    if live.get("_synced") == sel.get("syncedAt"):
        return False                      # 이미 반영한 연동
    out, touched = merge(live, draft, sel["keys"])
    if not touched:
        return False
    out["_synced"] = sel.get("syncedAt")
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("opinion sync: 반영", len(sel["keys"]), "항목")
    return True
