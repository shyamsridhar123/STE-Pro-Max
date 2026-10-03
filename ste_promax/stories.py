"""Evidence-linked story validation and companion formats; no model or network calls."""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

PURPOSES = {
    "explanation": "Question, concrete example, mechanism, and a check of understanding.",
    "decision-brief": "Decision question, evidence, options or proposal, and unresolved conditions.",
    "research-digest": "Research question, attributed findings, limits, and implications.",
    "incident-review": "Observed sequence, evidence, hypotheses, and corrective proposals without invented closure.",
}
CLAIM_TYPES = ("observation", "attribution", "inference", "proposal")
_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_INVALID_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")

STORY_SCHEMA = {
    "description": "An evidence-linked story with reader-controlled beats and complete source/claim ledgers.",
    "fields": {
        "version": "Required integer 1.",
        "title": "Required story title.",
        "audience": "Required intended audience; not inferred by the renderer.",
        "question": "Required question the story answers.",
        "purpose": "explanation, decision-brief, research-digest, or incident-review.",
        "summary": "Required source-grounded bottom line.",
        "context": "Optional context; label fictional or simulated examples.",
        "sources": "Up to 100 sources: {id,title,url?,locator?,note?}. URLs are not fetched.",
        "claims": "Up to 200 claims: {id,type,text,source_ids,scope?,uncertainty?,attributed_to?,basis?}.",
        "beats": "1–32 beats: {id,title,role?,text?,claim_ids,narration?,visual?,question?}.",
        "limitations": "Optional list of material story-level limitations; always displayed.",
    },
    "example": {
        "kind": "story", "version": 1, "title": "A check is not an approval",
        "audience": "A delivery team", "question": "Can this fictional release proceed?",
        "purpose": "decision-brief", "summary": "Validation passed; approval is still pending.",
        "context": "Illustrative scenario, not a live release.",
        "sources": [{"id": "notes", "title": "Fictional release notes", "note": "Provided example."}],
        "claims": [
            {"id": "validation", "type": "observation", "text": "The validation checks passed.",
             "source_ids": ["notes"], "scope": "The tested build only."},
            {"id": "approval", "type": "observation", "text": "Release approval is pending.",
             "source_ids": ["notes"], "uncertainty": "No approval date is supplied."},
        ],
        "beats": [
            {"id": "checks", "title": "What passed", "claim_ids": ["validation"]},
            {"id": "gate", "title": "What remains", "claim_ids": ["approval"],
             "question": {"prompt": "Does a passed test authorize a release?",
                          "answer": "No. The source says approval remains pending."}},
        ],
        "limitations": ["This example supplies no production-readiness or authorization evidence."],
    },
}


def _record(value, fields, path):
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    for key in value:
        if key not in fields:
            raise ValueError(f"{path}.{key}: unsupported field")
    return value


def _text(value, path, *, required=False):
    if not isinstance(value, str) or _INVALID_TEXT.search(value):
        raise ValueError(f"{path}: expected valid plain text")
    if required and not value.strip():
        raise ValueError(f"{path}: must not be empty")
    if len(value) > 12000:
        raise ValueError(f"{path}: text exceeds 12000 characters; split the material explicitly")


def _identifier(value, path):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{path}: use a unique lowercase identifier, up to 64 characters")


def _list(value, path, limit, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= limit:
        raise ValueError(f"{path}: expected a list of {minimum}–{limit} items")
    return value


def _references(value, known, path, required=False):
    values = _list(value, path, 200, int(required))
    seen = set()
    for index, item in enumerate(values):
        _identifier(item, f"{path}[{index}]")
        if item not in known:
            raise ValueError(f"{path}[{index}]: unknown reference {item!r}")
        if item in seen:
            raise ValueError(f"{path}[{index}]: duplicate reference {item!r}")
        seen.add(item)


def validate_story(story, location="story"):
    """Validate structure and traceability, not the truth or adequacy of evidence."""
    _record(story, {"kind", *STORY_SCHEMA["fields"]}, location)
    if "kind" in story and story["kind"] != "story":
        raise ValueError(f"{location}.kind: expected 'story'")
    if type(story.get("version")) is not int or story["version"] != 1:
        raise ValueError(f"{location}.version: supported story format is integer 1")
    for field in ("title", "audience", "question", "summary"):
        _text(story.get(field), f"{location}.{field}", required=True)
    if not isinstance(story.get("purpose"), str) or story["purpose"] not in PURPOSES:
        raise ValueError(f"{location}.purpose: choose {', '.join(PURPOSES)}")
    if "context" in story:
        _text(story["context"], f"{location}.context")
    source_ids = set()
    for index, source in enumerate(_list(story.get("sources"), f"{location}.sources", 100)):
        path = f"{location}.sources[{index}]"
        _record(source, {"id", "title", "url", "locator", "note"}, path)
        _identifier(source.get("id"), path + ".id")
        if source["id"] in source_ids:
            raise ValueError(f"{path}.id: duplicate source {source['id']!r}")
        source_ids.add(source["id"])
        _text(source.get("title"), path + ".title", required=True)
        for field in ("locator", "note"):
            if field in source:
                _text(source[field], path + "." + field)
        if "url" in source:
            _text(source["url"], path + ".url", required=True)
            try:
                url = urlsplit(source["url"])
                valid = (url.scheme in ("http", "https") and bool(url.netloc)
                         and not url.username and not url.password and url.port != 0
                         and not re.search(r"[\s\\]", source["url"]))
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(f"{path}.url: use an HTTP(S) source URL without credentials")
    claim_ids = set()
    claim_fields = {"id", "type", "text", "source_ids", "scope", "uncertainty", "attributed_to", "basis"}
    for index, claim in enumerate(_list(story.get("claims"), f"{location}.claims", 200)):
        path = f"{location}.claims[{index}]"
        _record(claim, claim_fields, path)
        _identifier(claim.get("id"), path + ".id")
        if claim["id"] in claim_ids:
            raise ValueError(f"{path}.id: duplicate claim {claim['id']!r}")
        claim_ids.add(claim["id"])
        if claim.get("type") not in CLAIM_TYPES:
            raise ValueError(f"{path}.type: choose {', '.join(CLAIM_TYPES)}")
        _text(claim.get("text"), path + ".text", required=True)
        _references(claim.get("source_ids"), source_ids, path + ".source_ids",
                    required=claim["type"] != "proposal")
        for field in ("scope", "uncertainty", "attributed_to", "basis"):
            if field in claim:
                _text(claim[field], path + "." + field)
        if claim["type"] == "attribution":
            _text(claim.get("attributed_to"), path + ".attributed_to", required=True)
        if claim["type"] == "inference":
            _text(claim.get("basis"), path + ".basis", required=True)
    beat_ids = set()
    beat_fields = {"id", "title", "role", "text", "claim_ids", "narration", "visual", "question"}
    for index, beat in enumerate(_list(story.get("beats"), f"{location}.beats", 32, 1)):
        path = f"{location}.beats[{index}]"
        _record(beat, beat_fields, path)
        _identifier(beat.get("id"), path + ".id")
        if beat["id"] in beat_ids:
            raise ValueError(f"{path}.id: duplicate beat {beat['id']!r}")
        beat_ids.add(beat["id"])
        _text(beat.get("title"), path + ".title", required=True)
        _references(beat.get("claim_ids"), claim_ids, path + ".claim_ids")
        for field in ("role", "text", "narration"):
            if field in beat:
                _text(beat[field], path + "." + field)
        if "visual" in beat:
            visual = beat["visual"]
            if not isinstance(visual, dict) or visual.get("kind") not in ("diagram", "chart"):
                raise ValueError(f"{path}.visual: use a validated diagram or chart section")
            if visual["kind"] == "diagram":
                from .diagrams import validate_diagram
                validate_diagram(visual, path + ".visual")
            else:
                from .charts import validate_chart
                validate_chart(visual, path + ".visual")
        if "question" in beat:
            question = _record(beat["question"], {"prompt", "answer"}, path + ".question")
            _text(question.get("prompt"), path + ".question.prompt", required=True)
            if "answer" in question:
                _text(question["answer"], path + ".question.answer", required=True)
    for index, limit in enumerate(_list(story.get("limitations", []), location + ".limitations", 100)):
        _text(limit, f"{location}.limitations[{index}]", required=True)


def _markdown_text(value):
    # Treat source as literal text, not as executable HTML or Markdown directives.
    text = html.escape(value, quote=False)
    return re.sub(r"([\\`*_{}\[\]#!|])", r"\\\1", text).replace("\n", "  \n")


def _claim_lines(claim):
    lines = [f"[{claim['type'].upper()} · {claim['id']}] {claim['text']}"]
    for field, label in (("attributed_to", "Attribution"), ("basis", "Basis"),
                         ("scope", "Scope"), ("uncertainty", "Qualification")):
        if claim.get(field):
            lines.append(f"{label}: {claim[field]}")
    lines.append("Source IDs: " + (", ".join(claim["source_ids"]) or "none; proposal"))
    return lines


def _visual_lines(visual):
    """Literal equivalent of a validated visual, without deriving findings."""
    lines = [f"Visual: {visual['title']}", visual["description"]]
    if visual["kind"] == "chart":
        lines.extend([
            f"Visual type: {visual['type']} chart.",
            f"Y-axis (including units): {visual['y_label']}",
        ])
        if "x_label" in visual:
            lines.append(f"X-axis: {visual['x_label']}")
        if "uncertainty_label" in visual:
            lines.extend([f"Source-provided uncertainty: {visual['uncertainty_label']}",
                          "No confidence interval is inferred."])
        if "domain" in visual:
            lines.append(f"Specified y-axis domain: {visual['domain'][0]} to {visual['domain'][1]}")
        lines.extend([
            "Categories are equally spaced and listed in source order; no time scale is inferred.",
            "Exact source values follow; no rounding is applied. Missing means unavailable, never zero.",
        ])
        intervals = any("lower" in series for series in visual["series"])
        if intervals:
            lines.append("Missing bounds mean null; Not supplied means the series has no interval arrays.")
        for index, category in enumerate(visual["categories"]):
            lines.extend(["", f"Category {index + 1}: {category}"])
            for number, series in enumerate(visual["series"], 1):
                lines.append(f"Series {number}: {series['label']}")
                fields = [("values", "Value")]
                if intervals:
                    fields.extend([("lower", "Lower bound"), ("upper", "Upper bound")])
                for field, label in fields:
                    value = ("Not supplied" if field not in series else
                             "Missing" if series[field][index] is None else str(series[field][index]))
                    lines.append(f"{label}: {value}")
    else:
        flow = visual["type"] == "flow"
        entities = visual["nodes" if flow else "participants"]
        links = visual["edges" if flow else "messages"]
        entity_name, link_name = ("Node", "Edge") if flow else ("Participant", "Message")
        lines.append(f"Visual type: {visual['type']} diagram.")
        if flow:
            lines.extend([f"Layout direction: {visual.get('direction', 'LR')}",
                          "Nodes and directed edges are listed in supplied order."])
        else:
            lines.extend(["Participants are listed in supplied order.",
                          "Messages are listed in supplied temporal order."])
        lines.append("No evidence classification is inferred from style.")
        for index, entity in enumerate(entities, 1):
            lines.extend(["", f"{entity_name} {index}: {entity['label']} (ID: {entity['id']})"])
            if "detail" in entity:
                lines.append(f"Detail: {entity['detail']}")
        labels = {entity["id"]: entity["label"] for entity in entities}
        if not links:
            lines.append("No edges supplied.")
        for index, link in enumerate(links, 1):
            lines.extend(["", f"{link_name} {index}: {link['from']} → {link['to']}",
                          f"From: {labels[link['from']]} (ID: {link['from']})",
                          f"To: {labels[link['to']]} (ID: {link['to']})"])
            lines.append(f"Label: {link['label']}" if "label" in link else "Label: Not supplied")
            lines.append(f"Style: {link.get('style', 'solid')} (presentation only)")
            if "note" in link:
                lines.append(f"Note: {link['note']}")
    if "caption" in visual:
        lines.extend(["", f"Caption: {visual['caption']}"])
    return lines


def story_companions(story):
    """Produce complete prose/ledger and reviewable narration/storyboard data."""
    validate_story(story)
    claims = {claim["id"]: claim for claim in story["claims"]}
    used = {identifier for beat in story["beats"] for identifier in beat["claim_ids"]}
    unused = [identifier for identifier in claims if identifier not in used]
    lines = [f"# {_markdown_text(story['title'])}", "",
             f"Audience: {_markdown_text(story['audience'])}",
             f"Question: {_markdown_text(story['question'])}",
             f"Purpose: {story['purpose']}", "", _markdown_text(story["summary"]), ""]
    if story.get("context"):
        lines.extend([_markdown_text(story["context"]), ""])
    cues = []
    for index, beat in enumerate(story["beats"], 1):
        lines.extend([f"## {index}. {_markdown_text(beat['title'])}", ""])
        if beat.get("role"):
            lines.extend([f"Role: {_markdown_text(beat['role'])}", ""])
        if beat.get("text"):
            lines.extend([_markdown_text(beat["text"]), ""])
        for identifier in beat["claim_ids"]:
            lines.extend(_markdown_text(line) for line in _claim_lines(claims[identifier]))
            lines.append("")
        if beat.get("visual"):
            lines.extend(_markdown_text(line) for line in _visual_lines(beat["visual"]))
            lines.extend(["", "The complete structured visual is preserved in storyboard.json.", ""])
        if beat.get("question"):
            lines.extend(["Check: " + _markdown_text(beat["question"]["prompt"])])
            if "answer" in beat["question"]:
                lines.append("Answer: " + _markdown_text(beat["question"]["answer"]))
            lines.append("")
        supplied_narration = beat.get("narration")
        default_narration = "\n".join(
            [beat["title"], beat.get("text", "")]
            + [line for identifier in beat["claim_ids"] for line in _claim_lines(claims[identifier])]
        ).strip()
        cues.append({"id": beat["id"], "title": beat["title"],
                     "text": supplied_narration if supplied_narration else default_narration,
                     "claim_ids": list(beat["claim_ids"]), "review_required": True,
                     "origin": "author-supplied" if supplied_narration else "literal-claim-outline"})
    if story.get("limitations"):
        lines.extend(["## Material limitations", ""])
        lines.extend("- " + _markdown_text(item) for item in story["limitations"])
        lines.append("")
    lines.extend(["## Complete claim ledger", "",
                  "All supplied claims are retained, including any omitted from the narrative.", ""])
    for claim in story["claims"]:
        lines.extend(_markdown_text(line) for line in _claim_lines(claim))
        lines.append("")
    lines.extend(["## Source register", "",
                  "Source registration is not independent verification.", ""])
    for source in story["sources"]:
        lines.append(f"- [{source['id']}] {_markdown_text(source['title'])}")
        for field in ("url", "locator", "note"):
            if source.get(field):
                lines.append("  " + field + ": " + _markdown_text(source[field]))
    diagnostics = {
        "source_verification": "not_performed",
        "semantic_review": "required",
        "unused_claim_ids": unused,
        "notes": [
            "References are structurally valid; the engine does not verify source truth or claim entailment.",
            "Review narrative text, visuals, and narration against claims and qualifications before delivery.",
        ],
    }
    storyboard = {"version": 1, "title": story["title"], "audience": story["audience"],
                  "question": story["question"], "purpose": story["purpose"],
                  "beats": story["beats"], "claims": story["claims"], "sources": story["sources"],
                  "limitations": story.get("limitations", []), "review": diagnostics}
    # JSON preserves the complete input, including authored narration and metadata.
    ledger = {"version": 1, "source_story": story, "review": diagnostics}
    return {
        "story.md": "\n".join(lines).rstrip() + "\n",
        "storyboard.json": json.dumps(storyboard, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        "narration.json": json.dumps({"version": 1, "cues": cues, "review_required": True},
                                   ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        "evidence.json": json.dumps(ledger, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
    }


def render_story(story):
    """Render safe native story content. Raw source HTML is never executed."""
    from jinja2 import Environment, FileSystemLoader

    validate_story(story)
    prefix = "ste-story-" + hashlib.sha256(
        json.dumps(story, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()
    ).hexdigest()[:12]
    claim_index = {claim["id"]: claim for claim in story["claims"]}
    beats = []
    for beat in story["beats"]:
        visual_html = ""
        if beat.get("visual"):
            if beat["visual"]["kind"] == "diagram":
                from .diagrams import render_diagram
                visual_html = render_diagram(beat["visual"])
            else:
                from .charts import render_chart
                visual_html = render_chart(beat["visual"])
        beats.append({**beat, "claims": [claim_index[key] for key in beat["claim_ids"]],
                      "visual_html": visual_html})
    environment = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                              autoescape=True)
    return environment.get_template("story.html.j2").render(
        story=story, beats=beats, prefix=prefix, purpose=PURPOSES[story["purpose"]],
    )
