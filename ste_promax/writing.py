"""Advisory STE-inspired prose counts; no semantic certification."""
import re


LIMITS = {"relaxed": 25, "procedure": 20, "description": 25}
LIMITATIONS = [
    "Advisory English word/sentence counts, not ASD certification or a score.",
    "Manual semantic review is required: no dictionary, noun, or causality analysis.",
    "Markdown and sentence boundaries are heuristic; uncommon abbreviations, tables, "
    "HTML, and complex nested Markdown may need manual counting.",
    "Hyphenated words and decimals count as one; code and URLs do not count. "
    "List items are separate paragraphs; unpunctuated prose counts as one sentence.",
]
URL = re.compile(r"(?:https?://|www\.)[^\s<>]+", re.I)
WORD = re.compile(r"[^\W_]+(?:[.'’\u2011-][^\W_]+)*", re.UNICODE)


def strip_frontmatter(text):
    return re.sub(r"\A\ufeff?---[ \t]*\r?\n.*?\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)",
                  "", text, count=1, flags=re.S)


def prose_paragraphs(text):
    lines = strip_frontmatter(text).splitlines()
    paragraphs, current = [], []
    fence = None

    def flush():
        if current:
            paragraphs.append(" ".join(current))
            current.clear()

    for index, line in enumerate(lines):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence:
            if re.fullmatch(r"\s{0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*", line):
                fence = None
            continue
        if marker:
            flush()
            fence = marker[1]
            continue
        if (not line.strip() or re.match(r"^\s{0,3}#{1,6}\s", line)
                or URL.fullmatch(line.strip().strip("<>"))
                or re.fullmatch(r"\s*(?:=+|-{3,})\s*", line)
                or (index + 1 < len(lines) and re.fullmatch(r"\s*(?:=+|-+)\s*", lines[index + 1]))):
            flush()
            continue
        line = re.sub(r"(`+)(.*?)\1", " ", line)
        line = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", line)
        # Discard URL internals, but retain terminal sentence punctuation.
        line = URL.sub(lambda m: re.search(r"[.!?]+$", m[0])[0]
                       if re.search(r"[.!?]+$", m[0]) else " ", line)
        item = re.match(r"^\s*(?:[-+*]|\d+[.)])\s+(?:\[[ xX]\]\s*)?", line)
        if item:
            flush()
            line = line[item.end():]
        if line.strip():
            current.append(line.strip())
    flush()
    return paragraphs


def sentences(text):
    # Protect common abbreviations, initials, and decimal points before splitting.
    protected = re.sub(r"\b(?:e\.g\.|i\.e\.|Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.|Sr\.|Jr\.|vs\.)",
                       lambda m: m[0].replace(".", "\u2024"), text, flags=re.I)
    protected = re.sub(r"\b(?:[A-Za-z]\.){2,}", lambda m: m[0].replace(".", "\u2024"), protected)
    protected = re.sub(r"\b[A-Z]\.(?=\s+[A-Z][a-z])", lambda m: m[0].replace(".", "\u2024"), protected)
    protected = re.sub(r"(?<=\d)\.(?=\d)", "\u2024", protected)
    return [part.replace("\u2024", ".").strip()
            for part in re.split(r'[.!?]+(?:["”’\')\]]*)(?:\s+|$)', protected)
            if WORD.search(part)]


def check_text(text, profile="relaxed"):
    findings = []
    total_words = total_sentences = total_paragraphs = 0
    for paragraph in prose_paragraphs(text):
        parts = sentences(paragraph)
        if not parts:
            continue
        total_paragraphs += 1
        total_sentences += len(parts)
        for number, sentence in enumerate(parts, 1):
            count = len(WORD.findall(sentence))
            total_words += count
            if count > LIMITS[profile]:
                findings.append({"kind": "sentence_length", "paragraph": total_paragraphs,
                                 "sentence": number, "word_count": count,
                                 "limit": LIMITS[profile], "text": sentence})
        if profile == "description" and len(parts) > 6:
            findings.append({"kind": "paragraph_length", "paragraph": total_paragraphs,
                             "sentence_count": len(parts), "limit": 6})
    return {"profile": profile, "sentence_word_limit": LIMITS[profile],
            "paragraph_sentence_limit": 6 if profile == "description" else None,
            "word_count": total_words, "sentence_count": total_sentences,
            "paragraph_count": total_paragraphs, "findings": findings,
            "limitations": LIMITATIONS}
