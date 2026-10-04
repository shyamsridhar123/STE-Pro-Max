"""Keep the public examples tied to their fictional source and explicit model."""
from html.parser import HTMLParser
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1] / "examples/showcase"
VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                 "link", "meta", "param", "source", "track", "wbr"}


class ExampleFacts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.counts = []
        self.source_parts = []
        self.source_depth = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        identifier = attributes.get("id")
        count = attributes.get("data-count")
        if identifier:
            self.ids.append(identifier)
        if count:
            self.counts.append(int(count))
        if self.source_depth and tag not in VOID_ELEMENTS:
            self.source_depth += 1
        elif attributes.get("id") == "source-text":
            self.source_depth = 1

    def handle_endtag(self, tag):
        if self.source_depth and tag not in VOID_ELEMENTS:
            self.source_depth -= 1

    def handle_data(self, data):
        if self.source_depth:
            self.source_parts.append(data)


class ShowcaseSourceTests(unittest.TestCase):
    def test_brief_embeds_the_original_source_without_rewriting_it(self):
        source = (ROOT / "sources/launch-note.md").read_text(encoding="utf-8").rstrip()
        facts = ExampleFacts()
        facts.feed((ROOT / "brief-transformation.html").read_text(encoding="utf-8"))
        self.assertEqual("".join(facts.source_parts), source)
        self.assertIn("fictional Northstar", source)
        self.assertGreaterEqual(len(source.split()), 120)

    def test_brief_counts_and_acceptance_calculation_agree(self):
        html = (ROOT / "brief-transformation.html").read_text(encoding="utf-8")
        facts = ExampleFacts()
        facts.feed(html)
        self.assertEqual(facts.counts, [186, 38, 16])
        self.assertEqual(sum(facts.counts), 240)
        self.assertEqual(facts.counts[0] / sum(facts.counts) * 100, 77.5)
        self.assertIn("77.5% accepted without changes", html)
        self.assertIn("Proposal, not a decision", html)
        self.assertIn("It has not begun.", html)
        self.assertNotIn("Ready for a shadow pilot", html)

    def test_new_examples_have_unique_control_and_source_ids(self):
        for name in ("brief-transformation", "retry-storm"):
            with self.subTest(name=name):
                facts = ExampleFacts()
                facts.feed((ROOT / f"{name}.html").read_text(encoding="utf-8"))
                self.assertTrue(facts.ids)
                self.assertEqual(len(facts.ids), len(set(facts.ids)))

    def test_retry_source_is_an_explicit_model_not_empirical_data(self):
        model = json.loads((ROOT / "sources/retry-storm.json").read_text(encoding="utf-8"))
        provenance = model["provenance"]
        for flag in ("observed_incident", "production_telemetry", "benchmark"):
            self.assertIs(provenance[flag], False)
        self.assertEqual(provenance["empirical_data"], [])
        self.assertNotIn("User-supplied", provenance["source"])
        self.assertEqual(model["inputs"]["backend_failure"], "persistent")
        self.assertIn("including the initial attempt", model["definitions"]["A"])
        self.assertIn("not a simultaneous call", model["definitions"]["attempt_mark"])

    def test_retry_default_and_boundary_counts_follow_the_stated_formulas(self):
        model = json.loads((ROOT / "sources/retry-storm.json").read_text(encoding="utf-8"))
        layers = model["inputs"]["serial_layers"]["default"]
        attempts = model["inputs"]["total_attempts_per_retrying_layer_per_incoming_call"]["default"]
        default = model["default_example"]
        self.assertEqual((layers, attempts), (4, 3))
        self.assertEqual(default["nested_boundary_counts"], [attempts ** i for i in range(1, layers + 1)])
        self.assertEqual(default["single_owner_boundary_counts"], [attempts] * layers)
        self.assertEqual(default["nested_backend_attempts"], attempts ** layers)
        self.assertEqual(default["single_owner_backend_attempts"], attempts)
        self.assertEqual(default["retries_per_incoming_call"], attempts - 1)
        for example in model["boundary_examples"]:
            with self.subTest(example=example):
                self.assertEqual(example["nested_backend_attempts"], example["A"] ** example["L"])
                self.assertEqual(example["single_owner_backend_attempts"], example["A"])


if __name__ == "__main__":
    unittest.main()
