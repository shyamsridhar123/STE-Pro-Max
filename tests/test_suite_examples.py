"""Contract and evidence-consistency checks for the explicitly fictional suite."""
import contextlib
from copy import deepcopy
import hashlib
from html import unescape
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import statistics
import tempfile
import unittest
import xml.etree.ElementTree as ET

import yaml

from ste_promax.charts import CHART_SCHEMA, chart_svg, render_chart, validate_chart
from ste_promax.diagrams import DIAGRAM_SCHEMA, diagram_svg, render_diagram, validate_diagram
from ste_promax.stories import STORY_SCHEMA, render_story, story_companions, validate_story


ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "examples" / "suite"
STORIES = {
    "explanation": "retry-explanation.json",
    "decision-brief": "workshop-decision.json",
    "research-digest": "instruction-research.json",
    "incident-review": "queue-incident.json",
}
REPORT = "caption-documentation.json"
NS = {"s": "http://www.w3.org/2000/svg"}


def load(name):
    return json.loads((SUITE / name).read_text(encoding="utf-8"))


def source_for(story):
    return json.loads((ROOT / story["sources"][0]["locator"]).read_text(encoding="utf-8"))


class VisibleText(HTMLParser):
    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.feed(markup)

    def handle_data(self, data):
        self.parts.append(data)


class SuiteExampleTests(unittest.TestCase):
    def test_four_distinct_purposes_and_one_structured_report(self):
        self.assertEqual({p.name for p in SUITE.glob("*.json")}, {*STORIES.values(), REPORT})
        questions = set()
        for purpose, filename in STORIES.items():
            story = load(filename)
            self.assertEqual(story["purpose"], purpose)
            self.assertIsNone(validate_story(story, filename))
            self.assertTrue(set(story) <= {"kind", *STORY_SCHEMA["fields"]})
            questions.add(story["question"])
        self.assertEqual(len(questions), 4)
        self.assertNotIn("body_html", load(REPORT))

    def test_every_source_is_local_explicitly_fictional_and_claim_linked(self):
        all_sources = set()
        for filename in STORIES.values():
            story = load(filename)
            self.assertIn("fictional", story["context"].lower())
            self.assertTrue(story["limitations"])
            registered = {}
            for entry in story["sources"]:
                self.assertNotIn("url", entry)
                path = (ROOT / entry["locator"]).resolve()
                self.assertTrue(path.is_relative_to((SUITE / "sources").resolve()))
                source = json.loads(path.read_text(encoding="utf-8"))
                self.assertIs(source["fictional"], True)
                self.assertEqual(source["id"], entry["id"])
                self.assertEqual(source["title"], entry["title"])
                self.assertTrue(source["provenance"])
                self.assertTrue(source["scope"])
                registered[entry["id"]] = source
                all_sources.add(path.name)
            used_claims = {key for beat in story["beats"] for key in beat["claim_ids"]}
            self.assertEqual(used_claims, {claim["id"] for claim in story["claims"]})
            for claim in story["claims"]:
                self.assertTrue(claim["source_ids"], claim["id"])
                for source_id in claim["source_ids"]:
                    support = registered[source_id]["claim_support"][claim["id"]]
                    self.assertTrue(support)
                    self.assertTrue(all(field in registered[source_id] for field in support))
                if claim["type"] == "inference":
                    self.assertTrue(claim["basis"])
            self.assertTrue(any(claim["type"] == "observation" for claim in story["claims"]))
            self.assertTrue(any(claim["type"] == "inference" for claim in story["claims"]))
        self.assertEqual(len(all_sources), 4)

    def test_source_to_claim_crosslinks_match_exactly(self):
        expected = {
            "retry-explanation.json": ("retry-log", {"same-receipt", "one-write", "bounded-lesson"}),
            "workshop-decision.json": ("workshop-notes", {
                "time-tradeoff", "quality-gate", "tray-eligible", "repeat-before-adoption"}),
            "instruction-research.json": ("walkthrough-notes", {
                "medians-and-ranges", "reported-pause", "not-a-general-effect", "broaden-the-check"}),
            "queue-incident.json": ("queue-notes", {
                "retained-depths", "missing-is-unknown", "cause-not-established",
                "closure-not-established", "instrument-and-recheck"}),
        }
        for filename, (source_id, claim_ids) in expected.items():
            story = load(filename)
            self.assertEqual({c["id"]: c["source_ids"] for c in story["claims"]},
                             {key: [source_id] for key in claim_ids})
            self.assertEqual(set(source_for(story)["claim_support"]), claim_ids)

    def test_all_story_visuals_validate_and_render_as_named_svg(self):
        kinds = set()
        for filename in STORIES.values():
            story = load(filename)
            for beat in story["beats"]:
                if "visual" not in beat:
                    continue
                visual = beat["visual"]
                schema = DIAGRAM_SCHEMA if visual["kind"] == "diagram" else CHART_SCHEMA
                validate = validate_diagram if visual["kind"] == "diagram" else validate_chart
                svg = diagram_svg if visual["kind"] == "diagram" else chart_svg
                render = render_diagram if visual["kind"] == "diagram" else render_chart
                self.assertTrue(set(visual) <= {"kind", *schema["fields"]})
                self.assertIsNone(validate(visual))
                parsed = ET.fromstring(svg(visual))
                self.assertEqual(parsed.get("role"), "img")
                self.assertIn(visual["title"], "".join(parsed.itertext()))
                self.assertIn(visual["description"], "".join(parsed.itertext()))
                self.assertIn(visual["caption"], "".join(VisibleText(render(visual)).parts))
                for source_id in {key for claim in story["claims"] if claim["id"] in beat["claim_ids"]
                                  for key in claim["source_ids"]}:
                    self.assertIn(source_id, visual["caption"])
                kinds.add((visual["kind"], visual["type"]))
        self.assertTrue({("diagram", "sequence"), ("chart", "bar"), ("chart", "line")} <= kinds)

    def test_retry_relationships_and_quantities_are_exact(self):
        story = load("retry-explanation.json")
        source = source_for(story)
        sequence = story["beats"][0]["visual"]
        self.assertEqual(sequence["participants"], source["participants"])
        self.assertEqual(sequence["messages"], source["events"])
        self.assertEqual([(m["from"], m["to"], m["label"]) for m in sequence["messages"]], [
            ("client", "register", "Submit key K7"),
            ("register", "register", "Store one record"),
            ("register", "client", "Receipt R9"),
            ("client", "register", "Retry key K7"),
            ("register", "client", "Return receipt R9"),
        ])
        chart = story["beats"][1]["visual"]
        self.assertEqual(source["counts"], {"requests": 2, "stored_records": 1})
        self.assertEqual(chart["categories"], ["Requests", "Stored records"])
        self.assertEqual(chart["series"][0]["values"], [2, 1])
        self.assertEqual(sum(m["from"] == "client" for m in sequence["messages"]), 2)
        self.assertEqual(sum(m["from"] == m["to"] for m in sequence["messages"]), 1)
        self.assertEqual(story["claims"][2]["uncertainty"], source["qualification"])

    def test_short_narration_is_exact_and_stays_concise(self):
        story = load("retry-explanation.json")
        self.assertEqual(len(story["beats"]), 2)
        transcript = "\n\n".join(beat["narration"] for beat in story["beats"]) + "\n"
        self.assertEqual((SUITE / "retry-explanation.narration.txt").read_text(encoding="utf-8"), transcript)
        words = len(transcript.split())
        self.assertEqual(words, 73)
        self.assertTrue(20 <= words / 150 * 60 <= 40)
        self.assertIn("two requests, one stored record", transcript)
        self.assertIn("crash safety or behavior under concurrent requests? No.", transcript)
        self.assertIn("fictional", transcript)
        self.assertIn("sequential requests only", transcript)
        for beat in story["beats"]:
            self.assertLessEqual(len(beat["text"].split()), 16)
            visual = beat["visual"]
            for item in visual.get("participants", []) + visual.get("messages", []):
                self.assertLessEqual(len(item["label"].split()), 4)
        self.assertEqual(len(story["beats"][0]["visual"]["messages"]), 5)
        self.assertEqual(len(story["beats"][1]["visual"]["categories"]), 2)

    def test_decision_compares_equal_batches_and_applies_the_supplied_gate(self):
        story = load("workshop-decision.json")
        source = source_for(story)
        runs = source["workflows"]
        self.assertEqual([r["sets"] for r in runs], [40, 40])
        self.assertEqual([r["minutes"] for r in runs], [24, 18])
        self.assertEqual([r["mislabelled_sets"] for r in runs], [1, 4])
        self.assertEqual(source["decision_rule"]["maximum_mislabelled_sets"], 2)
        self.assertEqual(story["beats"][0]["visual"]["series"][0]["values"],
                         [r["minutes"] for r in runs])
        self.assertEqual(story["beats"][1]["visual"]["series"][0]["values"],
                         [r["mislabelled_sets"] for r in runs])
        eligible = [r["label"] for r in runs
                    if r["mislabelled_sets"] <= source["decision_rule"]["maximum_mislabelled_sets"]]
        self.assertEqual(eligible, ["Tray"])
        self.assertEqual(runs[0]["minutes"] - runs[1]["minutes"], 6)
        self.assertIn("1 is at most 2, 4 exceeds 2, and 24 minus 18 is 6", story["claims"][2]["basis"])
        self.assertIn("twenty-four minutes", story["beats"][0]["narration"])
        self.assertIn("eighteen", story["beats"][0]["narration"])
        self.assertIn("Tray has one; Stack has four", story["beats"][1]["narration"])
        self.assertIn("not proof", story["beats"][1]["narration"])

    def test_research_intervals_are_source_ranges_not_invented_statistics(self):
        story = load("instruction-research.json")
        source = source_for(story)
        chart = story["beats"][0]["visual"]
        conditions = source["conditions"]
        self.assertEqual([row["seconds"] for row in conditions], [[10, 12, 14], [8, 9, 16]])
        self.assertEqual(chart["categories"], [row["label"] for row in conditions])
        for row in conditions:
            self.assertEqual(row["median_seconds"], statistics.median(row["seconds"]))
            self.assertEqual(row["minimum_seconds"], min(row["seconds"]))
            self.assertEqual(row["maximum_seconds"], max(row["seconds"]))
        self.assertEqual(chart["series"][0]["values"], [12, 9])
        self.assertEqual(chart["series"][0]["lower"], [10, 8])
        self.assertEqual(chart["series"][0]["upper"], [14, 16])
        self.assertEqual(chart["uncertainty_label"], source["uncertainty_meaning"])
        self.assertEqual(story["claims"][0]["uncertainty"], source["uncertainty_meaning"])
        narration = story["beats"][0]["narration"]
        for phrase in ("twelve seconds", "ten to fourteen", "nine", "eight to sixteen",
                       "not confidence intervals"):
            self.assertIn(phrase, narration)

    def test_research_attribution_does_not_turn_a_pause_into_a_cause(self):
        story = load("instruction-research.json")
        source = source_for(story)
        claim = story["claims"][1]
        self.assertEqual(claim["type"], "attribution")
        self.assertEqual(claim["text"], source["facilitator_note"]["text"])
        self.assertEqual(claim["attributed_to"], source["facilitator_note"]["attributed_to"])
        self.assertEqual(claim["uncertainty"], source["facilitator_note"]["qualification"])
        self.assertIn("does not isolate a cause", story["beats"][1]["narration"])
        self.assertEqual(story["claims"][2]["type"], "inference")
        self.assertIn("not counterbalanced", story["claims"][2]["basis"])
        self.assertIn("has not happened", story["beats"][2]["narration"])

    def test_incident_missing_value_and_chronology_are_preserved(self):
        story = load("queue-incident.json")
        source = source_for(story)
        chart = story["beats"][0]["visual"]
        self.assertEqual([sample["minute"] for sample in source["samples"]], [0, 1, 2, 3, 4])
        self.assertEqual(chart["categories"], [f"Minute {s['minute']}" for s in source["samples"]])
        self.assertEqual(chart["series"][0]["values"], [2, 5, None, 4, 1])
        self.assertEqual(chart["series"][0]["values"], [s["waiting_jobs"] for s in source["samples"]])
        self.assertIs(chart["series"][0]["values"][2], None)
        self.assertIn("null means unknown, not zero", chart["description"])
        self.assertIn("one-minute", chart["x_label"])
        self.assertIn("two, five, unknown, four and one", story["beats"][0]["narration"])
        self.assertEqual([event["minute"] for event in source["events"]], [1, 2, 3])
        self.assertIn("relative order is unknown", source["events"][0]["event"])
        self.assertIn("without their relative order", story["beats"][1]["narration"])
        self.assertIn("only a hypothesis", story["beats"][1]["narration"])
        self.assertIn("still has one waiting job", story["beats"][2]["narration"])
        self.assertIn("not completed corrections", story["beats"][2]["narration"])

    def test_chart_svg_uses_exact_values_bounds_and_an_actual_line_gap(self):
        charts = [beat["visual"] for filename in STORIES.values() for beat in load(filename)["beats"]
                  if beat.get("visual", {}).get("kind") == "chart"]
        charts.extend(section for section in load(REPORT)["sections"] if section["kind"] == "chart")
        self.assertEqual(len(charts), 6)
        for chart in charts:
            root = ET.fromstring(chart_svg(chart))
            point_titles = [node.text for node in root.findall(".//s:g[@class='chart-point']/s:title", NS)]
            expected = [
                f'{series["label"]}; {category}: {value}'
                for series in chart["series"]
                for category, value in zip(chart["categories"], series["values"])
                if value is not None
            ]
            self.assertEqual(point_titles, expected)
            intervals = root.findall(".//s:path[@class='chart-interval']/s:title", NS)
            if "lower" in chart["series"][0]:
                self.assertEqual([node.text for node in intervals],
                                 ["Source-provided bounds: 10 to 14", "Source-provided bounds: 8 to 16"])
            else:
                self.assertEqual(intervals, [])
            if chart["type"] == "line":
                line = root.find(".//s:path[@class='chart-line']", NS)
                assert line is not None
                path = line.get("d", "")
                self.assertEqual(path.count("M"), 2)
                self.assertEqual(path.count("L"), 2)
                self.assertEqual(len(point_titles), 4)
                self.assertIn("missing", "".join(root.itertext()).lower())

    def test_report_validates_every_section_without_emulating_shared_dispatch(self):
        from ste_promax.render import validate_input

        report = load(REPORT)
        self.assertEqual(set(report), {"title", "sections"})
        for section in report["sections"]:
            if section["kind"] == "diagram":
                validate_diagram(section)
            elif section["kind"] == "chart":
                validate_chart(section)
            else:
                validate_input({"title": report["title"], "sections": [section]})
        self.assertTrue({"diagram", "chart", "q-list", "status-table"}
                        <= {s["kind"] for s in report["sections"]})

    def test_report_architecture_counts_gate_and_source_register(self):
        report = load(REPORT)
        source = load("sources/caption-register.json")
        diagram = next(s for s in report["sections"] if s["kind"] == "diagram")
        chart = next(s for s in report["sections"] if s["kind"] == "chart")
        register = next(s for s in report["sections"] if s["kind"] == "status-table")["rows"][0]
        self.assertIs(source["fictional"], True)
        self.assertEqual(diagram["nodes"], source["nodes"])
        self.assertEqual(diagram["edges"], source["relationships"])
        self.assertEqual([(e["from"], e["to"]) for e in diagram["edges"]],
                         [("catalog", "draft"), ("draft", "draft"), ("draft", "review"),
                          ("review", "draft"), ("review", "package")])
        self.assertEqual(chart["categories"], [s["label"] for s in source["statuses"]])
        self.assertEqual(chart["series"][0]["values"], [7, 3, 2])
        self.assertEqual(chart["series"][0]["values"], [s["captions"] for s in source["statuses"]])
        self.assertEqual(sum(chart["series"][0]["values"]), 12)
        self.assertEqual(sum(chart["series"][0]["values"][:2]), 10)
        self.assertEqual(register["source"], source["id"])
        self.assertEqual((ROOT / register["locator"]).resolve(), (SUITE / "sources/caption-register.json").resolve())
        self.assertEqual(set(register["claims"].split(", ")), set(source["claim_support"]))
        self.assertIn("report-architecture", diagram["caption"])
        self.assertIn("report-counts", chart["caption"])
        for visual in (diagram, chart):
            self.assertIn(source["id"], visual["caption"])
        notes = " ".join(next(s for s in report["sections"] if s["kind"] == "callout")["items"])
        self.assertIn("7 corrected plus 3 already clear equals 10", notes)
        self.assertIn("2 pending captions mean that gate is not met", notes)
        self.assertIn("no timing, defect-rate comparison", notes)

    def test_report_diagram_renders_every_source_relationship_and_equivalent(self):
        source = load("sources/caption-register.json")
        diagram = next(s for s in load(REPORT)["sections"] if s["kind"] == "diagram")
        root = ET.fromstring(diagram_svg(diagram))
        groups = root.findall("s:g[@data-edge]", NS)
        self.assertEqual(len(groups), 5)
        for edge, group in zip(source["relationships"], groups):
            self.assertEqual(group.get("data-from"), edge["from"])
            self.assertEqual(group.get("data-to"), edge["to"])
            title = group.find("s:title", NS)
            assert title is not None
            self.assertEqual(title.text, edge["label"])
            self.assertIsNotNone(group.find("s:polygon", NS))
        text = "".join(VisibleText(render_diagram(diagram)).parts)
        for node in source["nodes"]:
            self.assertIn(node["label"], text)
            self.assertIn(node["detail"], text)
        for edge in source["relationships"]:
            self.assertIn(edge["label"], text)
        self.assertIn(diagram["caption"], text)

    def test_real_report_dispatch_renders_native_sections(self):
        from ste_promax.render import _SECTION_EMITTERS, _default_body_html, validate_input

        self.assertTrue({"diagram", "chart"} <= set(_SECTION_EMITTERS))
        report = load(REPORT)
        validate_input(report)
        rendered = _default_body_html(report)
        text = "".join(VisibleText(rendered).parts)
        self.assertEqual(rendered.count("<svg "), 2)
        for section in report["sections"]:
            if section["kind"] in ("diagram", "chart"):
                self.assertIn(section["title"], text)
                self.assertIn(section["caption"], text)
        self.assertIn("2 pending captions mean that gate is not met", text)
        self.assertIn("examples/suite/sources/caption-register.json", text)

    def test_all_five_fixtures_render_through_real_cli_with_checked_artifacts(self):
        from ste_promax import cli

        with tempfile.TemporaryDirectory(prefix="ste-suite-examples-") as directory:
            temporary_root = Path(directory).resolve()
            self.assertTrue(temporary_root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
            for filename in (*STORIES.values(), REPORT):
                with self.subTest(fixture=filename):
                    source = SUITE / filename
                    original = source.read_bytes()
                    output = temporary_root / "artifacts" / source.stem
                    with contextlib.redirect_stdout(io.StringIO()) as stdout, \
                            contextlib.redirect_stderr(io.StringIO()) as stderr:
                        code = cli.main(["render", str(source), "--output-dir", str(output)])
                    self.assertEqual(code, 0, stderr.getvalue())
                    manifest = json.loads(stdout.getvalue())
                    self.assertEqual(manifest["status"], "complete")
                    self.assertFalse(manifest["trusted_html"])
                    self.assertTrue(manifest["lint_passed"])
                    self.assertFalse(manifest["offline_verified"])
                    # A conservative string scan may report the SVG namespace,
                    # which identifies XML vocabulary rather than a fetched asset.
                    self.assertLessEqual(set(manifest["external_references"]), {NS["s"]})
                    self.assertEqual(manifest["source_sha256"], hashlib.sha256(original).hexdigest())
                    self.assertEqual(source.read_bytes(), original)
                    self.assertEqual((output / "source.json").read_bytes(), original)
                    document = load(filename)
                    self.assertEqual(json.loads((output / "input.json").read_text(encoding="utf-8")), document)
                    files = manifest["files"]
                    expected_files = {"source", "input", "html", "design", "meta", "gallery"}
                    if document.get("kind") == "story":
                        expected_files |= {"story", "storyboard", "narration", "evidence"}
                    visual_counts = {
                        "caption-documentation": 2, "instruction-research": 1,
                        "queue-incident": 1, "retry-explanation": 2, "workshop-decision": 2,
                    }
                    expected_files |= {f"visual-{index:02}" for index in range(1, visual_counts[source.stem] + 1)}
                    self.assertEqual(set(files), expected_files)
                    for record in files.values():
                        path = Path(record["path"]).resolve()
                        self.assertEqual(path.parent, output)
                        self.assertTrue(path.is_file())
                        self.assertGreater(path.stat().st_size, 0)
                        self.assertEqual(record["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
                    def read(key):
                        return Path(files[key]["path"]).read_text(encoding="utf-8")

                    self.assertEqual(json.loads((output / "manifest.json").read_text(encoding="utf-8")), manifest)
                    meta = yaml.safe_load(read("meta"))
                    self.assertEqual(meta["title"], document["title"])
                    self.assertTrue(meta["lint_passed"])
                    self.assertEqual(meta["design"], Path(files["design"]["path"]).name)
                    self.assertIn(Path(files["html"]["path"]).name, read("gallery"))
                    markup = read("html")
                    text = "".join(VisibleText(markup).parts)
                    expected_visuals = (
                        [beat["visual"] for beat in document["beats"] if "visual" in beat]
                        if document.get("kind") == "story"
                        else [section for section in document["sections"] if section["kind"] in ("diagram", "chart")]
                    )
                    self.assertEqual(markup.count("<svg "), len(expected_visuals))
                    for visual in expected_visuals:
                        self.assertIn(visual["title"], text)
                        self.assertIn(visual["caption"], text)
                    if document.get("kind") == "story":
                        self.assertEqual(json.loads(read("evidence"))["source_story"], document)
                        self.assertEqual(json.loads(read("storyboard"))["beats"], document["beats"])
                        cues = json.loads(read("narration"))["cues"]
                        self.assertEqual([c["text"] for c in cues], [b["narration"] for b in document["beats"]])
                        for claim in document["claims"]:
                            self.assertIn(claim["text"], text)
                            self.assertIn(claim["text"], unescape(read("story")))
                        for limitation in document["limitations"]:
                            self.assertIn(limitation, text)

    def test_authored_narration_and_all_claims_survive_companion_formats(self):
        for filename in STORIES.values():
            story = load(filename)
            before = deepcopy(story)
            outputs = story_companions(story)
            self.assertEqual(story, before)
            self.assertEqual(json.loads(outputs["evidence.json"])["source_story"], story)
            self.assertEqual(json.loads(outputs["storyboard.json"])["beats"], story["beats"])
            ledger = json.loads(outputs["evidence.json"])
            self.assertEqual(ledger["review"]["unused_claim_ids"], [])
            self.assertEqual(ledger["review"]["source_verification"], "not_performed")
            cues = json.loads(outputs["narration.json"])["cues"]
            self.assertEqual([c["text"] for c in cues], [b["narration"] for b in story["beats"]])
            self.assertEqual([c["claim_ids"] for c in cues], [b["claim_ids"] for b in story["beats"]])
            self.assertTrue(all(c["origin"] == "author-supplied" and c["review_required"] for c in cues))
            for claim in story["claims"]:
                self.assertIn(claim["text"], unescape(outputs["story.md"]))

    def test_rendered_stories_retain_questions_qualifications_and_sources(self):
        for filename in STORIES.values():
            story = load(filename)
            markup = render_story(story)
            text = "".join(VisibleText(markup).parts)
            for claim in story["claims"]:
                self.assertIn(claim["text"], text)
                for field in ("basis", "scope", "uncertainty", "attributed_to"):
                    if field in claim:
                        self.assertIn(claim[field], text)
            questions = [b["question"] for b in story["beats"] if "question" in b]
            self.assertTrue(questions)
            for question in questions:
                self.assertTrue(question["prompt"].endswith("?"))
                self.assertTrue(question["answer"])
                self.assertIn(question["prompt"], text)
                self.assertIn(question["answer"], text)
            for source in story["sources"]:
                self.assertIn(source["locator"], text)
            for limitation in story["limitations"]:
                self.assertIn(limitation, text)


if __name__ == "__main__":
    unittest.main()
