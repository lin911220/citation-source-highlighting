---
name: citation-source-highlighting
description: "核對論文引用與來源原文，在參考 PDF 畫螢光筆，依支持、部分支持及推論分色。適用於引用證據核對、中文改寫對應英文原文及來源 PDF 標註。Verify manuscript claims against original passages and highlight source PDFs with evidence colors."
---

# Citation Source Highlighting — AI 執行指引

初次使用請從 [README](README.md) 開始；以下是供 AI 執行任務時閱讀的指引。

Connect each cited manuscript claim to the actual passage in the identified source PDF. Highlight that passage and explain its relationship to the claim. Follow the author's requested language; Chinese paraphrases may be supported by English originals.

This is a standalone skill with its own instructions, LaTeX/BibTeX scanner, PDF annotation helper, dependency list, and regression checks. It handles citation evidence and source annotations; it does not certify the whole manuscript or silently revise its prose.

For setup questions and input preparation, read [the setup FAQ](references/standalone-setup.md). Read [the advanced guide](references/evidence-ledger.md) for CLI details, ledger fields, and tests.

## Establish the scope

Identify the active manuscript, bibliography, reference PDF folder, and requested output. Reuse an existing evidence ledger and confirmed PDF paths. Keep bibliography-only entries separate from citations used in the manuscript. A multi-source citation has one record per cited work.

When explaining input preparation, recommend a manuscript project containing the main TeX file and bibliography at its root, with cited full-text PDFs in a subfolder such as 參考論文 or reference_pdfs. These are conventions, not required names. Distinguish the bibliography from the source PDFs, and the manuscript project from the skill installation folder. Reuse existing paths when provided; ask only for missing locations. For in-place annotation, sources must reside inside the selected project root; external PDFs can be read to produce annotated copies inside the project. See README for the folder tree and a complete invocation example. Help first-time users follow its three steps; do not require them to edit JSON or run audit commands as preparation.

The bundled helper supports LaTeX with BibTeX, follows input/include files, and recognizes common citation commands. For other manuscript formats, use the host's available document tools to establish claim locations and explain that the LaTeX helper does not scan those formats. Do not pass a Word document or compiled manuscript PDF to the LaTeX scanner.

Read [the evidence ledger and CLI guide](references/evidence-ledger.md) before using the helper. Resolve the script from this skill's installed directory and pass the manuscript project with the root option; never assume the plugin cache is the manuscript root.

## Verify the source and the claim

- Confirm the PDF's own title, authors, and version against the bibliography. Filename similarity and metadata candidates are discovery aids. A cited title or DOI in another paper's references is not an identity match.
- If asked to organize sources, copy only cited works into the requested folder and use verified titles for filenames. Preserve originals and handle filesystem-invalid title characters. Do not require an old-filename mapping unless needed for the task.
- Read the exact manuscript claim, including relevant neighboring sentences, equations, captions, or table cells. Search the identified source for candidate passages, then read enough context to assess what they support. Search hits and embedding similarity alone do not establish support.
- Copy the actual source wording into the ledger. Keep source language and distinguish quotations from manuscript translations or paraphrases. Split evidence across PDF pages; use the PDF viewer's one-based page sequence, not printed journal pagination.
- Check qualifications, target populations, data types, metrics, formulas, and versions when they affect the claim. Abstracts may support broad summaries; inspect the method or result details for narrower assertions.
- Record partial support, absent evidence, and author inference explicitly. Do not manufacture a quote, translate one back into an invented English original, or highlight an unrelated passage to fill coverage.

## Record the support judgment

Use one review status per citation and notes describing what each passage supports:

| Status | Color | Meaning |
| --- | --- | --- |
| supported | Yellow | The cited claim's relevant substance is supported by the passage. |
| partial | Orange | Some substance is supported; a mismatch, omission, or overstatement needs clarification. |
| inferred | Purple | The manuscript draws an inference; the source does not directly state that conclusion. |
| unsupported | Red | Checked source material does not support the claim. Highlight a genuinely relevant contrary or limiting passage only if one exists. |
| unreviewed | Gray | Support has not been assessed; finding literal text does not change this status. |

Classify the citation's use of the source, not the quality of the source paper. A single citation can need multiple passages. When an identical passage supports multiple citation records, merge the highlight and list each record's own judgment in its comment. A shared highlight uses the most cautionary status: unsupported, partial, inferred, unreviewed, supported.

If no relevant original can be established, leave the evidence empty and report the unresolved citation. A colored mark is never a substitute for missing evidence. Do not change manuscript claims merely to make them fit available passages unless editing is part of the author's request.

## Annotate and verify

Respect review-only requests. When source annotation is requested, write annotated copies by default; use in-place mode when the author wants the mapped source files updated. Existing authorization carries forward; do not add another confirmation step for an already requested annotation.

Validate quotes before writing. Use text-based PDF highlights rather than rasterizing or painting over a rendered page. Preserve other annotations. Rerunning should replace this tool's annotations and merge repeated evidence rather than stacking marks. In-place mode validates every supplied quotation for a paper and verifies a temporary saved PDF before replacing it. PDFs outside the selected project are not written in place.

Reopen the saved files and check passage text, page, comment, color, and citation references. Confirm that page text and existing user annotations remain intact; visually inspect representative pages, especially equations, multi-column layouts, and the orange/purple exceptions. If the PDF has no usable text layer, report the need for OCR; if a formula or image cannot be safely located, report the limitation rather than a successful highlight.

The helper reports new or changed citation contexts. Rescan and reassess affected evidence before reusing it. Check the full relevant claim again when the user changes it; local citation-context identifiers do not prove that all surrounding manuscript text is unchanged. After deleting a citation or losing all valid evidence for a paper, inspect any older annotations in that PDF; a failed run is not evidence that previously written marks are current.

## Deliver a traceable result

Report citation coverage and missing sources separately from annotation counts. Separate PDF identity, literal quote matching, support judgment, and successful saved annotations. List unresolved or partial items with manuscript location, source title, PDF page, and the substantive reason. If multiple judgments share a highlight, explain the color precedence.

State what was actually read and checked. Whole-file text extraction is not cover-to-cover reading, and targeted passage review is not an examination of every figure, table, or conclusion. Never turn a clean script report into a claim that every citation or the whole paper is correct.

Keep private manuscripts, PDFs, evidence ledgers, and school-network credentials in the author's project. Publish only generic skill resources and synthetic fixtures when contributing this skill to a repository.
