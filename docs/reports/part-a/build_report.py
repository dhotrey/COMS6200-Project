#!/usr/bin/env python3
"""Generate Part A DOCX and PDF from Markdown plus a BibTeX library."""

from __future__ import annotations

import argparse
import hashlib
import html
import os
import re
import struct
import sys
import zipfile
from dataclasses import dataclass, field
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

import bibtexparser
from bibtexparser.bparser import BibTexParser
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_COLOR_INDEX, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from PIL import Image as PILImage
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, TextStringObject
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "part-a-source.md"
BIB_PATH = HERE / "references.bib"
ASSETS = HERE / "assets"
DOCX_PATH = HERE / "COMS6200_LLM_Network_Troubleshooting_PartA.docx"
PDF_PATH = HERE / "COMS6200_LLM_Network_Troubleshooting_PartA.pdf"

HEADING_BLUE = RGBColor(0x1F, 0x4E, 0x79)
HEADING_BLUE_HEX = "#1F4E79"
CITE_BLUE_HEX = "1F4E79"
PLACEHOLDER_YELLOW = "FFF2B2"
PLACEHOLDER_RE = re.compile(r"\[TEAM TO INSERT[^\]]*\]")
CAPTION_RE = re.compile(r"^(Figure|Table)\s+\d+\.")
HEADING_RE = re.compile(r"^(#{1,2})\s+(.*)$")
IMAGE_RE = re.compile(r"^!\[(.*?)\]\((.*?)\)$")
REFERENCES_HEADING_RE = re.compile(r"(?m)^# References[ \t]*$")
CITE_CLUSTER_RE = re.compile(r"\[@([^\]]*)\]")
KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
NUMERIC_CITE_RE = re.compile(r"\[(\d+)\]")
BIB_DECLARE_RE = re.compile(r"(?m)^@\w+\s*\{\s*([^,\s]+)\s*,")
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REQUIRED_SECTIONS = [
    "Abstract",
    "1. Introduction",
    "2. Background",
    "3. Related Work",
    "4. Project Aim and Scope",
    "5. Methodology",
    "6. Project Plan",
    "7. Progress So Far",
    "8. Risks and Mitigation",
    "9. Conclusion",
    "References",
]
MIN_PAGES = 10
MAX_PAGES = 12
MONTHS = {
    "jan": "Jan.",
    "january": "Jan.",
    "feb": "Feb.",
    "february": "Feb.",
    "mar": "Mar.",
    "march": "Mar.",
    "apr": "Apr.",
    "april": "Apr.",
    "may": "May",
    "jun": "Jun.",
    "june": "Jun.",
    "jul": "Jul.",
    "july": "Jul.",
    "aug": "Aug.",
    "august": "Aug.",
    "sep": "Sep.",
    "sept": "Sep.",
    "september": "Sep.",
    "oct": "Oct.",
    "october": "Oct.",
    "nov": "Nov.",
    "november": "Nov.",
    "dec": "Dec.",
    "december": "Dec.",
}
NOTE_TYPES = (
    "Official technical documentation",
    "Official technical specification",
    "Official project documentation",
    "Industry/vendor material",
    "Preprint",
)


@dataclass
class Inline:
    text: str
    bold: bool = False
    highlight: bool = False
    cite_key: str | None = None


@dataclass
class Block:
    kind: str
    text: str = ""
    inlines: list[Inline] = field(default_factory=list)
    items: list[list[Inline]] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    image_path: str = ""
    alt: str = ""
    level: int = 1
    centered: bool = False
    cite_key: str = ""
    cite_number: int = 0


@dataclass
class CitationCluster:
    start: int
    end: int
    keys: list[str]
    original: str
    error: str | None = None


@dataclass
class CitationReport:
    order: list[str]
    numbers: dict[str, int]
    occurrences: list[CitationCluster]
    occurrence_count: int
    unused: list[str]
    undefined: list[str]
    malformed: list[str]
    raw_numeric: list[str]
    duplicate_bib: list[str]
    failures: list[str]
    warnings: list[str]
    overall_ok: bool


class BookmarkCounter:
    def __init__(self) -> None:
        self.value = 0

    def next_id(self) -> str:
        self.value += 1
        return str(self.value)


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def split_body_and_references(source_text: str) -> tuple[str, str, str]:
    match = REFERENCES_HEADING_RE.search(source_text)
    if not match:
        die("Could not find a '# References' heading in the Markdown source")
    return source_text[: match.start()], match.group(0), source_text[match.end() :]


def placeholder_spans(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in PLACEHOLDER_RE.finditer(text)]


def _in_spans(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in spans)


def parse_cite_keys(inner: str) -> tuple[list[str], str | None]:
    if not inner.strip():
        return [], "empty citation cluster"
    keys: list[str] = []
    for piece in inner.split(";"):
        token = piece.strip()
        if token.startswith("@"):
            token = token[1:].strip()
        if not KEY_RE.fullmatch(token):
            return [], f"malformed citation token {piece!r}"
        keys.append(token)
    return keys, None


def extract_citation_clusters(body: str) -> list[CitationCluster]:
    spans = placeholder_spans(body)
    clusters: list[CitationCluster] = []
    for match in CITE_CLUSTER_RE.finditer(body):
        if _in_spans(match.start(), spans):
            continue
        keys, error = parse_cite_keys(match.group(1))
        clusters.append(
            CitationCluster(
                start=match.start(),
                end=match.end(),
                keys=keys,
                original=match.group(0),
                error=error,
            )
        )
    return clusters


def detect_raw_numeric_citations(body: str) -> list[str]:
    masked = PLACEHOLDER_RE.sub(" ", body)
    masked = CITE_CLUSTER_RE.sub(" ", masked)
    found: list[str] = []
    for match in NUMERIC_CITE_RE.finditer(masked):
        found.append(match.group(0))
    return found


def detect_manual_bibliography(references_body: str) -> list[str]:
    hits = []
    for match in re.finditer(r"(?m)^\[\d+\]\s+\S", references_body):
        hits.append(match.group(0).strip())
    return hits


def bookmark_name(key: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", key)
    name = f"ref_{safe}"
    if len(name) > 40:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
        name = f"{name[:31]}_{digest}"
    if not re.match(r"^[A-Za-z_]", name):
        name = f"r{name}"[:40]
    return name


def load_bibliography(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        die(f"Bibliography not found or empty: {path}")
    text = path.read_text(encoding="utf-8")
    declared = BIB_DECLARE_RE.findall(text)
    if not declared:
        die("references.bib does not contain any BibTeX entries")
    duplicates = sorted({key for key in declared if declared.count(key) > 1})
    if duplicates:
        die("Duplicate BibTeX keys: " + ", ".join(duplicates))
    parser = BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    try:
        database = bibtexparser.loads(text, parser=parser)
    except Exception as exc:  # pragma: no cover - parser errors are environment-specific
        die(f"Malformed BibTeX in {path.name}: {exc}")
    entries: dict[str, dict[str, str]] = {}
    for entry in database.entries:
        key = entry.get("ID", "").strip()
        if not key:
            die("Malformed BibTeX entry with an empty citation key")
        if key in entries:
            die(f"Duplicate BibTeX key after parse: {key}")
        entries[key] = entry
    if sorted(declared) != sorted(entries):
        die(
            "BibTeX parse mismatch between declared keys "
            f"{declared} and loaded keys {list(entries)}"
        )
    return entries


def assign_ieee_numbers(clusters: list[CitationCluster]) -> tuple[list[str], dict[str, int]]:
    order: list[str] = []
    numbers: dict[str, int] = {}
    for cluster in clusters:
        if cluster.error:
            continue
        for key in cluster.keys:
            if key not in numbers:
                numbers[key] = len(order) + 1
                order.append(key)
    return order, numbers


def validate_citation_keys(
    source_text: str,
    entries: dict[str, dict[str, str]],
) -> CitationReport:
    failures: list[str] = []
    warnings: list[str] = []
    body, _heading, references_body = split_body_and_references(source_text)
    clusters = extract_citation_clusters(body)
    raw_numeric = detect_raw_numeric_citations(body)
    manual_bib = detect_manual_bibliography(references_body)
    malformed = [cluster.original for cluster in clusters if cluster.error]
    order, numbers = assign_ieee_numbers(clusters)
    cited = set(order)
    undefined = [key for key in order if key not in entries]
    unused = [key for key in entries if key not in cited]
    if raw_numeric:
        failures.append(
            "hard-coded numeric citations in canonical body: " + ", ".join(raw_numeric)
        )
    if manual_bib:
        failures.append(
            "manual numbered bibliography entries found under # References: "
            + ", ".join(manual_bib)
        )
    if malformed:
        details = "; ".join(
            f"{cluster.original} ({cluster.error})" for cluster in clusters if cluster.error
        )
        failures.append(f"malformed citation syntax: {details}")
    if not order:
        failures.append("no stable citation keys were found before References")
    if undefined:
        failures.append("undefined citation keys: " + ", ".join(undefined))
    expected = list(range(1, len(order) + 1))
    actual = [numbers[key] for key in order]
    if actual != expected:
        failures.append(f"generated IEEE numbering is not sequential: {actual}")
    if unused:
        warnings.append(
            "unused bibliography entries (stored, not rendered): " + ", ".join(unused)
        )
    occurrence_count = sum(len(cluster.keys) for cluster in clusters if not cluster.error)
    report = CitationReport(
        order=order,
        numbers=numbers,
        occurrences=clusters,
        occurrence_count=occurrence_count,
        unused=unused,
        undefined=undefined,
        malformed=malformed,
        raw_numeric=raw_numeric,
        duplicate_bib=[],
        failures=failures,
        warnings=warnings,
        overall_ok=not failures,
    )
    return report


def bib_field(entry: dict[str, str], name: str) -> str:
    value = entry.get(name, "") or entry.get(name.lower(), "") or ""
    value = value.replace("\n", " ").strip()
    value = value.replace("{", "").replace("}", "")
    value = value.replace("--", "-")
    return re.sub(r"\s+", " ", value).strip()


def abbreviate_given_names(given: str) -> str:
    """Abbreviate given names to initials: 'Zhihao' -> 'Z.', 'Jean-Pierre' -> 'J.-P.'"""
    tokens = given.split()
    result: list[str] = []
    for tok in tokens:
        if "-" in tok:
            parts = tok.split("-")
            abbreviated = "-".join(p[0].upper() + "." if len(p) > 2 else p for p in parts if p)
            result.append(abbreviated)
        elif len(tok) > 2 or (len(tok) == 2 and not tok.endswith(".")):
            result.append(tok[0].upper() + ".")
        else:
            result.append(tok)
    return " ".join(result)


def format_authors(author: str) -> str:
    author = author.strip()
    if not author:
        return ""
    parts = [part.strip() for part in re.split(r"\s+and\s+", author) if part.strip()]
    names: list[str] = []
    et_al = False
    for part in parts:
        lowered = part.lower().rstrip(".")
        if lowered in {"others", "et al"}:
            et_al = True
            continue
        if "," in part:
            last, first = [item.strip() for item in part.split(",", 1)]
            names.append(f"{abbreviate_given_names(first)} {last}".strip())
        else:
            names.append(part)
    if et_al:
        if names:
            return f"{names[0]} et al."
        return "et al."
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + ", and " + names[-1]


def format_month(value: str) -> str:
    raw = value.strip().strip(".").lower()
    return MONTHS.get(raw, value.strip())


def split_note(note: str) -> tuple[str, str | None]:
    text = note.strip().rstrip(".")
    for label in NOTE_TYPES:
        if re.search(re.escape(label), text, flags=re.I):
            rest = re.sub(re.escape(label), "", text, flags=re.I)
            rest = re.sub(r"\s+", " ", rest).strip(" .")
            return rest, label
    return text, None


def join_ieee(parts: list[str]) -> str:
    text = " ".join(part.strip() for part in parts if part and part.strip())
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r",\s*,+", ", ", text)
    text = text.rstrip(" ,")
    if text and not text.endswith("."):
        text += "."
    return text


def format_ieee_entry(entry: dict[str, str]) -> str:
    entry_type = (entry.get("ENTRYTYPE") or "misc").lower()
    authors = format_authors(bib_field(entry, "author"))
    institution = bib_field(entry, "institution")
    who = authors or institution
    title = bib_field(entry, "title")
    year = bib_field(entry, "year")
    note = bib_field(entry, "note")
    howpublished = bib_field(entry, "howpublished")
    eprint = bib_field(entry, "eprint")
    url = bib_field(entry, "url")
    archive_prefix = bib_field(entry, "archiveprefix") or bib_field(entry, "archivePrefix")
    rest_note, note_type = split_note(note) if note else ("", None)

    if entry_type == "article":
        parts = [f'{who}, "{title},"']
        journal = bib_field(entry, "journal")
        volume = bib_field(entry, "volume")
        number = bib_field(entry, "number")
        pages = bib_field(entry, "pages")
        doi = bib_field(entry, "doi")
        if journal:
            parts.append(f"{journal},")
        if volume:
            parts.append(f"vol. {volume},")
        if number:
            parts.append(f"no. {number},")
        if pages:
            parts.append(f"pp. {pages},")
        if year:
            parts.append(year)
        text = join_ieee(parts)
        if doi:
            text = text.rstrip(".") + f", doi: {doi}."
        if url and url not in text:
            if not text.endswith("."):
                text += "."
            text += f" [Online]. Available: {url}."
        return text

    if entry_type == "inproceedings":
        parts = [f'{who}, "{title},"']
        booktitle = bib_field(entry, "booktitle")
        address = bib_field(entry, "address")
        doi = bib_field(entry, "doi")
        if booktitle:
            parts.append(f"in {booktitle},")
        if address:
            parts.append(f"{address},")
        if year:
            parts.append(year)
        text = join_ieee(parts)
        if doi:
            text = text.rstrip(".") + f", doi: {doi}."
        if url and url not in text:
            if not text.endswith("."):
                text += "."
            text += f" [Online]. Available: {url}."
        return text

    if entry_type == "techreport":
        parts = [f'{who}, "{title},"']
        number = bib_field(entry, "number")
        month = format_month(bib_field(entry, "month"))
        doi = bib_field(entry, "doi")
        if number:
            parts.append(f"{number},")
        date = " ".join(item for item in (month, year) if item)
        if date:
            parts.append(date)
        text = join_ieee(parts)
        if note_type:
            text = text.rstrip(".") + f". [{note_type}]."
        elif rest_note:
            text = text.rstrip(".") + f" {rest_note}."
        if doi:
            text = text.rstrip(".") + f", doi: {doi}."
        if url and url not in text:
            if not text.endswith("."):
                text += "."
            text += f" [Online]. Available: {url}."
        return text

    parts: list[str] = []
    if who:
        parts.append(f'{who}, "{title},"')
    else:
        parts.append(f'"{title},"')
    if eprint:
        prefix = archive_prefix if archive_prefix else "arXiv"
        parts.append(f"{prefix}:{eprint},")
        if year:
            parts.append(year)
        text = join_ieee(parts)
        if url:
            text = text.rstrip(".") + f" [Online]. Available: {url}."
        return text
    if howpublished:
        parts.append(f"{howpublished},")
    renderable_note = rest_note and any(
        token in rest_note.lower() for token in ("accessed", "arxiv", "official", "industry", "preprint")
    )
    if renderable_note:
        cleaned = rest_note
        if cleaned.lower().startswith("accessed"):
            cleaned = "accessed" + cleaned[8:]
        parts.append(cleaned)
    elif year:
        parts.append(year)
    text = join_ieee(parts)
    if year and year not in text:
        text = text.rstrip(".") + f", {year}."
    if note_type:
        text = text.rstrip(".") + f" [{note_type}]."
    if url and url not in text:
        if not text.endswith("."):
            text += "."
        text += f" [Online]. Available: {url}."
    return text


def print_citation_report(report: CitationReport, entries: dict[str, dict[str, str]]) -> None:
    print("Citation validation")
    print("-------------------")
    print()
    print("Citation keys in first-appearance order:")
    if report.order:
        for key in report.order:
            print(key)
    else:
        print("(none)")
    print()
    print("Generated IEEE mapping:")
    if report.order:
        for key in report.order:
            print(f"[{report.numbers[key]}] -> {key}")
    else:
        print("(none)")
    print()
    print(f"Bibliography entries in references.bib: {len(entries)}")
    print(f"Rendered bibliography entries: {len(report.order)}")
    print(f"In-text citation occurrences: {report.occurrence_count}")
    print()
    print("Unused bibliography entries:")
    if report.unused:
        for key in report.unused:
            print(f"INFO: {key} ({bib_field(entries[key], 'title')})")
    else:
        print("none")
    print()
    print("Undefined citation keys:")
    print(", ".join(report.undefined) if report.undefined else "none")
    print()
    print("Malformed citation syntax:")
    print(", ".join(report.malformed) if report.malformed else "none")
    print()
    print("Hard-coded numeric citations:")
    print(", ".join(report.raw_numeric) if report.raw_numeric else "none")
    print()
    print(f"Overall citation validation: {'PASS' if report.overall_ok else 'FAIL'}")
    if report.warnings:
        print()
        for item in report.warnings:
            print(f"WARNING: {item}")
    if report.failures:
        print()
        for item in report.failures:
            print(f"- {item}")


def print_citation_map(report: CitationReport, entries: dict[str, dict[str, str]]) -> None:
    print("IEEE | Citation key | Source")
    if not report.order:
        print("(none)")
        return
    for key in report.order:
        title = bib_field(entries[key], "title") or key
        print(f"[{report.numbers[key]}] | {key} | {title}")


def unescape_md(text: str) -> str:
    return text.replace("\\[", "[").replace("\\]", "]")


def parse_inlines(text: str, numbers: dict[str, int] | None = None) -> list[Inline]:
    text = unescape_md(text)
    parts: list[Inline] = []
    i = 0
    while i < len(text):
        if text.startswith("**<mark>", i):
            end = text.find("</mark>**", i)
            if end == -1:
                parts.append(Inline(text[i:], highlight=True, bold=True))
                break
            inner = text[i + 8 : end]
            parts.append(Inline(inner, bold=True, highlight=True))
            i = end + 9
            continue
        if text.startswith("<mark>", i):
            end = text.find("</mark>", i)
            if end == -1:
                parts.append(Inline(text[i:], highlight=True))
                break
            parts.append(Inline(text[i + 6 : end], highlight=True))
            i = end + 7
            continue
        if text.startswith("**", i):
            end = text.find("**", i + 2)
            if end == -1:
                parts.append(Inline(text[i:]))
                break
            inner = text[i + 2 : end]
            highlight = bool(PLACEHOLDER_RE.search(inner))
            parts.append(Inline(inner, bold=True, highlight=highlight))
            i = end + 2
            continue
        if text.startswith("[@", i):
            end = text.find("]", i)
            if end == -1:
                parts.append(Inline(text[i:]))
                break
            raw = text[i : end + 1]
            keys, error = parse_cite_keys(text[i + 2 : end])
            if error or numbers is None:
                parts.append(Inline(raw))
            else:
                rendered: list[Inline] = []
                for key in keys:
                    if key not in numbers:
                        rendered = [Inline(raw)]
                        break
                    rendered.append(Inline(f"[{numbers[key]}]", cite_key=key))
                for index, item in enumerate(rendered):
                    if index:
                        parts.append(Inline(", "))
                    parts.append(item)
            i = end + 1
            continue
        next_idx = len(text)
        for token in ("**<mark>", "<mark>", "**", "[@"):
            found = text.find(token, i + 1)
            if found != -1:
                next_idx = min(next_idx, found)
        chunk = text[i:next_idx]
        if PLACEHOLDER_RE.search(chunk):
            cursor = 0
            for match in PLACEHOLDER_RE.finditer(chunk):
                if match.start() > cursor:
                    parts.append(Inline(chunk[cursor : match.start()]))
                parts.append(Inline(match.group(0), highlight=True))
                cursor = match.end()
            if cursor < len(chunk):
                parts.append(Inline(chunk[cursor:]))
        else:
            parts.append(Inline(chunk))
        i = next_idx
    return [part for part in parts if part.text != ""]


def is_separator_row(cells: list[str]) -> bool:
    joined = "".join(cell.replace(" ", "") for cell in cells)
    return bool(joined) and re.fullmatch(r"[:\-]+", joined) is not None


def parse_table(lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in lines:
        cells = [unescape_md(cell.strip()) for cell in line.strip().strip("|").split("|")]
        cells = [re.sub(r"^\*\*(.*)\*\*$", r"\1", cell) for cell in cells]
        if is_separator_row(cells):
            continue
        rows.append(cells)
    return rows


def parse_markdown(text: str, numbers: dict[str, int] | None = None, entries: dict[str, dict[str, str]] | None = None, order: list[str] | None = None) -> list[Block]:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    lines = text.splitlines()
    blocks: list[Block] = []
    i = 0
    seen_abstract = False
    first_heading = True

    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue

        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            if first_heading and level == 1:
                blocks.append(Block(kind="title", text=title, centered=True))
                first_heading = False
            elif level == 1:
                if title.lower() == "abstract":
                    blocks.append(Block(kind="page_break"))
                    seen_abstract = True
                blocks.append(Block(kind="heading", text=title, level=1))
                if title.lower() == "references" and numbers and entries and order:
                    for key in order:
                        blocks.append(
                            Block(
                                kind="bibitem",
                                text=format_ieee_entry(entries[key]),
                                cite_key=key,
                                cite_number=numbers[key],
                            )
                        )
            else:
                blocks.append(Block(kind="heading", text=title, level=2))
            i += 1
            continue

        image = IMAGE_RE.match(line.strip())
        if image:
            blocks.append(
                Block(
                    kind="image",
                    alt=image.group(1),
                    image_path=image.group(2).strip(),
                    centered=True,
                )
            )
            i += 1
            continue

        if line.lstrip().startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            blocks.append(Block(kind="table", rows=parse_table(table_lines)))
            continue

        if line.startswith("- "):
            items: list[list[Inline]] = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(parse_inlines(lines[i][2:].strip(), numbers))
                i += 1
            blocks.append(Block(kind="list", items=items))
            continue

        if CAPTION_RE.match(line.strip()):
            blocks.append(Block(kind="caption", text=line.strip(), centered=True))
            i += 1
            continue

        inlines = parse_inlines(line.strip(), numbers)
        centered = not seen_abstract and not first_heading
        blocks.append(Block(kind="paragraph", inlines=inlines, text=line.strip(), centered=centered))
        i += 1

    return blocks


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        signature = handle.read(8)
        if signature != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"{path} is not a PNG file")
        length, chunk_type = struct.unpack(">I4s", handle.read(8))
        if chunk_type != b"IHDR" or length != 13:
            raise ValueError(f"{path} is missing a PNG IHDR chunk")
        width, height = struct.unpack(">II", handle.read(8))
    return width, height


def set_run_font(run, name: str = "Times New Roman", size: float = 11) -> None:
    run.font.name = name
    run.font.size = Pt(size)
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)
    rfonts.set(qn("w:cs"), name)


def shade_cell(cell, fill: str) -> None:
    tc = cell._tc
    tcpr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcpr.append(shd)


def set_cell_border(cell) -> None:
    tc = cell._tc
    tcpr = tc.get_or_add_tcPr()
    tc_borders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        element = OxmlElement(f"w:{edge}")
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), "4")
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), "8FAADC")
        tc_borders.append(element)
    tcpr.append(tc_borders)


def add_page_field(paragraph) -> None:
    run = paragraph.add_run()
    set_run_font(run, size=9)
    run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_end)


def add_internal_hyperlink(paragraph, text: str, anchor: str, size: float) -> None:
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("w:anchor"), anchor)
    hyperlink.set(qn("w:history"), "1")
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    rfonts = OxmlElement("w:rFonts")
    rfonts.set(qn("w:ascii"), "Times New Roman")
    rfonts.set(qn("w:hAnsi"), "Times New Roman")
    rfonts.set(qn("w:cs"), "Times New Roman")
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), str(int(size * 2)))
    sz_cs = OxmlElement("w:szCs")
    sz_cs.set(qn("w:val"), str(int(size * 2)))
    color = OxmlElement("w:color")
    color.set(qn("w:val"), CITE_BLUE_HEX)
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    for child in (rfonts, sz, sz_cs, color, underline):
        rpr.append(child)
    text_el = OxmlElement("w:t")
    text_el.set(qn("xml:space"), "preserve")
    text_el.text = text
    run.append(rpr)
    run.append(text_el)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def add_bookmarked_text(paragraph, name: str, text: str, size: float, counter: BookmarkCounter) -> None:
    bookmark_id = counter.next_id()
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), bookmark_id)
    start.set(qn("w:name"), name)
    paragraph._p.append(start)
    run = paragraph.add_run(text)
    set_run_font(run, size=size)
    run.bold = True
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), bookmark_id)
    paragraph._p.append(end)


def add_inlines_to_paragraph(paragraph, inlines: Iterable[Inline], size: float = 11) -> None:
    for part in inlines:
        if part.cite_key:
            add_internal_hyperlink(paragraph, part.text, bookmark_name(part.cite_key), size)
            continue
        run = paragraph.add_run(part.text)
        set_run_font(run, size=size)
        run.bold = part.bold
        if part.highlight:
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW


def configure_docx_section(document: Document) -> None:
    section = document.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.left_margin = Mm(20)
    section.right_margin = Mm(20)
    section.top_margin = Mm(22)
    section.bottom_margin = Mm(20)
    section.header_distance = Mm(10)
    section.footer_distance = Mm(10)

    header = section.header
    header.is_linked_to_previous = False
    header_p = header.paragraphs[0]
    header_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = header_p.add_run("LLM-Based Network Troubleshooting Agent")
    set_run_font(run, size=9)
    run.italic = True
    run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    footer = section.footer
    footer.is_linked_to_previous = False
    footer_p = footer.paragraphs[0]
    footer_p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    left = footer_p.add_run("COMS6200 Part A | Page ")
    set_run_font(left, size=9)
    left.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
    add_page_field(footer_p)

    normal = document.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(8)
    normal.paragraph_format.line_spacing = 1.12
    normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE


def add_docx_table(document: Document, rows: list[list[str]], numbers: dict[str, int] | None) -> None:
    if not rows:
        return
    ncols = max(len(row) for row in rows)
    table = document.add_table(rows=len(rows), cols=ncols)
    table.autofit = True
    table.allow_autofit = True
    usable = 170
    col_width = Mm(usable / ncols)
    for r_idx, row in enumerate(rows):
        for c_idx in range(ncols):
            text = row[c_idx] if c_idx < len(row) else ""
            cell = table.cell(r_idx, c_idx)
            cell.width = col_width
            cell.text = ""
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_before = Pt(1)
            paragraph.paragraph_format.space_after = Pt(1)
            highlight = bool(PLACEHOLDER_RE.search(text))
            add_inlines_to_paragraph(paragraph, parse_inlines(text, numbers), size=8.5)
            set_cell_border(cell)
            if r_idx == 0:
                shade_cell(cell, "1F4E79")
                for run in paragraph.runs:
                    run.bold = True
                    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                    run.font.size = Pt(8.5)
            elif r_idx % 2 == 0:
                shade_cell(cell, "F2F6FB")
            if highlight:
                shade_cell(cell, PLACEHOLDER_YELLOW)


def add_bibliography_entry_docx(
    document: Document,
    number: int,
    key: str,
    formatted: str,
    counter: BookmarkCounter,
) -> None:
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    paragraph.paragraph_format.space_after = Pt(6)
    paragraph.paragraph_format.left_indent = Mm(6)
    paragraph.paragraph_format.first_line_indent = Mm(-6)
    add_bookmarked_text(paragraph, bookmark_name(key), f"[{number}]", 10.5, counter)
    run = paragraph.add_run(" " + formatted)
    set_run_font(run, size=10.5)


def build_docx(
    blocks: list[Block],
    numbers: dict[str, int] | None,
) -> None:
    document = Document()
    configure_docx_section(document)
    counter = BookmarkCounter()

    for block in blocks:
        if block.kind == "title":
            p = document.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(72)
            p.paragraph_format.space_after = Pt(12)
            run = p.add_run(block.text)
            set_run_font(run, size=20)
            run.bold = True
            run.font.color.rgb = HEADING_BLUE
            continue

        if block.kind == "page_break":
            paragraph = document.add_paragraph()
            run = paragraph.add_run()
            run.add_break(WD_BREAK.PAGE)
            continue

        if block.kind == "heading":
            p = document.add_paragraph()
            p.paragraph_format.space_before = Pt(12 if block.level == 1 else 9)
            p.paragraph_format.space_after = Pt(6)
            p.paragraph_format.keep_with_next = True
            run = p.add_run(block.text)
            set_run_font(run, size=13 if block.level == 1 else 11.5)
            run.bold = True
            run.font.color.rgb = HEADING_BLUE
            continue

        if block.kind == "bibitem":
            add_bibliography_entry_docx(
                document,
                block.cite_number,
                block.cite_key,
                block.text,
                counter,
            )
            continue

        if block.kind == "paragraph":
            p = document.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if block.centered else WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.space_after = Pt(6 if block.centered else 8)
            size = 12 if block.centered else 11
            add_inlines_to_paragraph(p, block.inlines, size=size)
            if block.centered:
                for run in p.runs:
                    if "COMS6200" in run.text:
                        run.bold = True
            continue

        if block.kind == "list":
            for item in block.items:
                p = document.add_paragraph(style="List Bullet")
                p.paragraph_format.space_after = Pt(3)
                add_inlines_to_paragraph(p, item, size=11)
            continue

        if block.kind == "image":
            image_path = (HERE / block.image_path).resolve()
            if not image_path.exists():
                die(f"Missing figure asset: {image_path}")
            p = document.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(4)
            run = p.add_run()
            width_px, height_px = png_size(image_path)
            max_width_mm = 165
            max_height_mm = 88 if "figure3" in image_path.name else 80
            aspect = height_px / width_px
            width_mm = min(max_width_mm, max_height_mm / aspect)
            run.add_picture(str(image_path), width=Mm(width_mm))
            continue

        if block.kind == "caption":
            p = document.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(10)
            run = p.add_run(block.text)
            set_run_font(run, size=10)
            run.italic = True
            continue

        if block.kind == "table":
            add_docx_table(document, block.rows, numbers)
            document.add_paragraph().paragraph_format.space_after = Pt(2)
            continue

    document.save(DOCX_PATH)


def find_times_fonts() -> tuple[str, str, str] | None:
    groups = [
        (
            Path("/System/Library/Fonts/Supplemental/Times New Roman.ttf"),
            Path("/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"),
            Path("/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf"),
        ),
        (
            Path("/Library/Fonts/Times New Roman.ttf"),
            Path("/Library/Fonts/Times New Roman Bold.ttf"),
            Path("/Library/Fonts/Times New Roman Italic.ttf"),
        ),
        (
            Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"),
        ),
        (
            Path("/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf"),
            Path("/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf"),
            Path("/usr/share/fonts/truetype/liberation2/LiberationSerif-Italic.ttf"),
        ),
    ]
    for regular, bold, italic in groups:
        if regular.exists() and bold.exists() and italic.exists():
            return str(regular), str(bold), str(italic)
    return None


def register_pdf_fonts() -> tuple[str, str, str]:
    found = find_times_fonts()
    if found:
        regular, bold, italic = found
        pdfmetrics.registerFont(TTFont("ReportSerif", regular))
        pdfmetrics.registerFont(TTFont("ReportSerif-Bold", bold))
        pdfmetrics.registerFont(TTFont("ReportSerif-Italic", italic))
        return "ReportSerif", "ReportSerif-Bold", "ReportSerif-Italic"
    return "Times-Roman", "Times-Bold", "Times-Italic"


def rl_escape(text: str) -> str:
    return html.escape(text, quote=False)


def inlines_to_rl(inlines: Iterable[Inline]) -> str:
    chunks: list[str] = []
    for part in inlines:
        if part.cite_key:
            anchor = bookmark_name(part.cite_key)
            chunks.append(
                f'<link href="#{anchor}" color="{HEADING_BLUE_HEX}">{rl_escape(part.text)}</link>'
            )
            continue
        text = rl_escape(part.text)
        if part.highlight:
            text = f'<font backColor="#FFF2B2">{text}</font>'
        if part.bold:
            text = f"<b>{text}</b>"
        chunks.append(text)
    return "".join(chunks)


def make_pdf_styles(regular: str, bold: str, italic: str) -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle(
            "TitleStyle",
            fontName=bold,
            fontSize=18,
            leading=22,
            alignment=TA_CENTER,
            textColor=colors.HexColor(HEADING_BLUE_HEX),
            spaceAfter=8,
        ),
        "h1": ParagraphStyle(
            "H1Style",
            fontName=bold,
            fontSize=13,
            leading=16,
            textColor=colors.HexColor(HEADING_BLUE_HEX),
            spaceBefore=11,
            spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "H2Style",
            fontName=bold,
            fontSize=11.5,
            leading=14,
            textColor=colors.HexColor(HEADING_BLUE_HEX),
            spaceBefore=8,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "BodyStyle",
            fontName=regular,
            fontSize=10.5,
            leading=13.2,
            alignment=TA_JUSTIFY,
            spaceAfter=7,
        ),
        "center": ParagraphStyle(
            "CenterStyle",
            fontName=regular,
            fontSize=11,
            leading=14,
            alignment=TA_CENTER,
            spaceAfter=5,
        ),
        "caption": ParagraphStyle(
            "CaptionStyle",
            fontName=italic,
            fontSize=9.5,
            leading=12,
            alignment=TA_CENTER,
            spaceBefore=2,
            spaceAfter=8,
        ),
        "cell": ParagraphStyle(
            "CellStyle",
            fontName=regular,
            fontSize=8,
            leading=10,
            alignment=TA_LEFT,
        ),
        "cell_header": ParagraphStyle(
            "CellHeaderStyle",
            fontName=bold,
            fontSize=8,
            leading=10,
            alignment=TA_LEFT,
            textColor=colors.white,
        ),
        "bullet": ParagraphStyle(
            "BulletStyle",
            fontName=regular,
            fontSize=10.5,
            leading=13.2,
            alignment=TA_JUSTIFY,
            leftIndent=12,
        ),
        "reference": ParagraphStyle(
            "ReferenceStyle",
            fontName=regular,
            fontSize=9.5,
            leading=12,
            alignment=TA_LEFT,
            leftIndent=14,
            firstLineIndent=-14,
            spaceAfter=5,
        ),
    }


class BookmarkAnchor(Flowable):
    """Zero-height named destination bound to a citation key, not an IEEE number."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name
        self.width = 0
        self.height = 0

    def wrap(self, availWidth, availHeight):  # noqa: N803
        return (0, 0)

    def draw(self) -> None:
        self.canv.bookmarkHorizontal(self._name, 0, 10)


def decorate_pdf_page(canvas, doc) -> None:
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(colors.HexColor("#555555"))
    canvas.setFont(doc.header_font, 9)
    canvas.drawRightString(width - 20 * mm, height - 12 * mm, "LLM-Based Network Troubleshooting Agent")
    canvas.setStrokeColor(colors.HexColor(HEADING_BLUE_HEX))
    canvas.setLineWidth(0.7)
    canvas.line(20 * mm, height - 14.5 * mm, width - 20 * mm, height - 14.5 * mm)
    canvas.drawString(20 * mm, 11 * mm, "COMS6200 Part A")
    canvas.drawRightString(width - 20 * mm, 11 * mm, f"Page {doc.page}")
    canvas.line(20 * mm, 15 * mm, width - 20 * mm, 15 * mm)
    canvas.restoreState()


def scaled_image(path: Path, max_width: float, max_height: float) -> Image:
    with PILImage.open(path) as image:
        width_px, height_px = image.size
    aspect = height_px / float(width_px)
    width = max_width
    height = width * aspect
    if height > max_height:
        height = max_height
        width = height / aspect
    return Image(str(path), width=width, height=height)


def pdf_table(rows: list[list[str]], styles: dict[str, ParagraphStyle], content_width: float, numbers: dict[str, int] | None) -> Table:
    ncols = max(len(row) for row in rows)
    data = []
    highlight_cells: list[tuple[int, int]] = []
    for r_idx, row in enumerate(rows):
        rendered = []
        for c_idx in range(ncols):
            text = row[c_idx] if c_idx < len(row) else ""
            style = styles["cell_header"] if r_idx == 0 else styles["cell"]
            rendered.append(Paragraph(inlines_to_rl(parse_inlines(text, numbers)), style))
            if PLACEHOLDER_RE.search(text):
                highlight_cells.append((r_idx, c_idx))
        data.append(rendered)

    if ncols == 3:
        widths = [content_width * x for x in (0.28, 0.22, 0.50)]
    elif ncols == 2:
        widths = [content_width * x for x in (0.28, 0.72)]
    elif ncols == 5:
        widths = [content_width * x for x in (0.16, 0.22, 0.20, 0.22, 0.20)]
    else:
        widths = [content_width / ncols] * ncols

    table = Table(data, colWidths=widths, repeatRows=1)
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(HEADING_BLUE_HEX)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), styles["cell_header"].fontName),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#8FAADC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6FB")]),
    ]
    for r_idx, c_idx in highlight_cells:
        commands.append(("BACKGROUND", (c_idx, r_idx), (c_idx, r_idx), colors.HexColor("#FFF2B2")))
    table.setStyle(TableStyle(commands))
    return table


def build_pdf(blocks: list[Block], numbers: dict[str, int] | None) -> int:
    regular, bold, italic = register_pdf_fonts()
    styles = make_pdf_styles(regular, bold, italic)
    content_width = A4[0] - 40 * mm

    doc = BaseDocTemplate(
        str(PDF_PATH),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title="LLM-Based Network Troubleshooting Agent",
        author="COMS6200",
    )
    doc.header_font = regular
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="report", frames=frame, onPage=decorate_pdf_page)])

    story = []
    for block in blocks:
        if block.kind == "title":
            story.append(Spacer(1, 35 * mm))
            story.append(Paragraph(rl_escape(block.text), styles["title"]))
            continue
        if block.kind == "page_break":
            story.append(PageBreak())
            continue
        if block.kind == "heading":
            style = styles["h1"] if block.level == 1 else styles["h2"]
            story.append(Paragraph(rl_escape(block.text), style))
            continue
        if block.kind == "bibitem":
            anchor = bookmark_name(block.cite_key)
            story.append(
                KeepTogether(
                    [
                        BookmarkAnchor(anchor),
                        Paragraph(
                            f'<a name="{anchor}"/><b>[{block.cite_number}]</b> {rl_escape(block.text)}',
                            styles["reference"],
                        ),
                    ]
                )
            )
            continue
        if block.kind == "paragraph":
            style = styles["center"] if block.centered else styles["body"]
            story.append(Paragraph(inlines_to_rl(block.inlines), style))
            continue
        if block.kind == "list":
            items = [
                ListItem(Paragraph(inlines_to_rl(item), styles["bullet"]), leftIndent=12)
                for item in block.items
            ]
            story.append(
                ListFlowable(
                    items,
                    bulletType="bullet",
                    start="•",
                    leftIndent=18,
                    bulletFontName=regular,
                    bulletFontSize=10,
                    spaceAfter=6,
                )
            )
            continue
        if block.kind == "image":
            image_path = (HERE / block.image_path).resolve()
            if not image_path.exists():
                die(f"Missing figure asset: {image_path}")
            max_height = 90 * mm if "figure3" in image_path.name else 78 * mm
            image = scaled_image(image_path, content_width, max_height)
            image.hAlign = "CENTER"
            story.append(Spacer(1, 4))
            story.append(image)
            continue
        if block.kind == "caption":
            story.append(Paragraph(rl_escape(block.text), styles["caption"]))
            continue
        if block.kind == "table":
            story.append(Spacer(1, 3))
            story.append(pdf_table(block.rows, styles, content_width, numbers))
            story.append(Spacer(1, 4))
            continue

    doc.build(story)
    order = [block.cite_key for block in blocks if block.kind == "bibitem"]
    if order:
        embed_pdf_named_destinations(order)
    return doc.page


def embed_pdf_named_destinations(order: list[str]) -> None:
    """Write stable key-based named destinations onto the generated PDF.

    ReportLab resolves internal links to explicit GoTo coordinates. pypdf does
    not then see those destinations as named catalog entries, so this step
    records ``ref_<citation_key>`` names at the same bibliography locations.
    """
    reader = PdfReader(str(PDF_PATH))
    page_index = {page.indirect_reference.idnum: idx for idx, page in enumerate(reader.pages)}
    dest_groups: dict[tuple[int, float], list] = {}
    for page in reader.pages:
        for annot in page.annotations or []:
            obj = annot.get_object()
            dest = obj.get("/Dest")
            if dest is None:
                continue
            dest_list = list(dest)
            key = (dest_list[0].idnum, round(float(dest_list[3]), 1))
            dest_groups.setdefault(key, dest_list)
    ordered = sorted(dest_groups, key=lambda item: (page_index.get(item[0], 999), -item[1]))
    if len(ordered) != len(order):
        return
    writer = PdfWriter(clone_from=reader)
    for dest_key, cite_key in zip(ordered, order, strict=True):
        dest_list = dest_groups[dest_key]
        page_idx = page_index[dest_key[0]]
        named = ArrayObject(
            [
                writer.pages[page_idx].indirect_reference,
                dest_list[1],
                dest_list[2],
                dest_list[3],
                dest_list[4],
            ]
        )
        writer.add_named_destination_array(TextStringObject(bookmark_name(cite_key)), named)
    tmp_path = PDF_PATH.with_suffix(".pdf.tmp")
    with tmp_path.open("wb") as handle:
        writer.write(handle)
    tmp_path.replace(PDF_PATH)


def xml_text(node: ET.Element) -> str:
    return "".join(item.text or "" for item in node.iter(f"{{{W_NS}}}t"))


def extract_docx_stats() -> dict[str, int | bool | str]:
    with zipfile.ZipFile(DOCX_PATH) as archive:
        xml = archive.read("word/document.xml")
        headers = [name for name in archive.namelist() if name.startswith("word/header")]
        footers = [name for name in archive.namelist() if name.startswith("word/footer")]
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
    root = ET.fromstring(xml)
    text = xml_text(root)
    tables = list(root.iter(f"{{{W_NS}}}tbl"))
    return {
        "tables": len(tables),
        "images": len(media),
        "has_header": bool(headers),
        "has_footer": bool(footers),
        "has_title": "LLM-Based Network Troubleshooting Agent" in text,
        "has_abstract": "Abstract" in text,
        "has_references": "References" in text,
        "placeholder_count": len(PLACEHOLDER_RE.findall(text)),
        "text": text,
        "xml": xml,
    }


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


def text_has(haystack: str, needle: str) -> bool:
    return needle in haystack or compact_text(needle) in compact_text(haystack)


def validate_docx_links(report: CitationReport, xml: bytes) -> tuple[list[str], dict[str, int]]:
    failures: list[str] = []
    root = ET.fromstring(xml)
    bookmarks = {
        node.get(f"{{{W_NS}}}name"): node
        for node in root.iter(f"{{{W_NS}}}bookmarkStart")
        if node.get(f"{{{W_NS}}}name")
    }
    hyperlinks: list[tuple[str, str]] = []
    for node in root.iter(f"{{{W_NS}}}hyperlink"):
        anchor = node.get(f"{{{W_NS}}}anchor")
        if not anchor:
            continue
        hyperlinks.append((anchor, xml_text(node).strip()))

    expected_bookmarks = {bookmark_name(key): key for key in report.order}
    for anchor, key in expected_bookmarks.items():
        if anchor not in bookmarks:
            failures.append(f"DOCX missing bibliography bookmark {anchor} for {key}")

    cite_links = [(anchor, text) for anchor, text in hyperlinks if re.fullmatch(r"\[\d+\]", text)]
    if len(cite_links) < report.occurrence_count:
        failures.append(
            f"DOCX internal citation hyperlinks ({len(cite_links)}) "
            f"< citation occurrences ({report.occurrence_count})"
        )

    reverse = {number: key for key, number in report.numbers.items()}
    for anchor, text in cite_links:
        number = int(text[1:-1])
        key = reverse.get(number)
        if key is None:
            failures.append(f"DOCX citation {text} has no generated key")
            continue
        expected = bookmark_name(key)
        if anchor != expected:
            failures.append(
                f"DOCX citation {text} anchors to {anchor}, expected {expected} ({key})"
            )
    return failures, {
        "docx_citation_hyperlinks": len(cite_links),
        "docx_ref_bookmarks": sum(1 for name in bookmarks if name in expected_bookmarks),
    }


def _pdf_named_destinations(reader: PdfReader) -> dict[str, object]:
    dests: dict[str, object] = {}
    try:
        named = getattr(reader, "named_destinations", None) or {}
        for name, dest in named.items():
            dests[str(name)] = dest
    except Exception:
        pass
    try:
        root_names = reader.root_object.get("/Names")
        if root_names:
            dest_tree = root_names.get_object().get("/Dests")
            if dest_tree:
                names = dest_tree.get_object().get("/Names")
                if names:
                    items = list(names)
                    for idx in range(0, len(items), 2):
                        dests[str(items[idx])] = items[idx + 1]
    except Exception:
        pass
    return dests


def _annotation_destination_name(annotation: dict) -> str | None:
    dest = annotation.get("/Dest")
    if dest is not None:
        if hasattr(dest, "title"):
            return str(dest.title)
        text = str(dest)
        if text.startswith("/"):
            return text[1:]
        return text.strip("()/")
    action = annotation.get("/A")
    if action is None:
        return None
    try:
        action = action.get_object()
    except Exception:
        return None
    named = action.get("/D") or action.get("/Dest")
    if named is None:
        return None
    if hasattr(named, "title"):
        return str(named.title)
    text = str(named)
    if text.startswith("/"):
        return text[1:]
    return None


def validate_pdf_links(report: CitationReport, reader: PdfReader) -> tuple[list[str], list[str], dict[str, int]]:
    failures: list[str] = []
    warnings: list[str] = []
    dests = _pdf_named_destinations(reader)
    expected_names = {bookmark_name(key): key for key in report.order}
    page_index = {page.indirect_reference.idnum: idx for idx, page in enumerate(reader.pages)}
    dest_groups: dict[tuple[int, float], int] = defaultdict(int)
    internal_links = 0
    named_link_hits = 0

    missing_names = [
        f"{name} ({key})"
        for name, key in expected_names.items()
        if name not in dests and f"/{name}" not in dests
    ]
    if missing_names:
        warnings.append(
            "pypdf did not expose named destinations for: " + ", ".join(missing_names[:3])
            + ("..." if len(missing_names) > 3 else "")
            + ". Destination identity is instead verified from internal GoTo coordinates."
        )
    else:
        for name, key in expected_names.items():
            if name not in dests and f"/{name}" not in dests:
                failures.append(f"PDF missing named destination {name} for {key}")

    for page in reader.pages:
        for annot in page.annotations or []:
            try:
                obj = annot.get_object()
            except Exception:
                continue
            subtype = str(obj.get("/Subtype", ""))
            if subtype not in {"/Link", "Link"}:
                continue
            dest = obj.get("/Dest")
            action = obj.get("/A")
            kind = ""
            if action is not None:
                try:
                    kind = str(action.get_object().get("/S", ""))
                except Exception:
                    kind = ""
            if dest is None and kind not in {"/GoTo", "GoTo"}:
                continue
            internal_links += 1
            dest_name = _annotation_destination_name(obj)
            if dest_name and dest_name in expected_names:
                named_link_hits += 1
            if dest is not None:
                dest_list = list(dest)
                dest_page = dest_list[0].idnum
                dest_y = round(float(dest_list[3]), 1)
                dest_groups[(dest_page, dest_y)] += 1

    if internal_links < report.occurrence_count:
        failures.append(
            f"PDF internal citation links ({internal_links}) "
            f"< citation occurrences ({report.occurrence_count})"
        )
    if len(dest_groups) != len(report.order):
        failures.append(
            f"PDF unique bibliography destinations ({len(dest_groups)}) "
            f"!= rendered references ({len(report.order)})"
        )
    else:
        ordered = sorted(
            dest_groups,
            key=lambda item: (page_index.get(item[0], 999), -item[1]),
        )
        expected_counts = Counter()
        for cluster in report.occurrences:
            if cluster.error:
                continue
            for key in cluster.keys:
                expected_counts[key] += 1
        for idx, dest_key in enumerate(ordered):
            key = report.order[idx]
            actual = dest_groups[dest_key]
            expected = expected_counts[key]
            if actual != expected:
                failures.append(
                    f"PDF destination for [{idx + 1}] {key} has {actual} incoming links, expected {expected}"
                )

    refs_page_text = "\n".join((page.extract_text() or "") for page in reader.pages)
    if report.order and not text_has(refs_page_text, f"[{len(report.order)}]"):
        failures.append("PDF bibliography is missing the final generated reference number")

    return failures, warnings, {
        "pdf_internal_links": internal_links,
        "pdf_named_link_hits": named_link_hits,
        "pdf_named_destinations": len(dests),
        "pdf_unique_destinations": len(dest_groups),
    }


def validate_source(source_text: str) -> list[str]:
    failures: list[str] = []
    if not SOURCE.exists() or SOURCE.stat().st_size == 0:
        failures.append("canonical Markdown missing or empty")
    if "Generated automatically from references.bib" not in source_text:
        failures.append("References section is missing the generated-bibliography marker")
    figures = [
        ASSETS / "figure1_topology.png",
        ASSETS / "figure2_architecture.png",
        ASSETS / "figure3_schedule.png",
    ]
    for figure in figures:
        if not figure.exists() or figure.stat().st_size == 0:
            failures.append(f"figure missing or empty: {figure.name}")
        else:
            png_size(figure)
    for rel in (
        "assets/figure1_topology.png",
        "assets/figure2_architecture.png",
        "assets/figure3_schedule.png",
    ):
        if rel not in source_text:
            failures.append(f"Markdown does not reference {rel}")
    tables = [block for block in parse_markdown(source_text) if block.kind == "table"]
    expected_rows = {1: 7, 2: 6, 3: 8, 4: 11, 5: 11, 6: 7}
    if len(tables) != 6:
        failures.append(f"parsed table count is {len(tables)}, expected 6")
    else:
        for idx, table in enumerate(tables, start=1):
            actual = len(table.rows)
            expected = expected_rows[idx]
            if actual != expected:
                failures.append(f"Table {idx} has {actual} rows including header, expected {expected}")
    for idx in range(1, 7):
        if f"Table {idx}." not in source_text:
            failures.append(f"Table {idx} caption missing from source")
    if "TEAM TO INSERT" not in source_text:
        failures.append("TEAM TO INSERT placeholders missing from source")
    if "Not yet evidenced" not in source_text:
        failures.append("Not yet evidenced entries missing from source")
    for section in REQUIRED_SECTIONS:
        if section not in source_text:
            failures.append(f"required section missing from source: {section}")
    return failures


def validate_generated(
    source_text: str,
    page_count: int,
    report: CitationReport,
) -> tuple[list[str], list[str], dict]:
    failures: list[str] = []
    warnings: list[str] = []
    retained = len(report.order)

    if not DOCX_PATH.exists() or DOCX_PATH.stat().st_size == 0:
        failures.append("DOCX missing or empty")
    if not PDF_PATH.exists() or PDF_PATH.stat().st_size == 0:
        failures.append("PDF missing or empty")

    docx_stats = extract_docx_stats() if DOCX_PATH.exists() else {}
    link_stats: dict[str, int] = {}
    if docx_stats:
        if docx_stats["tables"] != 6:
            failures.append(f"DOCX table count is {docx_stats['tables']}, expected 6")
        if docx_stats["images"] != 3:
            failures.append(f"DOCX image count is {docx_stats['images']}, expected 3")
        if not docx_stats["has_header"]:
            failures.append("DOCX header missing")
        if not docx_stats["has_footer"]:
            failures.append("DOCX footer missing")
        if not docx_stats["has_title"]:
            failures.append("DOCX title missing")
        if not docx_stats["has_references"]:
            failures.append("DOCX references missing")
        if int(docx_stats["placeholder_count"]) < 1:
            failures.append("DOCX placeholders missing")
        docx_link_failures, docx_link_stats = validate_docx_links(report, docx_stats["xml"])
        failures.extend(docx_link_failures)
        link_stats.update(docx_link_stats)

    reader = PdfReader(str(PDF_PATH))
    pdf_pages = len(reader.pages)
    pages_text = [(page.extract_text() or "") for page in reader.pages]
    pdf_text = "\n".join(pages_text)
    page1 = pages_text[0] if pages_text else ""
    page2 = pages_text[1] if len(pages_text) > 1 else ""

    if pdf_pages != page_count:
        failures.append(f"PDF page count mismatch: builder={page_count}, reader={pdf_pages}")
    if pdf_pages > MAX_PAGES:
        failures.append(f"PDF has {pdf_pages} pages; maximum acceptable is {MAX_PAGES}")
    elif pdf_pages < MIN_PAGES:
        warnings.append(f"PDF has {pdf_pages} pages; target is {MIN_PAGES}-{MAX_PAGES}")

    if not text_has(page1, "LLM-Based Network Troubleshooting Agent"):
        failures.append("PDF page 1 does not contain the report title")
    if not text_has(page1, "University of Queensland"):
        failures.append("PDF page 1 does not contain The University of Queensland")
    if not text_has(page1, "4 September 2026"):
        failures.append("PDF page 1 does not contain the submission deadline")
    if not text_has(page1, "16 October 2026"):
        failures.append("PDF page 1 does not contain the final-report deadline")
    if text_has(page1, "This project investigates"):
        failures.append("PDF page 1 contains Abstract body text")
    if not text_has(page2, "Abstract"):
        failures.append("PDF page 2 does not contain Abstract")

    for section in REQUIRED_SECTIONS:
        if not text_has(pdf_text, section):
            failures.append(f"PDF is missing section {section!r}")
    for label in (
        "Figure 1",
        "Figure 2",
        "Figure 3",
        "Table 1",
        "Table 2",
        "Table 3",
        "Table 4",
        "Table 5",
        "Table 6",
        "TEAM TO INSERT",
        "References",
    ):
        if not text_has(pdf_text, label):
            failures.append(f"PDF text does not contain {label!r}")
    if retained:
        if not text_has(pdf_text, "[1]"):
            failures.append("PDF references do not start at [1]")
        last = f"[{retained}]"
        if not text_has(pdf_text, last):
            failures.append(f"PDF does not contain last bibliography number {last}")

    pdf_link_failures, pdf_link_warnings, pdf_link_stats = validate_pdf_links(report, reader)
    failures.extend(pdf_link_failures)
    warnings.extend(pdf_link_warnings)
    link_stats.update(pdf_link_stats)

    stats = {
        "pdf_pages": pdf_pages,
        "docx_stats": docx_stats,
        "retained": retained,
        "placeholder_count": len(PLACEHOLDER_RE.findall(source_text)),
        **link_stats,
    }
    return failures, warnings, stats


def print_document_validation(
    source_text: str,
    failures: list[str],
    warnings: list[str],
    stats: dict | None,
) -> None:
    print("Document validation")
    print("-------------------")
    print(f"  Markdown: {SOURCE} ({SOURCE.stat().st_size} bytes)")
    print(f"  Bibliography: {BIB_PATH} ({BIB_PATH.stat().st_size} bytes)")
    for figure in (
        ASSETS / "figure1_topology.png",
        ASSETS / "figure2_architecture.png",
        ASSETS / "figure3_schedule.png",
    ):
        if figure.exists():
            print(f"  Figure: {figure.name} ({figure.stat().st_size} bytes, {png_size(figure)[0]}x{png_size(figure)[1]})")
    if stats and stats.get("docx_stats"):
        docx_stats = stats["docx_stats"]
        print(f"  DOCX: {DOCX_PATH} ({DOCX_PATH.stat().st_size} bytes)")
        print(f"  PDF: {PDF_PATH} ({PDF_PATH.stat().st_size} bytes)")
        print(f"  PDF pages: {stats['pdf_pages']}")
        print(f"  DOCX tables: {docx_stats['tables']}")
        print(f"  DOCX images: {docx_stats['images']}")
        print(f"  DOCX placeholders: {docx_stats['placeholder_count']}")
        print(f"  Rendered bibliography entries: {stats['retained']}")
        print(f"  TEAM TO INSERT placeholders: {stats['placeholder_count']}")
        if "docx_citation_hyperlinks" in stats:
            print(f"  DOCX citation hyperlinks: {stats['docx_citation_hyperlinks']}")
            print(f"  DOCX bibliography bookmarks: {stats['docx_ref_bookmarks']}")
        if "pdf_internal_links" in stats:
            print(f"  PDF internal citation links: {stats['pdf_internal_links']}")
            print(f"  PDF unique bibliography destinations: {stats.get('pdf_unique_destinations', 0)}")
            print(f"  PDF named destinations visible to pypdf: {stats['pdf_named_destinations']}")
    if warnings:
        print("VALIDATION WARNINGS:")
        for item in warnings:
            print(f"  - {item}")
    if failures:
        print("VALIDATION FAILURES:")
        for item in failures:
            print(f"  - {item}")
        die("Report validation failed")
    print("Validation: PASS")


def build_outputs(source_text: str, report: CitationReport, entries: dict[str, dict[str, str]]) -> int:
    print(f"Reading {SOURCE}")
    blocks = parse_markdown(source_text, report.numbers, entries, report.order)
    if not blocks:
        die("Markdown parser produced no blocks")
    print("Building DOCX")
    build_docx(blocks, report.numbers)
    print(f"Wrote {DOCX_PATH}")
    print("Building PDF")
    page_count = build_pdf(blocks, report.numbers)
    print(f"Wrote {PDF_PATH} ({page_count} pages)")
    return page_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and validate the COMS6200 Part A report.")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate Markdown, references.bib and citation keys without building.",
    )
    parser.add_argument(
        "--show-citation-map",
        action="store_true",
        help="Print the generated IEEE-number to citation-key map.",
    )
    parser.add_argument(
        "--fix-ieee-references",
        action="store_true",
        help="Deprecated. Numeric citation rewriting is no longer used.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.fix_ieee_references:
        print(
            "Numeric citation fixing is no longer required. "
            "IEEE numbering is generated automatically from stable citation keys."
        )
        print("This flag does not rewrite part-a-source.md.")
        if not args.validate_only and not args.show_citation_map:
            return

    if not SOURCE.exists():
        die(f"Canonical source not found: {SOURCE}")
    source_text = SOURCE.read_text(encoding="utf-8")
    if not source_text.strip():
        die("Canonical Markdown source is empty")

    entries = load_bibliography(BIB_PATH)
    report = validate_citation_keys(source_text, entries)
    print_citation_report(report, entries)
    print()
    if args.show_citation_map:
        print_citation_map(report, entries)
        print()

    source_failures = validate_source(source_text)
    warnings = list(report.warnings)
    skip_build = args.validate_only or args.show_citation_map

    if skip_build:
        failures = list(source_failures)
        if not report.overall_ok:
            failures.append("citation validation failed")
        if warnings:
            print("VALIDATION WARNINGS:")
            for item in warnings:
                print(f"  - {item}")
        if failures:
            print("VALIDATION FAILURES:")
            for item in failures:
                print(f"  - {item}")
            raise SystemExit(1)
        print("Validation: PASS")
        return

    if not report.overall_ok:
        print("Citation validation failed. The canonical Markdown was not modified.")
        raise SystemExit(1)
    if source_failures:
        print_document_validation(source_text, source_failures, warnings, None)
    page_count = build_outputs(source_text, report, entries)
    generated_failures, generated_warnings, stats = validate_generated(source_text, page_count, report)
    print_document_validation(
        source_text,
        generated_failures,
        warnings + generated_warnings,
        stats,
    )


if __name__ == "__main__":
    main()
