"""Building heights from 3D BAG (tools/fetch_3dbag.py): the id, the height rule, the table, the resumable download."""
import http.server
import shutil
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from tools import tests  # noqa: F401  (puts tools/ on the path)
import fetch_3dbag


def make_dump(path):
    """A tiny stand-in for 3dbag_nl.gpkg: the pand layer (ground level) and the lod13_2d layer (roof heights, one row per part)."""
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE pand(fid INTEGER PRIMARY KEY, identificatie TEXT, b3_h_maaiveld REAL)')
    db.execute('CREATE TABLE lod13_2d(fid INTEGER PRIMARY KEY, identificatie TEXT, b3_pand_deel_id INT, b3_h_70p REAL)')
    db.executemany('INSERT INTO pand(identificatie, b3_h_maaiveld) VALUES (?,?)', [
        ('NL.IMBAG.Pand.0363100012345678', -0.5),     # Amsterdam: ground at -0.5 m NAP
        ('NL.IMBAG.Pand.0003100000117485', 10.0),
        ('NL.IMBAG.Pand.0003100000117487', 3.0),
        ('NL.IMBAG.Pand.0003100000117489', None),     # no ground level
        ('NL.IMBAG.Pand.0003100000117491', 1.0)])
    db.executemany('INSERT INTO lod13_2d(identificatie, b3_pand_deel_id, b3_h_70p) VALUES (?,?,?)', [
        ('NL.IMBAG.Pand.0363100012345678', 1, 19.5),  # 20.0 m above ground
        ('NL.IMBAG.Pand.0003100000117485', 1, 14.04),  # a part of 4.04 m ...
        ('NL.IMBAG.Pand.0003100000117485', 2, 16.74),  # ... and a taller part of 6.74 m: the tallest part counts
        ('NL.IMBAG.Pand.0003100000117487', 1, 3.4),   # 0.4 m: not a building height
        ('NL.IMBAG.Pand.0003100000117489', 1, 8.0),
        ('NL.IMBAG.Pand.0003100000117491', 1, None)])
    db.commit()
    db.close()


class Heights(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pand_number(self):
        self.assertEqual(fetch_3dbag.pand_number('NL.IMBAG.Pand.0363100012345678'), 363100012345678)
        self.assertEqual(fetch_3dbag.pand_number('0003100000117485'), 3100000117485)     # BAG light writes the bare 16 digits
        self.assertIsNone(fetch_3dbag.pand_number('NL.IMBAG.Pand.'))
        self.assertIsNone(fetch_3dbag.pand_number(None))
        self.assertIsNone(fetch_3dbag.pand_number('abc'))

    def test_height_dm(self):
        self.assertEqual(fetch_3dbag.height_dm(19.5, -0.5), 200)
        self.assertEqual(fetch_3dbag.height_dm(6.74 + 10, 10.0), 67)
        self.assertEqual(fetch_3dbag.height_dm(None, 1.0), 0)
        self.assertEqual(fetch_3dbag.height_dm(5.0, None), 0)
        self.assertEqual(fetch_3dbag.height_dm(float('nan'), 1.0), 0)
        self.assertEqual(fetch_3dbag.height_dm(3.4, 3.0), 0)          # under a metre: a slab, not a building
        self.assertEqual(fetch_3dbag.height_dm(2.0, 3.0), 0)          # below ground
        self.assertEqual(fetch_3dbag.height_dm(900.0, 0.0), 3000)     # nothing in the Netherlands is over 300 m

    def test_build_heights(self):
        dump = self.tmp / 'dump.gpkg'
        make_dump(dump)
        out = self.tmp / 'heights.sqlite'
        counts = fetch_3dbag.build_heights(dump, out)
        db = sqlite3.connect(out)
        self.assertEqual(dict(db.execute('SELECT pand, dm FROM height')), {363100012345678: 200, 3100000117485: 67})
        self.assertEqual(counts, {'buildings': 5, 'with_height': 2})
        meta = dict(db.execute('SELECT key, value FROM meta'))
        self.assertEqual((meta['buildings'], meta['with_height']), ('5', '2'))
        self.assertIn('CC BY 4.0', meta['source'])
        db.close()

    def test_lookup(self):
        dump = self.tmp / 'dump.gpkg'
        make_dump(dump)
        out = self.tmp / 'heights.sqlite'
        fetch_3dbag.build_heights(dump, out)
        h = fetch_3dbag.Heights(out)
        self.assertEqual(h.get('0363100012345678'), 200)
        self.assertEqual(h.get('0003100000117485'), 67)
        self.assertEqual(h.get('0003100000117487'), 0)
        self.assertEqual(h.get('9999999999999999'), 0)
        self.assertEqual(h.get(None), 0)
        h.close()


class Download(unittest.TestCase):
    def serve(self, body):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                rng = self.headers.get('Range')
                start = int(rng.split('=')[1].split('-')[0]) if rng else 0
                if start >= len(body) and rng:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{len(body)}')
                    self.end_headers()
                    return
                self.send_response(206 if rng else 200)
                self.send_header('Content-Length', str(len(body) - start))
                if rng:
                    self.send_header('Content-Range', f'bytes {start}-{len(body) - 1}/{len(body)}')
                self.end_headers()
                self.wfile.write(body[start:])

        srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return tmp, f'http://127.0.0.1:{srv.server_port}/f.bin'

    def test_a_part_longer_than_the_file_is_fetched_again(self):
        """A 416 means the .part reaches the end, or past it: only a .part of exactly the file's size counts as finished."""
        body = bytes(range(256)) * 100
        tmp, url = self.serve(body)
        (tmp / 'f.bin.part').write_bytes(b'x' * (len(body) + 500))
        self.assertEqual(fetch_3dbag.download(url, tmp / 'f.bin').read_bytes(), body)

    def test_a_complete_part_is_kept(self):
        body = bytes(range(256)) * 100
        tmp, url = self.serve(body)
        (tmp / 'f.bin.part').write_bytes(body)
        self.assertEqual(fetch_3dbag.download(url, tmp / 'f.bin').read_bytes(), body)

    def test_a_short_download_is_not_called_finished(self):
        body = bytes(range(256)) * 100
        tmp, url = self.serve(body)
        real = fetch_3dbag.urllib.request.urlopen

        class Short:
            def __init__(self, resp):
                self.resp, self.status, self.headers = resp, resp.status, resp.headers
            def read(self, n):
                return self.resp.read(min(n, 1000)) if not getattr(self, 'done', False) else b''
            def __enter__(self):
                return self
            def __exit__(self, *a):
                self.resp.close()
        calls = []

        def cut(req, timeout=60):
            r = real(req, timeout=timeout)
            calls.append(1)
            if len(calls) == 1:
                s = Short(r)
                orig = s.read
                def read(n, s=s, orig=orig):
                    b = orig(n)
                    s.done = True
                    return b
                s.read = read
                return s
            return r
        fetch_3dbag.urllib.request.urlopen = cut
        self.addCleanup(setattr, fetch_3dbag.urllib.request, 'urlopen', real)
        with self.assertRaises(OSError):
            fetch_3dbag.download(url, tmp / 'f.bin')
        self.assertFalse((tmp / 'f.bin').exists())
        self.assertEqual(fetch_3dbag.download(url, tmp / 'f.bin').read_bytes(), body)       # the next run resumes and completes

    def test_resumes(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        body = bytes(range(256)) * 400
        (tmp / 'www').mkdir()
        (tmp / 'www' / 'f.bin').write_bytes(body)

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=str(tmp / 'www'), **k)

            def log_message(self, *a):
                pass

            def do_GET(self):
                rng = self.headers.get('Range')
                if not rng:
                    return super().do_GET()
                start = int(rng.split('=')[1].split('-')[0])
                if start >= len(body):
                    self.send_response(416); self.end_headers(); return
                self.send_response(206)
                self.send_header('Content-Length', str(len(body) - start))
                self.send_header('Content-Range', f'bytes {start}-{len(body) - 1}/{len(body)}')
                self.end_headers()
                self.wfile.write(body[start:])

        srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        url = f'http://127.0.0.1:{srv.server_port}/f.bin'
        dest = tmp / 'f.bin'
        (tmp / 'f.bin.part').write_bytes(body[:3000])                       # an interrupted earlier run
        fetch_3dbag.download(url, dest)
        self.assertEqual(dest.read_bytes(), body)
        self.assertFalse((tmp / 'f.bin.part').exists())
        fetch_3dbag.download(url, dest)                                      # already there: left alone
        self.assertEqual(dest.read_bytes(), body)


if __name__ == '__main__':
    unittest.main()
