"""Standalone chart contracts; no renderer, browser, or external dependencies."""
from copy import deepcopy
from decimal import ROUND_UP, localcontext
from html.parser import HTMLParser
import math
import re
import sys
import unittest
import xml.etree.ElementTree as ET

from ste_promax.charts import CHART_SCHEMA, chart_svg, render_chart, validate_chart


NS = {"s": "http://www.w3.org/2000/svg"}


def example(chart_type="bar"):
    spec = deepcopy(CHART_SCHEMA["example"])
    spec["type"] = chart_type
    return spec


class TableReader(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == "tr":
            self.row = []
        if tag in ("td", "th"):
            self.cell = ""

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self.row.append(self.cell)
            self.cell = None
        if tag == "tr":
            self.rows.append(self.row)
            self.row = None


class ChartValidationTests(unittest.TestCase):
    def reject(self, spec, message=None):
        with self.assertRaisesRegex(ValueError, message or "chart"):
            validate_chart(spec)
        for render in (chart_svg, render_chart):
            with self.assertRaises(ValueError):
                render(spec)

    def test_schema_example_and_pure_validation(self):
        spec = example()
        original = deepcopy(spec)
        self.assertEqual(set(CHART_SCHEMA), {"description", "fields", "example"})
        self.assertIsNone(validate_chart(spec))
        chart_svg(spec)
        render_chart(spec)
        self.assertEqual(spec, original)
        del spec["kind"]
        validate_chart(spec)

    def test_missing_required_fields(self):
        for field in ("type", "title", "description", "categories", "series", "y_label"):
            with self.subTest(field=field):
                spec = example()
                del spec[field]
                self.reject(spec, field)

    def test_unknown_fields_and_types(self):
        for bad in (None, [], "chart", 3):
            self.reject(bad)
        for field, bad in (("kind", "graph"), ("kind", []), ("type", "pie"), ("type", []),
                           ("onload", "evil()"), (1, "bad"), ("domain", "0, 20")):
            spec = example()
            spec[field] = bad
            self.reject(spec)
        spec = example()
        spec["series"][0]["color"] = "red"
        self.reject(spec, "unsupported")

    def test_text_fields_and_xml_characters(self):
        for field in ("title", "description", "y_label", "x_label", "caption", "uncertainty_label"):
            for bad in (None, [], 42, "", " \n ", "evil\x00", "\ud800", "\ufffe"):
                with self.subTest(field=field, bad=repr(bad)):
                    spec = example()
                    spec[field] = bad
                    self.reject(spec, field)
        spec = example()
        spec["title"] = "x" * 161
        self.reject(spec, "160")
        spec = example()
        spec["description"] = "x" * 1201
        self.reject(spec, "1200")

    def test_shape_limits(self):
        for field, bad in (("categories", []), ("categories", ["x"] * 41), ("categories", "x"),
                           ("series", []), ("series", [{}] * 7), ("series", {})):
            spec = example()
            spec[field] = bad
            self.reject(spec, field)
        for bad in (["one"], [1, 2], ["x" * 121, "ok"]):
            spec = example()
            spec["categories"] = bad
            self.reject(spec)
        for bad in (None, "series", [], {"values": [1, 2]}, {"label": "label"},
                    {"label": "label", "values": [1]}, {"label": "label", "values": (1, 2)}):
            spec = example()
            spec["series"] = [bad]
            self.reject(spec)

    def test_reject_duplicate_series_labels(self):
        spec = example()
        spec["series"] *= 2
        self.reject(spec, "duplicate")

    def test_numbers_are_finite_not_boolean_or_coerced(self):
        for bad in (True, False, "12", {}, [], float("nan"), float("inf"), -float("inf"), 10**400):
            with self.subTest(bad=repr(bad)):
                spec = example()
                spec["series"][0]["values"][0] = bad
                self.reject(spec, "series")

    def test_valid_intervals_and_missing_intervals(self):
        spec = example()
        spec["uncertainty_label"] = "Source minimum and maximum"
        spec["categories"] = ["A", "B", "C"]
        spec["series"] = [{"label": "Measured", "values": [3, None, 0],
                           "lower": [1, None, None], "upper": [4, None, None]}]
        validate_chart(spec)
        self.assertEqual(len(ET.fromstring(chart_svg(spec)).findall(".//*[@class='chart-interval']")), 1)

    def test_interval_validation(self):
        base = example()
        base["uncertainty_label"] = "Reported bounds"
        base["series"][0].update(lower=[10, 17], upper=[14, 20])
        for field, value in (("lower", [None, 17]), ("upper", [None, 20]),
                             ("lower", [13, 17]), ("upper", [11, 20]),
                             ("lower", [15, 17]), ("lower", [1]), ("upper", None),
                             ("values", [None, 18]), ("lower", [True, 17]),
                             ("upper", [float("inf"), 20])):
            with self.subTest(field=field, value=value):
                spec = deepcopy(base)
                spec["series"][0][field] = value
                self.reject(spec)
        for field in ("lower", "upper"):
            spec = deepcopy(base)
            del spec["series"][0][field]
            self.reject(spec, "both")
        del base["uncertainty_label"]
        self.reject(base, "uncertainty_label")

    def test_domains_require_order_and_finite_numbers(self):
        for domain in ([], [0], [0, 1, 2], [0, None], [True, 20], ["0", 20],
                       [0, float("inf")], [20, 0], [0, 0], [1e308, -1e308]):
            spec = example()
            spec["domain"] = domain
            self.reject(spec, "domain")

    def test_bar_domain_cannot_truncate_zero(self):
        spec = example()
        spec["domain"] = [10, 20]
        self.reject(spec, "zero")
        spec["series"][0]["values"] = [-12, -18]
        spec["domain"] = [-20, -10]
        self.reject(spec, "zero")

    def test_domain_cannot_clip_values_or_intervals(self):
        for chart_type in ("bar", "line"):
            for domain in ([0, 17], [13, 20], [-20, -1]):
                spec = example(chart_type)
                spec["domain"] = domain
                self.reject(spec)
            spec = example(chart_type)
            spec["domain"] = [0, 20]
            spec["uncertainty_label"] = "Reported bounds"
            spec["series"][0].update(lower=[-1, 10], upper=[15, 22])
            self.reject(spec, "clips")

    def test_unrepresentable_domain_span_rejected(self):
        for explicit in (False, True):
            spec = example("line")
            spec["series"][0]["values"] = [-1e308, 1e308]
            if explicit:
                spec["domain"] = [-1e308, 1e308]
            self.reject(spec, "unrepresentable")

    def test_location_is_preserved(self):
        spec = example()
        spec["series"][0]["values"][0] = True
        with self.assertRaisesRegex(ValueError, r"input.sections\[2\].series\[0\].values\[0\]"):
            validate_chart(spec, "input.sections[2]")


class ChartRenderingTests(unittest.TestCase):
    def test_svg_is_well_formed_accessibly_named_and_self_contained(self):
        spec = example()
        root = ET.fromstring(chart_svg(spec))
        self.assertEqual(root.attrib["role"], "img")
        self.assertEqual(root.attrib["aria-label"], spec["title"])
        self.assertEqual(root.find("s:title", NS).text, spec["title"])
        self.assertIn(spec["description"], root.find("s:desc", NS).text)
        allowed = {"svg", "title", "desc", "rect", "text", "path", "g", "circle", "polygon"}
        for element in root.iter():
            self.assertIn(element.tag.split("}")[-1], allowed)
            for key in element.attrib:
                self.assertFalse(key.lower().startswith("on"))
                self.assertNotIn(key, ("href", "id"))
        self.assertNotRegex(chart_svg(spec), r"(?i)<(?:script|foreignObject)|url\(")

    def test_exact_table_preserves_every_value_and_bound(self):
        spec = example("line")
        spec["categories"] = ["First", "Next", "Last", "Unknown"]
        spec["series"] = [
            {"label": "Observed", "values": [1.2345678901234567, 0, -0.0, None],
             "lower": [1.234567890123456, 0, None, None],
             "upper": [1.234567890123457, 0, None, None]},
            {"label": "Other", "values": [123456789012345678901, 1e-300, -2, None]},
        ]
        spec["uncertainty_label"] = "Source range, not a statistical estimate"
        rows = TableReader(render_chart(spec)).rows
        self.assertEqual(len(rows), 9)
        for j, category in enumerate(spec["categories"]):
            for i, series in enumerate(spec["series"]):
                expected = [category, f'S{i+1}: {series["label"]}']
                for field in ("values", "lower", "upper"):
                    expected.append("Not supplied" if field not in series else
                                    "Missing" if series[field][j] is None else str(series[field][j]))
                self.assertEqual(rows[1+j*2+i], expected)

    def test_bars_distinguish_missing_zero_and_negative(self):
        spec = example()
        spec["categories"] = ["Zero", "Missing", "Negative", "Positive"]
        spec["series"][0]["values"] = [0, None, -5, 10]
        root = ET.fromstring(chart_svg(spec))
        bars = root.findall(".//*[@class='chart-bar']")
        self.assertEqual(len(bars), 3)
        self.assertEqual(float(bars[0].attrib["height"]), 0)
        self.assertGreater(float(bars[1].attrib["height"]), 0)
        self.assertGreater(float(bars[1].attrib["y"]), float(bars[2].attrib["y"]))
        self.assertEqual(len(root.findall(".//*[@class='chart-zero']")), 1)
        self.assertIn("S1 missing", "".join(root.itertext()))
        self.assertEqual([row[2] for row in TableReader(render_chart(spec)).rows[1:]],
                         ["0", "Missing", "-5", "10"])

    def test_positive_and_negative_bars_include_zero(self):
        for values in ([12, 18], [-12, -18], [0, 0]):
            spec = example()
            spec["series"][0]["values"] = values
            root = ET.fromstring(chart_svg(spec))
            self.assertEqual(len(root.findall(".//*[@class='chart-zero']")), 1)
            self.assertIn("Y-axis domain:", "".join(root.itertext()))

    def test_line_breaks_at_each_missing_value(self):
        spec = example("line")
        spec["categories"] = list("ABCDEFGH")
        spec["series"][0]["values"] = [None, 1, 2, None, 0, 4, None, 5]
        root = ET.fromstring(chart_svg(spec))
        path = root.find(".//*[@class='chart-line']").attrib["d"]
        self.assertEqual(path.count("M"), 3)
        self.assertEqual(path.count("L"), 2)
        self.assertEqual(len(root.findall(".//*[@class='chart-point']")), 5)
        self.assertEqual("".join(root.itertext()).count("S1 missing"), 3)

    def test_line_nonzero_domain_is_explicitly_labelled(self):
        spec = example("line")
        spec["domain"] = [10, 20]
        root = ET.fromstring(chart_svg(spec))
        self.assertFalse(root.findall(".//*[@class='chart-zero']"))
        self.assertIn("Y-axis domain: 10 to 20.", "".join(root.itertext()))
        self.assertIn(spec["y_label"], "".join(root.itertext()))

    def test_equal_tiny_huge_and_missing_values_have_finite_geometry(self):
        datasets = ([0, 0], [3, 3], [-3, -3], [1e-300, 2e-300],
                    [5e-324, 1e-323], [-5e-324, 5e-324], [None, None],
                    [sys.float_info.max, sys.float_info.max],
                    [int(sys.float_info.max), int(sys.float_info.max)],
                    [-sys.float_info.max, -sys.float_info.max],
                    [1e308, 1.0000000000000002e308], [10**300, 10**300 + 1])
        for chart_type in ("bar", "line"):
            for values in datasets:
                with self.subTest(chart_type=chart_type, values=values):
                    spec = example(chart_type)
                    spec["series"][0]["values"] = values
                    root = ET.fromstring(chart_svg(spec))
                    for element in root.iter():
                        for key, value in element.attrib.items():
                            if key in ("x", "y", "cx", "cy", "width", "height", "r"):
                                self.assertTrue(math.isfinite(float(value)))
                            if key in ("d", "points", "viewBox"):
                                self.assertNotRegex(value.lower(), "nan|inf")
                    self.assertEqual([row[2] for row in TableReader(render_chart(spec)).rows[1:]],
                                     ["Missing" if v is None else str(v) for v in values])

    def test_single_category_has_visible_marker(self):
        for chart_type in ("line", "bar"):
            spec = example(chart_type)
            spec["categories"] = ["Only"]
            spec["series"][0]["values"] = [7]
            root = ET.fromstring(chart_svg(spec))
            self.assertEqual(len(root.findall(".//*[@class='chart-point']")), 1)

    def test_tiny_values_retain_geometric_variation(self):
        spec = example()
        spec["series"][0]["values"] = [5e-324, 1e-323]
        bars = ET.fromstring(chart_svg(spec)).findall(".//*[@class='chart-bar']")
        self.assertEqual([float(bar.attrib["height"]) for bar in bars], [150, 300])

    def test_close_large_line_values_use_disclosed_offset(self):
        spec = example("line")
        spec["series"][0]["values"] = [10**30, 10**30 + 4]
        root = ET.fromstring(chart_svg(spec))
        text = " ".join(root.itertext())
        self.assertIn(f"Y tick labels are offsets from {10**30}", text)
        self.assertIn("add this base", text)
        self.assertEqual(len(root.findall(".//*[@class='chart-point']")), 2)

    def test_tick_labels_do_not_collapse_for_a_close_nonzero_domain(self):
        spec = example("line")
        spec["series"][0]["values"] = [100000, 100001]
        spec["domain"] = [100000, 100001]
        root = ET.fromstring(chart_svg(spec))
        ticks = [node.text for node in root.findall("s:text", NS)
                 if node.attrib.get("text-anchor") == "end"]
        self.assertEqual(len(ticks), 5)
        self.assertEqual(len(set(ticks)), 5)

    def test_multiseries_has_noncolor_encodings(self):
        spec = example("line")
        spec["series"] = [{"label": f"Series {i}", "values": [i, i+1]} for i in range(6)]
        root = ET.fromstring(chart_svg(spec))
        lines = root.findall(".//*[@class='chart-line']")
        self.assertEqual(len({line.attrib["stroke-dasharray"] for line in lines}), 6)
        points = root.findall(".//*[@class='chart-point']")
        signatures = {(list(point)[-1].tag, list(point)[-1].attrib.get("points", ""),
                       list(point)[-1].attrib.get("d", "")) for point in points}
        self.assertGreaterEqual(len(signatures), 6)
        for i in range(6):
            self.assertIn(f"S{i+1}: Series {i}", "".join(root.itertext()))

    def test_uncertainty_is_source_provided_and_not_invented(self):
        spec = example()
        self.assertNotIn('class="chart-interval"', render_chart(spec))
        spec["uncertainty_label"] = "Source-reported minimum and maximum"
        spec["series"][0].update(lower=[10, 15], upper=[13, 21])
        result = render_chart(spec)
        self.assertIn("Source-provided uncertainty:", result)
        self.assertIn(spec["uncertainty_label"], result)
        self.assertIn("No confidence interval is inferred.", result)
        self.assertEqual(result.count('class="chart-interval"'), 2)

    def test_uncertainty_label_without_arrays_is_not_discarded(self):
        spec = example()
        spec["uncertainty_label"] = "Measurement uncertainty was not quantified"
        result = render_chart(spec)
        self.assertIn(spec["uncertainty_label"], result)
        self.assertIn("No interval arrays were supplied.", result)
        self.assertNotIn('class="chart-interval"', result)

    def test_all_missing_chart_discloses_no_observations(self):
        spec = example("line")
        spec["series"][0]["values"] = [None, None]
        result = render_chart(spec)
        self.assertIn("No observed values are available", result)
        self.assertNotIn('class="chart-point"', result)
        self.assertNotIn('class="chart-line"', result)

    def test_hostile_strings_remain_plain_text_in_all_surfaces(self):
        hostile = '<script>alert("x")</script> & </style><img src=x onerror="bad">'
        spec = example()
        for field in ("title", "description", "y_label", "x_label", "caption", "uncertainty_label"):
            spec[field] = hostile
        spec["categories"] = [hostile, "safe"]
        spec["series"][0]["label"] = hostile
        spec["series"][0].update(lower=[10, 15], upper=[13, 21])
        result = render_chart(spec)
        parser = TableReader(result)
        self.assertNotIn("script", [tag for tag, _ in parser.tags])
        self.assertNotIn("img", [tag for tag, _ in parser.tags])
        for _, attrs in parser.tags:
            self.assertFalse(any(key.startswith("on") for key in attrs))
        self.assertEqual(parser.rows[1][0], hostile)
        self.assertEqual(parser.rows[1][1], "S1: " + hostile)
        self.assertEqual(ET.fromstring(chart_svg(spec)).find("s:title", NS).text, hostile)

    def test_long_labels_wrap_without_dropping_content(self):
        spec = example()
        spec["categories"] = ["W" * 120, "量" * 120]
        spec["series"][0]["label"] = "Long " * 31
        root = ET.fromstring(chart_svg(spec))
        text_nodes = [node.text or "" for node in root.findall("s:text", NS)]
        self.assertEqual("".join(t for t in text_nodes if set(t) == {"W"}), "W" * 120)
        self.assertEqual("".join(t for t in text_nodes if set(t) == {"量"}), "量" * 120)
        self.assertGreater(len([t for t in text_nodes if set(t) == {"量"}]), 1)
        self.assertEqual(TableReader(render_chart(spec)).rows[1][0], "W" * 120)

    def test_full_size_limit_is_bounded_and_scrollable(self):
        spec = example("line")
        spec["categories"] = [f"Category {i}" for i in range(40)]
        spec["series"] = [{"label": f"Series {i}", "values": [i]*40} for i in range(6)]
        root = ET.fromstring(chart_svg(spec))
        self.assertLess(float(root.attrib["width"]), 16000)
        parser = TableReader(render_chart(spec))
        self.assertEqual(len(parser.rows), 241)
        regions = [attrs for tag, attrs in parser.tags if attrs.get("role") == "region"]
        self.assertEqual(len(regions), 2)
        self.assertTrue(all(attrs["tabindex"] == "0" and attrs["aria-label"] for attrs in regions))
        self.assertIn("overflow:auto", render_chart(spec))
        self.assertIn("max-width:none", chart_svg(spec))
        self.assertIn(":focus-visible", render_chart(spec))

    def test_all_styles_are_scoped_and_no_duplicate_ids(self):
        result = render_chart(example())
        stylesheet = re.search(r"<style>(.*?)</style>", result, re.S).group(1)
        for rule in stylesheet.split("}"):
            if "{" in rule:
                for selector in rule.split("{")[0].split(","):
                    self.assertTrue(selector.strip().startswith(".ste-chart"))
        self.assertNotIn(" id=", result + result)

    def test_deterministic_output_independent_of_decimal_context(self):
        spec = example("line")
        spec["series"][0]["values"] = [10**100, 10**100 + 2]
        expected = render_chart(spec)
        with localcontext() as context:
            context.prec = 6
            context.rounding = ROUND_UP
            context.Emax = 10
            context.Emin = -10
            self.assertEqual(render_chart(spec), expected)
        self.assertEqual(render_chart(deepcopy(spec)), expected)


if __name__ == "__main__":
    unittest.main()
