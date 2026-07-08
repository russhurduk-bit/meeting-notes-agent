"""Export meeting protocol to a beautifully formatted .docx file."""
import re
import os
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def create_protocol_docx(protocol_md: str, meeting_id: str, title: str = "Протокол созвона") -> str:
    """Create a .docx from protocol markdown. Returns file path."""
    doc = Document()

    # Style setup
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Arial"
    font.size = Pt(11)

    lines = protocol_md.strip().split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # Empty line
        if not line.strip():
            i += 1
            continue

        # H1
        if line.startswith("# ") and not line.startswith("##"):
            p = doc.add_heading(line[2:].strip(), level=1)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            i += 1
            continue

        # H2
        if line.startswith("## "):
            doc.add_heading(line[3:].strip(), level=2)
            i += 1
            continue

        # H3
        if line.startswith("### "):
            doc.add_heading(line[4:].strip(), level=3)
            i += 1
            continue

        # Table
        if line.strip().startswith("|"):
            table_rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not re.match(r"^\|[\s\-:|]+\|$", lines[i].strip()):
                    cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                    table_rows.append(cells)
                i += 1

            if table_rows:
                cols = max(len(r) for r in table_rows)
                table = doc.add_table(rows=len(table_rows), cols=cols)
                table.style = "Light Grid Accent 1"
                table.alignment = WD_TABLE_ALIGNMENT.CENTER

                for row_idx, row_data in enumerate(table_rows):
                    for col_idx, cell_text in enumerate(row_data):
                        if col_idx < cols:
                            cell = table.cell(row_idx, col_idx)
                            cell.text = cell_text
                            if row_idx == 0:
                                for paragraph in cell.paragraphs:
                                    for run in paragraph.runs:
                                        run.bold = True
                doc.add_paragraph()  # spacing after table
            continue

        # Bullet
        if line.strip().startswith("- "):
            text = line.strip()[2:]
            # Handle bold in markdown (**text**)
            p = doc.add_paragraph(style="List Bullet")
            _add_formatted_text(p, text)
            i += 1
            continue

        # Numbered
        num_match = re.match(r"^(\d+)\.\s+(.+)", line.strip())
        if num_match:
            p = doc.add_paragraph(style="List Number")
            _add_formatted_text(p, num_match.group(2))
            i += 1
            continue

        # Sub-bullet (starts with spaces + -)
        if re.match(r"^\s+- ", line):
            text = line.strip()[2:]
            p = doc.add_paragraph(style="List Bullet 2")
            _add_formatted_text(p, text)
            i += 1
            continue

        # Regular text
        p = doc.add_paragraph()
        _add_formatted_text(p, line)
        i += 1

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"{meeting_id}_protocol.docx")
    doc.save(path)
    print(f"[docx] Saved: {path}")
    return path


def _add_formatted_text(paragraph, text: str):
    """Add text with markdown bold (**text**) support."""
    parts = re.split(r"(\*\*.*?\*\*)", text)
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        else:
            paragraph.add_run(part)
