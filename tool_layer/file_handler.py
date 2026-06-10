"""
tool_layer/file_handler.py — File content extraction for common formats.

Uses only Python stdlib. Supports:
  - Plain text: .txt .sql .md .py .json .xml .yaml .csv .log .java .js .ts .html .css .sh .bat
  - Images: .jpg .jpeg .png .gif .webp .bmp (read as base64 + dimensions)
  - Office (Open XML): .docx .xlsx .pptx (ZIP+XML text extraction)
  - PDF: basic text extraction (best-effort, no external libs)
"""

import base64
import io
import os
import re
import struct
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

# -- File type groups --

TEXT_EXTENSIONS = {
    '.txt', '.sql', '.md', '.py', '.js', '.ts', '.jsx', '.tsx',
    '.json', '.xml', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
    '.csv', '.log', '.html', '.css', '.scss', '.less',
    '.java', '.kt', '.swift', '.rs', '.go', '.c', '.cpp', '.h', '.hpp',
    '.sh', '.bat', '.ps1', '.rb', '.php', '.lua', '.r', '.m',
    '.env', '.gitignore', '.dockerfile', '.makefile',
}

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.ico', '.svg'}

OFFICE_EXTENSIONS = {'.docx', '.xlsx', '.pptx'}

PDF_EXTENSIONS = {'.pdf'}

ALL_SUPPORTED = TEXT_EXTENSIONS | IMAGE_EXTENSIONS | OFFICE_EXTENSIONS | PDF_EXTENSIONS


# -- Image helpers --

def _get_image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Get image dimensions from raw bytes. Supports PNG, JPEG, GIF, WebP, BMP."""
    try:
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            # PNG: width at offset 16, height at offset 20 (big-endian)
            w, h = struct.unpack('>II', data[16:24])
            return w, h
        elif data[:2] == b'\xff\xd8':
            # JPEG: scan for SOF0 marker
            i = 2
            while i < len(data) - 9:
                if data[i] == 0xff and data[i+1] in (0xc0, 0xc1, 0xc2):
                    h, w = struct.unpack('>HH', data[i+5:i+9])
                    return w, h
                i += 1
        elif data[:6] in (b'GIF87a', b'GIF89a'):
            w, h = struct.unpack('<HH', data[6:10])
            return w, h
        elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            w = h = 0
            # VP8 chunk
            if data[12:16] == b'VP8 ':
                w, h = struct.unpack('<HH', data[26:30])
            return w, h
        elif data[:2] == b'BM':
            w, h = struct.unpack('<II', data[18:26])
            return w, h
    except Exception:
        pass
    return None


def read_image_as_base64(path: str | Path) -> dict:
    """Read image file and return base64 data URL with metadata."""
    path = Path(path)
    data = path.read_bytes()
    ext = path.suffix.lower()
    mime_map = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.gif': 'image/gif',
        '.webp': 'image/webp', '.bmp': 'image/bmp',
        '.ico': 'image/x-icon', '.svg': 'image/svg+xml',
    }
    mime = mime_map.get(ext, 'application/octet-stream')
    b64 = base64.b64encode(data).decode('ascii')
    dims = _get_image_dimensions(data)

    return {
        'type': 'image',
        'mime': mime,
        'size': len(data),
        'width': dims[0] if dims else None,
        'height': dims[1] if dims else None,
        'base64': b64,
        'data_url': f'data:{mime};base64,{b64}',
    }


# -- Office Open XML extraction --

def _extract_xml_text(xml_bytes: bytes, tag_pattern: str) -> str:
    """Extract text from XML elements matching a tag pattern."""
    try:
        root = ET.fromstring(xml_bytes)
        texts = []
        for elem in root.iter():
            # Match tag without namespace prefix
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag == tag_pattern:
                if elem.text:
                    texts.append(elem.text)
            # Also collect child text
            for child in elem.iter():
                ctag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                if ctag == 't' and child.text:
                    pass  # handled by iter above
        return '\n'.join(texts) if texts else ''
    except Exception:
        return ''


def _extract_docx_xml(xml_bytes: bytes) -> str:
    """Extract all text from a docx document.xml."""
    try:
        root = ET.fromstring(xml_bytes)
        ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        paragraphs = []
        for p in root.iter(f'{{{ns}}}p'):
            texts = []
            for t in p.iter(f'{{{ns}}}t'):
                if t.text:
                    texts.append(t.text)
            if texts:
                paragraphs.append(''.join(texts))
        return '\n\n'.join(paragraphs)
    except Exception:
        return ''


def extract_docx_text(path: str | Path) -> str:
    """Extract text from a .docx file."""
    path = Path(path)
    try:
        with zipfile.ZipFile(path, 'r') as z:
            if 'word/document.xml' in z.namelist():
                xml_bytes = z.read('word/document.xml')
                return _extract_docx_xml(xml_bytes)
            return '[docx] No document.xml found.'
    except Exception as e:
        return f'[docx] Extraction failed: {e}'


def extract_xlsx_text(path: str | Path) -> str:
    """Extract text from a .xlsx file (shared strings + cell values)."""
    path = Path(path)
    try:
        with zipfile.ZipFile(path, 'r') as z:
            # Read shared strings
            strings = []
            if 'xl/sharedStrings.xml' in z.namelist():
                ss_root = ET.fromstring(z.read('xl/sharedStrings.xml'))
                ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
                for si in ss_root.iter(f'{{{ns}}}si'):
                    parts = []
                    for t in si.iter(f'{{{ns}}}t'):
                        if t.text:
                            parts.append(t.text)
                    strings.append(''.join(parts))

            # Read sheet data
            sheets = []
            for name in z.namelist():
                if name.startswith('xl/worksheets/sheet') and name.endswith('.xml'):
                    ws_root = ET.fromstring(z.read(name))
                    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
                    rows = []
                    for row in ws_root.iter(f'{{{ns}}}row'):
                        cells = []
                        for c in row.iter(f'{{{ns}}}c'):
                            t = c.get('t', '')
                            v = None
                            for v_elem in c.iter(f'{{{ns}}}v'):
                                v = v_elem.text
                                break
                            if v is not None:
                                if t == 's':
                                    try:
                                        idx = int(v)
                                        if 0 <= idx < len(strings):
                                            cells.append(strings[idx])
                                    except ValueError:
                                        cells.append(v)
                                else:
                                    cells.append(v)
                        if cells:
                            rows.append('\t'.join(cells))
                    if rows:
                        sheets.append(f'--- Sheet: {name} ---\n' + '\n'.join(rows))

            return '\n\n'.join(sheets) if sheets else '[xlsx] No sheet data found.'
    except Exception as e:
        return f'[xlsx] Extraction failed: {e}'


def extract_pptx_text(path: str | Path) -> str:
    """Extract text from a .pptx file."""
    path = Path(path)
    try:
        with zipfile.ZipFile(path, 'r') as z:
            slides = []
            slide_names = sorted(
                [n for n in z.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml')],
                key=lambda n: int(re.search(r'slide(\d+)', n).group(1))
            )
            ns = 'http://schemas.openxmlformats.org/drawingml/2006/main'
            for i, name in enumerate(slide_names, 1):
                root = ET.fromstring(z.read(name))
                texts = []
                for t in root.iter(f'{{{ns}}}t'):
                    if t.text:
                        texts.append(t.text)
                if texts:
                    slides.append(f'--- Slide {i} ---\n' + '\n'.join(texts))
            return '\n\n'.join(slides) if slides else '[pptx] No text found.'
    except Exception as e:
        return f'[pptx] Extraction failed: {e}'


# -- PDF (best-effort, stdlib only) --

def extract_pdf_text(path: str | Path) -> str:
    """Best-effort PDF text extraction using only stdlib.

    Scans for text between BT/ET operators and decodes literal strings.
    Does NOT handle compressed streams — works best on simple/uncompressed PDFs.
    """
    path = Path(path)
    try:
        data = path.read_bytes()
        text = data.decode('latin-1', errors='replace')

        # Find text blocks between BT and ET
        blocks = []
        bt_pos = 0
        while True:
            bt_pos = text.find('\nBT\n', bt_pos)
            if bt_pos == -1:
                bt_pos = text.find('\nBT\r', 0)
                if bt_pos == -1:
                    break
            et_pos = text.find('\nET\n', bt_pos)
            if et_pos == -1:
                et_pos = text.find('\nET\r', bt_pos)
                if et_pos == -1:
                    break
            block = text[bt_pos:et_pos]
            bt_pos = et_pos + 1

            # Extract parenthesized strings
            chars = []
            i = 0
            while i < len(block):
                if block[i] == '(':
                    depth = 1
                    j = i + 1
                    s = []
                    while j < len(block) and depth > 0:
                        if block[j] == '\\' and j + 1 < len(block):
                            j += 1
                            s.append(block[j])
                        elif block[j] == '(':
                            depth += 1
                            s.append('(')
                        elif block[j] == ')':
                            depth -= 1
                            if depth > 0:
                                s.append(')')
                        else:
                            s.append(block[j])
                        j += 1
                    chars.append(''.join(s))
                    i = j
                else:
                    i += 1

            line = ''.join(chars).strip()
            if line:
                blocks.append(line)

        if blocks:
            return '\n'.join(blocks)
        return '[pdf] No extractable text found (streams may be compressed).'
    except Exception as e:
        return f'[pdf] Extraction failed: {e}'


# -- Main dispatch --

def read_file_content(path: str | Path, max_chars: int = 50000) -> dict:
    """Read and extract content from any supported file type.

    Returns: {
        'type': 'text' | 'image' | 'office' | 'pdf' | 'unsupported',
        'content': str (text content or description),
        'size': int (bytes),
        'mime': str | None,
        'data_url': str | None (images only),
        'dimensions': (w, h) | None (images only),
    }
    """
    path = Path(path)
    if not path.exists():
        return {'type': 'error', 'content': f'File not found: {path}', 'size': 0}

    if not path.is_file():
        return {'type': 'error', 'content': f'Not a file: {path}', 'size': 0}

    ext = path.suffix.lower()
    size = path.stat().st_size

    # Plain text
    if ext in TEXT_EXTENSIONS:
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
            if len(text) > max_chars:
                text = text[:max_chars] + f'\n\n[... truncated, original size: {size} bytes, {len(text)} chars]'
            return {
                'type': 'text',
                'content': text,
                'size': size,
                'filename': path.name,
            }
        except Exception as e:
            return {'type': 'error', 'content': f'Read error: {e}', 'size': size}

    # Images
    if ext in IMAGE_EXTENSIONS:
        try:
            img = read_image_as_base64(path)
            return {
                'type': 'image',
                'content': f'[Image: {path.name}, {img["width"]}x{img["height"]}, {size} bytes]',
                'size': size,
                'mime': img['mime'],
                'data_url': img['data_url'],
                'dimensions': (img['width'], img['height']),
            }
        except Exception as e:
            return {'type': 'error', 'content': f'Image read error: {e}', 'size': size}

    # Office formats
    if ext == '.docx':
        text = extract_docx_text(path)
        if len(text) > max_chars:
            text = text[:max_chars] + '\n\n[... truncated]'
        return {'type': 'office', 'content': text, 'size': size, 'format': 'docx'}

    if ext == '.xlsx':
        text = extract_xlsx_text(path)
        if len(text) > max_chars:
            text = text[:max_chars] + '\n\n[... truncated]'
        return {'type': 'office', 'content': text, 'size': size, 'format': 'xlsx'}

    if ext == '.pptx':
        text = extract_pptx_text(path)
        if len(text) > max_chars:
            text = text[:max_chars] + '\n\n[... truncated]'
        return {'type': 'office', 'content': text, 'size': size, 'format': 'pptx'}

    # PDF
    if ext == '.pdf':
        text = extract_pdf_text(path)
        if len(text) > max_chars:
            text = text[:max_chars] + '\n\n[... truncated]'
        return {'type': 'pdf', 'content': text, 'size': size}

    return {
        'type': 'unsupported',
        'content': f'Unsupported file type: {ext}',
        'size': size,
    }


def list_directory(dir_path: str | Path, max_items: int = 200) -> dict:
    """List directory contents with metadata.

    Returns: {
        'path': str,
        'parent': str | None,
        'drives': [...] (Windows only, for root listing),
        'items': [{'name': ..., 'type': 'dir'|'file', 'size': ..., 'modified': ...}],
    }
    """
    dir_path = Path(dir_path)

    # Windows: if path is empty or '/', list drives
    if not dir_path or str(dir_path) in ('/', '\\'):
        import string
        drives = []
        for letter in string.ascii_uppercase:
            drive = Path(f'{letter}:\\')
            if drive.exists():
                drives.append({
                    'name': f'{letter}:',
                    'type': 'dir',
                    'size': 0,
                    'modified': '',
                })
        return {
            'path': 'This PC',
            'parent': None,
            'drives': drives,
            'items': [],
        }

    if not dir_path.exists():
        return {'error': f'Path not found: {dir_path}', 'path': str(dir_path)}

    if not dir_path.is_dir():
        return {'error': f'Not a directory: {dir_path}', 'path': str(dir_path)}

    parent = str(dir_path.parent) if dir_path.parent != dir_path else None

    items = []
    try:
        for entry in sorted(dir_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            if entry.name.startswith('.'):
                continue  # skip hidden
            try:
                stat = entry.stat()
                items.append({
                    'name': entry.name,
                    'type': 'dir' if entry.is_dir() else 'file',
                    'size': stat.st_size if entry.is_file() else 0,
                    'modified': '',
                })
            except OSError:
                continue
            if len(items) >= max_items:
                items.append({'name': '... (truncated)', 'type': 'info', 'size': 0, 'modified': ''})
                break
    except PermissionError:
        return {'error': f'Permission denied: {dir_path}', 'path': str(dir_path)}
    except Exception as e:
        return {'error': str(e), 'path': str(dir_path)}

    return {
        'path': str(dir_path),
        'parent': parent,
        'items': items,
    }
