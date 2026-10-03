import copy
import html
from html.parser import HTMLParser
import json
import unittest

from ste_promax.charts import CHART_SCHEMA
from ste_promax.diagrams import DIAGRAM_SCHEMA
from ste_promax.stories import STORY_SCHEMA, render_story, story_companions, validate_story


class ParsedHTML(HTMLParser):
    """Inspect decoded text and actual tags rather than one entity spelling."""
    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.tags, self.text, self.scripts = [], [], []
        self.in_script = False
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == "script":
            self.in_script = True
            self.scripts.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        self.text.append(data)
        if self.in_script:
            self.scripts[-1] += data


class StoryTests(unittest.TestCase):
    def setUp(self):
        self.story = copy.deepcopy(STORY_SCHEMA["example"])

    def test_complete_example_and_source_are_preserved(self):
        before = copy.deepcopy(self.story)
        validate_story(self.story)
        result = story_companions(self.story)
        self.assertEqual(self.story, before)
        self.assertEqual(json.loads(result["evidence.json"])["source_story"], before)
        self.assertEqual(set(result), {"story.md", "storyboard.json", "narration.json", "evidence.json"})
        self.assertIn("No approval date is supplied.", result["story.md"])
        self.assertIn("The tested build only.", result["story.md"])
        self.assertEqual(json.loads(result["storyboard.json"])["beats"], before["beats"])

    def test_claims_unused_by_beats_are_not_lost(self):
        self.story["beats"] = self.story["beats"][:1]
        result = story_companions(self.story)
        self.assertIn("Release approval is pending.", result["story.md"])
        ledger = json.loads(result["evidence.json"])
        self.assertEqual(ledger["review"]["unused_claim_ids"], ["approval"])
        self.assertIn("Release approval is pending.", render_story(self.story))

    def test_unknown_fields_and_wrong_types_fail(self):
        for field, value in (("unknown", "Do not deploy."), ("version", True),
                             ("purpose", "hero-journey"), ("beats", []), ("title", "")):
            with self.subTest(field=field):
                data = copy.deepcopy(self.story)
                data[field] = value
                with self.assertRaises(ValueError):
                    validate_story(data)

    def test_duplicate_and_dangling_references_fail(self):
        mutations = [
            lambda data: data["sources"].append(copy.deepcopy(data["sources"][0])),
            lambda data: data["claims"].append(copy.deepcopy(data["claims"][0])),
            lambda data: data["beats"].append(copy.deepcopy(data["beats"][0])),
            lambda data: data["claims"][0].update(source_ids=["missing"]),
            lambda data: data["beats"][0].update(claim_ids=["missing"]),
            lambda data: data["beats"][0].update(claim_ids=["validation", "validation"]),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                data = copy.deepcopy(self.story)
                mutation(data)
                with self.assertRaises(ValueError):
                    validate_story(data)

    def test_observation_needs_source_but_proposal_does_not(self):
        self.story["claims"][0]["source_ids"] = []
        with self.assertRaises(ValueError):
            validate_story(self.story)
        self.story["claims"][0]["type"] = "proposal"
        validate_story(self.story)
        self.assertIn("none; proposal", render_story(self.story))

    def test_attribution_and_inference_require_qualifying_fields(self):
        self.story["claims"][0]["type"] = "attribution"
        with self.assertRaisesRegex(ValueError, "attributed_to"):
            validate_story(self.story)
        self.story["claims"][0]["attributed_to"] = "The provided notes"
        validate_story(self.story)
        self.story["claims"][0]["type"] = "inference"
        with self.assertRaisesRegex(ValueError, "basis"):
            validate_story(self.story)
        self.story["claims"][0]["basis"] = "A stated interpretation of the notes, not a verified cause."
        validate_story(self.story)
        self.assertIn("not a verified cause", render_story(self.story))

    def test_hostile_strings_are_data_in_html_and_markdown(self):
        attack = '<script>alert("unsafe")</script> ![bad](javascript:run)'
        self.story["summary"] = attack
        self.story["claims"][0]["uncertainty"] = attack
        markup = render_story(self.story)
        self.assertNotIn(attack, markup)
        # Named and numeric quote entities are equally safe. Assert the actual
        # decoded text and tag structure, not an implementation's entity spelling.
        parsed = ParsedHTML(markup)
        self.assertEqual("".join(parsed.text).count(attack), 3)
        self.assertEqual(sum(tag == "script" for tag, _ in parsed.tags), 1)
        prose = story_companions(self.story)["story.md"]
        self.assertNotIn("<script>", prose)
        self.assertNotIn("![bad]", prose)

    def test_hostile_source_is_exact_text_not_tags_attributes_or_script(self):
        baseline = ParsedHTML(render_story(self.story))
        attack = '<img src=x onerror="alert(1)"> & </script><script>run()</script>'
        self.story["summary"] = attack
        self.story["claims"][0]["scope"] = attack
        markup = ParsedHTML(render_story(self.story))
        self.assertEqual("".join(markup.text).count(attack), 3)
        self.assertEqual([tag for tag, _ in markup.tags], [tag for tag, _ in baseline.tags])
        self.assertEqual(markup.scripts, baseline.scripts)
        self.assertFalse(any(key.startswith("on") for _, attrs in markup.tags for key in attrs))
        self.assertTrue(all(not value or not value.startswith("javascript:")
                            for _, attrs in markup.tags for key, value in attrs.items()
                            if key in ("href", "src")))

    def test_readable_chart_preserves_exact_values_bounds_units_and_order(self):
        visual = copy.deepcopy(CHART_SCHEMA["example"])
        visual.update(type="line", categories=["First", "Missing", "Zero", "Last"],
                      y_label="Elapsed time (ms)", x_label="Source sample",
                      uncertainty_label="Reported min/max, not a confidence estimate",
                      caption="Single fixture only; do not generalize.", domain=[-2, 10**25])
        visual["series"] = [
            {"label": "Observed", "values": [1.2345678901234567, None, -0.0, -1],
             "lower": [1.234567890123456, None, None, -2],
             "upper": [1.234567890123457, None, None, 0]},
            {"label": "Reference", "values": [123456789012345678901, 0, 1e-300, None]},
        ]
        self.story["beats"][0]["visual"] = visual
        prose = story_companions(self.story)["story.md"]
        expected = [
            "Visual type: line chart.", "Y-axis (including units): Elapsed time (ms)",
            "X-axis: Source sample",
            "Source-provided uncertainty: Reported min/max, not a confidence estimate",
            "No confidence interval is inferred.",
            f"Specified y-axis domain: -2 to {10**25}",
            "Category 1: First", "Series 1: Observed", "Value: 1.2345678901234567",
            "Lower bound: 1.234567890123456", "Upper bound: 1.234567890123457",
            "Series 2: Reference", "Value: 123456789012345678901",
            "Lower bound: Not supplied", "Upper bound: Not supplied",
            "Category 2: Missing", "Series 1: Observed", "Value: Missing",
            "Lower bound: Missing", "Upper bound: Missing", "Series 2: Reference", "Value: 0",
            "Category 3: Zero", "Series 1: Observed", "Value: -0.0",
            "Lower bound: Missing", "Upper bound: Missing", "Series 2: Reference", "Value: 1e-300",
            "Category 4: Last", "Series 1: Observed", "Value: -1",
            "Lower bound: -2", "Upper bound: 0", "Series 2: Reference", "Value: Missing",
            "Caption: Single fixture only; do not generalize.",
        ]
        cursor = 0
        for text in expected:
            with self.subTest(text=text):
                found = prose.find(text, cursor)
                self.assertNotEqual(found, -1, f"Missing or reordered: {text}")
                cursor = found + len(text)
        self.assertIn("Missing means unavailable, never zero.", prose)
        self.assertIn("Categories are equally spaced", prose)

    def test_readable_flow_retains_isolates_feedback_parallel_and_self_edges(self):
        visual = copy.deepcopy(DIAGRAM_SCHEMA["example"])
        visual.update(direction="TB", caption="A proposed process, not an observed cause.")
        visual["nodes"].append({"id": "isolated", "label": "Not connected", "detail": "No relationship supplied."})
        visual["edges"].extend([
            {"from": "draft", "to": "review", "label": "Alternative submission", "style": "dashed"},
            {"from": "review", "to": "review", "label": "Internal check"},
        ])
        self.story["beats"][0]["visual"] = visual
        prose = story_companions(self.story)["story.md"]
        for text in ("Visual type: flow diagram.", "Layout direction: TB",
                     "Node 1: Draft (ID: draft)", "Node 2: Review (ID: review)",
                     "Node 3: Not connected (ID: isolated)", "Detail: No relationship supplied.",
                     "Edge 1: draft → review", "Label: Submit", "Edge 2: review → draft",
                     "Label: Revise", "Edge 3: draft → review", "Label: Alternative submission",
                     "Edge 4: review → review", "Label: Internal check",
                     "Style: dashed (presentation only)", "Style: solid (presentation only)",
                     "Caption: A proposed process, not an observed cause."):
            with self.subTest(text=text):
                self.assertIn(text, prose)
        positions = [prose.index(f"Edge {i}:") for i in range(1, 5)]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("No evidence classification is inferred from style.", prose)

    def test_readable_sequence_preserves_message_order_and_notes(self):
        self.story["beats"][0]["visual"] = {
            "kind": "diagram", "type": "sequence", "title": "Illustrative exchange",
            "description": "Reported order only, not measured timing.",
            "participants": [{"id": "client", "label": "Client"}, {"id": "server", "label": "Server"}],
            "messages": [
                {"from": "server", "to": "client", "label": "Challenge", "note": "Origin not established."},
                {"from": "client", "to": "client", "label": "Prepare", "style": "dashed"},
                {"from": "client", "to": "server", "label": "Response", "note": "May fail."},
            ],
        }
        prose = story_companions(self.story)["story.md"]
        for text in ("Participant 1: Client (ID: client)", "Participant 2: Server (ID: server)",
                     "Message 1: server → client", "Message 2: client → client",
                     "Message 3: client → server", "Label: Challenge", "Label: Prepare",
                     "Label: Response", "Note: Origin not established.", "Note: May fail."):
            self.assertIn(text, prose)
        self.assertLess(prose.index("Message 1:"), prose.index("Message 2:"))
        self.assertLess(prose.index("Message 2:"), prose.index("Message 3:"))
        self.assertIn("Messages are listed in supplied temporal order.", prose)

    def test_empty_flow_does_not_invent_edges(self):
        visual = copy.deepcopy(DIAGRAM_SCHEMA["example"])
        visual["edges"] = []
        self.story["beats"][0]["visual"] = visual
        prose = story_companions(self.story)["story.md"]
        self.assertIn("No edges supplied.", prose)
        self.assertIn("Node 1: Draft", prose)
        self.assertNotIn("Edge 1:", prose)

    def test_hostile_visual_fields_are_literal_in_readable_equivalents(self):
        attack = '<script>run()</script> ![unsafe](javascript:run) | **not a claim**'
        visual = copy.deepcopy(CHART_SCHEMA["example"])
        visual["categories"][0] = attack
        visual["series"][0]["label"] = attack
        self.story["beats"][0]["visual"] = visual
        prose = story_companions(self.story)["story.md"]
        self.assertNotIn(attack, prose)
        self.assertNotIn("<script>", prose)
        self.assertNotIn("![unsafe]", prose)
        literal = (html.escape(attack, quote=False).replace("!", r"\!").replace("[", r"\[")
                   .replace("]", r"\]").replace("|", r"\|").replace("*", r"\*"))
        self.assertIn("Category 1: " + literal, prose)
        self.assertIn("Series 1: " + literal, prose)

    def test_companions_preserve_shared_object_identity_and_source_bytes(self):
        self.story["beats"][0]["visual"] = copy.deepcopy(CHART_SCHEMA["example"])
        # Legal in-memory aliasing: both beats refer to the same source visual.
        self.story["beats"][1]["visual"] = self.story["beats"][0]["visual"]
        before = json.dumps(self.story, ensure_ascii=False).encode("utf-8")
        tracked = [self.story, self.story["beats"], *self.story["beats"], self.story["claims"],
                   *self.story["claims"], self.story["beats"][0]["visual"]]
        identities = [id(item) for item in tracked]
        result = story_companions(self.story)
        render_story(self.story)
        self.assertEqual(json.dumps(self.story, ensure_ascii=False).encode("utf-8"), before)
        current = [self.story, self.story["beats"], *self.story["beats"], self.story["claims"],
                   *self.story["claims"], self.story["beats"][0]["visual"]]
        self.assertEqual([id(item) for item in current], identities)
        self.assertIs(self.story["beats"][0]["visual"], self.story["beats"][1]["visual"])
        evidence = json.loads(result["evidence.json"])
        self.assertEqual(json.dumps(evidence["source_story"], ensure_ascii=False).encode("utf-8"), before)
        evidence["source_story"]["claims"][0]["text"] = "Changed decoded companion only"
        self.assertEqual(story_companions(self.story), result)
        self.story["claims"][0]["text"] = "Changed source after serialization"
        self.assertNotIn("Changed source after serialization", result["evidence.json"])

    def test_default_narration_keeps_all_claim_qualifications(self):
        self.story["claims"][0].update(
            attributed_to="Named source", basis="Interpretation only", scope="Fixture only.",
            uncertainty="Not an approval.",
        )
        cue = json.loads(story_companions(self.story)["narration.json"])["cues"][0]
        for text in ("Attribution: Named source", "Basis: Interpretation only",
                     "Scope: Fixture only.", "Qualification: Not an approval.", "Source IDs: notes"):
            self.assertIn(text, cue["text"])
        self.assertTrue(cue["review_required"])
        self.assertEqual(cue["origin"], "literal-claim-outline")

    def test_authored_narration_is_unchanged_unverified_and_caveats_remain(self):
        authored = "  The author says deploy now.\nThis is not checked by the engine.  "
        self.story["beats"][1]["narration"] = authored
        result = story_companions(self.story)
        cue = json.loads(result["narration.json"])["cues"][1]
        self.assertEqual(cue["text"], authored)
        self.assertEqual(cue["origin"], "author-supplied")
        self.assertTrue(cue["review_required"])
        self.assertIn("No approval date is supplied.", result["story.md"])
        self.assertEqual(json.loads(result["evidence.json"])["review"]["semantic_review"], "required")

    def test_source_urls_reject_credentials_and_active_schemes(self):
        for url in ("javascript:alert(1)", "file:///etc/passwd", "https://user:pass@example.org",
                    "//example.org", "https://example.org/\nextra", "https://example.org:bad"):
            with self.subTest(url=url):
                self.story["sources"][0]["url"] = url
                with self.assertRaises(ValueError):
                    validate_story(self.story)
        self.story["sources"][0]["url"] = "https://example.org/source"
        validate_story(self.story)

    def test_narration_is_draft_and_never_claims_approval(self):
        self.story["beats"][0]["narration"] = "A supplied narration draft."
        result = json.loads(story_companions(self.story)["narration.json"])
        self.assertTrue(result["review_required"])
        self.assertEqual(result["cues"][0]["text"], "A supplied narration draft.")
        self.assertEqual(result["cues"][0]["origin"], "author-supplied")
        self.assertTrue(all(cue["review_required"] for cue in result["cues"]))

    def test_static_content_readable_without_javascript_and_print_rule_exists(self):
        markup = render_story(self.story)
        self.assertIn('data-story-beat>', markup)
        self.assertNotIn('data-story-beat hidden', markup)
        self.assertIn("The validation checks passed.", markup)
        self.assertIn("Release approval is pending.", markup)
        self.assertIn("Source register", markup)
        self.assertIn('@media print', markup)
        self.assertIn('aria-live="polite"', markup)
        self.assertIn("Show answer", markup)

    def test_optional_unanswered_question_does_not_fabricate_answer(self):
        self.story["beats"][1]["question"].pop("answer")
        markup = render_story(self.story)
        self.assertIn("Does a passed test authorize a release?", markup)
        self.assertNotIn("Show answer", markup)

    def test_output_is_deterministic(self):
        self.assertEqual(render_story(self.story), render_story(self.story))
        self.assertEqual(story_companions(self.story), story_companions(self.story))

    def test_invalid_text_and_oversized_inputs_fail(self):
        for text in ("\x00not valid", "\ud800", "x" * 12001):
            with self.subTest(text=text[:20]):
                self.story["title"] = text
                with self.assertRaises(ValueError):
                    validate_story(self.story)


if __name__ == "__main__":
    unittest.main()
