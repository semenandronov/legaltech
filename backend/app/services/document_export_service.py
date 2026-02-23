"""Document Export Service for Legal AI Vault"""
from typing import Optional
from sqlalchemy.orm import Session
from app.models.document_editor import Document
from app.services.document_editor_service import DocumentEditorService
from docx import Document as DocxDocument
from docx.shared import Pt, RGBColor
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.platypus import Table as RLTable, TableStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO
import logging
import os
import re
from html import unescape

from bs4 import BeautifulSoup, NavigableString, Tag

logger = logging.getLogger(__name__)

# Register Cyrillic-supporting fonts for PDF export
_FONT_REGISTERED = False
_FONT_NAME = 'Helvetica'
_FONT_NAME_BOLD = 'Helvetica-Bold'
_FONT_NAME_ITALIC = 'Helvetica-Oblique'


def _register_cyrillic_font():
    """Register a TTF font that supports Cyrillic characters."""
    global _FONT_REGISTERED, _FONT_NAME, _FONT_NAME_BOLD, _FONT_NAME_ITALIC
    if _FONT_REGISTERED:
        return

    font_candidates = [
        # macOS
        ('/System/Library/Fonts/Supplemental/Arial.ttf',
         '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
         '/System/Library/Fonts/Supplemental/Arial Italic.ttf'),
        ('/Library/Fonts/Arial Unicode.ttf', None, None),
        # Linux (DejaVu)
        ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf'),
        # Linux (Liberation)
        ('/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
         '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
         '/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf'),
    ]

    for regular, bold, italic in font_candidates:
        if os.path.exists(regular):
            try:
                pdfmetrics.registerFont(TTFont('CyrillicFont', regular))
                _FONT_NAME = 'CyrillicFont'
                if bold and os.path.exists(bold):
                    pdfmetrics.registerFont(TTFont('CyrillicFont-Bold', bold))
                    _FONT_NAME_BOLD = 'CyrillicFont-Bold'
                else:
                    _FONT_NAME_BOLD = 'CyrillicFont'
                if italic and os.path.exists(italic):
                    pdfmetrics.registerFont(TTFont('CyrillicFont-Italic', italic))
                    _FONT_NAME_ITALIC = 'CyrillicFont-Italic'
                else:
                    _FONT_NAME_ITALIC = 'CyrillicFont'
                _FONT_REGISTERED = True
                logger.info(f"Registered Cyrillic font from: {regular}")
                return
            except Exception as e:
                logger.warning(f"Failed to register font {regular}: {e}")
                continue

    logger.warning("No Cyrillic TTF font found, PDF may not render Cyrillic correctly")


# ─── DOCX helpers ────────────────────────────────────────────────────────────

BLOCK_TAGS = {
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'p', 'div', 'blockquote', 'pre',
    'ul', 'ol', 'li',
    'table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th',
    'hr',
}


def _add_hr_to_docx(doc: DocxDocument):
    """Add a horizontal rule paragraph to a docx document."""
    para = doc.add_paragraph()
    pPr = para._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '6')
    bottom.set(qn('w:space'), '1')
    bottom.set(qn('w:color'), '000000')
    pBdr.append(bottom)
    pPr.append(pBdr)
    return para


def _set_run_color_black(run):
    """Force a run's font color to black (overrides blue heading default)."""
    run.font.color.rgb = RGBColor(0, 0, 0)


def _inline_to_runs(para, element, bold=False, italic=False, underline=False):
    """
    Recursively add inline content of *element* as runs to *para*.
    Inherits bold/italic/underline from parent context.
    Colors from <a> and <span style="color:…"> are intentionally ignored
    so that hyperlinks don't appear blue in the exported document.
    """
    for child in element.children:
        if isinstance(child, NavigableString):
            text = str(child)
            if text:
                run = para.add_run(unescape(text))
                run.bold = bold
                run.italic = italic
                run.underline = underline
        elif isinstance(child, Tag):
            tag = child.name
            if not tag:
                continue

            cb = bold or tag in ('strong', 'b')
            ci = italic or tag in ('em', 'i')
            cu = underline or tag == 'u'

            if tag == 'span':
                style = child.get('style', '')
                if 'font-weight' in style and 'bold' in style:
                    cb = True
                if 'font-style' in style and 'italic' in style:
                    ci = True
                # intentionally drop color styles
                _inline_to_runs(para, child, cb, ci, cu)

            elif tag == 'a':
                # render link text without blue/underline hyperlink style
                _inline_to_runs(para, child, cb, ci, cu)

            elif tag == 'br':
                run = para.add_run('\n')
                run.bold = bold
                run.italic = italic

            elif tag in BLOCK_TAGS:
                # nested block inside inline context — just get its text
                text = child.get_text()
                if text.strip():
                    run = para.add_run(unescape(text))
                    run.bold = cb
                    run.italic = ci
                    run.underline = cu

            else:
                _inline_to_runs(para, child, cb, ci, cu)


def _add_heading_no_color(doc: DocxDocument, text: str, level: int):
    """Add a heading with black font color (suppress default blue)."""
    para = doc.add_heading(text, level=level)
    for run in para.runs:
        _set_run_color_black(run)
    return para


def _process_block_docx(doc: DocxDocument, element: Tag, list_style: Optional[str] = None):
    """
    Process a single block-level BeautifulSoup element and add it to *doc*.
    *list_style* is 'List Bullet' or 'List Number' when inside ul/ol.
    """
    tag = element.name
    if not tag:
        return

    if tag == 'hr':
        _add_hr_to_docx(doc)
        return

    if tag in ('ul', 'ol'):
        style = 'List Bullet' if tag == 'ul' else 'List Number'
        for child in element.children:
            if isinstance(child, Tag) and child.name == 'li':
                _process_block_docx(doc, child, list_style=style)
            elif isinstance(child, Tag):
                _process_block_docx(doc, child, list_style=style)
        return

    if tag == 'table':
        _process_table_docx(doc, element)
        return

    if tag in ('thead', 'tbody', 'tfoot'):
        for child in element.children:
            if isinstance(child, Tag):
                _process_block_docx(doc, child, list_style)
        return

    if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
        level = int(tag[1])
        text = element.get_text()
        if text.strip():
            _add_heading_no_color(doc, unescape(text), level=level)
        return

    if tag == 'li':
        style = list_style or 'List Bullet'
        para = doc.add_paragraph(style=style)
        _inline_to_runs(para, element)
        return

    if tag in ('p', 'div', 'blockquote', 'pre'):
        # Check if the element contains only block children (e.g. a div wrapping h2+p)
        has_block_child = any(
            isinstance(c, Tag) and c.name in BLOCK_TAGS
            for c in element.children
        )
        if has_block_child:
            for child in element.children:
                if isinstance(child, Tag):
                    if child.name in BLOCK_TAGS:
                        _process_block_docx(doc, child, list_style)
                    else:
                        # inline-only child of a div
                        para = doc.add_paragraph()
                        _inline_to_runs(para, child)
                elif isinstance(child, NavigableString):
                    text = str(child).strip()
                    if text:
                        doc.add_paragraph(unescape(text))
        else:
            para = doc.add_paragraph()
            _inline_to_runs(para, element)
        return

    # Unknown tag — try to extract inline content
    if element.get_text().strip():
        para = doc.add_paragraph()
        _inline_to_runs(para, element)


def _process_table_docx(doc: DocxDocument, table_el: Tag):
    """Convert an HTML <table> element to a python-docx table."""
    rows_data = []
    for tr in table_el.find_all('tr'):
        row = []
        for cell in tr.find_all(['td', 'th']):
            row.append(cell.get_text(separator=' ', strip=True))
        if row:
            rows_data.append(row)

    if not rows_data:
        return

    col_count = max(len(r) for r in rows_data)
    # Pad short rows
    for r in rows_data:
        while len(r) < col_count:
            r.append('')

    tbl = doc.add_table(rows=len(rows_data), cols=col_count)
    tbl.style = 'Table Grid'
    for r_idx, row_data in enumerate(rows_data):
        row = tbl.rows[r_idx]
        for c_idx, cell_text in enumerate(row_data):
            row.cells[c_idx].text = unescape(cell_text)


# ─── PDF helpers ──────────────────────────────────────────────────────────────

def _inline_to_rl_markup(element) -> str:
    """
    Convert inline HTML content of *element* to ReportLab Paragraph XML markup.
    Colors are stripped to prevent blue hyperlinks / colored spans.
    """
    parts = []
    for child in element.children:
        if isinstance(child, NavigableString):
            text = str(child)
            # Escape XML special characters
            text = (
                text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
            )
            parts.append(text)
        elif isinstance(child, Tag):
            tag = child.name
            if not tag:
                continue
            inner = _inline_to_rl_markup(child)

            if tag in ('strong', 'b'):
                parts.append(f'<b>{inner}</b>')
            elif tag in ('em', 'i'):
                parts.append(f'<i>{inner}</i>')
            elif tag == 'u':
                parts.append(f'<u>{inner}</u>')
            elif tag in ('a', 'span'):
                # strip color / link styling — just render text
                parts.append(inner)
            elif tag == 'br':
                parts.append('<br/>')
            elif tag in BLOCK_TAGS:
                parts.append(inner)
            else:
                parts.append(inner)
    return ''.join(parts)


def _process_block_pdf(element: Tag, story: list, styles: dict):
    """
    Process a block-level element and append ReportLab flowables to *story*.
    *styles* is a dict with keys: normal, bold, italic, h1..h4, title, li.
    """
    tag = element.name
    if not tag:
        return

    if tag == 'hr':
        story.append(HRFlowable(width='100%', thickness=1, color=colors.black))
        story.append(Spacer(1, 6))
        return

    if tag in ('ul', 'ol'):
        bullet = '\u2022' if tag == 'ul' else None
        idx = 1
        for child in element.children:
            if isinstance(child, Tag) and child.name == 'li':
                prefix = f'{idx}.' if tag == 'ol' else '\u2022'
                markup = _inline_to_rl_markup(child)
                markup = markup.strip()
                if markup:
                    story.append(Paragraph(f'{prefix}\u00a0{markup}', styles['li']))
                    story.append(Spacer(1, 4))
                idx += 1
        return

    if tag == 'table':
        _process_table_pdf(element, story, styles)
        return

    if tag in ('thead', 'tbody', 'tfoot'):
        for child in element.children:
            if isinstance(child, Tag):
                _process_block_pdf(child, story, styles)
        return

    if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
        level = int(tag[1])
        style_key = f'h{min(level, 4)}'
        markup = element.get_text(strip=True)
        if markup:
            story.append(Paragraph(
                markup.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'),
                styles[style_key]
            ))
            story.append(Spacer(1, 8))
        return

    if tag in ('p', 'div', 'blockquote', 'pre'):
        has_block_child = any(
            isinstance(c, Tag) and c.name in BLOCK_TAGS
            for c in element.children
        )
        if has_block_child:
            for child in element.children:
                if isinstance(child, Tag):
                    if child.name in BLOCK_TAGS:
                        _process_block_pdf(child, story, styles)
                    else:
                        markup = _inline_to_rl_markup(child).strip()
                        if markup:
                            story.append(Paragraph(markup, styles['normal']))
                            story.append(Spacer(1, 6))
                elif isinstance(child, NavigableString):
                    text = str(child).strip()
                    if text:
                        story.append(Paragraph(
                            text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'),
                            styles['normal']
                        ))
                        story.append(Spacer(1, 6))
        else:
            markup = _inline_to_rl_markup(element).strip()
            if markup:
                story.append(Paragraph(markup, styles['normal']))
                story.append(Spacer(1, 6))
        return

    # Fallback
    markup = _inline_to_rl_markup(element).strip()
    if markup:
        story.append(Paragraph(markup, styles['normal']))
        story.append(Spacer(1, 6))


def _process_table_pdf(table_el: Tag, story: list, styles: dict):
    """Convert an HTML <table> element to a ReportLab Table flowable."""
    rows_data = []
    for tr in table_el.find_all('tr'):
        row = []
        for cell in tr.find_all(['td', 'th']):
            text = cell.get_text(separator=' ', strip=True)
            row.append(Paragraph(
                text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'),
                styles['normal']
            ))
        if row:
            rows_data.append(row)

    if not rows_data:
        return

    col_count = max(len(r) for r in rows_data)
    for r in rows_data:
        while len(r) < col_count:
            r.append(Paragraph('', styles['normal']))

    tbl = RLTable(rows_data)
    tbl.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('FONTNAME', (0, 0), (-1, -1), _FONT_NAME),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 8))


# ─── Service ──────────────────────────────────────────────────────────────────

class DocumentExportService:
    """Service for exporting documents to various formats"""

    def __init__(self, db: Session):
        self.db = db
        self.document_service = DocumentEditorService(db)

    def export_to_docx(self, document_id: str, user_id: str) -> BytesIO:
        """Export document to DOCX format."""
        document = self.document_service.get_document(document_id, user_id)
        if not document:
            raise ValueError(f"Document {document_id} not found")

        doc = DocxDocument()
        _add_heading_no_color(doc, document.title, level=0)

        html_content = document.content or "<p>Пустой документ</p>"
        # Strip scripts/styles
        html_content = re.sub(
            r'<(script|style)[^>]*>.*?</\1>',
            '', html_content, flags=re.DOTALL | re.IGNORECASE
        )

        soup = BeautifulSoup(html_content, 'lxml')
        body = soup.find('body') or soup

        for child in body.children:
            if isinstance(child, NavigableString):
                text = str(child).strip()
                if text:
                    doc.add_paragraph(unescape(text))
            elif isinstance(child, Tag):
                _process_block_docx(doc, child)

        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        logger.info(f"Exported document {document_id} to DOCX")
        return buffer

    def export_to_pdf(self, document_id: str, user_id: str) -> BytesIO:
        """Export document to PDF format."""
        document = self.document_service.get_document(document_id, user_id)
        if not document:
            raise ValueError(f"Document {document_id} not found")

        _register_cyrillic_font()

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        story = []

        base_styles = getSampleStyleSheet()

        def _ms(name, parent_name, font, size, space_after=6, leading=None, left_indent=0):
            kw = dict(
                parent=base_styles[parent_name],
                fontName=font,
                fontSize=size,
                spaceAfter=space_after,
                leftIndent=left_indent,
            )
            if leading:
                kw['leading'] = leading
            return ParagraphStyle(name, **kw)

        pdf_styles = {
            'title': _ms('ExTitle', 'Heading1', _FONT_NAME_BOLD, 18, space_after=12),
            'h1':    _ms('ExH1', 'Heading1', _FONT_NAME_BOLD, 16),
            'h2':    _ms('ExH2', 'Heading2', _FONT_NAME_BOLD, 14),
            'h3':    _ms('ExH3', 'Heading3', _FONT_NAME_BOLD, 12),
            'h4':    _ms('ExH4', 'Heading4', _FONT_NAME_BOLD, 11),
            'normal': _ms('ExNormal', 'Normal', _FONT_NAME, 10, leading=14),
            'bold':   _ms('ExBold', 'Normal', _FONT_NAME_BOLD, 10),
            'italic': _ms('ExItalic', 'Normal', _FONT_NAME_ITALIC, 10),
            'li':     _ms('ExLi', 'Normal', _FONT_NAME, 10, left_indent=12),
        }

        # Title
        title_safe = (document.title or '')
        title_safe = title_safe.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        story.append(Paragraph(title_safe, pdf_styles['title']))
        story.append(Spacer(1, 12))

        html_content = document.content or "<p>Пустой документ</p>"
        html_content = re.sub(
            r'<(script|style)[^>]*>.*?</\1>',
            '', html_content, flags=re.DOTALL | re.IGNORECASE
        )

        soup = BeautifulSoup(html_content, 'lxml')
        body = soup.find('body') or soup

        for child in body.children:
            if isinstance(child, NavigableString):
                text = str(child).strip()
                if text:
                    story.append(Paragraph(
                        text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'),
                        pdf_styles['normal']
                    ))
                    story.append(Spacer(1, 6))
            elif isinstance(child, Tag):
                _process_block_pdf(child, story, pdf_styles)

        doc.build(story)
        buffer.seek(0)
        logger.info(f"Exported document {document_id} to PDF")
        return buffer
