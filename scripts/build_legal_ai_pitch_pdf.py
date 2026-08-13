#!/usr/bin/env python3
"""Serious Legal AI pitch PDF for due diligence lawyers."""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

SRC = Path("/Users/semyon_andronov04/Desktop/скрины сервиса")
ASSETS = Path("/Users/semyon_andronov04/Desktop/C ДВ/tmp_presentation_assets")
OUT = SRC / "Legal_AI_презентация.pdf"

# Landscape 16:9-ish presentation size (points)
W, H = 960, 540  # ~16:9 at readable print size

# Serious editorial palette
BG = (0.965, 0.961, 0.953)  # warm paper, subtle
INK = (0.08, 0.09, 0.10)
MUTED = (0.38, 0.38, 0.40)
LINE = (0.78, 0.76, 0.72)
ACCENT = (0.10, 0.18, 0.22)  # deep slate-navy
WHITE = (1, 1, 1)
DARK = (0.07, 0.08, 0.09)


def font_regular() -> str:
    for p in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ):
        if Path(p).exists():
            return p
    return "helv"


def font_bold() -> str:
    for p in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ):
        if Path(p).exists():
            return p
    return "hebo"


def font_serif() -> str:
    for p in (
        "/System/Library/Fonts/NewYork.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/Library/Fonts/Times New Roman.ttf",
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
    ):
        if Path(p).exists():
            return p
    return font_regular()


FR, FB, FS = font_regular(), font_bold(), font_serif()


def new_page(doc: fitz.Document, dark: bool = False) -> fitz.Page:
    page = doc.new_page(width=W, height=H)
    color = DARK if dark else BG
    page.draw_rect(fitz.Rect(0, 0, W, H), color=color, fill=color)
    return page


def text(
    page: fitz.Page,
    s: str,
    x: float,
    y: float,
    *,
    fontfile: str,
    size: float,
    color=INK,
    width: float | None = None,
) -> float:
    """Draw text; if width set, wrap and return bottom y."""
    if width is None:
        page.insert_font(fontname="f", fontfile=fontfile)
        page.insert_text(
            (x, y),
            s,
            fontsize=size,
            fontname="f",
            fontfile=fontfile,
            color=color,
        )
        return y
    # use textbox
    # estimate lines
    words = s.split()
    lines: list[str] = []
    cur = ""
    # approximate char width
    avg = size * 0.48
    max_chars = max(12, int(width / avg))
    for w in words:
        trial = f"{cur} {w}".strip()
        if len(trial) <= max_chars:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    yy = y
    for line in lines:
        page.insert_text(
            (x, yy),
            line,
            fontsize=size,
            fontname="f",
            fontfile=fontfile,
            color=color,
        )
        yy += size * 1.45
    return yy


def footer(page: fitz.Page, n: int, total: int, dark: bool = False) -> None:
    col = (0.55, 0.55, 0.55) if not dark else (0.45, 0.45, 0.48)
    y = H - 22
    page.draw_line(fitz.Point(48, y - 10), fitz.Point(W - 48, y - 10), color=LINE if not dark else (0.22, 0.22, 0.24), width=0.5)
    page.insert_text((48, y), "Legal AI", fontsize=9, fontname="f", fontfile=FR, color=col)
    page.insert_text((W - 70, y), f"{n} / {total}", fontsize=9, fontname="f", fontfile=FR, color=col)


def place_image(page: fitz.Page, path: Path, rect: fitz.Rect, radius: float = 4) -> None:
    if not path.exists():
        return
    # white frame
    page.draw_rect(rect, color=LINE, fill=WHITE, width=0.6)
    inner = fitz.Rect(rect.x0 + 1, rect.y0 + 1, rect.x1 - 1, rect.y1 - 1)
    page.insert_image(inner, filename=str(path), keep_proportion=True)


def slide_title(doc: fitz.Document) -> None:
    page = new_page(doc)
    # left dark panel
    page.draw_rect(fitz.Rect(0, 0, W * 0.36, H), color=ACCENT, fill=ACCENT)
    page.insert_text((48, 72), "LEGAL AI", fontsize=13, fontname="f", fontfile=FB, color=WHITE)
    text(
        page,
        "Платформа для\nlegal due diligence",
        48,
        120,
        fontfile=FS,
        size=22,
        color=WHITE,
        width=W * 0.28,
    )
    page.insert_text(
        (48, H - 48),
        "Для юридической практики",
        fontsize=10,
        fontname="f",
        fontfile=FR,
        color=(0.7, 0.75, 0.78),
    )

    text(
        page,
        "Быстрый анализ\nмассива документов сделки.",
        W * 0.42,
        160,
        fontfile=FS,
        size=34,
        color=INK,
        width=W * 0.5,
    )
    text(
        page,
        "Tabular Review помогает команде DD массово извлекать факты из документов "
        "и проверять каждый вывод по исходному PDF.",
        W * 0.42,
        290,
        fontfile=FR,
        size=13,
        color=MUTED,
        width=W * 0.5,
    )


def slide_problem(doc: fitz.Document) -> None:
    page = new_page(doc)
    page.insert_text((48, 56), "КОНТЕКСТ", fontsize=10, fontname="f", fontfile=FB, color=MUTED)
    text(page, "Что тормозит legal due diligence", 48, 88, fontfile=FS, size=28, color=INK, width=700)
    points = [
        ("Документы", "Сотни уставов, корпоративных документов и договоров приходится просматривать вручную по PDF."),
        ("Повторяющиеся вопросы", "Consent, change of control, termination, liability caps и другие пункты нужно искать по каждому документу заново."),
        ("Контроль качества", "Недостаточно получить ответ: юристу нужен источник, страница и цитата для быстрой проверки."),
    ]
    y = 170
    for title, desc in points:
        page.draw_rect(fitz.Rect(48, y, W - 48, y + 78), color=LINE, fill=WHITE, width=0.6)
        page.draw_rect(fitz.Rect(48, y, 54, y + 78), color=ACCENT, fill=ACCENT)
        page.insert_text((72, y + 28), title, fontsize=14, fontname="f", fontfile=FB, color=INK)
        text(page, desc, 72, y + 48, fontfile=FR, size=12, color=MUTED, width=W - 140)
        y += 92
    footer(page, 2, 6)


def slide_pillars(doc: fitz.Document) -> None:
    page = new_page(doc)
    page.insert_text((48, 56), "РЕШЕНИЕ", fontsize=10, fontname="f", fontfile=FB, color=MUTED)
    text(page, "Один инструмент для DD-проверки документов", 48, 88, fontfile=FS, size=28, color=INK, width=780)
    text(
        page,
        "Вы задаёте структуру проверки, а Tabular Review массово извлекает факты по всему документальному периметру сделки.",
        48,
        130,
        fontfile=FR,
        size=13,
        color=MUTED,
        width=860,
    )
    rect = fitz.Rect(48, 180, W - 48, H - 48)
    page.draw_rect(rect, color=LINE, fill=WHITE, width=0.6)
    page.insert_text((rect.x0 + 24, rect.y0 + 36), "Tabular Review", fontsize=20, fontname="f", fontfile=FB, color=INK)
    yy = rect.y0 + 78
    for line in (
        "Строка = документ",
        "Столбец = вопрос DD-чеклиста",
        "Ячейка = извлечённый факт",
        "Каждый ответ связан с цитатой и страницей PDF",
        "Команда получает единую таблицу для findings memo и issues list",
    ):
        page.draw_circle(fitz.Point(rect.x0 + 32, yy - 4), 2.5, color=ACCENT, fill=ACCENT)
        page.insert_text((rect.x0 + 48, yy), line, fontsize=13, fontname="f", fontfile=FR, color=INK)
        yy += 32
    footer(page, 3, 6)


def slide_video_tabular(doc: fitz.Document) -> None:
    page = new_page(doc, dark=True)
    page.insert_text((48, 42), "ДЕМО  ·  TABULAR REVIEW", fontsize=10, fontname="f", fontfile=FB, color=(0.55, 0.58, 0.60))
    text(
        page,
        "Один DD-вопрос — по всему массиву документов",
        48,
        72,
        fontfile=FS,
        size=24,
        color=WHITE,
        width=700,
    )
    text(
        page,
        "Система извлекает факты по каждому документу, а юрист сразу сверяет цитату с оригиналом PDF.",
        48,
        108,
        fontfile=FR,
        size=12,
        color=(0.65, 0.67, 0.70),
        width=700,
    )

    hero = ASSETS / "hero_tabular_1.jpg"
    # large media frame
    media = fitz.Rect(48, 140, W - 48, H - 70)
    page.draw_rect(media, color=(0.15, 0.16, 0.17), fill=(0.12, 0.13, 0.14))
    if hero.exists():
        page.insert_image(media, filename=str(hero), keep_proportion=True)

    # play badge
    cx, cy = W / 2, (media.y0 + media.y1) / 2
    page.draw_circle(fitz.Point(cx, cy), 28, color=(1, 1, 1), fill=(1, 1, 1))
    # triangle
    page.draw_polyline(
        [fitz.Point(cx - 8, cy - 12), fitz.Point(cx - 8, cy + 12), fitz.Point(cx + 14, cy)],
        color=DARK,
        fill=DARK,
        width=1,
        closePath=True,
    )

    video = SRC / "demo_tabular_review.mp4"
    caption = "Слайд для демо-видео  ·  откройте файл рядом с презентацией: demo_tabular_review.mp4"
    page.insert_text((48, H - 36), caption, fontsize=10, fontname="f", fontfile=FR, color=(0.55, 0.57, 0.60))
    if video.exists():
        # Clickable link over the media area → local video file
        uri = video.resolve().as_uri()
        page.insert_link({"kind": fitz.LINK_URI, "from": media, "uri": uri})
    footer(page, 4, 6, dark=True)


def slide_control(doc: fitz.Document) -> None:
    page = new_page(doc)
    page.insert_text((48, 56), "ПРОВЕРКА ИСТОЧНИКА", fontsize=10, fontname="f", fontfile=FB, color=MUTED)
    text(page, "Юрист не полагается на ответ вслепую — он проверяет источник", 48, 88, fontfile=FS, size=26, color=INK, width=820)

    # left copy, right image
    text(
        page,
        "В DD-таблице каждый ответ сопровождается цитатой и ссылкой на страницу документа. "
        "Открываете оригинал — сразу видите нужный фрагмент.",
        48,
        150,
        fontfile=FR,
        size=13,
        color=MUTED,
        width=380,
    )
    bullets = [
        "Вы задаёте вопросы DD-чеклиста",
        "Система массово извлекает факты",
        "Команда быстро сверяет выводы с PDF",
    ]
    y = 260
    for b in bullets:
        page.draw_circle(fitz.Point(56, y - 4), 2.5, color=ACCENT, fill=ACCENT)
        page.insert_text((72, y), b, fontsize=13, fontname="f", fontfile=FR, color=INK)
        y += 28

    hero = ASSETS / "hero_tabular_1.jpg"
    place_image(page, hero, fitz.Rect(460, 140, W - 48, H - 48))
    footer(page, 5, 6)


def slide_close(doc: fitz.Document) -> None:
    page = new_page(doc)
    page.draw_rect(fitz.Rect(48, 48, W - 48, H - 48), color=ACCENT, fill=ACCENT)
    text(
        page,
        "Меньше рутины.\nБольше дел.\nПолный контроль над выводами.",
        80,
        160,
        fontfile=FS,
        size=30,
        color=WHITE,
        width=700,
    )
    text(
        page,
        "Tabular Review ускоряет legal due diligence по массиву документов — "
        "чтобы команда сосредоточилась на анализе рисков и подготовке выводов.",
        80,
        320,
        fontfile=FR,
        size=13,
        color=(0.72, 0.76, 0.78),
        width=700,
    )
    page.insert_text(
        (80, H - 80),
        "Демо-видео: demo_tabular_review.mp4",
        fontsize=10,
        fontname="f",
        fontfile=FR,
        color=(0.55, 0.60, 0.62),
    )


def main() -> None:
    doc = fitz.open()
    slide_title(doc)
    slide_problem(doc)
    slide_pillars(doc)
    slide_video_tabular(doc)
    slide_control(doc)
    slide_close(doc)
    # embedding full mp4 in annot makes huge PDF — instead attach by path reference?
    # We already embedded bytes which makes PDF huge (~60MB). Better: only link, don't embed full video.
    # Rebuild video slides without embedding full bytes — use URI to local files instead.
    doc.save(str(OUT), deflate=True, garbage=4)
    print("saved", OUT, "size_mb", round(OUT.stat().st_size / 1e6, 1), "pages", doc.page_count)
    doc.close()


if __name__ == "__main__":
    main()
