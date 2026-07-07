#!/usr/bin/env python3
"""Generate Kaggle-ready visual assets for writeup and video thumbnails.

Outputs PNG files in docs/assets with dimensions >= 640x360 and small file size.
"""

from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw

ASSETS_DIR = Path(__file__).resolve().parent.parent / "docs" / "assets"


def _gradient_background(width: int, height: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    return image


def _draw_header(draw: ImageDraw.ImageDraw, title: str, subtitle: str, width: int) -> None:
    draw.rounded_rectangle((40, 30, width - 40, 150), radius=24, fill=(245, 250, 255), outline=(170, 196, 220), width=2)
    draw.text((70, 55), title, fill=(16, 45, 84))
    draw.text((70, 102), subtitle, fill=(53, 79, 112))


def _draw_flow(draw: ImageDraw.ImageDraw, y: int, labels: list[str], width: int) -> None:
    x = 60
    box_w = (width - 120 - 30 * (len(labels) - 1)) // len(labels)
    for i, label in enumerate(labels):
        x1 = x + i * (box_w + 30)
        x2 = x1 + box_w
        draw.rounded_rectangle((x1, y, x2, y + 90), radius=14, fill=(236, 244, 252), outline=(130, 168, 201), width=2)
        draw.text((x1 + 14, y + 35), label, fill=(24, 54, 90))
        if i < len(labels) - 1:
            arrow_x = x2 + 8
            draw.line((arrow_x, y + 45, arrow_x + 14, y + 45), fill=(24, 54, 90), width=3)
            draw.polygon([(arrow_x + 14, y + 45), (arrow_x + 7, y + 40), (arrow_x + 7, y + 50)], fill=(24, 54, 90))


def make_kaggle_cover() -> None:
    width, height = 1280, 720
    image = _gradient_background(width, height, (232, 242, 251), (212, 230, 246))
    draw = ImageDraw.Draw(image)

    _draw_header(
        draw,
        "PharmaGenomics Advisor",
        "Multi-agent precision medicine pipeline with ADK, MCP, Ollama, and security guardrails",
        width,
    )
    _draw_flow(draw, 220, ["VCF Input", "Gene Agents", "PGx Advisor", "Literature", "Clinical Reports"], width)

    draw.rounded_rectangle((60, 380, 1220, 660), radius=18, fill=(248, 252, 255), outline=(160, 188, 215), width=2)
    draw.text((90, 420), "What this project delivers", fill=(17, 51, 88))
    bullets = [
        "Actionable variant interpretation with route-aware specialist handling",
        "Evidence-backed drug recommendations and literature synthesis",
        "Dual report outputs: JSON + Markdown + Official-style HTML",
        "Audience-friendly tooling summary and clinical warning guidance",
    ]
    y = 470
    for bullet in bullets:
        draw.text((100, y), f"- {bullet}", fill=(35, 66, 102))
        y += 42

    image.save(ASSETS_DIR / "kaggle-cover.png", format="PNG", optimize=True)


def make_architecture_slide() -> None:
    width, height = 1600, 900
    image = _gradient_background(width, height, (229, 239, 248), (206, 223, 239))
    draw = ImageDraw.Draw(image)
    _draw_header(draw, "Architecture at a glance", "Agentic orchestration, MCP tools, local inference, and secure runtime", width)

    _draw_flow(draw, 210, ["Security", "Supervisor", "Specialists", "Recommendations", "Reports"], width)

    draw.rounded_rectangle((70, 360, 760, 840), radius=18, fill=(246, 251, 255), outline=(146, 177, 204), width=2)
    draw.text((95, 390), "Core concepts used", fill=(18, 50, 84))
    items = [
        "ADK workflow runtime",
        "Message bus multi-agent dispatch",
        "ClinVar / CPIC / PharmGKB MCP bridge",
        "Ollama-based narrative generation",
        "PHI, injection, and rate-limit checks",
    ]
    yy = 440
    for item in items:
        draw.text((105, yy), f"- {item}", fill=(40, 69, 101))
        yy += 65

    draw.rounded_rectangle((840, 360, 1530, 840), radius=18, fill=(246, 251, 255), outline=(146, 177, 204), width=2)
    draw.text((865, 390), "Produced artifacts", fill=(18, 50, 84))
    outputs = [
        "report.json: structured machine-readable output",
        "report.md: concise narrative review summary",
        "report.html: official-style stakeholder report",
        "warnings: impact + recommended action",
    ]
    yy = 440
    for out in outputs:
        draw.text((875, yy), f"- {out}", fill=(40, 69, 101))
        yy += 65

    image.save(ASSETS_DIR / "pipeline-architecture.png", format="PNG", optimize=True)


def make_report_preview() -> None:
    width, height = 1600, 900
    image = _gradient_background(width, height, (238, 245, 252), (219, 233, 245))
    draw = ImageDraw.Draw(image)
    _draw_header(draw, "Clinical report outputs", "Readable markdown + polished HTML designed for real-world review", width)

    draw.rounded_rectangle((70, 190, 770, 840), radius=16, fill=(255, 255, 255), outline=(165, 190, 213), width=2)
    draw.text((95, 220), "Markdown report", fill=(18, 50, 84))
    md_lines = [
        "# PharmaGenomics Advisor Clinical Report",
        "- Variants analyzed: 3",
        "- Drug recommendations: 5",
        "## Variant Classifications",
        "## Drug Recommendations",
        "## Literature Evidence",
        "## Tools and Platform Features",
        "## Warnings",
    ]
    yy = 270
    for line in md_lines:
        draw.text((100, yy), line, fill=(52, 76, 107))
        yy += 56

    draw.rounded_rectangle((830, 190, 1530, 840), radius=16, fill=(255, 255, 255), outline=(165, 190, 213), width=2)
    draw.text((855, 220), "HTML report", fill=(18, 50, 84))
    html_lines = [
        "- Header + KPI cards",
        "- Variant interpretation cards",
        "- Recommendations table",
        "- Literature evidence sections",
        "- Tools and platform feature matrix",
        "- Clinical and operational warnings",
    ]
    yy = 290
    for line in html_lines:
        draw.text((860, yy), line, fill=(52, 76, 107))
        yy += 82

    image.save(ASSETS_DIR / "report-preview.png", format="PNG", optimize=True)


def make_youtube_thumbnail() -> None:
    width, height = 1280, 720
    image = _gradient_background(width, height, (223, 236, 249), (194, 218, 240))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((30, 30, width - 30, height - 30), radius=30, fill=(244, 250, 255), outline=(123, 163, 200), width=3)
    draw.rounded_rectangle((55, 55, 430, 210), radius=18, fill=(22, 63, 110))
    draw.text((80, 115), "KAGGLE CAPSTONE", fill=(245, 250, 255))

    draw.text((80, 260), "PharmaGenomics Advisor", fill=(14, 43, 77))
    draw.text((80, 325), "ADK + MCP + Ollama + Security", fill=(30, 66, 103))

    draw.rounded_rectangle((80, 400, 1200, 630), radius=16, fill=(232, 243, 253), outline=(140, 177, 208), width=2)
    pills = ["VCF", "Gene Agents", "Drug Guidance", "Evidence", "HTML Report"]
    x = 110
    for pill in pills:
        draw.rounded_rectangle((x, 450, x + 200, 560), radius=20, fill=(255, 255, 255), outline=(132, 170, 203), width=2)
        draw.text((x + 28, 495), pill, fill=(25, 61, 98))
        x += 215

    image.save(ASSETS_DIR / "youtube-thumbnail.png", format="PNG", optimize=True)


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    make_kaggle_cover()
    make_architecture_slide()
    make_report_preview()
    make_youtube_thumbnail()
    print("Generated assets:")
    for file_name in [
        "kaggle-cover.png",
        "pipeline-architecture.png",
        "report-preview.png",
        "youtube-thumbnail.png",
    ]:
        path = ASSETS_DIR / file_name
        print(f"- {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
