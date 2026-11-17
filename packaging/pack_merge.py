#!/usr/bin/env python3
"""Put an add-on (documents added to a library) into a library, or take it out again. Close Lastbook first.

  python3 packaging/pack_merge.py add --data /path/to/LastbookData derived/packs/state-zips/Lastbook-Addon-NL-Preparedness.zip
  python3 packaging/pack_merge.py add --data /path/to/LastbookData derived/nl-guides/addon        # an add-on folder works too
  python3 packaging/pack_merge.py remove --data /path/to/LastbookData nl-preparedness

The work is done by engine/setup/addons.py, which setup also uses when it installs an add-on listed in its manifest; see that
module for what is read, checked and written. Nothing is downloaded and no network is used.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from engine.setup.addons import *               # noqa: E402,F401,F403  (the names the tests and older scripts use)
from engine.setup.addons import Refused, add, remove   # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description='Add an add-on to a Lastbook library, or remove it. Close Lastbook first.')
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('add', help='put an add-on (folder or zip) into the library')
    a.add_argument('addon')
    r = sub.add_parser('remove', help='take an add-on out of the library, by its name')
    r.add_argument('name')
    for p in (a, r):
        p.add_argument('--data', default=os.environ.get('LASTBOOK_DATA'), help='the data folder, the one that holds library-data/ (default: LASTBOOK_DATA)')
    args = ap.parse_args(argv)
    if not args.data:
        ap.error('--data is needed (or set LASTBOOK_DATA)')
    try:
        ids = add(args.data, args.addon) if args.cmd == 'add' else remove(args.data, args.name)
    except Refused as e:
        sys.exit(f'pack_merge: {e}')
    print(f'{"added" if args.cmd == "add" else "removed"} {len(ids)} documents: {", ".join(ids)}')


if __name__ == '__main__':
    main()
