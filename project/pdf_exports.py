from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from flask import Response
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.platypus import (
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

RED = colors.HexColor("#c93636")
RED_DARK = colors.HexColor("#a9232b")
INK = colors.HexColor("#17283b")
MUTED = colors.HexColor("#687382")
PALE_RED = colors.HexColor("#fff0ed")
LINE = colors.HexColor("#eadfdd")
WHITE = colors.white
FONT_DIR = Path(reportlab.__file__).resolve().parent / "fonts"
pdfmetrics.registerFont(TTFont("Vera", str(FONT_DIR / "Vera.ttf")))
pdfmetrics.registerFont(TTFont("Vera-Bold", str(FONT_DIR / "VeraBd.ttf")))
registerFontFamily(
    "Vera",
    normal="Vera",
    bold="Vera-Bold",
    italic="Vera",
    boldItalic="Vera-Bold",
)


def pdf_money(value, currency):
    symbol = currency.strip()
    try:
        symbol.encode("cp1252")
    except UnicodeEncodeError:
        symbol = "BDT"
    return f"{symbol}\u00a0{value:,.2f}"


def _paragraph(value, style):
    text = escape(str(value)).replace("\n", "<br/>")
    return Paragraph(text, style)


def _footer(canvas, document):
    canvas.saveState()
    width, _ = landscape(A4)
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.6)
    canvas.line(14 * mm, 12 * mm, width - 14 * mm, 12 * mm)
    canvas.setFont("Vera", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(14 * mm, 7.5 * mm, "STALL DESK  |  INTERNAL REPORT")
    canvas.drawRightString(width - 14 * mm, 7.5 * mm, f"Page {document.page}")
    canvas.restoreState()


def build_pdf_response(
    *,
    title,
    subtitle,
    period,
    generated_at,
    metrics,
    columns,
    rows,
    filename,
    note=None,
):
    """Build a styled, landscape PDF with a repeatable, readable data table."""
    buffer = BytesIO()
    page_width, page_height = landscape(A4)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=(page_width, page_height),
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=13 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="Stall Desk",
        pageCompression=1,
    )

    sample_styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=sample_styles["Title"],
        fontName="Vera-Bold",
        fontSize=20,
        leading=23,
        textColor=WHITE,
        alignment=TA_LEFT,
        spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=sample_styles["Normal"],
        fontName="Vera",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#ffe6e2"),
    )
    meta_style = ParagraphStyle(
        "ReportMeta",
        parent=sample_styles["Normal"],
        fontName="Vera",
        fontSize=8,
        leading=11,
        textColor=INK,
        alignment=TA_RIGHT,
    )
    metric_label_style = ParagraphStyle(
        "MetricLabel",
        parent=sample_styles["Normal"],
        fontName="Vera-Bold",
        fontSize=7,
        leading=9,
        textColor=MUTED,
    )
    metric_value_style = ParagraphStyle(
        "MetricValue",
        parent=sample_styles["Normal"],
        fontName="Vera-Bold",
        fontSize=13,
        leading=16,
        textColor=RED_DARK,
    )
    section_style = ParagraphStyle(
        "TableHeading",
        parent=sample_styles["Heading2"],
        fontName="Vera-Bold",
        fontSize=12,
        leading=15,
        textColor=INK,
        spaceBefore=5,
        spaceAfter=8,
    )
    header_style = ParagraphStyle(
        "TableHeader",
        parent=sample_styles["Normal"],
        fontName="Vera-Bold",
        fontSize=7,
        leading=9,
        textColor=WHITE,
        alignment=TA_LEFT,
    )
    cell_style = ParagraphStyle(
        "TableCell",
        parent=sample_styles["Normal"],
        fontName="Vera",
        fontSize=7.5,
        leading=10,
        textColor=INK,
    )
    right_cell_style = ParagraphStyle(
        "RightTableCell",
        parent=cell_style,
        alignment=TA_RIGHT,
    )
    note_style = ParagraphStyle(
        "ReportNote",
        parent=sample_styles["Normal"],
        fontName="Vera",
        fontSize=8,
        leading=11,
        textColor=MUTED,
        spaceBefore=7,
    )

    header = Table(
        [
            [
                [
                    _paragraph("STALL DESK  /  BUSINESS REPORT", subtitle_style),
                    Spacer(1, 3),
                    _paragraph(title, title_style),
                    Spacer(1, 3),
                    _paragraph(subtitle, subtitle_style),
                ],
                Paragraph(
                    f"<b>REPORTING PERIOD</b><br/>{escape(str(period))}<br/><br/>"
                    f"<b>GENERATED</b><br/>{escape(str(generated_at))}",
                    meta_style,
                ),
            ]
        ],
        colWidths=[doc.width * 0.70, doc.width * 0.30],
    )
    header.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), RED),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, 0), 15),
                ("RIGHTPADDING", (0, 0), (0, 0), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 13),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 13),
                ("LEFTPADDING", (1, 0), (1, 0), 8),
                ("RIGHTPADDING", (1, 0), (1, 0), 15),
                ("LINEBEFORE", (1, 0), (1, 0), 0.8, colors.HexColor("#e87979")),
            ]
        )
    )

    metric_cells = []
    for label, value in metrics:
        metric_cells.append(
            [
                _paragraph(label.upper(), metric_label_style),
                Spacer(1, 3),
                _paragraph(value, metric_value_style),
            ]
        )
    metrics_table = Table(
        [metric_cells],
        colWidths=[doc.width / max(len(metric_cells), 1)] * len(metric_cells),
        hAlign="LEFT",
    )
    metrics_style = [
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("BOX", (0, 0), (-1, -1), 0.7, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]
    for index in range(len(metric_cells)):
        if index % 2 == 0:
            metrics_style.append(("BACKGROUND", (index, 0), (index, 0), PALE_RED))
    metrics_table.setStyle(TableStyle(metrics_style))

    table_data = [
        [_paragraph(column, header_style) for column in columns],
    ]
    for row in rows:
        table_data.append(
            [
                _paragraph(value, right_cell_style if numeric else cell_style)
                for value, numeric in row
            ]
        )
    data_table = LongTable(
        table_data,
        colWidths=[doc.width * fraction for fraction in _column_fractions(len(columns))],
        repeatRows=1,
        hAlign="LEFT",
        splitByRow=1,
    )
    data_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), RED_DARK),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, RED),
                ("LINEBELOW", (0, 1), (-1, -1), 0.35, LINE),
            ]
            + [
                ("BACKGROUND", (0, index), (-1, index), PALE_RED)
                for index in range(2, len(table_data), 2)
            ]
        )
    )

    story = [header, Spacer(1, 10), metrics_table, Spacer(1, 12)]
    if note:
        story.extend([_paragraph(note, note_style), Spacer(1, 5)])
    story.extend(
        [
            _paragraph("DETAILED BREAKDOWN", section_style),
            data_table,
        ]
    )
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return Response(
        buffer.getvalue(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _column_fractions(column_count):
    if column_count == 10:
        return (0.20, 0.13, 0.08, 0.10, 0.085, 0.085, 0.065, 0.075, 0.09, 0.09)
    if column_count == 9:
        return (0.06, 0.23, 0.075, 0.075, 0.075, 0.13, 0.13, 0.13, 0.095)
    return (1 / column_count,) * column_count
