from __future__ import annotations

import textwrap
from typing import Iterable

PAGE_WIDTH = 595
PAGE_HEIGHT = 842
LEFT_MARGIN = 48
RIGHT_MARGIN = 48
TOP_MARGIN = 72
BOTTOM_MARGIN = 56
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN

ACCENT = (0.09, 0.39, 0.34)
ACCENT_SOFT = (0.91, 0.95, 0.93)
ACCENT_WARM = (0.82, 0.54, 0.30)
TEXT = (0.15, 0.20, 0.18)
MUTED = (0.37, 0.43, 0.40)
LINE = (0.78, 0.83, 0.80)

STYLE_MAP = {
    "title": {
        "font": "F2",
        "size": 20,
        "leading": 24,
        "wrap": 44,
        "space_before": 0,
        "space_after": 8,
        "x": LEFT_MARGIN,
        "color": TEXT,
    },
    "heading": {
        "font": "F2",
        "size": 13,
        "leading": 16,
        "wrap": 66,
        "space_before": 7,
        "space_after": 7,
        "x": LEFT_MARGIN,
        "color": ACCENT,
        "divider": True,
    },
    "subheading": {
        "font": "F2",
        "size": 11.5,
        "leading": 14,
        "wrap": 74,
        "space_before": 4,
        "space_after": 4,
        "x": LEFT_MARGIN,
        "color": TEXT,
    },
    "body": {
        "font": "F1",
        "size": 10.5,
        "leading": 13.5,
        "wrap": 90,
        "space_before": 0,
        "space_after": 3,
        "x": LEFT_MARGIN,
        "color": TEXT,
    },
    "bullet": {
        "font": "F1",
        "size": 10.4,
        "leading": 13.2,
        "wrap": 84,
        "space_before": 0,
        "space_after": 2,
        "x": LEFT_MARGIN + 8,
        "color": TEXT,
    },
    "small": {
        "font": "F3",
        "size": 9.2,
        "leading": 11.5,
        "wrap": 96,
        "space_before": 0,
        "space_after": 8,
        "x": LEFT_MARGIN,
        "color": MUTED,
    },
}

PDF_SANITIZE_MAP = str.maketrans(
    {
        "•": "-",
        "–": "-",
        "—": "-",
        "“": '"',
        "”": '"',
        "’": "'",
        "\t": "    ",
    }
)


def _sanitize_text(text: str) -> str:
    return text.translate(PDF_SANITIZE_MAP)


def _pdf_text_bytes(text: str) -> bytes:
    encoded = _sanitize_text(text).encode("cp1252", "replace")
    escaped = bytearray()
    for byte in encoded:
        if byte in (0x28, 0x29, 0x5C):
            escaped.append(0x5C)
        escaped.append(byte)
    return bytes(escaped)


def _wrap_lines(text: str, width: int, bullet: bool = False) -> list[str]:
    cleaned = _sanitize_text(text).strip()
    if not cleaned:
        return [""]
    kwargs = {"width": width, "break_long_words": False, "replace_whitespace": False}
    if bullet:
        return textwrap.wrap(cleaned, initial_indent="- ", subsequent_indent="  ", **kwargs) or ["- "]
    return textwrap.wrap(cleaned, **kwargs) or [cleaned]


def _text_command(font_name: str, font_size: float, x: float, y: float, text: str, color: tuple[float, float, float]) -> bytes:
    prefix = (
        f"BT /{font_name} {font_size:.2f} Tf "
        f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg "
        f"1 0 0 1 {x:.2f} {y:.2f} Tm ("
    ).encode("ascii")
    suffix = b") Tj ET\n"
    return prefix + _pdf_text_bytes(text) + suffix


def _line_command(x1: float, y1: float, x2: float, y2: float, width: float, color: tuple[float, float, float]) -> bytes:
    return (
        f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} RG "
        f"{width:.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S\n"
    ).encode("ascii")


def _rect_fill_command(x: float, y: float, width: float, height: float, color: tuple[float, float, float]) -> bytes:
    return (
        f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg "
        f"{x:.2f} {y:.2f} {width:.2f} {height:.2f} re f\n"
    ).encode("ascii")


def _page_decorations(page_number: int, total_pages: int) -> bytes:
    commands = bytearray()
    commands.extend(_rect_fill_command(0, PAGE_HEIGHT - 18, PAGE_WIDTH, 18, ACCENT))
    commands.extend(_rect_fill_command(0, PAGE_HEIGHT - 22, PAGE_WIDTH, 4, ACCENT_WARM))
    if page_number == 1:
        commands.extend(_rect_fill_command(LEFT_MARGIN - 10, PAGE_HEIGHT - 110, CONTENT_WIDTH + 20, 62, ACCENT_SOFT))
        commands.extend(_rect_fill_command(LEFT_MARGIN - 10, PAGE_HEIGHT - 114, 132, 4, ACCENT))
    commands.extend(_line_command(LEFT_MARGIN, BOTTOM_MARGIN - 10, PAGE_WIDTH - RIGHT_MARGIN, BOTTOM_MARGIN - 10, 0.8, LINE))
    commands.extend(_text_command("F2", 8.2, LEFT_MARGIN, PAGE_HEIGHT - 13.5, "Planejador alimentar com base TACO", (1.0, 1.0, 1.0)))
    commands.extend(_text_command("F1", 8.2, LEFT_MARGIN, BOTTOM_MARGIN - 24, "Relatório gerado automaticamente para estudo e apresentação do caso.", MUTED))
    commands.extend(_text_command("F2", 8.2, PAGE_WIDTH - RIGHT_MARGIN - 62, BOTTOM_MARGIN - 24, f"Página {page_number}/{total_pages}", MUTED))
    return bytes(commands)


def _content_stream_for_page(elements: list[dict[str, object]], page_number: int, total_pages: int) -> bytes:
    commands = bytearray(_page_decorations(page_number, total_pages))
    for element in elements:
        if element["type"] == "text":
            commands.extend(
                _text_command(
                    str(element["font"]),
                    float(element["size"]),
                    float(element["x"]),
                    float(element["y"]),
                    str(element["text"]),
                    element["color"],  # type: ignore[arg-type]
                )
            )
        elif element["type"] == "rule":
            commands.extend(
                _line_command(
                    float(element["x1"]),
                    float(element["y"]),
                    float(element["x2"]),
                    float(element["y"]),
                    float(element["width"]),
                    element["color"],  # type: ignore[arg-type]
                )
            )
    return bytes(commands)


def render_simple_pdf(blocks: Iterable[tuple[str, str]]) -> bytes:
    pages: list[list[dict[str, object]]] = []
    current_page: list[dict[str, object]] = []
    y = PAGE_HEIGHT - TOP_MARGIN

    def start_new_page() -> None:
        nonlocal current_page, y
        if current_page:
            pages.append(current_page)
        current_page = []
        y = PAGE_HEIGHT - TOP_MARGIN

    def ensure_page_space(required_height: float) -> None:
        nonlocal y
        if y - required_height < BOTTOM_MARGIN:
            start_new_page()

    for kind, raw_text in blocks:
        style = STYLE_MAP.get(kind, STYLE_MAP["body"])
        space_before = float(style.get("space_before", 0))
        if space_before:
            ensure_page_space(space_before)
            y -= space_before

        paragraphs = raw_text.splitlines() or [""]
        last_line_y: float | None = None
        trailing_height = float(style.get("space_after", 0)) + (6 if style.get("divider") else 0)
        for paragraph in paragraphs:
            wrapped = _wrap_lines(paragraph, int(style["wrap"]), bullet=(kind == "bullet"))
            for line in wrapped:
                ensure_page_space(float(style["leading"]) + trailing_height)
                current_page.append(
                    {
                        "type": "text",
                        "font": style["font"],
                        "size": style["size"],
                        "x": style["x"],
                        "y": y,
                        "text": line,
                        "color": style["color"],
                    }
                )
                last_line_y = y
                y -= float(style["leading"])

        if style.get("divider") and last_line_y is not None:
            divider_y = y + 4
            current_page.append(
                {
                    "type": "rule",
                    "x1": float(style["x"]),
                    "x2": PAGE_WIDTH - RIGHT_MARGIN,
                    "y": divider_y,
                    "width": 0.9,
                    "color": LINE,
                }
            )
            y -= 4

        y -= float(style.get("space_after", 0))

    if current_page or not pages:
        pages.append(current_page)

    objects: list[bytes] = []

    def add_object(data: str | bytes) -> int:
        encoded = data.encode("ascii") if isinstance(data, str) else data
        objects.append(encoded)
        return len(objects)

    regular_font_id = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    bold_font_id = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    italic_font_id = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique /Encoding /WinAnsiEncoding >>")

    content_ids: list[int] = []
    total_pages = len(pages)
    for page_number, page in enumerate(pages, start=1):
        stream = _content_stream_for_page(page, page_number, total_pages)
        content_ids.append(add_object(b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream"))

    pages_object_id = len(objects) + len(content_ids) + 1
    page_ids: list[int] = []
    for content_id in content_ids:
        page_ids.append(
            add_object(
                (
                    f"<< /Type /Page /Parent {pages_object_id} 0 R "
                    f"/MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                    f"/Resources << /Font << /F1 {regular_font_id} 0 R /F2 {bold_font_id} 0 R /F3 {italic_font_id} 0 R >> >> "
                    f"/Contents {content_id} 0 R >>"
                )
            )
        )

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    add_object(f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>")
    catalog_id = add_object(f"<< /Type /Catalog /Pages {pages_object_id} 0 R >>")

    body = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    xref_offsets = [0]
    for index, obj in enumerate(objects, start=1):
        xref_offsets.append(len(body))
        body.extend(f"{index} 0 obj\n".encode("ascii"))
        body.extend(obj)
        body.extend(b"\nendobj\n")

    xref_position = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    body.extend(b"0000000000 65535 f \n")
    for offset in xref_offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    body.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref_position}\n%%EOF"
        ).encode("ascii")
    )
    return bytes(body)
