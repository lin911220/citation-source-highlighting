"""Build a LaTeX citation evidence ledger and highlight verified PDF quotations.

Run from the thesis directory:
    python scripts/highlight_citations.py scan
    python scripts/highlight_citations.py scan --pdf-dir "D:/My papers"
    python scripts/highlight_citations.py highlight --dry-run
    python scripts/highlight_citations.py highlight
    python scripts/highlight_citations.py highlight --in-place

Only literal source quotations are matched. This does not infer which source
passage supports a paraphrase. Copies are the default; --in-place updates the
mapped PDFs after validating all quotations for each paper.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unicodedata
from difflib import SequenceMatcher


ROOT = Path.cwd()
ANNOTATION_SUBJECT = "thesis-citation:"
REVIEW_STYLES = {
    "supported": {"label": "有原文支持", "color": (1, 1, 0), "priority": 0},
    "inferred": {"label": "作者推論", "color": (0.65, 0.35, 1), "priority": 2},
    "partial": {"label": "部分支持／需釐清", "color": (1, 0.55, 0), "priority": 3},
    "unsupported": {"label": "未獲支持", "color": (1, 0.25, 0.25), "priority": 4},
    "unreviewed": {"label": "尚未判定支持關係", "color": (0.65, 0.65, 0.65), "priority": 1},
}


def highlight_review(records) -> str:
    """A shared passage takes the most cautionary linked citation status."""
    states = [r.get("review", {}).get("status", "unreviewed") for r in records]
    states = [s if s in REVIEW_STYLES else "unreviewed" for s in states]
    return max(states, key=lambda s: REVIEW_STYLES[s]["priority"], default="unreviewed")
CITE = re.compile(
    r"\\(?:cite|citep|citet|citealp|citealt|citeauthor|citeyear|citeyearpar|"
    r"parencite|textcite|autocite|footcite|smartcite|supercite|nocite)"
    r"\*?\s*(?:\[[^\]]*\]\s*)*\{([^{}]+)\}", re.I
)
INCLUDE = re.compile(r"\\(?:input|include)\s*\{([^{}]+)\}")
BIB_ENTRY = re.compile(r"(?im)^\s*@([a-z]+)\s*\{\s*([^,\s]+)\s*,")


def short_claim(record: dict, limit: int = 120) -> str:
    """The thesis sentence for a citation, with TeX markup reduced to plain text."""
    text = record.get("claim") or record.get("context", "")

    def plain(part: str) -> str:
        part = re.sub(r"\\(?:cite\w*|label)\*?\s*(?:\[[^\]]*\]\s*)*\{[^{}]*\}", "", part)
        part = re.sub(r"\\(?:ref|eqref|autoref|cref)\s*\{([^{}]*)\}", r"[\1]", part)
        part = re.sub(r"\\(?:begin|end)\s*\{[^{}]*\}(?:\{[^{}]*\})?", " ", part)
        part = re.sub(r"\\(?:textbf|textit|emph|mathrm|text|textsc)\s*\{([^{}]*)\}", r"\1", part)
        part = re.sub(r"\\\\|\\(?:midrule|toprule|bottomrule|hline|item)", " ", part)
        part = re.sub(r"\s*&\s*", "｜", part)
        part = re.sub(r"\\[A-Za-z]+\*?", "", part)
        return part.replace("~", " ").replace("{", "").replace("}", "")

    # Math stays as written TeX; only surrounding prose is simplified.
    pieces = re.split(r"(\$\$.*?\$\$|\$[^$]*\$)", text, flags=re.S)
    text = "".join(p if p.startswith("$") else plain(p) for p in pieces)
    text = re.sub(r"\s+([，。、；：,.])", r"\1", " ".join(text.split())).strip("｜ ")
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def resolve(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def mask_tex(text: str) -> str:
    """Mask comments and literal examples while preserving offsets and lines."""
    def blank(match: re.Match) -> str:
        return re.sub(r"[^\n]", " ", match.group())

    text = re.sub(
        r"\\begin\{(verbatim\*?|lstlisting|minted|comment)\}.*?\\end\{\1\}",
        blank, text, flags=re.S,
    )
    text = re.sub(r"\\verb\*?([^\w\s]).*?\1", blank, text)
    return _mask_comments(text)


def _mask_comments(text: str) -> str:
    chars = list(text)
    for match in re.finditer("%", text):
        pos = match.start() - 1
        slashes = 0
        while pos >= 0 and text[pos] == "\\":
            slashes += 1
            pos -= 1
        if slashes % 2 == 0:
            end = text.find("\n", match.start())
            end = end if end >= 0 else len(text)
            chars[match.start():end] = " " * (end - match.start())
    return "".join(chars)


def bib_field(body: str, field: str) -> str:
    match = re.search(r"\b" + field + r"\s*=\s*", body, re.I)
    if not match:
        return ""
    start = match.end()
    if start >= len(body):
        return ""
    if body[start] == "{":
        depth = 1
        for pos in range(start + 1, len(body)):
            if body[pos] in "{}" and body[pos - 1] != "\\":
                depth += 1 if body[pos] == "{" else -1
                if depth == 0:
                    return body[start + 1:pos]
    elif body[start] == '"':
        end = re.search(r'(?<!\\)"', body[start + 1:])
        if end:
            return body[start + 1:start + 1 + end.start()]
    return body[start:].split(",", 1)[0].strip()


def read_bib(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    entries = list(BIB_ENTRY.finditer(text))
    result = {}
    for index, match in enumerate(entries):
        if match[1].lower() in {"comment", "string", "preamble"}:
            continue
        body = text[match.end():entries[index + 1].start() if index + 1 < len(entries) else len(text)]
        result[match[2]] = {name: bib_field(body, name) for name in ("title", "doi")}
    return result


def collect_citations(root: Path, entry: str) -> list[dict]:
    records = []
    visited = set()
    counts = Counter()

    def visit(path: Path) -> None:
        path = path.resolve()
        if path in visited:
            return
        visited.add(path)
        text = mask_tex(path.read_text(encoding="utf-8-sig"))
        source = display_path(path, root)
        for match in CITE.finditer(text):
            # A bibliography-only inclusion does not identify supporting text.
            if match.group().lower().startswith("\\nocite"):
                continue
            boundary = text.rfind("\n\n", 0, match.start())
            start = boundary + 2 if boundary >= 0 else 0
            start = max(0, min(start, match.start()), match.start() - 220)
            end = text.find("\n\n", match.end())
            end = min(end if end >= 0 else len(text), match.end() + 140)
            context = " ".join(text[start:end].split())
            for key in dict.fromkeys(k.strip() for k in match[1].split(",") if k.strip()):
                signature = f"{source}\n{key}\n{context}"
                digest = hashlib.sha256(signature.encode()).hexdigest()[:20]
                counts[digest] += 1
                records.append({
                    "id": f"{digest}-{counts[digest]}", "cite_key": key,
                    "source": source, "line": text.count("\n", 0, match.start()) + 1,
                    "context": context, "evidence": [],
                })
        for match in INCLUDE.finditer(text):
            included = Path(match[1].strip())
            if not included.suffix:
                included = included.with_suffix(".tex")
            # TeX normally resolves includes from the project directory.
            target = root / included
            if not target.exists():
                target = path.parent / included
            if not target.exists():
                raise ValueError(f"Included TeX file does not exist: {target}")
            visit(target)

    visit(resolve(root, entry))
    return records


def pdf_library():
    try:
        import pymupdf
        return pymupdf
    except ImportError as exc:
        raise ValueError("Install the PDF dependency: python -m pip install -r tools/requirements-citations.txt") from exc


def normalized_title(value: str) -> str:
    value = re.sub(r"\\[A-Za-z]+", "", value)
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def find_candidates(directory: Path, papers: dict, root: Path) -> list[str]:
    """Suggest paths without accepting or renaming a source PDF."""
    if not directory.is_dir():
        raise ValueError(f"PDF directory does not exist: {directory}")
    pdf = pdf_library()
    warnings = []
    for paper in papers.values():
        paper["candidates"] = []
    for path in sorted(p for p in directory.rglob("*") if p.suffix.lower() == ".pdf"):
        try:
            with pdf.open(path) as doc:
                if doc.needs_pass:
                    warnings.append(f"Password-protected PDF: {path}")
                    continue
                title = (doc.metadata or {}).get("title", "")
                beginning = "\n".join(doc[i].get_text() for i in range(min(2, len(doc))))
        except Exception as exc:
            warnings.append(f"Could not inspect {path}: {exc}")
            continue
        first_text = normalized_title(beginning)
        meta_title = normalized_title(title)
        for paper in papers.values():
            wanted = normalized_title(paper["title"])
            doi = paper.get("doi", "").strip().casefold()
            score, reason = 0.0, ""
            if wanted and len(wanted) >= 15:
                if wanted in first_text:
                    score, reason = 1.0, "title_in_first_two_pages"
                elif meta_title:
                    ratio = SequenceMatcher(None, wanted, meta_title).ratio()
                    if ratio >= 0.80:
                        score, reason = round(ratio, 3), "similar_metadata_title"
            if doi and doi in re.sub(r"\s+", "", beginning).casefold():
                score, reason = 1.0, "doi_in_first_two_pages"
            if score:
                paper["candidates"].append({
                    "pdf": display_path(path.resolve(), root), "score": score, "reason": reason,
                })
    for paper in papers.values():
        paper["candidates"] = sorted(paper["candidates"], key=lambda item: (-item["score"], item["pdf"]))[:5]
    return warnings


def read_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("version") != 1:
        raise ValueError("Unsupported evidence ledger version.")
    return data


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def scan(args) -> int:
    root = args.root.resolve()
    manifest_path = resolve(root, args.manifest)
    old = read_manifest(manifest_path) if manifest_path.exists() else {}
    entry = args.entry or old.get("entry", "thesis.tex")
    bibliography = args.bib or old.get("bibliography", "references.bib")
    bib = read_bib(resolve(root, bibliography))
    citations = collect_citations(root, entry)
    history = {item["id"]: item for item in old.get("archived_citations", []) + old.get("citations", [])}
    papers = dict(old.get("papers", {}))
    for record in citations:
        previous = history.pop(record["id"], None)
        if previous:
            record["evidence"] = previous.get("evidence", [])
            for name in ("claim", "review"):
                if name in previous:
                    record[name] = previous[name]
        key = record["cite_key"]
        paper = papers.setdefault(key, {"pdf": ""})
        paper.update(bib.get(key, {"title": "", "doi": ""}))
    warnings = []
    if args.pdf_dir:
        warnings = find_candidates(resolve(root, args.pdf_dir), papers, root)
    write_json(manifest_path, {
        "version": 1, "entry": entry, "bibliography": bibliography,
        "papers": papers, "citations": citations, "archived_citations": list(history.values()),
    })
    missing = sorted({r["cite_key"] for r in citations} - bib.keys())
    print(f"Saved {len(citations)} citation records / {len({r['cite_key'] for r in citations})} papers: {manifest_path}")
    print(f"Archived records (excluded from highlighting): {len(history)}")
    if missing:
        print("Missing BibTeX keys: " + ", ".join(missing))
    for warning in warnings:
        print(warning, file=sys.stderr)
    return 0


def pdf_text_digest(doc) -> str:
    digest = hashlib.sha256()
    for page in doc:
        digest.update(page.get_text().encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def foreign_annotations(doc) -> list:
    """Compare existing user annotations before and after saving."""
    return [
        (page.number, annot.type, dict(annot.info), tuple(annot.rect))
        for page in doc for annot in (page.annots() or [])
        if not annot.info.get("subject", "").startswith(ANNOTATION_SUBJECT)
    ]


def save_verified_pdf(doc, target: Path, expected_text: str, expected_annotations: list, expected_owned: int) -> None:
    """Write beside the target, verify the saved file, then replace atomically."""
    pdf = pdf_library()
    handle, temporary_name = tempfile.mkstemp(prefix=".citation-", suffix=".pdf", dir=target.parent)
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        doc.save(temporary, garbage=4, deflate=True)
        with pdf.open(temporary) as saved:
            if pdf_text_digest(saved) != expected_text:
                raise ValueError("Saved PDF text differs from the source.")
            if foreign_annotations(saved) != expected_annotations:
                raise ValueError("Saved PDF changed existing user annotations.")
            owned = sum(
                a.info.get("subject", "").startswith(ANNOTATION_SUBJECT)
                for p in saved for a in (p.annots() or [])
            )
            if owned != expected_owned:
                raise ValueError("Saved highlight count differs from the planned count.")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def highlight(args) -> int:
    root = args.root.resolve()
    data = read_manifest(resolve(root, args.manifest))
    current = {r["id"]: r for r in collect_citations(root, data["entry"])}
    bib = read_bib(resolve(root, data["bibliography"]))
    grouped = defaultdict(list)
    results = []
    known = {r["id"] for r in data["citations"]}
    for identifier in current.keys() - known:
        results.append({"id": identifier, "status": "untracked_citation", "detail": "New citation; run scan to update the ledger."})
    for record in data["citations"]:
        if record["id"] in current:
            record.update(source=current[record["id"]]["source"], line=current[record["id"]]["line"])
        if record["id"] not in current:
            results.append({"id": record["id"], "status": "stale_citation", "detail": "Thesis text changed; run scan and review archived evidence."})
        elif record["cite_key"] not in bib:
            results.append({"id": record["id"], "status": "missing_bib_key"})
        elif not record.get("evidence"):
            results.append({"id": record["id"], "status": "no_evidence"})
        else:
            grouped[record["cite_key"]].append(record)
    pdf = pdf_library() if grouped else None
    in_place = getattr(args, "in_place", False)
    if in_place:
        mapped_paths = defaultdict(list)
        for key in grouped:
            value = data["papers"].get(key, {}).get("pdf", "")
            if value:
                mapped_paths[resolve(root, value)].append(key)
        for path, keys in mapped_paths.items():
            if len(keys) > 1:
                for key in keys:
                    results.extend({"id": r["id"], "cite_key": key, "status": "ambiguous_pdf_mapping",
                                    "detail": "Multiple bibliography keys map to one PDF; consolidate aliases before in-place annotation: " + ", ".join(keys)} for r in grouped.pop(key))
    search_flags = ((pdf.TEXTFLAGS_TEXT | pdf.TEXT_DEHYPHENATE) & ~pdf.TEXT_PRESERVE_LIGATURES) if pdf else 0
    run_dir = None
    if not args.dry_run:
        output = resolve(root, args.out_dir)
        output.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone(timedelta(hours=8))).strftime("run-%Y%m%d-%H%M%S-")
        run_dir = Path(tempfile.mkdtemp(prefix=stamp, dir=output))
    for key, records in grouped.items():
        value = data["papers"].get(key, {}).get("pdf", "")
        path = resolve(root, value) if value else None
        if path is None or not path.is_file():
            results.extend({"id": r["id"], "status": "missing_pdf", "detail": value} for r in records)
            continue
        paper_results = []
        try:
            if in_place and not path.is_relative_to(root):
                raise ValueError("In-place highlighting is restricted to PDFs inside the project directory.")
            # An in-memory source leaves no Windows file handle locking target.
            with pdf.open(stream=path.read_bytes(), filetype="pdf") as doc:
                if not doc.is_pdf or doc.needs_pass:
                    raise ValueError("The source must be an unlocked PDF.")
                matches = {}
                for record in records:
                    for evidence_index, evidence in enumerate(record["evidence"]):
                        result = {"id": record["id"], "cite_key": key, "evidence_index": evidence_index}
                        paper_results.append(result)
                        if not isinstance(evidence, dict):
                            result["status"] = "invalid_evidence"
                            continue
                        number, quote = evidence.get("page"), evidence.get("quote")
                        if type(number) is not int or not isinstance(quote, str) or not quote.strip():
                            result["status"] = "invalid_evidence"
                            continue
                        result.update(page=number, quote=quote)
                        if not 1 <= number <= len(doc):
                            result["status"] = "page_out_of_range"
                            continue
                        page = doc[number - 1]
                        if not page.get_text().strip():
                            result["status"] = "no_text_layer"
                            continue
                        # PyMuPDF handles multiline text and line-end hyphenation.
                        normalized_quote = " ".join(quote.split())
                        quads = page.search_for(normalized_quote, quads=True, flags=search_flags)
                        if not quads:
                            result["status"] = "quote_not_found"
                            continue
                        group = (number, normalized_quote)
                        result.update(status="matched", quads=len(quads),
                                      annotation_group=hashlib.sha256(f"{key}\n{number}\n{normalized_quote}".encode()).hexdigest()[:20])
                        matches.setdefault(group, {"quads": quads, "references": []})["references"].append((record, evidence, result))
                failed = any(r["status"] != "matched" for r in paper_results)
                if in_place and failed and not args.dry_run:
                    for result in paper_results:
                        if result["status"] == "matched":
                            result.update(status="pdf_not_written", detail="A quotation for this paper failed validation; the source was left unchanged.")
                elif run_dir and matches:
                    source_text = pdf_text_digest(doc)
                    source_annotations = foreign_annotations(doc)
                    for page in doc:
                        for annot in list(page.annots() or []):
                            if annot.info.get("subject", "").startswith(ANNOTATION_SUBJECT):
                                page.delete_annot(annot)
                    for (number, quote), matched in matches.items():
                        page = doc[number - 1]
                        review = highlight_review(r for r, _, _ in matched["references"])
                        style = REVIEW_STYLES[review]
                        annot = page.add_highlight_annot(matched["quads"])
                        annot.set_colors(stroke=style["color"])
                        annot.set_opacity(0.35)
                        references = matched["references"]
                        lines = [f"【{style['label']}】"]
                        if len(references) > 1:
                            lines.append(f"（此段原文供 {len(references)} 處引用，顏色取最需注意者）")
                        for record, evidence, result in references:
                            result["highlight_review"] = review
                            state = record.get("review", {}).get("status", "unreviewed")
                            label = REVIEW_STYLES.get(state, REVIEW_STYLES["unreviewed"])["label"]
                            lines += ["", f"▍{record['source']}:{record['line']}　{label}",
                                      f"論文：{short_claim(record)}"]
                            if evidence.get("note"):
                                lines.append(f"依據：{evidence['note']}")
                        # Machine-readable footer used by the report verifier.
                        lines += ["", "────────", f"Highlight review: {review}"]
                        lines += [f"ID: {record['id']}" for record, _, _ in references]
                        annot.set_info(title=f"引用核對 {key}", subject=ANNOTATION_SUBJECT + key,
                                       content="\n".join(lines))
                        annot.update()
                    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:90]
                    digest = hashlib.sha256(key.encode()).hexdigest()[:8]
                    target = path if in_place else run_dir / f"{safe}-{digest}.highlighted.pdf"
                    if not in_place and target.resolve() == path:
                        raise ValueError("Output must differ from the source PDF.")
                    save_verified_pdf(doc, target, source_text, source_annotations, len(matches))
                    for result in paper_results:
                        if result["status"] == "matched":
                            result["status"] = "highlighted"
                            result["output"] = str(target)
        except Exception as exc:
            # Never report an unsaved annotation as successfully highlighted.
            for result in paper_results:
                if result.get("status") in {"highlighted", "matched"} and not args.dry_run:
                    result.update(status="pdf_error", detail=str(exc))
                    result.pop("output", None)
            paper_results.append({"cite_key": key, "status": "pdf_error", "detail": str(exc)})
        results.extend(paper_results)
    counts = dict(Counter(r["status"] for r in results))
    report = {"manifest": args.manifest, "dry_run": args.dry_run, "in_place": in_place,
              "counts": counts, "unique_highlights": len({r["annotation_group"] for r in results if r.get("status") in {"highlighted", "matched"}}),
              "highlight_review_counts": dict(Counter({r["annotation_group"]: r["highlight_review"] for r in results if r.get("status") == "highlighted"}.values())),
              "results": results}
    if run_dir:
        write_json(run_dir / "report.json", report)
        lines = ["# Citation highlighting report", "", "Counts: " + json.dumps(counts, ensure_ascii=False), ""]
        by_id = {**current, **{r["id"]: r for r in data["citations"]}}
        for result in results:
            record = by_id.get(result.get("id"), {})
            lines.extend([
                f"- {result['status']}: {record.get('cite_key', result.get('cite_key', ''))} "
                f"{record.get('source', '')}:{record.get('line', '')}",
                f"  - ID: {result.get('id', '')}",
            ])
            for name in ("page", "quote", "detail", "output"):
                if name in result:
                    lines.append(f"  - {name}: {result[name]}")
        (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{'Updated mapped PDFs; reports' if in_place else 'PDF copies and reports'}: {run_dir}")
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    failures = set(counts) - {"highlighted", "matched"}
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, function in (("scan", scan), ("highlight", highlight)):
        command = commands.add_parser(name)
        command.add_argument("--root", type=Path, default=ROOT, help="Project directory")
        command.add_argument("--manifest", default="citation_evidence.json")
        command.set_defaults(function=function)
        if name == "scan":
            command.add_argument("--entry", help="LaTeX entry file; initially thesis.tex")
            command.add_argument("--bib", help="BibTeX file; initially references.bib")
            command.add_argument("--pdf-dir", help="Recursively inspect PDFs and suggest file mappings")
        else:
            command.add_argument("--out-dir", default="annotated_papers")
            command.add_argument("--in-place", action="store_true", help="Write highlights directly into mapped PDFs inside the project")
            command.add_argument("--dry-run", action="store_true", help="Validate evidence without writing PDFs or reports")
    args = parser.parse_args()
    try:
        return args.function(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
