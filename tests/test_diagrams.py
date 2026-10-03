"""Semantic, geometric, accessibility and hostile-input tests for native diagrams."""
from copy import deepcopy
import math
from typing import Any
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from ste_promax.diagrams import DIAGRAM_SCHEMA, diagram_svg, render_diagram, validate_diagram


NS = {"s": "http://www.w3.org/2000/svg"}


def flow() -> dict[str, Any]:
    return deepcopy(DIAGRAM_SCHEMA["example"])


def sequence() -> dict[str, Any]:
    return {
        "type": "sequence", "title": "Commit sequence", "description": "Ordered protocol messages.",
        "participants": [{"id": "client", "label": "Client"}, {"id": "store", "label": "Store"}],
        "messages": [
            {"from": "client", "to": "store", "label": "Prepare", "note": "Keep the original revision."},
            {"from": "store", "to": "store", "label": "Validate", "style": "dashed"},
            {"from": "store", "to": "client", "label": "Commit"},
        ],
    }


class DiagramTests(unittest.TestCase):
    def test_schema_shape_and_example(self):
        self.assertEqual(set(DIAGRAM_SCHEMA), {"description", "fields", "example"})
        self.assertIn("32768", DIAGRAM_SCHEMA["description"])
        self.assertIsNone(validate_diagram(flow()))

    def test_validation_is_pure_and_output_deterministic(self):
        for spec in (flow(), sequence()):
            before = deepcopy(spec)
            with patch("builtins.open", side_effect=AssertionError("Unexpected I/O")):
                validate_diagram(spec)
                self.assertEqual(diagram_svg(spec), diagram_svg(deepcopy(spec)))
                self.assertEqual(render_diagram(spec), render_diagram(deepcopy(spec)))
            self.assertEqual(spec, before)

    def test_accessible_name_description_caption_and_scrolling(self):
        spec = flow()
        spec["caption"] = "This is a supplied caption."
        root = ET.fromstring(render_diagram(spec))
        svg = root.find("s:svg", NS)
        self.assertIsNone(svg)  # SVG is inside the scroll region, not an overflowing sibling.
        region = root.find("div")
        assert region is not None
        self.assertEqual(region.get("role"), "region")
        self.assertEqual(region.get("tabindex"), "0")
        self.assertIn("overflow:auto", region.attrib["style"])
        self.assertIn("max-width:100%", region.attrib["style"])
        svg = region.find("s:svg", NS)
        assert svg is not None
        self.assertEqual(svg.get("role"), "img")
        self.assertEqual(svg.get("aria-label"), spec["title"])
        title = svg.find("s:title", NS)
        description = svg.find("s:desc", NS)
        caption = root.find("figcaption")
        assert title is not None
        assert description is not None
        assert caption is not None
        self.assertEqual(title.text, spec["title"])
        self.assertEqual(description.text, spec["description"])
        self.assertIn(spec["caption"], "".join(caption.itertext()))
        self.assertIn("min-width:", svg.attrib["style"])
        self.assertIn("max-width:none", svg.attrib["style"])

    def test_flow_cycles_parallel_and_self_links_keep_every_edge(self):
        spec = flow()
        spec["nodes"].append({"id": "done", "label": "Done", "detail": "Versioned artifact"})
        spec["edges"] += [
            {"from": "draft", "to": "draft", "label": "Self correction"},
            {"from": "draft", "to": "review", "label": "Second submission"},
            {"from": "review", "to": "done", "label": "Accept"},
        ]
        for direction in ("LR", "TB"):
            spec["direction"] = direction
            root = ET.fromstring(diagram_svg(spec))
            groups = root.findall("s:g[@data-edge]", NS)
            self.assertEqual(len(groups), len(spec["edges"]))
            self.assertEqual(len(root.findall("s:g[@data-entity]", NS)), 3)
            paths = []
            for index, (group, edge) in enumerate(zip(groups, spec["edges"]), 1):
                self.assertEqual(group.get("data-edge"), str(index))
                self.assertEqual(group.get("data-from"), edge["from"])
                self.assertEqual(group.get("data-to"), edge["to"])
                title = group.find("s:title", NS)
                polyline = group.find("s:polyline", NS)
                assert title is not None
                assert polyline is not None
                self.assertEqual(title.text, edge["label"])
                paths.append(polyline.get("points"))
                self.assertIsNotNone(group.find("s:polygon", NS))
            self.assertEqual(len(set(paths)), len(paths))

    def test_sequence_order_and_self_message_geometry(self):
        spec = sequence()
        root = ET.fromstring(diagram_svg(spec))
        groups = root.findall("s:g[@data-edge]", NS)
        titles = []
        for group in groups:
            title = group.find("s:title", NS)
            assert title is not None
            titles.append(title.text)
        self.assertEqual(titles, ["Prepare", "Validate", "Commit"])
        self.assertEqual(len(root.findall("s:line[@data-lifeline]", NS)), 2)
        first_y = []
        for group in groups:
            polyline = group.find("s:polyline", NS)
            assert polyline is not None
            points = polyline.attrib["points"].split()
            first_y.append(float(points[0].split(",")[1]))
        self.assertEqual(first_y, sorted(set(first_y)))
        self_polyline = groups[1].find("s:polyline", NS)
        assert self_polyline is not None
        self_points = self_polyline.attrib["points"].split()
        self.assertEqual(len(self_points), 4)
        self.assertGreater(float(self_points[2].split(",")[1]), float(self_points[0].split(",")[1]))
        self.assertIsNotNone(self_polyline.get("stroke-dasharray"))

    def test_visible_equivalent_retains_exact_text_and_order(self):
        for spec in (flow(), sequence()):
            entities = spec.get("nodes", spec.get("participants"))
            links = spec.get("edges", spec.get("messages"))
            assert entities is not None and links is not None
            entities[0]["label"] = "Namespace::" + "TechnicalIdentifier" * 12
            links[0]["label"] = "Operation\nwith\ttabs\rand <exact> & punctuation"
            root = ET.fromstring(render_diagram(spec))
            equivalent = root.find("div[@class='ste-diagram-equivalent']")
            assert equivalent is not None
            text = "".join(equivalent.itertext())
            for entity in entities:
                self.assertIn(entity["label"], text)
                self.assertIn(entity["id"], text)
            rows = equivalent.findall("ol/li")
            self.assertEqual(len(rows), len(links))
            for row, link in zip(rows, links):
                actual = "".join(row.itertext())
                self.assertIn(link["label"], actual)
                if "note" in link:
                    self.assertIn(link["note"], actual)

    def test_wrapping_long_identifiers_unicode_and_newlines(self):
        spec = flow()
        label = "W" * 256
        spec["nodes"][0]["label"] = label
        spec["nodes"][0]["detail"] = "漢字🙂e\u0301 " * 50
        spec["edges"][0]["label"] = "first\nsecond\n" + "Q" * 200
        root = ET.fromstring(diagram_svg(spec))
        node = root.find("s:g[@data-entity='draft']", NS)
        assert node is not None
        text = node.find("s:text", NS)
        assert text is not None
        spans = text.findall("s:tspan", NS)
        self.assertGreater(len(spans), 1)
        self.assertEqual("".join(s.text or "" for s in spans), label)
        self.assertTrue(all(len(s.text or "") <= 20 for s in spans))
        self.assertIn(spec["nodes"][0]["detail"], "".join(ET.fromstring(render_diagram(spec)).itertext()))

    def test_no_ids_or_references_across_repeated_figures(self):
        root = ET.fromstring("<main>" + render_diagram(flow()) * 2 + render_diagram(sequence()) + "</main>")
        for element in root.iter():
            self.assertNotIn("id", element.attrib)
            self.assertNotIn("marker-end", element.attrib)
            self.assertNotIn("href", element.attrib)
            self.assertNotIn("url(", " ".join(element.attrib.values()))

    def test_injection_is_literal_text_in_every_text_surface(self):
        payload = '<script>alert("x")</script>&<!ENTITY x SYSTEM "file:///secret">'
        for spec in (flow(), sequence()):
            spec["title"] = spec["description"] = spec["caption"] = payload
            entities = spec.get("nodes", spec.get("participants"))
            links = spec.get("edges", spec.get("messages"))
            assert entities is not None and links is not None
            entities[0]["label"] = payload
            old_id = entities[0]["id"]
            entities[0]["id"] = payload
            for link in links:
                link["label"] = payload
                for key in ("from", "to"):
                    if link[key] == old_id:
                        link[key] = payload
            if spec["type"] == "flow":
                entities[0]["detail"] = payload
            else:
                links[0]["note"] = payload
            rendered = render_diagram(spec)
            self.assertNotIn("<script>", rendered)
            self.assertNotIn("<!ENTITY", rendered)
            root = ET.fromstring(rendered)
            self.assertIn(payload, "".join(root.itertext()))
            for element in root.iter():
                tag = element.tag.rsplit("}", 1)[-1]
                self.assertNotIn(tag, {"script", "foreignObject", "image", "a", "use", "style"})
                self.assertFalse(any(key.startswith("on") for key in element.attrib))

    def test_coordinates_and_arrowheads_within_canvas_and_outside_nodes(self):
        for spec in (flow(), dict(flow(), direction="TB"), sequence()):
            root = ET.fromstring(diagram_svg(spec))
            width, height = float(root.attrib["width"]), float(root.attrib["height"])
            boxes = []
            for group in root.findall("s:g[@data-entity]", NS):
                box = group.find("s:rect", NS)
                assert box is not None
                boxes.append(tuple(float(box.attrib[k]) for k in ("x", "y", "width", "height")))
            for shape in root.findall(".//s:polyline", NS) + root.findall(".//s:polygon", NS):
                points = [tuple(map(float, p.split(","))) for p in shape.attrib["points"].split()]
                for x, y in points:
                    self.assertTrue(math.isfinite(x) and math.isfinite(y))
                    self.assertTrue(0 <= x <= width and 0 <= y <= height)
                    for bx, by, bw, bh in boxes:
                        self.assertFalse(bx < x < bx + bw and by < y < by + bh)
            for rect in root.findall(".//s:rect", NS):
                x, y = float(rect.get("x", "0")), float(rect.get("y", "0"))
                self.assertLessEqual(x + float(rect.attrib["width"]), width)
                self.assertLessEqual(y + float(rect.attrib["height"]), height)

    def test_zero_flow_edges_and_single_sequence_participant(self):
        spec = flow()
        spec["edges"] = []
        self.assertIn("No directed relationships supplied", render_diagram(spec))
        single = sequence()
        single["participants"] = [single["participants"][1]]
        single["messages"] = [single["messages"][1]]
        self.assertEqual(len(ET.fromstring(diagram_svg(single)).findall("s:g[@data-edge]", NS)), 1)

    def test_arrowhead_tips_land_on_the_named_target(self):
        for spec in (flow(), dict(flow(), direction="TB"), sequence()):
            root = ET.fromstring(diagram_svg(spec))
            boxes = {g.get("data-entity"): g.find("s:rect", NS)
                     for g in root.findall("s:g[@data-entity]", NS)}
            for group in root.findall("s:g[@data-edge]", NS):
                box = boxes[group.get("data-to")]
                assert box is not None
                bx, by, bw, bh = [float(box.attrib[k]) for k in ("x", "y", "width", "height")]
                polygon = group.find("s:polygon", NS)
                assert polygon is not None
                tip = polygon.attrib["points"].split()[0]
                x, y = map(float, tip.split(","))
                if spec["type"] == "sequence":
                    self.assertEqual(x, bx + bw / 2)
                    self.assertGreater(y, by + bh)
                elif spec.get("direction", "LR") == "LR":
                    self.assertEqual(y, by)
                    self.assertTrue(bx < x < bx + bw)
                else:
                    self.assertEqual(x, bx + bw)
                    self.assertTrue(by < y < by + bh)

    def test_dense_self_links_have_distinct_spaced_ports(self):
        for direction in ("LR", "TB"):
            spec = flow()
            spec["direction"] = direction
            spec["edges"] = [{"from": "draft", "to": "draft", "label": str(i)} for i in range(8)]
            root = ET.fromstring(diagram_svg(spec))
            ports = []
            for group in root.findall("s:g[@data-edge]", NS):
                polyline = group.find("s:polyline", NS)
                polygon = group.find("s:polygon", NS)
                assert polyline is not None
                assert polygon is not None
                start = polyline.attrib["points"].split()[0]
                end = polygon.attrib["points"].split()[0]
                axis = 0 if direction == "LR" else 1
                ports.extend(float(p.split(",")[axis]) for p in (start, end))
            ports.sort()
            self.assertEqual(len(set(ports)), 16)
            self.assertTrue(all(b - a >= 13.9 for a, b in zip(ports, ports[1:])))

    def test_maximum_count_long_label_figures_are_not_truncated(self):
        spec = flow()
        spec["nodes"] = [{"id": str(i), "label": "W" * 256, "detail": "d" * 512} for i in range(16)]
        spec["edges"] = [{"from": str(i % 16), "to": str((i + 1) % 16), "label": "e" * 256}
                         for i in range(32)]
        seq = sequence()
        seq["participants"] = [{"id": str(i), "label": "W" * 256} for i in range(12)]
        seq["messages"] = [{"from": str(i % 12), "to": str((i + 1) % 12),
                           "label": "m" * 256, "note": "n" * 512} for i in range(32)]
        for value in (spec, dict(spec, direction="TB"), seq):
            root = ET.fromstring(diagram_svg(value))
            self.assertLessEqual(int(root.attrib["width"]), 32768)
            self.assertLessEqual(int(root.attrib["height"]), 32768)
            self.assertEqual(len(root.findall("s:g[@data-edge]", NS)), 32)
            for rect in root.findall(".//s:rect", NS):
                self.assertLessEqual(float(rect.get("x", "0")) + float(rect.attrib["width"]),
                                     int(root.attrib["width"]))
                self.assertLessEqual(float(rect.get("y", "0")) + float(rect.attrib["height"]),
                                     int(root.attrib["height"]))

    def test_style_is_only_presentation(self):
        spec = flow()
        spec["edges"][0]["style"] = "dashed"
        rendered = render_diagram(spec)
        self.assertIn("not evidence classifications", rendered)
        self.assertIn("[dashed line]", rendered)
        group = ET.fromstring(diagram_svg(spec)).find("s:g[@data-edge='1']", NS)
        assert group is not None
        self.assertEqual(group.get("data-style"), "dashed")
        polyline = group.find("s:polyline", NS)
        assert polyline is not None
        self.assertEqual(polyline.get("stroke-dasharray"), "7 5")


class InvalidDiagramTests(unittest.TestCase):
    def reject(self, spec, pattern="diagram"):
        for entry in (validate_diagram, diagram_svg, render_diagram):
            with self.subTest(entry=entry.__name__), self.assertRaisesRegex(ValueError, pattern):
                entry(spec)

    def test_bad_root_and_missing_fields(self):
        for value in (None, [], "flow", 3, True, {}):
            self.reject(value)
        for key in ("type", "title", "description", "nodes", "edges"):
            spec = flow()
            del spec[key]
            self.reject(spec, key)

    def test_unknown_fields_and_wrong_type_specific_fields(self):
        for key, value in (("html", "<b>"), ("participants", []), ("messages", []), (42, "bad")):
            self.reject(dict(flow(), **{key: value}) if isinstance(key, str) else {**flow(), key: value})
        spec = sequence()
        spec["direction"] = "LR"
        self.reject(spec, "direction")
        for collection, extra in (("nodes", "url"), ("edges", "evidence")):
            spec = flow()
            spec[collection][0][extra] = "untrusted"
            self.reject(spec, extra)
        for collection, extra in (("participants", "detail"), ("messages", "html")):
            spec = sequence()
            spec[collection][0][extra] = "untrusted"
            self.reject(spec, extra)

    def test_invalid_enums_and_malformed_collections(self):
        for key in ("type", "kind", "direction"):
            for value in ("unknown", None, [], {}, True):
                self.reject({**flow(), key: value}, key)
        for key in ("nodes", "edges"):
            for value in (None, {}, "text", [None], [1]):
                self.reject({**flow(), key: value}, key)
        for value in ("inferred", "", None, [], True):
            spec = flow()
            spec["edges"][0]["style"] = value
            self.reject(spec, "style")

    def test_text_type_blank_limits_and_xml_controls(self):
        for value in (None, 3, True, [], {}, "", " \t\n", "x" * 4097, "\0", "\x08", "\ud800", "\ufffe"):
            self.reject({**flow(), "title": value}, "title")
        for collection, field in (("nodes", "label"), ("nodes", "detail"), ("edges", "label")):
            for value in (None, [], "\x01", "x" * 513):
                spec = flow()
                spec[collection][0][field] = value
                self.reject(spec, field)
        spec = sequence()
        spec["messages"][0]["label"] = ""
        self.reject(spec, "label")
        spec["messages"][0]["label"] = "Okay"
        spec["messages"][0]["note"] = "\x0b"
        self.reject(spec, "note")

    def test_duplicates_missing_endpoints_and_malformed_ids(self):
        for template, entities, links in ((flow, "nodes", "edges"), (sequence, "participants", "messages")):
            spec = template()
            spec[entities][1]["id"] = spec[entities][0]["id"]
            self.reject(spec, "duplicate")
            for field in ("from", "to"):
                spec = template()
                spec[links][0][field] = "missing"
                self.reject(spec, "unknown endpoint")
                del spec[links][0][field]
                self.reject(spec, field)
            for value in ("", [], 3, "x" * 129):
                spec = template()
                spec[entities][0]["id"] = value
                self.reject(spec, "id")

    def test_explicit_size_bounds(self):
        self.reject({**flow(), "nodes": []}, "nodes")
        self.reject({**flow(), "nodes": [{"id": str(i), "label": str(i)} for i in range(17)]}, "nodes")
        self.reject({**flow(), "edges": flow()["edges"] * 17}, "edges")
        self.reject({**flow(), "edges": [flow()["edges"][0]] * 17}, "incident")
        spec = sequence()
        self.reject({**spec, "messages": []}, "messages")
        self.reject({**spec, "messages": [spec["messages"][0]] * 33}, "messages")
        self.reject({**spec, "participants": [{"id": str(i), "label": str(i)} for i in range(13)]},
                    "participants")

    def test_location_is_preserved_in_errors(self):
        with self.assertRaisesRegex(ValueError, r"sections\[2\]\.nodes\[0\]\.label"):
            validate_diagram({**flow(), "nodes": [{"id": "x", "label": None}]}, "sections[2]")

    def test_extreme_newline_layout_is_explicitly_rejected(self):
        spec = sequence()
        spec["messages"] = [{"from": "client", "to": "store", "label": "x\n" * 128,
                             "note": "x\n" * 256} for _ in range(32)]
        self.reject(spec, "32768 CSS pixels")


if __name__ == "__main__":
    unittest.main()
