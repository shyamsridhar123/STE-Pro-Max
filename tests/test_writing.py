"""Regression tests for advisory prose checks."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from ste_promax import writing
from ste_promax.cli import main


class CheckTests(unittest.TestCase):
    def test_thresholds_and_no_score(self):
        for profile, limit in (("relaxed", 25), ("procedure", 20), ("description", 25)):
            with self.subTest(profile=profile):
                result = writing.check_text(" ".join(["word"] * limit) + ".", profile)
                self.assertEqual(result["findings"], [])
                result = writing.check_text(" ".join(["word"] * (limit + 1)) + ".", profile)
                self.assertEqual(result["findings"][0]["word_count"], limit + 1)
                self.assertNotIn("score", result)
                self.assertIn("manual", " ".join(result["limitations"]).lower())

    def test_ignored_markdown_and_code(self):
        text = """---
title: Ignore this sentence.
---
# Ignore this heading.
https://example.org/some.path
```python
Ignore this sentence.
```
~~~text
Ignore this too.
~~~
Actual `ignored. code` words.
"""
        result = writing.check_text(text, "relaxed")
        self.assertEqual(result["sentence_count"], 1)
        self.assertEqual(result["word_count"], 2)

    def test_decimals_abbreviations_links_and_lists(self):
        text = (
            "Dr. Smith uses 3.14 units, e.g. small samples. See "
            "[the guide](https://example.org/a.b). Visit https://example.org/a.b.\n\n"
            "1. Turn on power\n2. Check the status\n- Stop now."
        )
        result = writing.check_text(text, "relaxed")
        self.assertEqual(result["sentence_count"], 6)
        self.assertEqual(result["paragraph_count"], 4)
        self.assertEqual(result["word_count"], 20)

    def test_description_paragraph_limit_and_wrapping(self):
        text = "One. Two.\nThree. Four. Five. Six. Seven."
        result = writing.check_text(text, "description")
        self.assertEqual(result["findings"][0]["sentence_count"], 7)
        self.assertEqual(writing.check_text(text, "relaxed")["findings"], [])
        self.assertEqual(writing.check_text("One. Two. Three. Four. Five. Six.", "description")["findings"], [])

    def test_setext_heading_and_empty(self):
        result = writing.check_text("Ignored title\n=====\n\n`code only`\n\n", "relaxed")
        self.assertEqual(result["sentence_count"], 0)
        self.assertEqual(result["word_count"], 0)

    def test_initials_hyphens_quotes_and_continued_list(self):
        text = 'J. Smith said, "Use the well-tested U.S. device." Next step!\n\n- Turn on\n  the power.'
        result = writing.check_text(text, "procedure")
        self.assertEqual(result["sentence_count"], 3)
        self.assertEqual(result["word_count"], 14)

    def test_longer_fence_and_inline_backticks(self):
        text = "````\n```\nNot prose.\n````\nUse ``x ` y`` safely."
        result = writing.check_text(text, "relaxed")
        self.assertEqual(result["word_count"], 2)
        self.assertEqual(result["sentence_count"], 1)

    def test_cli_advisory_and_explicit_failure_preserve_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "input.md"
            original = (" ".join(["word"] * 26) + ".\r\n").encode()
            source.write_bytes(original)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["check", str(source), "--json"]), 0)
            self.assertEqual(len(json.loads(output.getvalue())["findings"]), 1)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["check", str(source), "--fail-on-findings"]), 1)
            self.assertEqual(source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
