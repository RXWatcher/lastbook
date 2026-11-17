#!/usr/bin/env python3
"""The Dutch government's preparedness documents as a library add-on: text-only PDFs, a catalog, a search index and a zip.

  python3 tools/build_nl_documents.py derived/nl-guides/addon [--zip derived/nl-guides/Lastbook-Addon-NL-Preparedness.zip] [--src content/nl-documents]

Reads: content/nl-documents/ (sources.json and the page texts it names). Each text is the wording of an official English document of
the Dutch government, page by page, as written out by hand from the PDF or web page it names (Denk vooruit, https://english.denkvooruit.nl,
published by the National Coordinator for Counterterrorism and Security). The site's copyright page puts its content under CC0 1.0 and
excludes photographs, videos, infographics and other images, and the PDFs carry pictures and icons, so the originals are not shipped:
this tool makes a text-only PDF of each, with the original's page numbers. Nothing is downloaded; the files in content/ are the source.
Writes: a folder laid out like a pack (docs/SETUP-API.md; derived/packs/pack-spec.json "addons"): pack.json, pack-manifest.tsv and
library-data/ with catalog.json, search.sqlite, summary.json, documents/netherlands/<id>.pdf and text/<id>.txt, and with --zip the same
under LastbookData/ in one zip. packaging/pack_merge.py puts it into a library.
Licence of the words: CC0 1.0 (Government of the Netherlands). Pictures, icons and layout are not copied.

A page's text is written in a small markup, one block to a line: "# Heading", "## Subheading", "• or - an item", a blank line for space,
anything else a paragraph. "@@ page N" starts page N, and "@@ page N | printed page M" says what the original printed there. A page must
fit on one PDF page, or the build stops: a citation to page N is then always page N of the original.
"""
import argparse
import datetime
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import unicodedata
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'content' / 'nl-documents'
SCHEMA = 'CREATE VIRTUAL TABLE pages USING fts5(doc_id UNINDEXED,title,collection,category,path UNINDEXED,page UNINDEXED,body,tokenize="unicode61")'


class Overflow(ValueError):
    """A page's text does not fit on one PDF page."""


# ------------------------------------------------------------------------------------------------------------ pages ----
MARK = re.compile(r'^@@ page (\d+)(?: \| (.*))?$')


def read_pages(text):
    """[{'n', 'label', 'text'}] from a page text file. Pages are numbered 1, 2, 3 ... in order."""
    pages = []
    for line in text.splitlines():
        m = MARK.match(line.rstrip())
        if m:
            if int(m.group(1)) != len(pages) + 1:
                raise ValueError(f'page {m.group(1)} follows page {len(pages)}: pages must be numbered 1, 2, 3 ... in order')
            pages.append({'n': len(pages) + 1, 'label': (m.group(2) or '').strip(), 'lines': []})
        elif pages:
            pages[-1]['lines'].append(line.rstrip())
        elif line.strip():
            raise ValueError('text before the first "@@ page 1" line')
    return [{'n': p['n'], 'label': p['label'], 'text': '\n'.join(p['lines']).strip('\n')} for p in pages]


def blocks(text):
    """[(kind, text)] with kind h1, h2, li, p or gap."""
    out = []
    for line in text.split('\n'):
        if not line.strip():
            out.append(('gap', ''))
        elif line.startswith('## '):
            out.append(('h2', line[3:].strip()))
        elif line.startswith('# '):
            out.append(('h1', line[2:].strip()))
        elif line.startswith(('• ', '- ')):
            out.append(('li', line[2:].strip()))
        else:
            out.append(('p', line.strip()))
    return out


def plain(text):
    """The page's own words, without the markup: what the search index and the Text view hold."""
    out = []
    for kind, t in blocks(text):
        out.append('' if kind == 'gap' else '• ' + t if kind == 'li' else t)
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(out)).strip()


# ------------------------------------------------------------------------------------------------------------- fonts ----
# Helvetica and Helvetica-Bold advance widths (1/1000 em) for ASCII 32..126, from Adobe's standard-14 font metrics.
REGULAR = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278,
           584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944,
           667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500,
           278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]
BOLD = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333,
        584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944,
        667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556,
        333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584]
SPECIAL = {'’': (222, 278), '‘': (222, 278), '“': (333, 500), '”': (333, 500), '–': (556, 556), '—': (1000, 1000),
           '•': (350, 350), '€': (556, 556), '…': (1000, 1000), '·': (278, 278), ' ': (278, 278), '°': (400, 400)}


def width(text, bold=False):
    """Width of text in 1/1000 em."""
    total = 0
    for ch in text:
        if ch in SPECIAL:
            total += SPECIAL[ch][1 if bold else 0]
        elif 32 <= ord(ch) <= 126:
            total += (BOLD if bold else REGULAR)[ord(ch) - 32]
        else:
            base = unicodedata.normalize('NFD', ch)[0]
            total += (BOLD if bold else REGULAR)[ord(base) - 32] if 32 <= ord(base) <= 126 else 556
    return total


def wrap(text, size, limit, bold=False):
    """Lines of text no wider than limit points, broken at spaces (a word wider than a line is cut)."""
    lines, cur = [], ''
    for word in text.split():
        while width(word, bold) * size / 1000 > limit:
            room = cur + (' ' if cur else '')
            cut = len(word)
            while cut > 1 and width(room + word[:cut], bold) * size / 1000 > limit:
                cut -= 1
            if cur and cut <= 1:
                lines.append(cur)
                cur = ''
                continue
            lines.append(room + word[:cut])
            word, cur = word[cut:], ''
        trial = (cur + ' ' + word) if cur else word
        if cur and width(trial, bold) * size / 1000 > limit:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


# --------------------------------------------------------------------------------------------------------------- pdf ----
PAGE_W, PAGE_H = 595, 842
MARGIN, TOP, BOTTOM = 56, 62, 100
BODY, LEAD = 11, 15
FOOT, FOOT_LEAD = 7.5, 10


def pdf_text(s):
    try:
        b = s.encode('cp1252')
    except UnicodeEncodeError as e:
        raise ValueError(f'a character that PDF text cannot hold in WinAnsi: {s[e.start:e.start + 1]!r}')
    return b.replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)')


def page_lines(page):
    """[(font, size, x, y, text)] for a page's blocks, or Overflow."""
    out, y = [], PAGE_H - TOP
    limit = PAGE_W - 2 * MARGIN
    for kind, t in blocks(page['text']):
        if kind == 'gap':
            y -= 7
            continue
        font, size, lead, indent, before, after = {'h1': ('F2', 17, 22, 0, 0, 6), 'h2': ('F2', 13, 18, 0, 6, 3), 'li': ('F1', BODY, LEAD, 16, 0, 3),
                                                   'p': ('F1', BODY, LEAD, 0, 0, 6)}[kind]
        y -= before
        for n, line in enumerate(wrap(t, size, limit - indent, bold=font == 'F2')):
            y -= lead
            if y < BOTTOM:
                raise Overflow(f'page {page["n"]} is too long for one PDF page')
            if kind == 'li' and n == 0:
                out.append(('F1', size, MARGIN + 3, y, '•'))
            out.append((font, size, MARGIN + indent, y, line))
        y -= after
    return out


def footer(page, count, title, url):
    where = f'page {page["n"]} of {count}' + (f' ({page["label"]})' if page['label'] else '')
    lines = wrap(f'{title}. Text-only edition, {where}.', FOOT, PAGE_W - 2 * MARGIN)
    lines += wrap(f'The words are the Government of the Netherlands’s, CC0 1.0. The original’s pictures and layout are not included. '
                  f'This is an unofficial copy: the government does not necessarily agree with how it is shown here. Original: {url}',
                  FOOT, PAGE_W - 2 * MARGIN)
    return [('F1', FOOT, MARGIN, 62 - FOOT_LEAD * i, t) for i, t in enumerate(lines)]


def make_pdf(pages, title, url):
    """A PDF with one page for each of pages and only text on it: standard fonts, no images, the same bytes for the same input."""
    objs = []                                   # object n (1-based) is objs[n - 1]
    objs.append(b'<< /Type /Catalog /Pages 2 0 R >>')
    objs.append(None)                           # the page tree, once the page objects are numbered
    objs.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>')
    objs.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>')
    objs.append(b'<< /Title (' + pdf_text(title) + b') /Author (Government of the Netherlands; text-only edition made for Lastbook) /Producer (tools/build_nl_documents.py) >>')
    kids = []
    for page in pages:
        ops = []
        for color, items in (('0 g', page_lines(page)), ('0.35 g', footer(page, len(pages), title, url))):
            ops.append(color)
            for font, size, x, y, t in items:
                ops.append(b'BT /%s %s Tf %.2f %.2f Td (%s) Tj ET' % (font.encode(), (b'%g' % size), x, y, pdf_text(t)))
        stream = zlib.compress(b'\n'.join(o if isinstance(o, bytes) else o.encode() for o in ops), 9)
        objs.append(b'<< /Length %d /Filter /FlateDecode >>\nstream\n' % len(stream) + stream + b'\nendstream')
        content = len(objs)
        objs.append(b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>'
                    % (PAGE_W, PAGE_H, content))
        kids.append(len(objs))
    objs[1] = b'<< /Type /Pages /Count %d /Kids [%s] >>' % (len(kids), b' '.join(b'%d 0 R' % k for k in kids))
    out = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b'%d 0 obj\n' % n + body + b'\nendobj\n'
    start = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1)
    for o in offsets:
        out += b'%010d 00000 n \n' % o
    out += b'trailer\n<< /Size %d /Root 1 0 R /Info 5 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, start)
    return bytes(out)


# ------------------------------------------------------------------------------------------------------------ add-on ----
def sha256_of(data):
    return hashlib.sha256(data).hexdigest()


def edition(published):
    try:
        d = datetime.date.fromisoformat(published)
    except (TypeError, ValueError):
        return None
    return f'Published {d.day} {d:%B %Y}'


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.partial')
    tmp.write_bytes(data)
    tmp.replace(path)


def build(out, src=SRC, built=None):
    """Writes the add-on folder out from the sources in src. Returns {'documents', 'pages', 'bytes'}."""
    out, src = Path(out), Path(src)
    spec = json.loads((src / 'sources.json').read_text(encoding='utf-8'))
    built = built or datetime.date.today().isoformat()
    for old in ('library-data', 'pack.json', 'pack-manifest.tsv'):
        p = out / old
        shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
    lib = out / 'library-data'
    (lib / 'documents' / 'netherlands').mkdir(parents=True)
    (lib / 'text').mkdir()
    records, rows, pages_for_search = [], [], []
    for d in spec['documents']:
        pages = read_pages((src / d['file']).read_text(encoding='utf-8'))
        if len(pages) != d['pages']:
            raise ValueError(f'{d["id"]}: {d["file"]} has {len(pages)} pages, the original has {d["pages"]}')
        for p in pages:
            if not p['text'].strip():
                raise ValueError(f'{d["id"]} page {p["n"]} is empty')
        pdf = make_pdf(pages, d['title'], d['source_url'])
        rel_pdf, rel_text = f'documents/netherlands/{d["id"]}.pdf', f'text/{d["id"]}.txt'
        write_atomic(lib / rel_pdf, pdf)
        texts = [plain(p['text']) for p in pages]
        write_atomic(lib / rel_text, '\n\f\n'.join(texts).encode('utf-8'))
        rec = {'id': d['id'], 'title': d['title'], 'kind': 'pdf', 'publisher': spec['publisher'], 'collection': spec['collection'],
               'category': spec['category'], 'path': rel_pdf, 'bytes': len(pdf), 'sha256': sha256_of(pdf), 'pages': len(pages)}
        if edition(d.get('published')):
            rec['edition'] = edition(d['published'])
        rec.update({'retrieved_at': spec.get('retrieved_at', built) + 'T00:00:00Z', 'source_url': d['source_url'], 'license': d['licence'],
                    'license_url': d['licence_url'], 'searchability': 'text', 'notes': d['notes'], 'text_path': rel_text})
        records.append(rec)
        for p, t in zip(pages, texts):
            pages_for_search.append((d['id'], d['title'], spec['collection'], spec['category'], rel_pdf, p['n'], t))
    db = lib / 'search.sqlite'
    con = sqlite3.connect(db)
    con.execute(SCHEMA)
    con.executemany('INSERT INTO pages VALUES (?,?,?,?,?,?,?)', pages_for_search)
    con.commit()
    con.close()
    summary = {'resources': len(records), 'pdfs': len(records), 'pdf_pages': sum(r['pages'] for r in records), 'web_pages': 0, 'videos': 0,
               'collections': 0, 'document_bytes': sum(r['bytes'] for r in records)}
    write_atomic(lib / 'catalog.json', json.dumps(records, indent=2).encode('utf-8'))
    write_atomic(lib / 'summary.json', json.dumps(summary, indent=1).encode('utf-8'))
    pack = {'name': spec['name'], 'size': spec['name'], 'map': 'none', 'built': built, 'snapshot': None, 'sample': False, 'add_ons': [],
            'counts': {'pdf': len(records)}, 'known_gaps': [], 'incomplete': 0, 'content_revision': f'{built}-{spec["name"]}-v1'}
    write_atomic(out / 'pack.json', json.dumps(pack, indent=1).encode('utf-8'))
    for f in sorted(p for p in lib.rglob('*') if p.is_file()):
        data = f.read_bytes()
        rows.append(f'{f.relative_to(out).as_posix()}\t{len(data)}\t{sha256_of(data)}\tgenerated\t')
    write_atomic(out / 'pack-manifest.tsv', ('path\tbytes\tsha256\thow\tchanges\n' + '\n'.join(rows) + '\n').encode('utf-8'))
    return {'documents': len(records), 'pages': summary['pdf_pages'], 'bytes': summary['document_bytes']}


def zip_addon(out, zip_path):
    """The folder as one zip, every file under LastbookData/, so setup's unpacking checks and packaging/pack_merge.py read it as any pack."""
    out, zip_path = Path(out), Path(zip_path)
    tmp = zip_path.with_suffix('.partial')
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted(p for p in out.rglob('*') if p.is_file()):
            zi = zipfile.ZipInfo('LastbookData/' + f.relative_to(out).as_posix(), date_time=(2026, 11, 17, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, f.read_bytes())
    tmp.replace(zip_path)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Build the Netherlands preparedness documents add-on.')
    ap.add_argument('out', help='the add-on folder to write')
    ap.add_argument('--zip', help='also write the add-on as this zip file')
    ap.add_argument('--src', default=str(SRC), help='the sources (default: content/nl-documents)')
    a = ap.parse_args(argv)
    info = build(a.out, a.src)
    print(f'{info["documents"]} documents, {info["pages"]} pages, {info["bytes"]:,} bytes of PDF -> {a.out}')
    if a.zip:
        zip_addon(a.out, a.zip)
        print(f'zip: {a.zip} ({Path(a.zip).stat().st_size:,} bytes)')


if __name__ == '__main__':
    sys.exit(main())
