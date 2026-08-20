#!/usr/bin/env python3
"""Regenerate Part A figures from code (not hand-drawn screenshots)."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"

BLUE = (91, 155, 213)
BLUE_EDGE = (46, 117, 182)
NAVY = (31, 78, 121)
INK = (50, 50, 50)
GREY = (90, 90, 90)
DASH = (196, 89, 17)
WHITE = (255, 255, 255)
BOX = (232, 240, 248)
BOX_EDGE = (31, 78, 121)
ORANGE = (237, 125, 49)
GREEN = (112, 173, 71)
PURPLE = (112, 48, 160)
RED = (192, 80, 77)
BROWN = (191, 144, 0)
PINK = (197, 90, 137)
TEAL = (0, 176, 166)
OLIVE = (169, 166, 77)


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/Library/Fonts/Arial Bold.ttf",
            ]
        )
    candidates.extend(
        [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/Library/Fonts/Arial.ttf",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _center(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font, fill=WHITE) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((xy[0] - w / 2, xy[1] - h / 2 - 1), text, font=font, fill=fill)


def _line(draw: ImageDraw.ImageDraw, a, b, fill=INK, width=4) -> None:
    draw.line((a[0], a[1], b[0], b[1]), fill=fill, width=width)


def _dashed(draw: ImageDraw.ImageDraw, a, b, fill=DASH, width=4, dash=14, gap=9) -> None:
    x1, y1 = a
    x2, y2 = b
    dist = math.hypot(x2 - x1, y2 - y1)
    if dist == 0:
        return
    dx, dy = (x2 - x1) / dist, (y2 - y1) / dist
    pos = 0.0
    on = True
    while pos < dist:
        step = dash if on else gap
        npos = min(pos + step, dist)
        if on:
            draw.line(
                (x1 + dx * pos, y1 + dy * pos, x1 + dx * npos, y1 + dy * npos),
                fill=fill,
                width=width,
            )
        pos = npos
        on = not on


def _switch(draw, xy, label, font, w=108, h=56) -> None:
    x, y = xy
    box = [x - w // 2, y - h // 2, x + w // 2, y + h // 2]
    draw.rounded_rectangle(box, radius=8, fill=BLUE, outline=BLUE_EDGE, width=3)
    _center(draw, xy, label, font)


def _host(draw, xy, label, font, r=28) -> None:
    x, y = xy
    draw.ellipse([x - r, y - r, x + r, y + r], fill=BLUE, outline=BLUE_EDGE, width=3)
    _center(draw, xy, label, font)


def _role(draw, xy, text, font) -> None:
    draw.text(xy, text, font=font, fill=NAVY)


def draw_figure1(path: Path) -> None:
    img = Image.new("RGBA", (1957, 1016), WHITE)
    draw = ImageDraw.Draw(img)
    title = _font(28, bold=True)
    body = _font(22)
    small = _font(18)
    node = _font(24, bold=True)

    s1, s2 = (980, 170), (980, 640)
    s3, s4 = (430, 280), (430, 530)
    s5, s6 = (1500, 250), (1500, 560)
    h1, h2 = (160, 200), (160, 360)
    h3, h4 = (160, 470), (160, 630)
    h5, h6 = (1800, 170), (1800, 340)
    h7, h8 = (1800, 500), (1800, 660)

    # Baseline physical links
    for a, b in (
        (s1, s2),
        (s1, s3), (s1, s4), (s1, s5), (s1, s6),
        (s2, s3), (s2, s4), (s2, s5), (s2, s6),
        (s3, h1), (s3, h2), (s4, h3), (s4, h4),
        (s5, h5), (s5, h6), (s6, h7), (s6, h8),
    ):
        _line(draw, a, b, INK, 4)

    # Controlled test / extension links
    _dashed(draw, s3, s4, DASH, 5)
    _dashed(draw, h6, s6, DASH, 5)

    for xy, name in (
        (s1, "s1"), (s2, "s2"), (s3, "s3"), (s4, "s4"), (s5, "s5"), (s6, "s6"),
    ):
        _switch(draw, xy, name, node)
    for xy, name in (
        (h1, "h1"), (h2, "h2"), (h3, "h3"), (h4, "h4"),
        (h5, "h5"), (h6, "h6"), (h7, "h7"), (h8, "h8"),
    ):
        _host(draw, xy, name, node)

    _role(draw, (920, 92), "Core A", body)
    _role(draw, (920, 710), "Core B", body)
    _role(draw, (370, 200), "User Access A", small)
    _role(draw, (370, 450), "User Access B", small)
    _role(draw, (1440, 170), "Server Access", small)
    _role(draw, (1410, 480), "Admin/Test Access", small)
    _role(draw, (1688, 390), "h6-eth0 primary", small)
    _role(draw, (1575, 430), "h6-eth1 secondary", small)

    # Legend
    draw.rectangle([70, 860, 1880, 980], outline=NAVY, width=2)
    _line(draw, (110, 900), (210, 900), INK, 5)
    draw.text((230, 886), "Physical link (present in the Mininet topology)", font=small, fill=INK)
    _dashed(draw, (110, 945), (210, 945), DASH, 5)
    draw.text(
        (230, 931),
        "Controlled test/extension link (physically present; unused by baseline forwarding)",
        font=small,
        fill=INK,
    )
    draw.text((1280, 886), "Squares = OpenFlow switches", font=small, fill=GREY)
    draw.text((1280, 931), "Circles = hosts   IPv4 10.0.0.0/24", font=small, fill=GREY)

    img.save(path)


def _box(draw, xy, w, h, title, font, fill=BOX) -> tuple[int, int, int, int]:
    x, y = xy
    rect = [x, y, x + w, y + h]
    draw.rounded_rectangle(rect, radius=10, fill=fill, outline=BOX_EDGE, width=3)
    _center(draw, (x + w // 2, y + h // 2), title, font, fill=NAVY)
    return x, y, x + w, y + h


def _arrow(draw, a, b, text="", font=None) -> None:
    _line(draw, a, b, NAVY, 3)
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    ah = 14
    for da in (2.6, -2.6):
        draw.line(
            (
                b[0],
                b[1],
                b[0] - ah * math.cos(ang + da),
                b[1] - ah * math.sin(ang + da),
            ),
            fill=NAVY,
            width=3,
        )
    if text and font:
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.rectangle([mx - tw / 2 - 6, my - th / 2 - 16, mx + tw / 2 + 6, my + th / 2 - 2], fill=WHITE)
        draw.text((mx - tw / 2, my - th - 6), text, font=font, fill=GREY)


def draw_figure2(path: Path) -> None:
    img = Image.new("RGBA", (1957, 1011), WHITE)
    draw = ImageDraw.Draw(img)
    title = _font(22, bold=True)
    small = _font(16)

    # Row 1
    inj = _box(draw, (80, 80), 360, 90, "Fault Injector", title)
    mn = _box(draw, (560, 80), 360, 90, "Mininet / OVS", title)
    onos = _box(draw, (1040, 80), 420, 90, "ONOS 2.7.0", title)
    _arrow(draw, (inj[2], 125), (mn[0], 125), "inject faults", small)
    _arrow(draw, (mn[2], 125), (onos[0], 125), "OpenFlow 1.3", small)

    # Row 2
    gw = _box(draw, (1040, 300), 420, 90, "Telemetry / Tool Gateway", title)
    _arrow(draw, (1250, onos[3]), (1250, gw[1]), "read-only REST  (no credentials to LLM)", small)

    # Row 3
    llm = _box(draw, (1040, 520), 420, 90, "OpenAI LLM Agent", title)
    _arrow(draw, (1250, gw[3]), (1250, llm[1]), "structured JSON / tools", small)

    # Row 4
    diag = _box(draw, (1040, 740), 420, 90, "Diagnosis (+ optional repair)", title)
    ev = _box(draw, (80, 740), 520, 90, "Evaluator / Logger", title)
    _arrow(draw, (1250, llm[3]), (1250, diag[1]))
    _arrow(draw, (diag[0], 785), (ev[2], 785))

    # Ground-truth isolation
    _dashed(draw, (260, inj[3]), (260, ev[1]), DASH, 4)
    draw.text((280, 430), "ground truth only", font=small, fill=DASH)
    draw.text((280, 460), "(never shown to the agent)", font=small, fill=DASH)

    draw.rectangle([80, 880, 1870, 970], outline=NAVY, width=2)
    draw.text(
        (110, 900),
        "The LLM and scripted baseline call the telemetry gateway only. They do not receive ONOS credentials,",
        font=small,
        fill=INK,
    )
    draw.text(
        (110, 932),
        "unrestricted REST, or injector configuration. Hidden ground truth remains evaluator-only.",
        font=small,
        fill=INK,
    )
    img.save(path)


def draw_figure3(path: Path) -> None:
    img = Image.new("RGBA", (2179, 1252), WHITE)
    draw = ImageDraw.Draw(img)
    title = _font(22, bold=True)
    small = _font(16)
    tiny = _font(14)

    left = 430
    right = 2080
    top = 110
    row_h = 92
    tasks = [
        ("Environment + main topology", BLUE, 0.00, 0.11),
        ("ONOS/OpenFlow 1.3 + telemetry", ORANGE, 0.05, 0.18),
        ("Fault injection: link + ACL", GREEN, 0.12, 0.24),
        ("First LLM tool-calling vertical slice", RED, 0.18, 0.30),
        ("Part A write-up/evidence", PURPLE, 0.20, 0.32),
        ("Remaining faults + scripted baseline", BROWN, 0.32, 0.55),
        ("Pilot + freeze experiment protocol", PINK, 0.48, 0.62),
        ("Repeated experiments", GREY, 0.60, 0.78),
        ("Optional one-case repair demo", OLIVE, 0.70, 0.84),
        ("Analysis + final report/demo prep", TEAL, 0.78, 1.00),
    ]

    # Date axis 18 Aug - 16 Oct ~ 59 days
    labels = ["18 Aug", "25 Aug", "1 Sep", "8 Sep", "15 Sep", "22 Sep", "29 Sep", "6 Oct", "13 Oct"]
    for i, lab in enumerate(labels):
        x = left + i * (right - left) / (len(labels) - 1)
        draw.line((x, top - 10, x, top + row_h * len(tasks) + 10), fill=(230, 230, 230), width=1)
        bbox = draw.textbbox((0, 0), lab, font=tiny)
        draw.text((x - (bbox[2] - bbox[0]) / 2, 70), lab, font=tiny, fill=GREY)

    part_a = left + (right - left) * (17 / 59)  # 4 Sep is ~17 days from 18 Aug
    final = right
    draw.line((part_a, 55, part_a, top + row_h * len(tasks) + 20), fill=NAVY, width=3)
    draw.line((final, 55, final, top + row_h * len(tasks) + 20), fill=NAVY, width=3)
    draw.text((part_a - 40, 32), "Part A due", font=tiny, fill=NAVY)
    draw.text((final - 70, 32), "Final due", font=tiny, fill=NAVY)

    for i, (name, color, start, end) in enumerate(tasks):
        y = top + i * row_h
        draw.text((40, y + 28), name, font=small, fill=INK)
        x1 = left + start * (right - left)
        x2 = left + end * (right - left)
        draw.rounded_rectangle([x1, y + 18, x2, y + 62], radius=8, fill=color)

    img.save(path)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    draw_figure1(ASSETS / "figure1_topology.png")
    draw_figure2(ASSETS / "figure2_architecture.png")
    draw_figure3(ASSETS / "figure3_schedule.png")
    print(f"Wrote figures under {ASSETS}")


if __name__ == "__main__":
    main()
