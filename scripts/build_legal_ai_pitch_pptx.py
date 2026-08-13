#!/usr/bin/env python3
"""Legal AI pitch as PowerPoint with embedded playable videos."""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt
from lxml import etree

SRC = Path("/Users/semyon_andronov04/Desktop/скрины сервиса")
ASSETS = Path("/Users/semyon_andronov04/Desktop/C ДВ/tmp_presentation_assets")
OUT = SRC / "Legal_AI_презентация.pptx"

# 16:9
SW, SH = Inches(13.333), Inches(7.5)

INK = RGBColor(0x14, 0x16, 0x18)
MUTED = RGBColor(0x5C, 0x5E, 0x62)
ACCENT = RGBColor(0x1A, 0x2E, 0x38)
BG = RGBColor(0xF6, 0xF4, 0xF0)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
DARK = RGBColor(0x11, 0x12, 0x14)


def blank_slide(prs: Presentation):
    return prs.slides.add_slide(prs.slide_layouts[6])


def fill_bg(slide, color: RGBColor) -> None:
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SW, SH)
    shape.line.fill.background()
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    # send to back
    spTree = slide.shapes._spTree
    sp = shape._element
    spTree.remove(sp)
    spTree.insert(2, sp)


def add_text(
    slide,
    text: str,
    left,
    top,
    width,
    height,
    *,
    size: int = 18,
    bold: bool = False,
    color: RGBColor = INK,
    align=PP_ALIGN.LEFT,
    font_name: str = "Arial",
):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = font_name
    return box


def add_multiline(
    slide,
    lines: list[str],
    left,
    top,
    width,
    height,
    *,
    size: int = 14,
    color: RGBColor = INK,
    bold: bool = False,
    space_after: int = 10,
):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(space_after)
        run = p.add_run()
        run.text = line
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color
        run.font.name = "Arial"
    return box


def enable_movie_autoplay(movie_shape) -> None:
    """Best-effort: mark movie timing for click-to-play (default PowerPoint behavior)."""
    try:
        nvPr = movie_shape._element.nvPicPr.cNvPr
        # ensure description is set
        if not nvPr.get("descr"):
            nvPr.set("descr", "demo video")
    except Exception:
        pass


def slide_title(prs: Presentation) -> None:
    slide = blank_slide(prs)
    fill_bg(slide, BG)
    # left panel — wider so text is not clipped
    panel = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(5.2), SH)
    panel.line.fill.background()
    panel.fill.solid()
    panel.fill.fore_color.rgb = ACCENT
    add_text(slide, "LEGAL AI", Inches(0.55), Inches(0.7), Inches(4.3), Inches(0.4), size=14, bold=True, color=WHITE)
    add_multiline(
        slide,
        ["Платформа для", "legal due diligence"],
        Inches(0.55),
        Inches(1.5),
        Inches(4.3),
        Inches(1.6),
        size=24,
        color=WHITE,
        bold=True,
        space_after=6,
    )
    add_text(
        slide,
        "Для юридической практики",
        Inches(0.55),
        Inches(6.7),
        Inches(4.3),
        Inches(0.3),
        size=11,
        color=RGBColor(0xA8, 0xB4, 0xBA),
    )
    add_multiline(
        slide,
        ["Быстрый анализ", "массива документов сделки."],
        Inches(5.7),
        Inches(2.0),
        Inches(7.0),
        Inches(1.8),
        size=30,
        color=INK,
        bold=True,
        space_after=6,
    )
    add_text(
        slide,
        "Tabular Review помогает команде DD массово извлекать факты из документов и проверять каждый вывод по исходному PDF.",
        Inches(5.7),
        Inches(4.2),
        Inches(6.8),
        Inches(1.2),
        size=14,
        color=MUTED,
    )


def slide_problem(prs: Presentation) -> None:
    slide = blank_slide(prs)
    fill_bg(slide, BG)
    add_text(slide, "КОНТЕКСТ", Inches(0.7), Inches(0.45), Inches(4), Inches(0.3), size=11, bold=True, color=MUTED)
    add_text(
        slide,
        "Что тормозит legal due diligence",
        Inches(0.7),
        Inches(0.85),
        Inches(11),
        Inches(0.6),
        size=28,
        bold=True,
        color=INK,
    )
    items = [
        ("Документы", "Сотни уставов, корпоративных документов и договоров приходится просматривать вручную по PDF."),
        ("Повторяющиеся вопросы", "Consent, change of control, termination, liability caps и другие пункты нужно искать по каждому документу заново."),
        ("Контроль качества", "Недостаточно получить ответ: юристу нужен источник, страница и цитата для быстрой проверки."),
    ]
    y = Inches(1.9)
    for title, desc in items:
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.7), y, Inches(11.9), Inches(1.35))
        card.adjustments[0] = 0.08
        card.fill.solid()
        card.fill.fore_color.rgb = WHITE
        card.line.color.rgb = RGBColor(0xD8, 0xD4, 0xCC)
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.7), y, Inches(0.12), Inches(1.35))
        bar.fill.solid()
        bar.fill.fore_color.rgb = ACCENT
        bar.line.fill.background()
        add_text(slide, title, Inches(1.2), y + Inches(0.28), Inches(10), Inches(0.35), size=16, bold=True, color=INK)
        add_text(slide, desc, Inches(1.2), y + Inches(0.7), Inches(10.5), Inches(0.45), size=13, color=MUTED)
        y += Inches(1.55)


def slide_pillars(prs: Presentation) -> None:
    slide = blank_slide(prs)
    fill_bg(slide, BG)
    add_text(slide, "РЕШЕНИЕ", Inches(0.7), Inches(0.45), Inches(4), Inches(0.3), size=11, bold=True, color=MUTED)
    add_text(
        slide,
        "Один инструмент для DD-проверки документов",
        Inches(0.7),
        Inches(0.85),
        Inches(11),
        Inches(0.55),
        size=28,
        bold=True,
        color=INK,
    )
    add_text(
        slide,
        "Вы задаёте структуру проверки, а Tabular Review массово извлекает факты по всему документальному периметру сделки.",
        Inches(0.7),
        Inches(1.45),
        Inches(11.5),
        Inches(0.4),
        size=14,
        color=MUTED,
    )
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.7), Inches(2.2), Inches(11.9), Inches(4.3))
    card.adjustments[0] = 0.06
    card.fill.solid()
    card.fill.fore_color.rgb = WHITE
    card.line.color.rgb = RGBColor(0xD8, 0xD4, 0xCC)
    add_text(slide, "Tabular Review", Inches(1.1), Inches(2.55), Inches(5), Inches(0.5), size=22, bold=True, color=INK)
    add_multiline(
        slide,
        [
            "•  Строка = документ",
            "•  Столбец = вопрос DD-чеклиста",
            "•  Ячейка = извлечённый факт",
            "•  Каждый ответ связан с цитатой и страницей PDF",
            "•  Команда получает единую таблицу для findings memo и issues list",
        ],
        Inches(1.1),
        Inches(3.2),
        Inches(10.8),
        Inches(2.8),
        size=16,
        color=INK,
        space_after=14,
    )


def slide_video(
    prs: Presentation,
    *,
    eyebrow: str,
    title: str,
    subtitle: str,
    video_path: Path,
    poster_path: Path,
) -> None:
    slide = blank_slide(prs)
    fill_bg(slide, DARK)
    add_text(slide, eyebrow, Inches(0.7), Inches(0.35), Inches(10), Inches(0.3), size=11, bold=True, color=RGBColor(0x8A, 0x90, 0x96))
    add_text(slide, title, Inches(0.7), Inches(0.65), Inches(12), Inches(0.5), size=24, bold=True, color=WHITE)
    add_text(slide, subtitle, Inches(0.7), Inches(1.2), Inches(12), Inches(0.35), size=13, color=RGBColor(0xA0, 0xA6, 0xAC))

    left, top = Inches(0.7), Inches(1.7)
    width, height = Inches(11.9), Inches(5.2)
    movie = slide.shapes.add_movie(
        str(video_path),
        left,
        top,
        width,
        height,
        poster_frame_image=str(poster_path) if poster_path.exists() else None,
        mime_type="video/mp4",
    )
    enable_movie_autoplay(movie)
    add_text(
        slide,
        "Нажмите на видео, чтобы воспроизвести  ·  работает в Microsoft PowerPoint и Keynote",
        Inches(0.7),
        Inches(7.05),
        Inches(11),
        Inches(0.3),
        size=11,
        color=RGBColor(0x8A, 0x90, 0x96),
    )


def slide_control(prs: Presentation) -> None:
    """Full-bleed product shot: original PDF open + yellow highlight must be visible."""
    slide = blank_slide(prs)
    fill_bg(slide, DARK)
    add_text(
        slide,
        "ПРОВЕРКА ИСТОЧНИКА",
        Inches(0.5),
        Inches(0.28),
        Inches(6),
        Inches(0.28),
        size=11,
        bold=True,
        color=RGBColor(0x8A, 0x90, 0x96),
    )
    add_text(
        slide,
        "Вывод DD-таблицы → цитата → оригинал PDF с подсветкой",
        Inches(0.5),
        Inches(0.52),
        Inches(12),
        Inches(0.4),
        size=20,
        bold=True,
        color=WHITE,
    )
    poster = ASSETS / "source_proof_0.jpg"
    if not poster.exists():
        poster = ASSETS / "hero_tabular_1.jpg"
    # Almost full slide — do not crop the right PDF pane
    if poster.exists():
        slide.shapes.add_picture(str(poster), Inches(0.4), Inches(1.05), width=Inches(12.5))


def slide_close(prs: Presentation) -> None:
    slide = blank_slide(prs)
    fill_bg(slide, BG)
    panel = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.7), Inches(0.7), Inches(11.9), Inches(6.1))
    panel.adjustments[0] = 0.04
    panel.fill.solid()
    panel.fill.fore_color.rgb = ACCENT
    panel.line.fill.background()
    # Centered headline
    box = slide.shapes.add_textbox(Inches(1.5), Inches(2.0), Inches(10.3), Inches(2.6))
    tf = box.text_frame
    tf.word_wrap = True
    for i, line in enumerate(["Меньше рутины.", "Больше дел.", "Полный контроль над выводами."]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.CENTER
        p.space_after = Pt(6)
        run = p.add_run()
        run.text = line
        run.font.size = Pt(32)
        run.font.bold = True
        run.font.color.rgb = WHITE
        run.font.name = "Arial"
    sub = slide.shapes.add_textbox(Inches(2.2), Inches(4.9), Inches(9.0), Inches(1.0))
    tf2 = sub.text_frame
    tf2.word_wrap = True
    p2 = tf2.paragraphs[0]
    p2.alignment = PP_ALIGN.CENTER
    run2 = p2.add_run()
    run2.text = (
        "Tabular Review ускоряет legal due diligence по массиву документов — "
        "чтобы команда сосредоточилась на анализе рисков и подготовке выводов."
    )
    run2.font.size = Pt(14)
    run2.font.color.rgb = RGBColor(0xB0, 0xBC, 0xC2)
    run2.font.name = "Arial"


def main() -> None:
    tabular_video = ASSETS / "demo_tabular_720.mp4"
    if not tabular_video.exists():
        raise SystemExit(f"Missing compressed video: {tabular_video}")

    prs = Presentation()
    prs.slide_width = SW
    prs.slide_height = SH

    slide_title(prs)
    slide_problem(prs)
    slide_pillars(prs)
    slide_video(
        prs,
        eyebrow="ДЕМО  ·  TABULAR REVIEW",
        title="Один DD-вопрос — по всему массиву документов",
        subtitle="Система извлекает факты по каждому документу, а юрист сразу сверяет цитату с оригиналом PDF.",
        video_path=tabular_video,
        poster_path=ASSETS / "hero_tabular_1.jpg",
    )
    slide_control(prs)
    slide_close(prs)

    prs.save(str(OUT))
    print("saved", OUT)
    print("size_mb", round(OUT.stat().st_size / 1e6, 1))
    print("open in: Microsoft PowerPoint / Apple Keynote (видео воспроизводятся внутри)")


if __name__ == "__main__":
    main()
