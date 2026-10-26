"""The static build of the two recorded configurations (the Portugal dashboard and the Nordic transfer demo): the web files, one
catalog, one record per member, nothing a browser must not get, relative URLs only, a refusal instead of an empty site. Offline."""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from build_site import SourceUnavailable, build  # noqa: E402
from listing import catalog, config  # noqa: E402

NORDIC = ROOT / "config" / "nordic-dashboard.yaml"


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.builds = {}
        for name, path in (("portugal", None), ("nordic", str(NORDIC))):
            out = Path(cls.tmp.name) / f"dist-{name}"
            cls.builds[name] = (out, build(out, config.load(ROOT, path)))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_site_has_the_page_the_data_and_no_jekyll(self):
        for name, (out, cat) in self.builds.items():
            for file in ("index.html", "app.js", "views.js", "styles.css", ".nojekyll", "data/catalog.json", "data/generation.json", "data/capabilities.json"):
                self.assertTrue((out / file).is_file(), f"{name}: {file}")
            self.assertEqual(json.loads((out / "data" / "catalog.json").read_text(encoding="utf-8"))["counts"], cat["counts"], name)
        portugal, nordic = self.builds["portugal"][1], self.builds["nordic"][1]
        self.assertEqual((portugal["source_kind"], portugal["generation"]["data_origin"], portugal["counts"]["usable"], portugal["counts"]["not_usable"]), ("pids", "real", 3, 0))
        self.assertEqual((nordic["source_kind"], nordic["generation"]["data_origin"], nordic["counts"]["usable"], nordic["counts"]["not_usable"]), ("community", "real", 9, 0))

    def test_every_member_has_a_record_file_and_every_snapshot_item_is_recorded(self):
        for name, (out, cat) in self.builds.items():
            rows = cat["rows"] + cat["not_usable"]
            for row in rows:
                path = out / cat["records"].replace("{key}", row["key"])
                self.assertTrue(path.is_file(), f"{name}: {row['pid']}")
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["pid"], row["pid"])
            self.assertEqual(len(list((out / "data" / "records").glob("*.json"))), len(rows), name)
            generation = json.loads((out / "data" / "generation.json").read_text(encoding="utf-8"))
            self.assertEqual({i["status"] for i in generation["items"]}, {"recorded"}, name)
            self.assertEqual(len(generation["items"]), len(rows), name)

    def test_the_build_copies_metadata_only_and_uses_relative_urls(self):
        for name, (out, _) in self.builds.items():
            names = {p.name for p in out.rglob("*") if p.is_file()}
            self.assertNotIn("ro-crate-metadata.json", names, name)
            self.assertFalse(any(n.endswith((".fgb", ".pmtiles", ".pdf", ".gpkg")) for n in names), names)
            for file in ("index.html", "app.js", "views.js", "styles.css"):
                text = (out / file).read_text(encoding="utf-8")
                self.assertIsNone(re.search(r'(href|src)="/[^/]', text), f"{name}: {file} has an absolute URL")   # any base path works (GitHub Pages)
            self.assertNotIn("@", json.dumps(json.load((out / "data" / "catalog.json").open(encoding="utf-8"))["rows"]), f"{name}: an e-mail address in the catalog rows")

    def test_a_manifest_of_another_shape_is_named_and_its_outcomes_are_unknown(self):
        cfg = config.load(ROOT)
        folder = Path(self.tmp.name) / "old-manifest"
        shutil.copytree(ROOT / cfg["source"]["recorded"], folder)
        (folder / "manifest.json").write_text("[]", encoding="utf-8")                                        # a manifest of another shape (a JSON list)
        cfg["source"]["recorded"] = str(folder)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            build(Path(self.tmp.name) / "dist-old-manifest", cfg)
        self.assertIn("manifest.json does not describe this snapshot; outcomes unknown", err.getvalue())
        generation = json.loads((Path(self.tmp.name) / "dist-old-manifest" / "data" / "generation.json").read_text(encoding="utf-8"))
        self.assertTrue(generation["items"] and all(i["status"] == "unknown" for i in generation["items"]))

    def test_a_source_without_a_recorded_member_is_refused_and_an_unreadable_index_is_named(self):
        cfg = config.load(ROOT)
        empty = Path(self.tmp.name) / "empty"
        (empty / "objects").mkdir(parents=True)
        (empty / "pids.json").write_text("{}", encoding="utf-8")
        cfg["source"]["recorded"] = str(empty)
        out = Path(self.tmp.name) / "dist-refused"
        with self.assertRaises(SourceUnavailable) as ctx:                     # listed by PID but nothing recorded: no member can be shown
            build(out, cfg)
        self.assertIn("none of the 3 members can be shown", str(ctx.exception))
        self.assertFalse(out.exists())
        cfg["source"] = {"kind": "community", "data_origin": "real", "community": "X", "search": ["x"], "recorded": str(empty), "crate_url": "{pid}"}
        with self.assertRaises(SourceUnavailable) as ctx:                     # gathered by community but nothing recorded
            build(out, cfg)
        self.assertIn("no member is recorded", str(ctx.exception))
        self.assertFalse(out.exists())
        cfg["source"]["recorded"] = str(Path(self.tmp.name) / "missing")
        with self.assertRaises(SourceUnavailable):
            build(out, cfg)
        bad = Path(self.tmp.name) / "bad"
        (bad / "objects").mkdir(parents=True)
        (bad / "pids.json").write_text("[1, 2", encoding="utf-8")
        cfg["source"]["recorded"] = str(bad)
        with self.assertRaises(ValueError) as ctx:
            catalog.snapshot_index(ROOT, cfg)
        self.assertIn("pids.json", str(ctx.exception))

    def test_the_catalog_and_the_records_validate_against_their_schemas(self):
        try:
            import jsonschema
        except ImportError:
            if os.environ.get("CI"):
                self.fail("jsonschema is required in CI")
            self.skipTest("jsonschema not installed; the CI job installs it")
        schema_dir = ROOT / "listing" / "schema"
        catalog_schema = json.loads((schema_dir / "catalog.schema.json").read_text(encoding="utf-8"))
        record_schema = json.loads((schema_dir / "resource-record.schema.json").read_text(encoding="utf-8"))
        for name, (out, cat) in self.builds.items():
            jsonschema.validate(cat, catalog_schema)
            for path in (out / "data" / "records").glob("*.json"):
                jsonschema.validate(json.loads(path.read_text(encoding="utf-8")), record_schema)


if __name__ == "__main__":
    unittest.main()
