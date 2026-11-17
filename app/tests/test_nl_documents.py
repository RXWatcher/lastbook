"""The Netherlands documents add-on: the text-only PDFs and add-on folder tools/build_nl_documents.py makes, packaging/pack_merge.py
putting them into (and taking them out of) a library, the server hiding a guide whose documents are not in the library, and the
Dutch guides citing real pages.

  python3 -B -m unittest app.tests.test_nl_documents

Uses made-up libraries in temporary folders and the real sources in content/nl-documents/. No network, no real library."""
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


build = load('build_nl_documents', 'tools/build_nl_documents.py')
merge = load('pack_merge', 'packaging/pack_merge.py')

SMALL_SOURCES = {
    'documents': [
        {'id': 'nl-test-kit', 'title': 'Test kit list', 'file': 'kit.txt', 'pages': 2, 'source_url': 'https://example.invalid/kit',
         'published': '2025-11-25', 'licence': 'CC0 1.0', 'licence_url': 'https://creativecommons.org/publicdomain/zero/1.0/',
         'notes': 'A made-up document.'},
    ]}
SMALL_TEXT = ('@@ page 1\n# Kit\nWater: at least 3 litres per person per day. It’s “enough” for 72 hours, €70 in cash.\n\n'
              '• Radio with batteries\n• Torch\n@@ page 2 | printed page 1\n## Plan\nTalk with your neighbours about the plan.\n')


def small_sources(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'sources.json').write_text(json.dumps({**SMALL_SOURCES, 'name': 'nl-test', 'collection': 'Test collection',
                                                     'publisher': 'Test publisher', 'category': 'disaster-response'}), encoding='utf-8')
    (folder / 'kit.txt').write_text(SMALL_TEXT, encoding='utf-8')
    return folder


def pdf_pages(data):
    import pypdfium2
    pdf = pypdfium2.PdfDocument(data)
    try:
        return [p.get_textpage().get_text_bounded() for p in pdf]
    finally:
        pdf.close()


class TextOnlyPdf(unittest.TestCase):
    def test_pages_are_read_with_their_labels(self):
        pages = build.read_pages(SMALL_TEXT)
        self.assertEqual([p['n'] for p in pages], [1, 2])
        self.assertEqual(pages[1]['label'], 'printed page 1')
        self.assertIn('Talk with your neighbours', pages[1]['text'])

    def test_pages_must_be_numbered_in_order(self):
        with self.assertRaises(ValueError):
            build.read_pages('@@ page 1\na\n@@ page 3\nb\n')

    def test_one_pdf_page_per_source_page_and_the_text_is_there(self):
        data = build.make_pdf(build.read_pages(SMALL_TEXT), 'Test kit list', 'https://example.invalid/kit')
        self.assertTrue(data.startswith(b'%PDF-'))
        got = pdf_pages(data)
        self.assertEqual(len(got), 2)
        self.assertIn('Water: at least 3 litres per person per day', ' '.join(got[0].split()))
        self.assertIn('“enough”', got[0])
        self.assertIn('€70', got[0])
        self.assertIn('Talk with your neighbours', ' '.join(got[1].split()))
        self.assertIn('Text-only', got[0])         # every page says what it is
        self.assertIn('CC0', got[0])

    def test_no_image_in_the_pdf(self):
        data = build.make_pdf(build.read_pages(SMALL_TEXT), 'Test kit list', 'https://example.invalid/kit')
        self.assertNotIn(b'/Subtype /Image', data)
        self.assertNotIn(b'/XObject', data)
        import pypdfium2
        pdf = pypdfium2.PdfDocument(data)
        try:
            kinds = {o.type for p in pdf for o in p.get_objects()}
        finally:
            pdf.close()
        self.assertEqual(kinds, {pypdfium2.raw.FPDF_PAGEOBJ_TEXT})

    def test_same_input_same_bytes(self):
        a = build.make_pdf(build.read_pages(SMALL_TEXT), 'T', 'https://example.invalid/kit')
        b = build.make_pdf(build.read_pages(SMALL_TEXT), 'T', 'https://example.invalid/kit')
        self.assertEqual(a, b)

    def test_long_words_and_lines_wrap_inside_the_page(self):
        text = '@@ page 1\n' + ' '.join(['word'] * 60) + '\n' + 'x' * 300 + '\n'
        got = pdf_pages(build.make_pdf(build.read_pages(text), 'T', 'u'))
        self.assertEqual(len(got), 1)
        self.assertGreater(got[0].count('\n') + got[0].count('\r'), 3)

    def test_a_page_that_does_not_fit_is_an_error_not_a_second_page(self):
        text = '@@ page 1\n' + '\n\n'.join(f'Paragraph {i}.' for i in range(200)) + '\n'
        with self.assertRaises(build.Overflow):
            build.make_pdf(build.read_pages(text), 'T', 'u')


class AddonBuild(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.src = small_sources(Path(self.tmp.name) / 'src')
        self.out = Path(self.tmp.name) / 'addon'

    def tearDown(self):
        self.tmp.cleanup()

    def test_folder_layout_and_records(self):
        info = build.build(self.out, self.src, built='2026-11-17')
        lib = self.out / 'library-data'
        cat = json.loads((lib / 'catalog.json').read_text(encoding='utf-8'))
        self.assertEqual([r['id'] for r in cat], ['nl-test-kit'])
        r = cat[0]
        self.assertEqual((r['kind'], r['pages'], r['category'], r['collection']), ('pdf', 2, 'disaster-response', 'Test collection'))
        self.assertEqual(r['license'], 'CC0 1.0')
        self.assertEqual(r['source_url'], 'https://example.invalid/kit')
        pdf = lib / r['path']
        self.assertEqual(pdf.stat().st_size, r['bytes'])
        self.assertEqual(hashlib.sha256(pdf.read_bytes()).hexdigest(), r['sha256'])
        self.assertEqual(len(pdf_pages(pdf.read_bytes())), r['pages'])
        text = (lib / r['text_path']).read_text(encoding='utf-8').split('\n\f\n')
        self.assertEqual(len(text), 2)
        self.assertIn('Radio with batteries', text[0])
        self.assertNotIn('Text-only', text[0])     # the text file is the page's own words
        pack = json.loads((self.out / 'pack.json').read_text(encoding='utf-8'))
        self.assertEqual((pack['name'], pack['size'], pack['map']), ('nl-test', 'nl-test', 'none'))
        self.assertEqual(info['documents'], 1)

    def test_search_rows_one_per_page(self):
        build.build(self.out, self.src, built='2026-11-17')
        con = sqlite3.connect(self.out / 'library-data' / 'search.sqlite')
        rows = con.execute("SELECT doc_id, page FROM pages WHERE pages MATCH '\"neighbours\"'").fetchall()
        self.assertEqual(rows, [('nl-test-kit', 2)])
        self.assertEqual(con.execute('SELECT count(*) FROM pages').fetchone()[0], 2)

    def test_manifest_lists_every_file_with_its_hash(self):
        build.build(self.out, self.src, built='2026-11-17')
        rows = [l.split('\t') for l in (self.out / 'pack-manifest.tsv').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(rows[0][:3], ['path', 'bytes', 'sha256'])
        paths = {r[0] for r in rows[1:]}
        self.assertIn('library-data/catalog.json', paths)
        self.assertTrue(any(p.endswith('.pdf') for p in paths))
        for rel, size, digest, *_ in rows[1:]:
            data = (self.out / rel).read_bytes()
            self.assertEqual((len(data), hashlib.sha256(data).hexdigest()), (int(size), digest), rel)

    def test_rebuild_is_identical(self):
        build.build(self.out, self.src, built='2026-11-17')
        a = (self.out / 'library-data' / 'catalog.json').read_bytes()
        build.build(self.out, self.src, built='2026-11-17')
        self.assertEqual(a, (self.out / 'library-data' / 'catalog.json').read_bytes())

    def test_page_count_that_disagrees_with_the_original_is_refused(self):
        spec = json.loads((self.src / 'sources.json').read_text(encoding='utf-8'))
        spec['documents'][0]['pages'] = 3
        (self.src / 'sources.json').write_text(json.dumps(spec), encoding='utf-8')
        with self.assertRaises(ValueError):
            build.build(self.out, self.src, built='2026-11-17')

    def test_zip_holds_one_lastbookdata_folder(self):
        build.build(self.out, self.src, built='2026-11-17')
        z = Path(self.tmp.name) / 'addon.zip'
        build.zip_addon(self.out, z)
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
        self.assertTrue(all(n.startswith('LastbookData/') for n in names))
        self.assertIn('LastbookData/library-data/catalog.json', names)
        self.assertIn('LastbookData/pack.json', names)


def made_up_library(folder):
    """A library of one PDF record, with the files a pack has and a manifest that matches them."""
    data = Path(folder) / 'LastbookData'
    lib = data / 'library-data'
    (lib / 'documents').mkdir(parents=True)
    (lib / 'text').mkdir()
    (lib / 'documents' / 'a.pdf').write_bytes(b'%PDF-1.4 a')
    (lib / 'text' / 'doc-a.txt').write_text('first page about water\n\f\nsecond page', encoding='utf-8')
    rec = {'id': 'doc-a', 'title': 'Water', 'kind': 'pdf', 'publisher': 'P', 'collection': 'C', 'category': 'water',
           'path': 'documents/a.pdf', 'bytes': 10, 'sha256': hashlib.sha256(b'%PDF-1.4 a').hexdigest(), 'pages': 2, 'text_path': 'text/doc-a.txt'}
    (lib / 'catalog.json').write_text(json.dumps([rec], indent=2), encoding='utf-8')
    con = sqlite3.connect(lib / 'search.sqlite')
    con.execute('CREATE VIRTUAL TABLE pages USING fts5(doc_id UNINDEXED,title,collection,category,path UNINDEXED,page UNINDEXED,body,tokenize="unicode61")')
    con.execute("INSERT INTO pages VALUES ('doc-a','Water','C','water','documents/a.pdf',1,'first page about water')")
    con.commit()
    con.close()
    (lib / 'summary.json').write_text(json.dumps({'resources': 1, 'pdfs': 1, 'pdf_pages': 2, 'web_pages': 0, 'videos': 0, 'collections': 0, 'document_bytes': 10}, indent=1))
    (data / 'pack.json').write_text(json.dumps({'name': 'small', 'size': 'small', 'map': 'base', 'built': '2026-11-13', 'add_ons': [],
                                               'counts': {'pdf': 1}, 'content_revision': 'x'}, indent=1))
    rows = ['path\tbytes\tsha256\thow\tchanges']
    for rel in ('library-data/catalog.json', 'library-data/search.sqlite', 'library-data/summary.json', 'library-data/documents/a.pdf', 'library-data/text/doc-a.txt'):
        b = (data / rel).read_bytes()
        rows.append(f'{rel}\t{len(b)}\t{hashlib.sha256(b).hexdigest()}\tgenerated\t')
    (data / 'pack-manifest.tsv').write_text('\n'.join(rows) + '\n', encoding='utf-8')
    (data / 'derived').mkdir()
    return data


def manifest_problems(data):
    """What setup's repair would call damaged: rows whose file is missing or differs."""
    bad = []
    for line in (data / 'pack-manifest.tsv').read_text(encoding='utf-8').splitlines()[1:]:
        rel, size, digest = line.split('\t')[:3]
        p = data / rel
        if not p.is_file() or p.stat().st_size != int(size) or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            bad.append(rel)
    return bad


class Merge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        base = Path(self.tmp.name)
        self.data = made_up_library(base)
        self.addon = base / 'addon'
        build.build(self.addon, small_sources(base / 'src'), built='2026-11-17')

    def tearDown(self):
        self.tmp.cleanup()

    def cat(self):
        return json.loads((self.data / 'library-data' / 'catalog.json').read_text(encoding='utf-8'))

    def test_add_joins_catalog_files_search_and_summary(self):
        merge.add(self.data, self.addon)
        self.assertEqual([r['id'] for r in self.cat()], ['doc-a', 'nl-test-kit'])
        rec = self.cat()[1]
        pdf = self.data / 'library-data' / rec['path']
        self.assertTrue(pdf.is_file() and not pdf.is_symlink())
        self.assertEqual(os.stat(pdf).st_nlink, 1)
        con = sqlite3.connect(self.data / 'library-data' / 'search.sqlite')
        self.assertEqual(con.execute("SELECT page FROM pages WHERE pages MATCH 'neighbours'").fetchall(), [(2,)])
        self.assertEqual(con.execute("SELECT count(*) FROM pages WHERE doc_id='doc-a'").fetchone()[0], 1)    # what was there stays
        s = json.loads((self.data / 'library-data' / 'summary.json').read_text())
        self.assertEqual((s['resources'], s['pdfs'], s['pdf_pages']), (2, 2, 4))
        pack = json.loads((self.data / 'pack.json').read_text())
        self.assertEqual([a['name'] for a in pack['add_ons']], ['nl-test'])
        self.assertEqual(pack['add_ons'][0]['ids'], ['nl-test-kit'])
        self.assertEqual(pack['counts']['pdf'], 2)

    def test_manifest_still_matches_so_repair_finds_nothing_wrong(self):
        self.assertEqual(manifest_problems(self.data), [])
        merge.add(self.data, self.addon)
        self.assertEqual(manifest_problems(self.data), [])
        listed = (self.data / 'pack-manifest.tsv').read_text(encoding='utf-8')
        self.assertIn(self.cat()[1]['path'], listed)

    def test_adding_twice_changes_nothing(self):
        merge.add(self.data, self.addon)
        first = (self.data / 'library-data' / 'catalog.json').read_bytes()
        merge.add(self.data, self.addon)
        self.assertEqual(first, (self.data / 'library-data' / 'catalog.json').read_bytes())
        con = sqlite3.connect(self.data / 'library-data' / 'search.sqlite')
        self.assertEqual(con.execute('SELECT count(*) FROM pages').fetchone()[0], 3)
        self.assertEqual(len(json.loads((self.data / 'pack.json').read_text())['add_ons']), 1)
        self.assertEqual(manifest_problems(self.data), [])

    def test_add_from_a_zip(self):
        z = Path(self.tmp.name) / 'a.zip'
        build.zip_addon(self.addon, z)
        merge.add(self.data, z)
        self.assertEqual([r['id'] for r in self.cat()], ['doc-a', 'nl-test-kit'])
        self.assertEqual(manifest_problems(self.data), [])

    def test_remove_puts_it_back(self):
        before = {rel: (self.data / rel).read_bytes() for rel in ('library-data/documents/a.pdf', 'library-data/text/doc-a.txt')}
        merge.add(self.data, self.addon)
        rec = self.cat()[1]
        merge.remove(self.data, 'nl-test')
        self.assertEqual([r['id'] for r in self.cat()], ['doc-a'])
        self.assertFalse((self.data / 'library-data' / rec['path']).exists())
        self.assertFalse((self.data / 'library-data' / rec['text_path']).exists())
        con = sqlite3.connect(self.data / 'library-data' / 'search.sqlite')
        self.assertEqual(con.execute('SELECT count(*) FROM pages').fetchone()[0], 1)
        s = json.loads((self.data / 'library-data' / 'summary.json').read_text())
        self.assertEqual((s['resources'], s['pdf_pages']), (1, 2))
        pack = json.loads((self.data / 'pack.json').read_text())
        self.assertEqual((pack['add_ons'], pack['counts']['pdf']), ([], 1))
        self.assertEqual(manifest_problems(self.data), [])
        for rel, b in before.items():
            self.assertEqual((self.data / rel).read_bytes(), b)

    def test_an_id_the_library_already_has_is_not_overwritten(self):
        cat = self.cat()
        cat[0]['id'] = 'nl-test-kit'
        (self.data / 'library-data' / 'catalog.json').write_text(json.dumps(cat, indent=2), encoding='utf-8')
        with self.assertRaises(merge.Refused):
            merge.add(self.data, self.addon)

    def addon_records(self):
        return json.loads((self.addon / 'library-data' / 'catalog.json').read_text(encoding='utf-8'))

    def test_a_file_the_library_already_has_is_not_overwritten(self):
        """A record of the library's own that names the add-on's file path: refused, and the library's file is left as it was."""
        theirs = self.addon_records()[0]['path']
        cat = self.cat()
        cat[0]['path'] = theirs
        (self.data / 'library-data' / 'catalog.json').write_text(json.dumps(cat, indent=2), encoding='utf-8')
        mine = self.data / 'library-data' / theirs
        mine.parent.mkdir(parents=True, exist_ok=True)
        mine.write_bytes(b'%PDF-1.4 the library own')
        with self.assertRaises(merge.Refused):
            merge.add(self.data, self.addon)
        self.assertEqual(mine.read_bytes(), b'%PDF-1.4 the library own')

    def test_a_stray_file_in_the_way_is_not_overwritten(self):
        theirs = self.data / 'library-data' / self.addon_records()[0]['text_path']
        theirs.parent.mkdir(parents=True, exist_ok=True)
        theirs.write_text('somebody else', encoding='utf-8')
        with self.assertRaises(merge.Refused):
            merge.add(self.data, self.addon)
        self.assertEqual(theirs.read_text(encoding='utf-8'), 'somebody else')

    def test_a_refused_add_writes_nothing(self):
        """A search index the add-on's pages do not fit: refused before any file is copied."""
        db = self.data / 'library-data' / 'search.sqlite'
        db.unlink()
        con = sqlite3.connect(db)
        con.execute('CREATE VIRTUAL TABLE pages USING fts5(doc_id UNINDEXED, body)')
        con.commit()
        con.close()
        before = sorted(p.relative_to(self.data).as_posix() for p in self.data.rglob('*') if p.is_file())
        with self.assertRaises(merge.Refused):
            merge.add(self.data, self.addon)
        after = sorted(p.relative_to(self.data).as_posix() for p in self.data.rglob('*') if p.is_file())
        self.assertEqual(after, before)

    def test_remove_keeps_a_file_another_record_names(self):
        merge.add(self.data, self.addon)
        theirs = self.addon_records()[0]
        cat = self.cat()
        cat.append({**cat[0], 'id': 'doc-b', 'path': theirs['path'], 'text_path': theirs['text_path']})
        (self.data / 'library-data' / 'catalog.json').write_text(json.dumps(cat, indent=2), encoding='utf-8')
        merge.remove(self.data, json.loads((self.addon / 'pack.json').read_text())['name'])
        self.assertTrue((self.data / 'library-data' / theirs['path']).is_file())
        self.assertTrue((self.data / 'library-data' / theirs['text_path']).is_file())

    def test_not_a_library_is_refused(self):
        with self.assertRaises(merge.Refused):
            merge.add(Path(self.tmp.name) / 'empty', self.addon)

    def test_a_zip_with_a_file_outside_the_add_on_is_refused(self):
        z = Path(self.tmp.name) / 'bad.zip'
        with zipfile.ZipFile(z, 'w') as zf:
            zf.writestr('LastbookData/library-data/catalog.json', '[]')
            zf.writestr('LastbookData/derived/geo/national.sqlite', 'x')
        with self.assertRaises(merge.Refused):
            merge.add(self.data, z)
        self.assertEqual([r['id'] for r in self.cat()], ['doc-a'])

    def test_a_zip_that_climbs_out_is_refused(self):
        z = Path(self.tmp.name) / 'climb.zip'
        with zipfile.ZipFile(z, 'w') as zf:
            zf.writestr('LastbookData/library-data/documents/../../../evil.txt', 'x')
        with self.assertRaises(merge.Refused):
            merge.add(self.data, z)

    def test_command_line(self):
        tool = ROOT / 'packaging' / 'pack_merge.py'
        r = subprocess.run([sys.executable, '-I', '-B', str(tool), 'add', '--data', str(self.data), str(self.addon)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([x['id'] for x in self.cat()], ['doc-a', 'nl-test-kit'])
        r = subprocess.run([sys.executable, '-I', '-B', str(tool), 'remove', '--data', str(self.data), 'nl-test'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([x['id'] for x in self.cat()], ['doc-a'])


class GuidesHideWithoutTheirDocuments(unittest.TestCase):
    def setUp(self):
        global server
        import server
        self.server = server

    def resolved(self, topics, ids):
        with mock.patch.object(self.server, 'topics', lambda: topics), \
                mock.patch.object(self.server, 'catalog', lambda: {'by_id': {i: {'id': i, 'kind': 'pdf', 'title': i, 'path': i, 'publisher': 'p', 'collection': 'c'} for i in ids}}), \
                mock.patch.object(self.server, 'zim_names', lambda: []):
            return self.server.topics_resolved()

    def test_a_guide_that_needs_a_document_shows_only_with_it(self):
        nl = {'id': 'nl-x', 'mode': 'now', 'title': 'X', 'needs_doc': 'nl-doc', 'choices': [{'id': 'c', 'label': 'l', 'read': [{'doc': 'nl-doc', 'page': 1, 'label': 'a'}]}]}
        us = {'id': 'us-x', 'mode': 'now', 'title': 'Y', 'choices': [{'id': 'c', 'label': 'l', 'read': [{'doc': 'other', 'page': 1, 'label': 'a'}]}]}
        self.assertEqual([t['id'] for t in self.resolved([nl, us], {'other'})], ['us-x'])
        self.assertEqual([t['id'] for t in self.resolved([nl, us], {'other', 'nl-doc'})], ['nl-x', 'us-x'])

    def test_netherlands_government_is_government_guidance(self):
        r = {'publisher': 'Government of the Netherlands (NCTV)', 'collection': 'Netherlands preparedness', 'category': 'disaster-response'}
        self.assertEqual(self.server.trust(r)[0], 'Government guidance')
        self.assertEqual(self.server.trust({'publisher': 'Someone', 'collection': 'X', 'category': 'y'})[0], 'Reference')


# (document, page) -> words the guides' notes rely on, each of which must be on that page of the text edition
CHECKS = {
    ('nl-denkvooruit-kit', 1): ['whistle', 'cash', 'spare keys', 'keys, ID and cash'],
    ('nl-denkvooruit-booklet', 7): ['on their own', 'everywhere at once'],
    ('nl-denkvooruit-booklet', 8): ['longer than 72 hours', '112 emergency number', 'NL-Alert', '+8 hours'],
    ('nl-denkvooruit-booklet', 9): ['+48 hours', 'emergency radio', '+72 hours', 'petrol pumps'],
    ('nl-denkvooruit-booklet', 12): ['every six months', 'suddenly have to leave', 'bag ready'],
    ('nl-denkvooruit-booklet', 13): ['3 litres', 'power bank', 'cash', 'whistle', 'tampons'],
    ('nl-denkvooruit-booklet', 14): ['lift', 'medical equipment', 'internet is down'],
    ('nl-denkvooruit-booklet', 15): ['photo or make a copy', 'handy place'],
    ('nl-denkvooruit-booklet', 16): ['neighbours', 'start the conversation'],
    ('nl-denkvooruit-booklet', 17): ['anxious', 'small, manageable steps'],
    ('nl-denkvooruit-booklet', 18): ['need help preparing', 'what can we do to help them'],
    ('nl-denkvooruit-booklet', 21): ['flashlight', 'non-perishable', 'radio'],
    ('nl-denkvooruit-booklet', 22): ['3 litres', 'power bank', 'NL-Alerts', 'reliable sources'],
    ('nl-denkvooruit-booklet', 23): ['central place', 'neighbours', 'meet family'],
    ('nl-denkvooruit-booklet', 25): ['floods in limburg', 'towels'],
    ('nl-denkvooruit-booklet', 27): ['emergency support office', 'run out of food', 'paper map', 'nl-alert, the warning siren'],
    ('nl-denkvooruit-booklet', 29): ['0900 8844', '1400', 'siren', 'close windows', 'frequency', 'Google Play'],
    ('nl-denkvooruit-booklet', 30): ['WhatsApp', 'Red Cross', 'safety region'],
    ('nl-denkvooruit-booklet', 31): ['six months', 'paper copy', 'expiry date'],
    ('nl-denkvooruit-plan', 1): ['who lives here', 'special assistance', 'who can help'],
    ('nl-denkvooruit-plan', 2): ['meeting place', 'mhz', 'emergency contacts', 'normal way out'],
    ('nl-denkvooruit-plan', 3): ['0900-8844', '1400', 'out-of-hours'],
    ('nl-denkvooruit-pages', 1): ['first Monday in June and December', 'overloaded', 'incident near you'],
    ('nl-denkvooruit-pages', 2): ['first Monday', 'close windows', 'there is danger'],
    ('nl-denkvooruit-pages', 3): ['DAB+', 'FM', 'battery-operated radio'],
    ('nl-denkvooruit-pages', 4): ['Radio Noord', '97.5', 'Roermond', '100.3'],
    ('nl-denkvooruit-pages', 5): ['25 safety regions', 'Zuid-Limburg', 'Amsterdam-Amstelland'],
    ('nl-denkvooruit-pages', 6): ['skylight', 'gas valve', 'overstroomik', 'dry', 'neighbours', 'animals'],
    ('nl-denkvooruit-pages', 7): ['0800-9009', 'do not call 112', 'unplug', 'power bank', 'smallest spaces'],
    ('nl-denkvooruit-pages', 8): ['24 hours', '3 minutes', 'main tap', 'bucket', 'jerry can', '72 hours', '3 litres'],
    ('nl-denkvooruit-pages', 9): ['code red', '0900-0904', 'life-threatening', 'where you are going'],
}
NL_TOPICS = sorted((ROOT / 'content' / 'topics').glob('nl-*.json'))
SOURCES = ROOT / 'content' / 'nl-documents'


@unittest.skipUnless(SOURCES.is_dir(), 'no content/nl-documents yet')
class RealDocuments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.addon = Path(cls.tmp.name) / 'addon'
        cls.info = build.build(cls.addon, SOURCES, built='2026-11-17')
        cls.cat = {r['id']: r for r in json.loads((cls.addon / 'library-data' / 'catalog.json').read_text(encoding='utf-8'))}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_documents(self):
        self.assertEqual(set(self.cat), {'nl-denkvooruit-booklet', 'nl-denkvooruit-kit', 'nl-denkvooruit-plan', 'nl-denkvooruit-pages'})
        self.assertEqual(self.cat['nl-denkvooruit-booklet']['pages'], 32)
        self.assertEqual(self.cat['nl-denkvooruit-plan']['pages'], 3)
        self.assertEqual(self.cat['nl-denkvooruit-kit']['pages'], 1)
        for r in self.cat.values():
            self.assertTrue(r['license'].startswith('CC0 1.0'), r['id'])
            self.assertIn('creativecommons.org/publicdomain/zero/1.0', r['license_url'])
            self.assertTrue(r['source_url'].startswith('https://english.denkvooruit.nl/'), r['id'])
            self.assertEqual(r['publisher'], 'Government of the Netherlands (Denk vooruit, NCTV)')

    def test_every_page_has_words_on_it(self):
        for r in self.cat.values():
            pages = (self.addon / 'library-data' / r['text_path']).read_text(encoding='utf-8').split('\n\f\n')
            self.assertEqual(len(pages), r['pages'], r['id'])
            for n, p in enumerate(pages, 1):
                self.assertGreater(len(p.split()), 5, f"{r['id']} page {n}")

    def test_no_document_carries_an_image(self):
        for r in self.cat.values():
            self.assertNotIn(b'/Image', (self.addon / 'library-data' / r['path']).read_bytes(), r['id'])


@unittest.skipUnless(NL_TOPICS, 'no Dutch guides yet')
class DutchGuides(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.data = made_up_library(cls.tmp.name)
        addon = Path(cls.tmp.name) / 'addon'
        build.build(addon, SOURCES, built='2026-11-17')
        merge.add(cls.data, addon)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_guides_pass_the_validator_against_a_library_with_the_documents(self):
        r = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'tools' / 'validate_topics.py'), '--data', str(self.data)] + [str(f) for f in NL_TOPICS],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('ERRORS 0', r.stdout)

    def test_every_guide_waits_for_the_documents_and_cites_only_them(self):
        ids = {r['id'] for r in json.loads((self.data / 'library-data' / 'catalog.json').read_text(encoding='utf-8')) if r['id'].startswith('nl-')}
        for f in NL_TOPICS:
            t = json.loads(f.read_text(encoding='utf-8'))
            self.assertIn(t['needs_doc'], ids, f.name)
            self.assertEqual(t['mode'], 'now')
            cited = set()

            def walk(o):
                if isinstance(o, dict):
                    if 'doc' in o:
                        cited.add(o['doc'])
                    for v in o.values():
                        walk(v)
                elif isinstance(o, list):
                    for v in o:
                        walk(v)
            walk(t)
            self.assertTrue(cited, f.name)
            self.assertLessEqual(cited, ids, f.name)

    def test_what_a_note_says_is_on_the_page_it_cites(self):
        """Every page a guide cites has an entry in CHECKS (words the guide's note relies on), and each is on that page."""
        lib = self.data / 'library-data'
        cat = {r['id']: r for r in json.loads((lib / 'catalog.json').read_text(encoding='utf-8'))}

        def items(o):
            if isinstance(o, dict):
                if o.get('doc') and o.get('page'):
                    yield o
                for v in o.values():
                    yield from items(v)
            elif isinstance(o, list):
                for v in o:
                    yield from items(v)
        cited = set()
        for f in NL_TOPICS:
            for i in items(json.loads(f.read_text(encoding='utf-8'))):
                cited.add((i['doc'], i['page']))
        self.assertEqual(sorted(cited - set(CHECKS)), [], 'cited pages that CHECKS does not cover')
        for (doc, page), words in CHECKS.items():
            pages = (lib / cat[doc]['text_path']).read_text(encoding='utf-8').split('\n\f\n')
            text = ' '.join(pages[page - 1].split()).lower()
            for word in words:
                self.assertIn(word.lower(), text, f'{doc} page {page}: {word}')


if __name__ == '__main__':
    unittest.main()
