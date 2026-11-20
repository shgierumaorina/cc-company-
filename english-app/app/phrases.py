"""日常会話フレーズ：区間からの抜き出し・フレーズ帳（間隔反復）・ロールプレイ会話。"""
import re
import uuid
from datetime import datetime, timedelta

from . import gemini, questions, store

PHRASES_VERSION = 1
INTERVALS = [1, 3, 7, 14, 30]  # 復習の間隔（日）。段階0-1:聞く、2-3:日本語→英語、4:場面→英語

SCENES = {
    "cafe": "ordering at a cafe / restaurant",
    "work": "small talk with a coworker at the office",
    "friend": "making plans with a friend",
    "shop": "shopping at a store",
    "street": "asking for or giving directions on the street",
    "meeting": "an online meeting with a colleague",
}

ROLEPLAY_RULES = """- This is a ROLE-PLAY. Scene: {scene}. You play the other person in this scene (a clerk, coworker, friend, stranger, etc.) and stay in character.
- Steer the situation so that he naturally NEEDS to say each target expression (e.g. create a moment to ask, request, react or refuse). Do not say the target expressions yourself first and do not tell him which one to use.
- When he has used all target expressions, wrap up the scene in a natural way and invite him to continue freely.
"""


def _day(offset=0):
    return (datetime.now(store.JST) + timedelta(days=offset)).strftime("%Y-%m-%d")


def _find_line(lines, quote):
    q = (quote or "").lower().strip(" .,!?\"'")
    if not q:
        return None
    for head in (q, " ".join(q.split()[:4])):  # AIが少し言い換えた場合は前半だけで探す
        for i, l in enumerate(lines):
            if head and head in l["text"].lower():
                return i
    return None


def extract(ep_id, idx, force=False):
    """区間から、日常会話でそのまま使えるフレーズを抜き出す（1区間1回だけAIを呼ぶ）。"""
    sections = questions.load_sections(ep_id)
    s = sections[idx]
    if s.get("phrases_v") == PHRASES_VERSION and not force:
        return s
    numbered = "\n".join(f"{i}: {l['text']}" for i, l in enumerate(s["lines"]))
    prompt = (
        "Below is a numbered section of a natural English podcast transcript. Pick the sentences or "
        "phrases that a Japanese adult learner (lower-intermediate) can reuse AS IS in everyday "
        "conversation: questions, requests, reactions, small talk, agreeing/disagreeing, polite refusals, "
        "checking understanding, etc. Skip podcast-specific talk (intros, ads, episode numbers). Return JSON:\n"
        '{"phrases":[{"line":0,"quote":"the exact words from that line (max 14 words)",'
        '"en":"reusable form of the phrase; use ~ for the part you can swap, e.g. Do you have ~ on you?",'
        '"ja":"自然な日本語訳","scene_ja":"どんな場面で使うか（30字以内）",'
        '"nuance_ja":"ニュアンス・似た表現との違い・注意点（60字以内）",'
        '"register":"カジュアル or ふつう or ていねい","alts":[{"en":"another natural way to say it","ja":"訳"}],'
        '"task_ja":"このフレーズを自分で言う練習用の場面設定。答えの英語は書かない（例：会議中、隣の同僚にペンを持っていないか聞きたい。何と言う？）"}]}\n'
        "Rules: 3-6 items, most useful first. alts: 1-2 items. If the section has nothing usable in daily "
        "conversation, take a useful sentence pattern from it instead (quote must still be the exact words).\n\n"
        + numbered)
    data = gemini.generate(prompt, questions.PREP_SYSTEM, max_tokens=8192, json_mode=True)
    out, seen = [], set()
    for p in data.get("phrases") or []:
        if not isinstance(p, dict) or not isinstance(p.get("en"), str) or p["en"].lower().strip() in seen:
            continue
        p["quote"] = p.get("quote") if isinstance(p.get("quote"), str) else ""
        seen.add(p["en"].lower().strip())
        li = p.get("line")
        ok = isinstance(li, int) and 0 <= li < len(s["lines"])
        if not ok or (p.get("quote") and p["quote"].lower()[:20] not in s["lines"][li]["text"].lower()):
            found = _find_line(s["lines"], p.get("quote"))
            li = found if found is not None else (li if ok else None)
        p["line"] = li
        p["alts"] = [a for a in (p.get("alts") or []) if isinstance(a, dict) and a.get("en")][:2]
        out.append(p)
    if not out:
        raise gemini.GeminiError("フレーズを作れませんでした。もう一度お試しください")
    return questions.update_section(ep_id, idx, lambda sec: sec.update(phrases=out, phrases_v=PHRASES_VERSION))


def save(pr, b):
    """区間のフレーズ（b["i"]番目）をフレーズ帳に入れる。同じ英語は1つだけ。"""
    ep, idx = b["ep"], int(b["idx"])
    s = questions.load_sections(ep)[idx]
    ph = b.get("phrase") if isinstance(b.get("phrase"), dict) and b["phrase"].get("en") else None
    if not ph:  # 画面が持っているフレーズを優先し、無ければ保存済みの番号から探す
        lst = s.get("phrases") or []
        i = int(b.get("i", -1))
        if not 0 <= i < len(lst):
            raise ValueError("フレーズが見つかりません。画面を開き直してください")
        ph = lst[i]
    if any(x["en"].lower().strip() == ph["en"].lower().strip() for x in pr["phrases"]):
        return
    li = ph.get("line")
    ln = s["lines"][li] if isinstance(li, int) and 0 <= li < len(s["lines"]) else None
    pr["phrases"].append({
        "id": uuid.uuid4().hex[:10], "en": ph["en"], "ja": ph.get("ja", ""), "quote": ph.get("quote", ""),
        "scene_ja": ph.get("scene_ja", ""), "nuance_ja": ph.get("nuance_ja", ""),
        "register": ph.get("register", ""), "alts": ph.get("alts") or [], "task_ja": ph.get("task_ja", ""),
        "ep": ep, "idx": idx, "line": li, "start": ln["start"] if ln else None, "end": ln["end"] if ln else None,
        "context": ln["text"] if ln else "", "added": store.today(), "due": _day(1), "stage": 0,
        "reviews": 0, "used_count": 0})


def answer(pr, pid, ok):
    it = by_id(pr, pid)
    if not it:
        return
    if ok:
        it["stage"] = it.get("stage", 0) + 1
        if it["stage"] >= len(INTERVALS):
            it["done"] = True
        else:
            it["due"] = _day(INTERVALS[it["stage"]])
    else:  # 忘れていたら1段階戻して明日もう一度
        it["stage"], it["due"] = max(0, it.get("stage", 0) - 1), _day(1)
    it["reviews"] = it.get("reviews", 0) + 1
    it["last_review"] = store.today()


def by_id(pr, pid):
    return next((x for x in pr.get("phrases", []) if x["id"] == pid), None)


def _norm(s):
    s = re.sub(r"[~〜…]|\(.*?\)|\bsomeone\b|\bsomething\b|\bsb\b|\bsth\b", " ", (s or "").lower())
    return " ".join(re.sub(r"[^a-z' ]+", " ", s).split())


def match_targets(used, targets):
    """AIが返した「使えた表現」を、目標表現の文字列にそろえる（表記ゆれ対策）。"""
    out = []
    for t in targets:
        tn = _norm(t.get("en"))
        parts = [_norm(x) for x in re.split(r"~|〜", t.get("en") or "") if _norm(x)]
        for u in used or []:
            un = _norm(u)
            if tn and un and (un == tn or (len(un) >= 4 and (un in tn or tn in un))
                              or (len(parts) > 1 and all(x in un for x in parts))):
                out.append(t["en"])
                break
    return out


def count_usage(talk, used):
    """保存したフレーズを会話で使えたら記録する（同じ会話では1回だけ数える）。"""
    already = {u for m in talk["messages"] for u in (m.get("used") or [])}
    pids = [t["pid"] for t in talk["targets"] if t.get("pid") and t["en"] in used and t["en"] not in already]
    if not pids:
        return
    pr = store.progress()
    for pid in pids:
        ph = by_id(pr, pid)
        if ph:
            ph["used_count"], ph["last_used"] = ph.get("used_count", 0) + 1, store.today()
    store.save_progress(pr)


def roleplay_start(body, talk_system):
    pr = store.progress()
    phs = [x for x in (by_id(pr, pid) for pid in (body.get("phrase_ids") or [])) if x][:4]
    if not phs:
        raise ValueError("練習するフレーズを選んでください")
    targets = [{"en": x["en"], "ja": x.get("ja", ""), "pid": x["id"]} for x in phs]
    tlist = ", ".join(t["en"] for t in targets)
    scene = SCENES.get(body.get("scene") or "", "")
    ask = (f'Scene: "{scene}".' if scene else
           f"Choose ONE everyday scene where all of these expressions would naturally be needed ({tlist}).")
    first = gemini.generate(
        f"{ask} Start a role-play: briefly set the scene in character and open with one line that leads him "
        'toward the first target expression. Return ONLY JSON {"scene":"the scene in short English",'
        '"scene_ja":"場面の短い日本語説明（25字以内）","reply":"your first line","reply_ja":"その日本語訳"}',
        talk_system.format(targets=tlist, extra=ROLEPLAY_RULES.format(scene=scene or "(you choose)")),
        1024, True)
    scene = scene or first.get("scene") or "everyday conversation"
    tid = datetime.now(store.JST).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    talk = {"id": tid, "mode": "roleplay", "scene": scene,
            "theme": f"ロールプレイ：{first.get('scene_ja') or scene}", "targets": targets,
            "started": store.now_iso(), "messages": [
                {"role": "ai", "en": first.get("reply", ""), "ja": first.get("reply_ja", "")}]}
    store.put(f"talk:{tid}", talk)
    return talk
