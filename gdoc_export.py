"""Export meeting protocol to a beautifully formatted Google Doc."""
import os
import re
from google.oauth2 import service_account
from googleapiclient.discovery import build

SA_KEY = os.environ.get("GOOGLE_SA_KEY", "service-account.json")
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]


def _get_services():
    creds = service_account.Credentials.from_service_account_file(SA_KEY, scopes=SCOPES)
    docs = build("docs", "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
    return docs, drive


def create_protocol_doc(protocol_md: str, title: str = "Протокол созвона") -> str:
    """Create a Google Doc from protocol markdown, return shareable link."""
    docs, drive = _get_services()

    # 1. Create empty doc
    doc = docs.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]

    # 2. Parse markdown and build formatted requests
    requests = _md_to_docs_requests(protocol_md)

    if requests:
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

    # 3. Make publicly accessible (anyone with link can edit)
    drive.permissions().create(
        fileId=doc_id,
        body={"type": "anyone", "role": "writer"},
    ).execute()

    link = f"https://docs.google.com/document/d/{doc_id}/edit"
    print(f"[gdoc] Created: {link}")
    return link


def _md_to_docs_requests(md: str) -> list:
    """Convert markdown protocol to Google Docs API requests with formatting."""
    requests = []
    idx = 1  # cursor position (1-based, after doc start)

    lines = md.strip().split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # Skip empty lines
        if not line.strip():
            text = "\n"
            requests.append({"insertText": {"location": {"index": idx}, "text": text}})
            idx += len(text)
            i += 1
            continue

        # H1: # Title
        if line.startswith("# ") and not line.startswith("##"):
            text = line[2:].strip() + "\n"
            requests.append({"insertText": {"location": {"index": idx}, "text": text}})
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": idx, "endIndex": idx + len(text)},
                    "paragraphStyle": {"namedStyleType": "HEADING_1"},
                    "fields": "namedStyleType",
                }
            })
            idx += len(text)
            i += 1
            continue

        # H2: ## Section
        if line.startswith("## "):
            text = line[3:].strip() + "\n"
            requests.append({"insertText": {"location": {"index": idx}, "text": text}})
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": idx, "endIndex": idx + len(text)},
                    "paragraphStyle": {"namedStyleType": "HEADING_2"},
                    "fields": "namedStyleType",
                }
            })
            idx += len(text)
            i += 1
            continue

        # H3: ### Subsection
        if line.startswith("### "):
            text = line[4:].strip() + "\n"
            requests.append({"insertText": {"location": {"index": idx}, "text": text}})
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": idx, "endIndex": idx + len(text)},
                    "paragraphStyle": {"namedStyleType": "HEADING_3"},
                    "fields": "namedStyleType",
                }
            })
            idx += len(text)
            i += 1
            continue

        # Table: | ... | ... |
        if line.strip().startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                # Skip separator lines (|---|---|)
                if not re.match(r'^\|[\s\-:|]+\|$', lines[i].strip()):
                    cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                    table_lines.append(cells)
                i += 1

            if table_lines:
                rows = len(table_lines)
                cols = max(len(r) for r in table_lines)

                # Insert table
                requests.append({
                    "insertTable": {
                        "rows": rows,
                        "columns": cols,
                        "location": {"index": idx},
                    }
                })

                # Calculate cell positions — need to re-read doc structure
                # Simpler: insert table then fill cells
                # Google Docs tables are complex — use a flat text approach for now
                # Actually, let's insert table content after creating it
                # We need to track index carefully

                # For simplicity, convert table to formatted text instead
                # (Google Docs table API is very complex with index tracking)
                requests.pop()  # remove insertTable

                for row_idx, row in enumerate(table_lines):
                    if row_idx == 0:
                        # Header row — bold
                        text = "  |  ".join(row) + "\n"
                        requests.append({"insertText": {"location": {"index": idx}, "text": text}})
                        requests.append({
                            "updateTextStyle": {
                                "range": {"startIndex": idx, "endIndex": idx + len(text) - 1},
                                "textStyle": {"bold": True},
                                "fields": "bold",
                            }
                        })
                        idx += len(text)
                        # Add separator
                        sep = "─" * (len(text) - 1) + "\n"
                        requests.append({"insertText": {"location": {"index": idx}, "text": sep}})
                        idx += len(sep)
                    else:
                        text = "  |  ".join(row) + "\n"
                        requests.append({"insertText": {"location": {"index": idx}, "text": text}})
                        idx += len(text)

            continue

        # Bullet: - item
        if line.strip().startswith("- "):
            text = line.strip()[2:] + "\n"
            requests.append({"insertText": {"location": {"index": idx}, "text": text}})
            requests.append({
                "createParagraphBullets": {
                    "range": {"startIndex": idx, "endIndex": idx + len(text)},
                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                }
            })
            idx += len(text)
            i += 1
            continue

        # Numbered: 1. item
        num_match = re.match(r'^(\d+)\.\s+(.+)', line.strip())
        if num_match:
            text = num_match.group(2) + "\n"
            requests.append({"insertText": {"location": {"index": idx}, "text": text}})
            requests.append({
                "createParagraphBullets": {
                    "range": {"startIndex": idx, "endIndex": idx + len(text)},
                    "bulletPreset": "NUMBERED_DECIMAL_NESTED",
                }
            })
            idx += len(text)
            i += 1
            continue

        # Regular text
        text = line + "\n"
        requests.append({"insertText": {"location": {"index": idx}, "text": text}})
        idx += len(text)
        i += 1

    return requests
