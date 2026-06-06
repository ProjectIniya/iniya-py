---
name: file-reading
description: "Use this skill whenever a file has been uploaded but its content is NOT already in your context — you only have a path under the uploads folder. This is a dispatch guide: it tells you the correct first action for each file type so you never blindly open a binary as text. Triggers: any uploads folder path in context, an uploaded_files block, a file_path tag, or the user asking about a file you have not read yet. Do NOT use this skill if the file content is already visible inside a documents block — you already have it."
platform: Windows (PowerShell + Python)
---

# Handling Uploaded Files on Windows

## What this document is for

When a file is uploaded, it lands on disk and you receive its path. The file's
content is **not** in your context — you have to go read it yourself.

The wrong move is treating every file the same way. Opening a PDF as raw text
prints binary noise. Loading a 200MB CSV all at once fills your context with
data you don't need. Trying to read a DOCX as plain text gives you the ZIP
internals, not the document.

This guide tells you the right first action per file type, and when a
deeper specialist skill should take over.

## Core rules before you touch any file

1. **Check the extension first.** It determines your approach.
2. **Check the file size before reading.** Big files must be sampled.

```powershell
# Get file size and last modified time
(Get-Item "uploads\report.pdf").Length
(Get-Item "uploads\report.pdf").LastWriteTime
```

3. **Read only as much as the question requires.** A question about row
   count doesn't justify loading a 500MB CSV into memory.
4. **When a dedicated skill exists, consult it.** This guide covers initial
   reads; the specialist skills cover editing, creation, and advanced ops.

## The `extract-text` command

For Office formats (docx, odt, epub, xlsx, pptx, rtf) and notebooks (ipynb),
your first move is `extract-text <filepath>`. It converts the file to readable
text: markdown for word-processor formats, `## Sheet:` sections for
spreadsheets, `## Slide N` sections for presentations, fenced blocks for
notebooks, plain text for RTF.

If the extension is misleading (e.g. an `.xlsm` file), pass `--format xlsx`.
If `extract-text` fails entirely, fall back to `pandoc <file> -t plain`, or
for spreadsheets/presentations use the dedicated Python-based skill.

---

## Dispatch table

| Extension | First move | Go deeper? |
|---|---|---|
| `.pdf` | Python `pdfplumber` — see PDF section | Yes → pdf-reading skill |
| `.docx` | `extract-text` | Yes → docx skill |
| `.doc` (old format) | Convert via python-docx2txt, then read | Yes → docx skill |
| `.xlsx` | `extract-text` | Yes → xlsx skill |
| `.xlsm` | `extract-text --format xlsx` | Yes → xlsx skill |
| `.xls` (old format) | `pd.read_excel(engine="xlrd")` | Yes → xlsx skill |
| `.ods` | `pd.read_excel(engine="odf")` | Yes → xlsx skill |
| `.pptx` | `extract-text` | Yes → pptx skill |
| `.ppt` (old format) | Convert via python-pptx or LibreOffice | Yes → pptx skill |
| `.csv`, `.tsv` | pandas with `nrows=5` | No — handled below |
| `.json`, `.jsonl` | Python `json` module for structure | No — handled below |
| `.jpg`, `.png`, `.gif`, `.webp` | Already visible as vision input | No — handled below |
| `.zip` | List contents only, do not extract | No — handled below |
| `.tar`, `.tar.gz`, `.tar.xz` | List contents only | No — handled below |
| `.gz` (single file, not tar) | Decompress in Python, peek first 50 lines | No — handled below |
| `.epub`, `.odt` | `extract-text` | No — handled below |
| `.rtf`, `.ipynb` | `extract-text` | No — handled below |
| `.txt`, `.md`, `.log`, code files | Check size, then read | No — handled below |
| Unknown | Python `imghdr` + read first 16 bytes as hex | No — ask user |

---

## PDF

Never open a PDF as raw text — it will be unreadable binary.

Start by checking whether the PDF has a real text layer, or is just scanned
images of pages:

```python
import pdfplumber

with pdfplumber.open(r"uploads\report.pdf") as pdf:
    print(f"Pages: {len(pdf.pages)}")
    sample = pdf.pages[0].extract_text()
    print("Text layer present:" , bool(sample and sample.strip()))
    if sample:
        print(sample[:500])
```

Two outcomes:

- **Text extracted successfully** → the PDF has a real text layer. Read
  whichever pages answer the user's question.
- **Empty or None returned** → this is a scanned PDF. `pdfplumber`
  won't help. Hand off to the pdf-reading skill which covers OCR via
  `pytesseract` and page rasterization via `pdf2image`.

Don't narrate this check to the user. Just lead with the answer. If you
successfully find the content, open with that — "This is a 12-page invoice.
The total due on page 3 is ₹4,500." — not "Let me check if this PDF is
extractable."

For anything involving tables, figures, form fields, embedded attachments,
or scanned content, consult the pdf-reading skill.

---

## DOCX / DOC

For a quick preview:

```powershell
extract-text uploads\memo.docx | Select-Object -First 200
```

Or in Python if `extract-text` isn't available:

```python
import docx2txt
text = docx2txt.process(r"uploads\memo.docx")
print(text[:2000])
```

Old `.doc` format (pre-2007) is not a ZIP file — python-docx will reject it.
Use `docx2txt` which handles both, or convert with LibreOffice first. See the
docx skill for full conversion instructions.

For editing, creating, tracked changes, or image extraction, go to the docx skill.

---

## XLSX / XLS / Spreadsheets

Quick preview:

```powershell
extract-text uploads\data.xlsx | Select-Object -First 100
```

When you need structured Python access:

```python
from openpyxl import load_workbook

wb = load_workbook(r"uploads\data.xlsx", read_only=True, data_only=True)
print("Sheets:", wb.sheetnames)
ws = wb.active
for row in ws.iter_rows(max_row=5, values_only=True):
    print(row)
wb.close()
```

Always pass `read_only=True` — without it, openpyxl loads the entire file into
memory, which fails on large workbooks. Also note: `ws.max_row` is unreliable
in read-only mode because many tools skip writing the dimension record. Use
iteration or pandas if you need an accurate count.

**Old `.xls` format** — openpyxl will raise an error. Switch to pandas:

```python
import pandas as pd
df = pd.read_excel(r"uploads\old.xls", engine="xlrd", nrows=5)
print(df)
```

**`.ods` (OpenDocument Spreadsheet)** — openpyxl also rejects this. Use:

```python
import pandas as pd
df = pd.read_excel(r"uploads\data.ods", engine="odf", nrows=5)
print(df)
```

For formulas, formatting, charts, or writing new spreadsheets, go to the xlsx skill.

---

## PPTX / PPT

```powershell
extract-text uploads\deck.pptx | Select-Object -First 200
```

Or in Python:

```python
from pptx import Presentation

prs = Presentation(r"uploads\deck.pptx")
for i, slide in enumerate(prs.slides):
    print(f"\n--- Slide {i+1} ---")
    for shape in slide.shapes:
        if shape.has_text_frame:
            print(shape.text_frame.text)
```

Old `.ppt` format requires LibreOffice to convert first. See the pptx skill
for the conversion approach on Windows (the `soffice` wrapper).

For anything beyond reading — editing slides, replacing images, generating
decks — go to the pptx skill.

---

## CSV / TSV

Never open these blindly. A single cell with 50KB of quoted text will
give you garbage output on a naive first read. Use pandas with a row limit:

```python
import pandas as pd

df = pd.read_csv(r"uploads\data.csv", nrows=5)
print(df)
print()
print(df.dtypes)
```

To get an approximate row count without loading everything:

```powershell
(Get-Content "uploads\data.csv").Count
```

Note: this counts lines, not records. Multi-line quoted fields will cause
it to over-count. It's a quick orientation check, not a precise number.

Full load only after you understand the shape:

```python
df = pd.read_csv(r"uploads\data.csv")
print(df.shape)
print(df.describe())
```

TSV files are the same — just add `sep="\t"` to `read_csv`.

---

## JSON / JSONL

Start with structure, not content:

```python
import json

with open(r"uploads\data.json", encoding="utf-8") as f:
    data = json.load(f)

print(type(data).__name__)
if isinstance(data, list):
    print(f"Array with {len(data)} items")
    print("First item:", data[0])
elif isinstance(data, dict):
    print("Keys:", list(data.keys()))
```

JSONL (newline-delimited JSON, one object per line) — do not load the whole
file. Read it line by line:

```python
with open(r"uploads\data.jsonl", encoding="utf-8") as f:
    for i, line in enumerate(f):
        if i >= 3:
            break
        print(json.loads(line))

# Row count
with open(r"uploads\data.jsonl", encoding="utf-8") as f:
    count = sum(1 for _ in f)
print(f"Total records: {count}")
```

---

## Images (JPG / PNG / GIF / WEBP)

Uploaded images are already injected into your context as vision inputs.
You can describe, analyze, or answer questions about them without touching
the disk at all.

Only go to disk if you need to **process** the image programmatically:

```python
from PIL import Image

img = Image.open(r"uploads\photo.jpg")
print(img.size, img.mode, img.format)
```

For OCR (extracting text from the image, not describing it):

```python
import pytesseract
from PIL import Image

img = Image.open(r"uploads\scan.png")
print(pytesseract.image_to_string(img))
```

On Windows, `pytesseract` needs the Tesseract binary installed separately.
If it errors with a path issue, set:

```python
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
```

One thing to be aware of: the upload client may resize images larger than
2000×2000 and re-encode them as JPEG. For tasks that depend on original
pixel data or resolution, let the user know this may have happened.

---

## Archives (ZIP / TAR / GZ)

List contents first. Do not auto-extract — archives can be gigabytes,
deeply nested, or contain path-traversal filenames.

**ZIP:**

```python
import zipfile

with zipfile.ZipFile(r"uploads\bundle.zip") as zf:
    for info in zf.infolist():
        print(f"{info.filename}  ({info.file_size} bytes)")
```

**TAR / TAR.GZ / TAR.XZ:**

```python
import tarfile

with tarfile.open(r"uploads\bundle.tar.gz") as tf:
    for member in tf.getmembers():
        print(f"{member.name}  ({member.size} bytes)")
```

`tarfile.open` auto-detects compression — works on `.tar`, `.tar.gz`,
`.tar.bz2`, `.tar.xz` without changing anything.

To extract a single file when the user asks for it:

```python
with zipfile.ZipFile(r"uploads\bundle.zip") as zf:
    content = zf.read("path/inside/file.txt")
    print(content.decode("utf-8"))
```

**Standalone `.gz`** (one compressed file, not a tar archive) — there's no
file listing, just peek at what's inside:

```python
import gzip

with gzip.open(r"uploads\data.json.gz", "rt", encoding="utf-8") as f:
    for i, line in enumerate(f):
        if i >= 50:
            break
        print(line, end="")
```

---

## EPUB / ODT

```powershell
extract-text uploads\book.epub | Select-Object -First 200
```

Long ebooks rarely need to be loaded entirely — limit to what the user asked
about. If you need a specific chapter, `extract-text` output is usually
structured enough to locate it.

---

## RTF / IPYNB

```powershell
extract-text uploads\notes.rtf | Select-Object -First 200
extract-text uploads\notebook.ipynb | Select-Object -First 200
```

For `.ipynb`, the output separates code cells from markdown cells so you
can tell at a glance what kind of notebook it is.

---

## Plain text, code files, and logs

Check size before reading:

```powershell
(Get-Item "uploads\app.log").Length
```

- **Under ~20KB** — read the whole thing:
  ```powershell
  Get-Content "uploads\app.log"
  ```
- **Over ~20KB** — read the head and tail to orient:
  ```powershell
  Get-Content "uploads\app.log" | Select-Object -First 100
  Get-Content "uploads\app.log" | Select-Object -Last 100
  ```
  If the user asked about something specific, search for it:
  ```powershell
  Select-String -Path "uploads\app.log" -Pattern "ERROR"
  ```

Log files almost always have the most relevant content at the end —
start there when the user hasn't told you what to look for.

---

## Unknown file type

Read the first few bytes to identify it:

```python
with open(r"uploads\mystery.bin", "rb") as f:
    header = f.read(16)

print(header.hex())
print(header)
```

Common magic bytes:
- `25 50 44 46` → PDF (`%PDF`)
- `50 4B 03 04` → ZIP (also DOCX, XLSX, PPTX, JAR)
- `D0 CF 11 E0` → Old Office format (`.doc`, `.xls`, `.ppt`)
- `89 50 4E 47` → PNG
- `FF D8 FF` → JPEG
- `1F 8B` → GZIP

If the bytes don't match anything recognizable, ask the user what the file
is rather than guessing.
