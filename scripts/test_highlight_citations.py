"""Behavior checks for the citation ledger and actual saved PDF annotations."""

import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import subprocess
import unittest

import pymupdf

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import highlight_citations as tool


class CitationHighlightTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "sections").mkdir()
        (self.root / "thesis.tex").write_text(r"\input{sections/chapter}", encoding="utf-8")
        self.chapter = self.root / "sections/chapter.tex"
        self.chapter.write_text("中文論述 \\cite{example}.\n", encoding="utf-8")
        (self.root / "references.bib").write_text(
            "@article{example,\n title={A {Nested} Title for Recognition},\n doi={10.1234/example}\n}\n",
            encoding="utf-8",
        )
        self.args = argparse.Namespace(
            root=self.root, manifest="citation_evidence.json", entry=None, bib=None,
            pdf_dir=None, out_dir="annotated_papers", dry_run=False,
        )

    def quiet(self, function):
        with contextlib.redirect_stdout(io.StringIO()):
            return function(self.args)

    def load(self):
        return json.loads((self.root / self.args.manifest).read_text(encoding="utf-8"))

    def write(self, data):
        tool.write_json(self.root / self.args.manifest, data)

    def prepare_pdf(self, text="The source evidence is a complete sentence.", existing_annotation=False):
        self.quiet(tool.scan)
        source = self.root / "unordered 013 document.pdf"
        with pymupdf.open() as doc:
            page = doc.new_page()
            if text:
                page.insert_text((72, 72), text)
            if existing_annotation:
                page.add_text_annot((40, 40), "Original annotation")
            doc.save(source)
        data = self.load()
        data["papers"]["example"]["pdf"] = source.name
        data["citations"][0]["evidence"] = [{"page": 1, "quote": "The source evidence is a complete sentence."}]
        data["citations"][0]["review"] = {"status": "supported"}
        self.write(data)
        return source

    def reports(self):
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.root.glob("annotated_papers/*/report.json"))]

    def test_comments_literals_multikey_and_includes(self):
        self.chapter.write_text(
            r"% ignored \cite{comment}" + "\n"
            + r"10\% kept \citep[see][p. 3]{example,second} % ignore \cite{later_comment}" + "\n"
            + r"\\% ignored \cite{also_comment}" + "\n"
            + r"\verb|\cite{inline}|" + "\n"
            + r"\begin{verbatim}\cite{literal}\end{verbatim}" + "\n"
            + r"\nocite{*}" + "\n",
            encoding="utf-8",
        )
        records = tool.collect_citations(self.root, "thesis.tex")
        self.assertEqual([r["cite_key"] for r in records], ["example", "second"])
        self.assertEqual(records[0]["line"], 2)
        self.assertEqual(tool.read_bib(self.root / "references.bib")["example"]["title"], "A {Nested} Title for Recognition")

    def test_rescan_preserves_evidence_and_archives_changed_claim(self):
        self.prepare_pdf()
        original = self.load()["citations"][0]
        self.chapter.write_text("\n\n" + self.chapter.read_text(encoding="utf-8"), encoding="utf-8")
        self.quiet(tool.scan)
        self.assertEqual(self.load()["citations"][0]["evidence"], original["evidence"])
        self.chapter.write_text("不同的敘述 \\cite{example}.\n", encoding="utf-8")
        self.quiet(tool.scan)
        data = self.load()
        self.assertEqual(data["citations"][0]["evidence"], [])
        self.assertEqual(data["archived_citations"][0]["evidence"], original["evidence"])

    def test_saved_highlights_preserve_source_annotations_and_are_repeatable(self):
        source = self.prepare_pdf(existing_annotation=True)
        original = hashlib.sha256(source.read_bytes()).digest()
        for _ in range(2):
            self.assertEqual(self.quiet(tool.highlight), 0)
        reports = self.reports()
        self.assertEqual(len(reports), 2)
        for report in reports:
            self.assertEqual(report["counts"], {"highlighted": 1})
            with pymupdf.open(report["results"][0]["output"]) as doc:
                page = doc[0]
                annotations = list(page.annots())
                self.assertEqual(len(annotations), 2)
                highlight = next(a for a in annotations if a.type[1] == "Highlight")
                self.assertEqual(highlight.colors["stroke"], [1.0, 1.0, 0.0])
                self.assertIn("中文論述", highlight.info["content"])
                self.assertIn("sections/chapter.tex:1", highlight.info["content"])
        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), original)

    def test_dry_run_does_not_write(self):
        self.prepare_pdf()
        self.args.dry_run = True
        self.assertEqual(self.quiet(tool.highlight), 0)
        self.assertFalse((self.root / "annotated_papers").exists())

    def test_empty_evidence_is_unresolved_and_does_not_modify_the_pdf(self):
        source = self.prepare_pdf()
        original = source.read_bytes()
        data = self.load()
        data["citations"][0]["evidence"] = []
        self.write(data)
        self.args.in_place = True
        self.assertEqual(self.quiet(tool.highlight), 1)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.reports()[0]["counts"], {"no_evidence": 1})

    def test_in_place_alias_mapping_is_rejected_without_losing_annotations(self):
        source = self.prepare_pdf(existing_annotation=True)
        original = source.read_bytes()
        data = self.load()
        evidence = data["citations"][0]["evidence"]
        self.chapter.write_text(r"Two sources \cite{example,alias}.", encoding="utf-8")
        with (self.root / "references.bib").open("a", encoding="utf-8") as bib:
            bib.write("\n@article{alias, title={A Nested Title for Recognition}}\n")
        self.quiet(tool.scan)
        data = self.load()
        data["papers"]["alias"]["pdf"] = source.name
        for row in data["citations"]:
            row["evidence"] = evidence
        self.write(data)
        self.args.in_place = True
        self.assertEqual(self.quiet(tool.highlight), 1)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.reports()[0]["counts"], {"ambiguous_pdf_mapping": 2})

    def test_installed_script_uses_manuscript_cwd_or_explicit_root(self):
        self.prepare_pdf()
        script = Path(tool.__file__).resolve()
        for arguments, cwd in (([], self.root), (["--root", str(self.root)], self.root.parent)):
            result = subprocess.run([sys.executable, str(script), "highlight", "--dry-run", *arguments],
                                    cwd=cwd, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout), {"matched": 1})
        self.assertFalse((self.root / "annotated_papers").exists())

    def test_in_place_deduplicates_references_and_replaces_own_highlights(self):
        source = self.prepare_pdf(existing_annotation=True)
        evidence = self.load()["citations"][0]["evidence"]
        self.chapter.write_text(self.chapter.read_text(encoding="utf-8") * 2, encoding="utf-8")
        self.quiet(tool.scan)
        data = self.load()
        self.assertEqual(len(data["citations"]), 2)
        data["citations"][0]["evidence"] = evidence
        data["citations"][1]["evidence"] = evidence
        data["citations"][1]["review"] = {"status": "partial", "note": "Only partial support"}
        self.write(data)
        self.args.in_place = True
        with pymupdf.open(source) as doc:
            original_text = doc[0].get_text()
        for _ in range(2):
            self.assertEqual(self.quiet(tool.highlight), 0)
            with pymupdf.open(source) as doc:
                page = doc[0]
                annotations = list(page.annots())
                self.assertEqual(len(annotations), 2)
                self.assertEqual(page.get_text(), original_text)
                highlight = next(a for a in annotations if a.type[1] == "Highlight")
                self.assertIn("sections/chapter.tex:1", highlight.info["content"])
                self.assertIn("sections/chapter.tex:2", highlight.info["content"])
                self.assertIn("部分支持", highlight.info["content"])
                self.assertTrue(highlight.info["content"].startswith("【部分支持"))
                for actual, expected in zip(highlight.colors["stroke"], tool.REVIEW_STYLES["partial"]["color"]):
                    self.assertAlmostEqual(actual, expected, places=5)
                self.assertTrue(highlight.info["subject"].startswith(tool.ANNOTATION_SUBJECT))
        for report in self.reports():
            self.assertTrue(report["in_place"])
            self.assertEqual(report["unique_highlights"], 1)
            self.assertEqual(report["counts"], {"highlighted": 2})
        self.assertEqual(list(self.root.glob("annotated_papers/*/*.pdf")), [])

    def test_review_colors_are_saved_and_updated_without_stacking(self):
        source = self.prepare_pdf(existing_annotation=True)
        self.args.in_place = True
        for state in ("partial", "inferred", "supported"):
            data = self.load()
            data["citations"][0]["review"] = {"status": state}
            self.write(data)
            self.assertEqual(self.quiet(tool.highlight), 0)
            with pymupdf.open(source) as doc:
                page = doc[0]
                annotations = list(page.annots())
                self.assertEqual(len(annotations), 2)
                highlight = next(a for a in annotations if a.type[1] == "Highlight")
                for actual, expected in zip(highlight.colors["stroke"], tool.REVIEW_STYLES[state]["color"]):
                    self.assertAlmostEqual(actual, expected, places=5)
                self.assertIn(f"Highlight review: {state}", highlight.info["content"])

    def test_in_place_quote_failure_leaves_whole_source_unchanged(self):
        source = self.prepare_pdf(existing_annotation=True)
        original = source.read_bytes()
        data = self.load()
        data["citations"][0]["evidence"].append({"page": 1, "quote": "Missing evidence"})
        self.write(data)
        self.args.in_place = True
        self.assertEqual(self.quiet(tool.highlight), 1)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.reports()[0]["counts"], {"pdf_not_written": 1, "quote_not_found": 1})

    def test_rescan_preserves_manual_review(self):
        self.prepare_pdf()
        data = self.load()
        review = {"status": "partial", "note": "Some thesis details exceed this quotation."}
        data["citations"][0]["review"] = review
        self.write(data)
        self.quiet(tool.scan)
        self.assertEqual(self.load()["citations"][0]["review"], review)

    def test_annotation_uses_current_line_after_blank_line_insertion(self):
        self.prepare_pdf()
        self.chapter.write_text("\n\n" + self.chapter.read_text(encoding="utf-8"), encoding="utf-8")
        self.assertEqual(self.quiet(tool.highlight), 0)
        with pymupdf.open(self.reports()[0]["results"][0]["output"]) as doc:
            page = doc[0]
            self.assertIn("sections/chapter.tex:3", next(page.annots()).info["content"])

    def test_multiline_and_line_end_hyphenation(self):
        self.prepare_pdf("Our recogni-\ntion method detects unknown samples.")
        data = self.load()
        data["citations"][0]["evidence"] = [{"page": 1, "quote": "Our recognition method detects unknown samples."}]
        self.write(data)
        self.assertEqual(self.quiet(tool.highlight), 0)
        self.assertGreater(self.reports()[0]["results"][0]["quads"], 1)

    def test_missing_quote_page_and_invalid_evidence_are_reported(self):
        self.prepare_pdf()
        data = self.load()
        data["citations"][0]["evidence"] = [
            {"page": 1, "quote": "This sentence is absent."},
            {"page": 2, "quote": "The source evidence"},
            {"page": True, "quote": "The source evidence"},
            {"page": 1, "quote": ""},
        ]
        self.write(data)
        self.assertEqual(self.quiet(tool.highlight), 1)
        self.assertEqual(self.reports()[0]["counts"], {"quote_not_found": 1, "page_out_of_range": 1, "invalid_evidence": 2})
        self.assertEqual(list(self.root.glob("annotated_papers/*/*.pdf")), [])

    def test_no_text_layer_is_reported(self):
        self.prepare_pdf(text="")
        self.assertEqual(self.quiet(tool.highlight), 1)
        self.assertEqual(self.reports()[0]["counts"], {"no_text_layer": 1})

    def test_changed_citation_is_never_highlighted_from_old_evidence(self):
        self.prepare_pdf()
        self.chapter.write_text("新的不同主張 \\cite{example}.\n", encoding="utf-8")
        self.assertEqual(self.quiet(tool.highlight), 1)
        self.assertEqual(self.reports()[0]["counts"], {"untracked_citation": 1, "stale_citation": 1})

    def test_filename_independent_candidates_require_mapping_confirmation(self):
        self.prepare_pdf("A Nested Title for Recognition\nA paper about recognition.")
        self.args.pdf_dir = str(self.root)
        self.quiet(tool.scan)
        paper = self.load()["papers"]["example"]
        self.assertEqual(paper["candidates"][0]["pdf"], "unordered 013 document.pdf")
        data = self.load()
        data["papers"]["example"]["pdf"] = ""
        self.write(data)
        self.quiet(tool.scan)
        self.assertEqual(self.load()["papers"]["example"]["pdf"], "")
        self.assertEqual(self.quiet(tool.highlight), 1)
        self.assertEqual(self.reports()[0]["counts"], {"missing_pdf": 1})


if __name__ == "__main__":
    unittest.main()
