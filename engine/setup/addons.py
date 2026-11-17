"""Put an add-on (documents added to a library) into a library, or take it out again: used by setup (engine/setup/api.py, a job item
of kind "addon") and by packaging/pack_merge.py on the command line. From the command line, close Lastbook first.

  python3 packaging/pack_merge.py add --data /path/to/LastbookData derived/nl-guides/Lastbook-Addon-NL-Preparedness.zip
  python3 packaging/pack_merge.py add --data /path/to/LastbookData derived/nl-guides/addon        # an add-on folder works too
  python3 packaging/pack_merge.py remove --data /path/to/LastbookData nl-preparedness

Reads: an add-on, which is laid out as derived/packs/pack-spec.json says ("addons": the layout of a size, with its own catalog.json,
search.sqlite and summary.json, and no map set), as a folder or as a zip with everything under LastbookData/. tools/build_nl_documents.py
makes the Netherlands one. A zip is checked the way setup checks a pack (engine/setup/install.py): relative names only, no links, and
here only the add-on's own files.
Writes, in the library: the add-on's documents and text, its records joined into library-data/catalog.json, its pages inserted into
library-data/search.sqlite, library-data/summary.json recomputed, pack.json (add_ons and counts), and pack-manifest.tsv, so a repair from setup
still finds every file as it should be. `remove` undoes it. Nothing is downloaded and no network is used.
An id or a file the library already has is never overwritten, unless it came from this same add-on (then adding again replaces it).
Everything is checked before anything is written, and an add that fails part way takes out what it had copied. `remove` deletes a
file only when no record left in the catalog names it. Setting up a different library (an upgrade) leaves the add-on behind: add it
again.
Licence: the tool is Lastbook's; each document keeps the licence its catalog record names.
"""
import collections
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

from . import install

CORE = ('library-data/catalog.json', 'library-data/search.sqlite', 'library-data/summary.json')
FILE = re.compile(r'(pack\.json|pack-manifest\.tsv|library-data/(catalog\.json|search\.sqlite|summary\.json)'
                  r'|library-data/documents/[A-Za-z0-9._ -]+(/[A-Za-z0-9._ -]+)*\.(pdf|html|txt)|library-data/text/[A-Za-z0-9._-]+\.txt)')
DIRS = re.compile(r'(library-data(/(documents|text)(/[A-Za-z0-9._ -]+)*)?)?')


class Refused(Exception):
    pass


class _NeverStopped:
    @staticmethod
    def check():
        pass


def allowed(rel, is_dir=False):
    rel = rel.strip('/')
    return bool(DIRS.fullmatch(rel)) if is_dir else bool(FILE.fullmatch(rel))


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while b := f.read(1 << 22):
            h.update(b)
    return h.hexdigest()


def write_atomic(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + '.partial')
    tmp.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))
    os.replace(tmp, path)


def copy_atomic(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + '.partial')
    shutil.copyfile(src, tmp)             # a copy, never a link: the library refuses files with more than one name
    os.replace(tmp, dst)


def library(data):
    data = Path(data)
    if not (data / 'library-data' / 'catalog.json').is_file():
        raise Refused(f'{data} is not a Lastbook library (no library-data/catalog.json). Name the folder that holds library-data/.')
    return data


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        if default is not None:
            return default
        raise Refused(f'{path} is missing')
    except ValueError:
        raise Refused(f'{path} is not readable')


# ---------------------------------------------------------------------------------------------------- the add-on ----
class Staged:
    """An add-on's folder, checked: the folder itself, or a zip unpacked to a folder of its own."""

    def __init__(self, addon):
        self.tmp = None
        addon = Path(addon)
        if addon.is_file():
            self.tmp = tempfile.TemporaryDirectory(prefix='lastbook-addon-')
            try:      # a ceiling on what the zip may unpack to, so a damaged or hostile one cannot fill the disk
                limit = max(256 * 2 ** 20, 8 * addon.stat().st_size)
                lib = install.unpack(addon, self.tmp.name, limit, _NeverStopped, lambda done, total: None, allowed=allowed,
                                     verify=lambda lib: None)
            except install.Refused as e:
                self.close()
                raise Refused(e.message)
            self.root = Path(lib)
        elif addon.is_dir():
            self.root = addon
            for f in addon.rglob('*'):
                rel = f.relative_to(addon).as_posix()
                if f.is_symlink() or (f.is_file() and not allowed(rel)) or (f.is_dir() and not allowed(rel, True)):
                    raise Refused(f'The add-on holds something that is not part of an add-on ({rel[:80]!r}).')
        else:
            raise Refused(f'No add-on at {addon}.')
        try:
            self.pack = read_json(self.root / 'pack.json')
            self.records = read_json(self.root / 'library-data' / 'catalog.json')
            if not (isinstance(self.pack.get('name'), str) and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,60}', self.pack['name'])):
                raise Refused('The add-on has no usable name in its pack.json.')
            if not (isinstance(self.records, list) and self.records and all(isinstance(r, dict) and isinstance(r.get('id'), str) for r in self.records)):
                raise Refused('The add-on has no catalog records.')
            if not (self.root / 'library-data' / 'search.sqlite').is_file():
                raise Refused('The add-on has no search.sqlite.')
            self.files = []
            for r in self.records:
                for key in ('path', 'text_path'):
                    rel = 'library-data/' + str(r.get(key) or '')
                    if not r.get(key) or not allowed(rel) or '..' in Path(rel).parts or not (self.root / rel).is_file():
                        raise Refused(f'The add-on record {r["id"]} names a file it does not hold or may not hold ({r.get(key)!r}).')
                    self.files.append(rel)
                pdf = self.root / 'library-data' / r['path']
                if r.get('sha256') and sha256(pdf) != r['sha256']:
                    raise Refused(f'{r["path"]} does not match its checksum in the add-on.')
        except Refused:
            self.close()
            raise

    def close(self):
        if self.tmp:
            self.tmp.cleanup()
            self.tmp = None


# ------------------------------------------------------------------------------------------------------ the library ----
def summary(records):
    kinds = collections.Counter(r['kind'] for r in records)
    return {'resources': len(records), 'pdfs': kinds['pdf'], 'pdf_pages': sum(r.get('pages') or 0 for r in records if r['kind'] == 'pdf'),
            'web_pages': kinds['html'] + kinds['htm'], 'videos': sum(kinds[k] for k in ('video', 'mp4', 'webm', 'mkv')),
            'collections': kinds['zim'], 'document_bytes': sum(r.get('bytes') or 0 for r in records)}


def refresh_manifest(data, drop=(), add=(), how=''):
    """pack-manifest.tsv after a change: the three shared files at their new size and hash, `drop` rows gone, `add` rows (paths) listed."""
    path = data / 'pack-manifest.tsv'
    if not path.is_file():
        return
    lines = path.read_text(encoding='utf-8').splitlines()
    out, seen = [lines[0]], set()
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = line.split('\t')
        rel = cells[0]
        if rel in drop:
            continue
        if rel in CORE or rel in add:
            cells[1:3] = [str((data / rel).stat().st_size), sha256(data / rel)]
            cells = (cells + [''] * 5)[:5]
            if rel in add:
                cells[3] = how
        out.append('\t'.join(cells))
        seen.add(rel)
    for rel in add:
        if rel not in seen:
            p = data / rel
            out.append(f'{rel}\t{p.stat().st_size}\t{sha256(p)}\t{how}\t')
    write_atomic(path, '\n'.join(out) + '\n')


def refresh_contents(data, drop_ids=(), add=()):
    """pack-contents.tsv (id, kind, title, publisher, source_url, path, bytes), if the library has one."""
    path = data / 'pack-contents.tsv'
    if not path.is_file():
        return
    lines = path.read_text(encoding='utf-8').splitlines()
    out = [lines[0]] + [l for l in lines[1:] if l.strip() and l.split('\t')[0] not in drop_ids]
    for r in add:
        out.append('\t'.join(str(r.get(k, '')) for k in ('id', 'kind', 'title', 'publisher', 'source_url', 'path', 'bytes')).replace('\n', ' '))
    write_atomic(path, '\n'.join(out) + '\n')


def write_catalog(data, records, pack):
    """catalog.json, summary.json and pack.json, for the records the library now has."""
    lib = data / 'library-data'
    write_atomic(lib / 'catalog.json', json.dumps(records, indent=2))
    write_atomic(lib / 'summary.json', json.dumps(summary(records), indent=1))
    pack['counts'] = dict(collections.Counter(r['kind'] for r in records))
    write_atomic(data / 'pack.json', json.dumps(pack, indent=1))


def record_files(records):
    """The library files the records name (path and text_path, as library-data/...)."""
    return {'library-data/' + str(r[key]) for r in records for key in ('path', 'text_path') if r.get(key)}


def add(data, addon):
    """Puts the add-on into the library at data. Returns the ids added. Everything is checked before anything is written: an id,
    or a file, that the library already has and that is not this add-on's is refused, and so is a search index the add-on's pages
    do not fit. A failure while copying or indexing takes out what this add had written."""
    data = library(data)
    staged = Staged(addon)
    try:
        pack = read_json(data / 'pack.json', default={})
        name = staged.pack['name']
        lib = data / 'library-data'
        records = read_json(lib / 'catalog.json')
        earlier = next((a for a in pack.get('add_ons', []) if isinstance(a, dict) and a.get('name') == name), None)
        own_ids = set(earlier['ids']) if earlier else set()
        others = [r for r in records if r.get('id') not in own_ids]
        own_files = record_files([r for r in records if r.get('id') in own_ids])
        clash = sorted(r['id'] for r in staged.records if r['id'] in {o.get('id') for o in others})
        if clash:
            raise Refused(f'The library already has {clash[0]}, and it is not from this add-on. Nothing was changed.')
        named = record_files(others)
        for rel in staged.files:
            if rel in named or ((data / rel).exists() and rel not in own_files):
                raise Refused(f'The library already has a file at {rel}, and it is not from this add-on. Nothing was changed.')
        db = lib / 'search.sqlite'
        con = sqlite3.connect(db)
        try:
            mine = [c[1] for c in con.execute('PRAGMA table_info(pages)')]
        finally:
            con.close()
        if not mine:
            raise Refused('The library has no search index to add to. Nothing was changed.')
        con = sqlite3.connect(f'file:{staged.root / "library-data" / "search.sqlite"}?mode=ro', uri=True)
        try:
            theirs = [c[1] for c in con.execute('PRAGMA table_info(pages)')]
        finally:
            con.close()
        if theirs != mine:
            raise Refused("The add-on's search pages do not fit this library's search index. Nothing was changed.")
        if earlier:
            remove(data, name)                       # adding again replaces: the same files, the new ones
            pack = read_json(data / 'pack.json', default={})
            records = read_json(lib / 'catalog.json')
        ids = [r['id'] for r in staged.records]
        copied = []
        try:
            for rel in staged.files:
                copy_atomic(staged.root / rel, data / rel)
                copied.append(rel)
            con = sqlite3.connect(db)
            try:
                con.execute('ATTACH DATABASE ? AS addon', (str(staged.root.joinpath('library-data', 'search.sqlite').resolve()),))
                con.execute(f'DELETE FROM main.pages WHERE doc_id IN ({",".join("?" * len(ids))})', ids)     # a stop half way through an earlier add
                con.execute(f'INSERT INTO main.pages SELECT * FROM addon.pages WHERE doc_id IN ({",".join("?" * len(ids))})', ids)
                con.commit()
                con.execute('DETACH DATABASE addon')
            finally:
                con.close()
        except (OSError, sqlite3.Error) as e:
            for rel in copied:
                (data / rel).unlink(missing_ok=True)
            try:
                con = sqlite3.connect(db)
                con.execute(f'DELETE FROM pages WHERE doc_id IN ({",".join("?" * len(ids))})', ids)
                con.commit()
                con.close()
            except sqlite3.Error:
                pass
            raise Refused(f'The add-on could not be added ({e}); what was copied was taken out again'
                          + (', and the earlier copy of this add-on had already been removed.' if earlier else '.'))
        pack.setdefault('add_ons', []).append({'name': name, 'ids': ids, 'revision': staged.pack.get('content_revision', '')})
        write_catalog(data, records + staged.records, pack)       # the records last: they name files that are now there
        refresh_manifest(data, add=staged.files, how=f'add-on:{name}')
        refresh_contents(data, add=staged.records)
        return ids
    finally:
        staged.close()


def remove(data, name):
    """Takes the add-on called name out of the library at data. Returns the ids removed. The catalog is written first, so no record
    is left naming a file that is gone; a file another record still names is kept."""
    data = library(data)
    pack = read_json(data / 'pack.json', default={})
    entry = next((a for a in pack.get('add_ons', []) if isinstance(a, dict) and a.get('name') == name), None)
    if not entry:
        raise Refused(f'{name} is not an add-on of this library.')
    lib = data / 'library-data'
    ids = set(entry['ids'])
    records = read_json(lib / 'catalog.json')
    gone = [r for r in records if r['id'] in ids]
    keep = [r for r in records if r['id'] not in ids]
    pack['add_ons'] = [a for a in pack['add_ons'] if a is not entry]
    write_catalog(data, keep, pack)
    con = sqlite3.connect(lib / 'search.sqlite')
    try:
        con.execute(f'DELETE FROM pages WHERE doc_id IN ({",".join("?" * len(ids))})', sorted(ids))
        con.commit()
    finally:
        con.close()
    kept = record_files(keep)
    paths = []
    for rel in sorted(record_files(gone)):
        if allowed(rel) and '..' not in Path(rel).parts and rel not in kept:
            paths.append(rel)
            (data / rel).unlink(missing_ok=True)
    for rel in paths:                                # a folder the add-on made, now empty
        p = (data / rel).parent
        while p != lib and p.is_dir() and not any(p.iterdir()):
            p.rmdir()
            p = p.parent
    refresh_manifest(data, drop=set(paths))
    refresh_contents(data, drop_ids=ids)
    return sorted(ids)
