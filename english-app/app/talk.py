"""AIとの英会話（Gemini）。"""
import uuid
from datetime import datetime

from . import gemini, store

TALK_SYSTEM = """You are a friendly English conversation partner for Shigeru, a Japanese adult whose English is lower-intermediate (understands about 30% of natural podcasts).
Rules:
- Speak natural, everyday spoken English. Keep each reply SHORT: 1-3 sentences, then ask one follow-up question.
- Use simple vocabulary but natural chunks (phrasal verbs, "kind of", etc.).
- Try to naturally create chances for him to use these target expressions: {targets}
- If his last message has a grammar mistake or sounds unnatural, give a corrected natural version. If it is fine, correction is null. Ignore missing punctuation/capitalization (it comes from speech recognition).
Return ONLY JSON:
{{"reply":"your reply","reply_ja":"natural Japanese translation of your reply","correction":null or {{"better":"more natural version of HIS sentence","note_ja":"短い日本語の説明"}},"used":["target expressions he used correctly in his last message"]}}"""


def start(body):
    theme = (body.get("theme") or "").strip() or "Free talk"
    targets = body.get("targets") or []
    if not targets:
        data = gemini.generate(
            f'Conversation theme: "{theme}". Suggest 3 useful natural spoken English expressions '
            'a learner could use when talking about this. Return JSON {"targets":[{"en":"...","ja":"意味"}]}',
            None, 1024, True)
        targets = data.get("targets", [])[:4]
    system = TALK_SYSTEM.format(targets=", ".join(t.get("en", "") for t in targets))
    first = gemini.generate(
        f'Start a casual conversation about this theme: "{theme}". (The theme may be written in Japanese.) '
        'Open with one friendly question. correction must be null and used must be [].',
        system, 1024, True)
    tid = datetime.now(store.JST).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    talk = {"id": tid, "theme": theme, "theme_id": body.get("theme_id"), "targets": targets,
            "started": store.now_iso(), "messages": [
                {"role": "ai", "en": first.get("reply", ""), "ja": first.get("reply_ja", "")}]}
    store.put(f"talk:{tid}", talk)
    p = store.progress()
    for t in p["themes"]:
        if t["id"] == body.get("theme_id"):
            t["count"] = t.get("count", 0) + 1
            t["last"] = store.today()
    store.save_progress(p)
    return talk


def reply(body):
    talk = store.get(f"talk:{body.get('id', '')}")
    if not talk:
        raise ValueError("会話が見つかりません")
    text = (body.get("text") or "").strip()
    if not text:
        raise ValueError("発言が空です")
    history = [{"role": "model" if m["role"] == "ai" else "user", "parts": [{"text": m["en"]}]}
               for m in talk["messages"]]
    if history and history[0]["role"] == "model":
        history.insert(0, {"role": "user", "parts": [{"text": f"(Let's talk about: {talk['theme']})"}]})
    system = TALK_SYSTEM.format(targets=", ".join(t.get("en", "") for t in talk["targets"]))
    res = gemini.generate(text, system, 1024, True, history=history)
    talk["messages"] += [
        {"role": "me", "en": text, "correction": res.get("correction") or None, "used": res.get("used") or []},
        {"role": "ai", "en": res.get("reply", ""), "ja": res.get("reply_ja", "")},
    ]
    store.put(f"talk:{talk['id']}", talk)
    return talk


def summaries():
    return [{"id": t["id"], "theme": t["theme"], "started": t["started"],
             "turns": sum(1 for m in t["messages"] if m["role"] == "me")} for t in store.list_talks()]
