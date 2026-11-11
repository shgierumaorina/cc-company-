"""区間分割と、Geminiによる要旨問題・表現・翻訳の作成。"""
from . import gemini, store


def split_sections(lines, minutes):
    target = minutes * 60
    sections, cur = [], []
    for ln in lines:
        cur.append(ln)
        length = cur[-1]["end"] - cur[0]["start"]
        sentence_end = ln["text"].rstrip().endswith((".", "?", "!", '"'))
        if (length >= target and sentence_end) or length >= target + 60:
            sections.append(cur)
            cur = []
    if cur:
        if sections and cur[-1]["end"] - cur[0]["start"] < 60:
            sections[-1].extend(cur)  # 短すぎる最後の区間は前に結合
        else:
            sections.append(cur)
    return [{"index": i, "start": s[0]["start"], "end": s[-1]["end"], "lines": s}
            for i, s in enumerate(sections)]


PREP_SYSTEM = (
    "You create listening-comprehension material for a Japanese adult learner of English "
    "(about 30% listening comprehension of natural podcasts). Write all Japanese naturally. "
    "Output only JSON."
)


def build_questions(sections):
    out = {}
    for b in range(0, len(sections), 6):
        text = "\n\n".join(f"### SECTION {s['index']}\n" + " ".join(l["text"] for l in s["lines"])
                           for s in sections[b:b + 6])
        prompt = (
            "For each section of this podcast transcript, return JSON:\n"
            '{"sections":[{"index":0,"topic_ja":"区間の話題（15字以内）",'
            '"summary_ja":"区間の要旨（60字以内）",'
            '"correct_ja":"正しい要旨の選択肢（30字以内）",'
            '"wrong_ja":["もっともらしい誤りの選択肢","もう1つ"],'
            '"chunks":[{"en":"phrasal verb or spoken chunk exactly as used","ja":"意味"}]}]}\n'
            "Rules: wrong choices must be plausible but clearly wrong for someone who understood. "
            "chunks: 3-5 phrasal verbs / idioms / colloquial chunks that a learner who knows individual "
            "words would still miss (e.g. 'end up', 'kind of', 'come about').\n\n" + text)
        data = gemini.generate(prompt, PREP_SYSTEM, max_tokens=8192, json_mode=True)
        for s in data.get("sections", []):
            out[int(s.get("index", -1))] = s
    return out


def translate_section(ep_id, idx):
    sections = store.get(f"ep:{ep_id}:sections", [])
    s = sections[idx]
    if all(l.get("ja") for l in s["lines"]):
        return s
    numbered = "\n".join(f"{i}: {l['text']}" for i, l in enumerate(s["lines"]))
    prompt = ("Translate each numbered line of this spoken English into natural Japanese. "
              'Return JSON {"ja":["...", ...]} with exactly one string per line, same order.\n\n' + numbered)
    ja = gemini.generate(prompt, None, max_tokens=8192, json_mode=True).get("ja", [])
    for i, l in enumerate(s["lines"]):
        if i < len(ja):
            l["ja"] = ja[i]
    store.put(f"ep:{ep_id}:sections", sections)
    return s
