# Part A Report

Canonical editable prose:

`part-a-source.md`

Canonical bibliographic database:

`references.bib`

Canonical report figures (user-supplied, not regenerated at build time):

`figures/`

- `figures/figure1.png`
- `figures/figure2.png`
- `figures/figure3.png`

`generate_figures.py` is unused historical source and must not overwrite those files.

Generated Word output:

`COMS6200_LLM_Network_Troubleshooting_PartA.docx`

Generated PDF output:

`COMS6200_LLM_Network_Troubleshooting_PartA.pdf`

Build script:

`build_report.py`

Build dependencies:

`requirements-docs.txt`

Future report edits should normally be made to `part-a-source.md` first, followed by regeneration of DOCX and PDF.

Do not independently edit the same content in Markdown, Word and PDF because that creates version drift.

Do not manually maintain a numbered bibliography in the Markdown file. `references.bib` is the bibliographic source of truth.

## Citation model

Numbers are not the identity of references.

The canonical Markdown uses Pandoc-style stable citation keys:

```markdown
OpenFlow provides an open, standardised interface
[@mckeown2008_openflow].
```

Multiple supporting sources:

```markdown
... OpenFlow mechanisms ...
[@mckeown2008_openflow; @onf2015_openflow13].
```

Do **not** type IEEE numbers such as `[1]`, `[2]`, or `[1]–[4]` in `part-a-source.md`.

During every build, IEEE numbers are assigned from first appearance:

1. The first unique citation key becomes `[1]`.
2. The next previously unseen key becomes `[2]`.
3. A previously cited key reuses its assigned number.

If a paragraph is later moved, the generated numbers may change. The citation key continues to identify the same source. This prevents a reference from becoming attached to the wrong source when citations are inserted, removed, or reordered.

Only cited `references.bib` entries are rendered under References. Unused library entries are kept and reported as informational warnings; they are not deleted.

## Report-maintenance commands

Canonical source:

`docs/reports/part-a/part-a-source.md`

Canonical bibliography:

`docs/reports/part-a/references.bib`

Validate:

```bash
python docs/reports/part-a/build_report.py --validate-only
```

This checks the Markdown source, `references.bib`, citation keys, hard-coded numeric citations, and report structure. It does not modify source files and does not regenerate DOCX/PDF.

Build:

```bash
python docs/reports/part-a/build_report.py
```

The normal build loads Markdown and `references.bib`, validates citation keys, assigns IEEE numbers by first appearance, generates DOCX/PDF with clickable citation-to-bibliography links, and validates the outputs.

Show the generated citation map:

```bash
python docs/reports/part-a/build_report.py --show-citation-map
```

Example:

```
IEEE | Citation key | Source
[1] | wang2025_nika | A Network Arena for Benchmarking AI Agents on Network Troubleshooting
[2] | tseng2026_sade | SADE: Symptom-Aware Diagnostic Escalation for LLM-Based Network Troubleshooting
[3] | mckeown2008_openflow | OpenFlow: Enabling Innovation in Campus Networks
```

Numeric citation rewriting (`--fix-ieee-references`) is obsolete. IEEE numbering is generated automatically from stable keys and that flag does not rewrite the Markdown source.

## Evidence rules

- Implementation claims must only be updated after actual evidence exists.
- Screenshots and results must come from real project execution.
- Planned work must not be rewritten as completed work.
- `TEAM TO INSERT` placeholders must not be filled with invented information.

The current `part-a-source.md` file is a snapshot of the 10-page Part A report. Later repository progress, including completed M0 environment verification, must not be copied into this report until a separate controlled update is approved.

## Build instructions

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r docs/reports/part-a/requirements-docs.txt
python docs/reports/part-a/build_report.py
```

If `.venv` already exists, skip the `python3 -m venv .venv` step.

Expected outputs:

```
docs/reports/part-a/COMS6200_LLM_Network_Troubleshooting_PartA.docx
docs/reports/part-a/COMS6200_LLM_Network_Troubleshooting_PartA.pdf
```

These generated Word and PDF files are version-controlled so team members can open them without installing the documentation toolchain.

## How team members get the report

Authenticated Git/SSH is preferred because the GitHub repository may be private. Do not rely on unauthenticated raw GitHub URLs.

### Method 1 — Existing clone

```bash
git switch develop
git pull origin develop
```

Then open:

```
docs/reports/part-a/COMS6200_LLM_Network_Troubleshooting_PartA.pdf
docs/reports/part-a/COMS6200_LLM_Network_Troubleshooting_PartA.docx
```

### Method 2 — Fresh clone using SSH

```bash
git clone --branch develop --single-branch git@github.com:dhotrey/COMS6200-Project.git
cd COMS6200-Project
```

Then access `docs/reports/part-a/`.

### Method 3 — Get only the PDF from an existing authenticated Git repository

```bash
git fetch origin develop
git show origin/develop:docs/reports/part-a/COMS6200_LLM_Network_Troubleshooting_PartA.pdf > COMS6200_LLM_Network_Troubleshooting_PartA.pdf
```

### Method 4 — Get only the Word file

```bash
git fetch origin develop
git show origin/develop:docs/reports/part-a/COMS6200_LLM_Network_Troubleshooting_PartA.docx > COMS6200_LLM_Network_Troubleshooting_PartA.docx
```
