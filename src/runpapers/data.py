"""Fetching a pack's data from its original repository into a local cache, with resume and checksum checks.
Controlled-access data is never fetched automatically; the user gets the access instructions instead."""
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from . import DEFAULT_BASE, ids

UA = f"runpapers/0.2 (+{DEFAULT_BASE})"


def cache_root():
    return Path(os.environ.get("RUNPAPERS_CACHE", "~/.cache/runpapers")).expanduser()


def data_dir(doi):
    return cache_root() / "data" / ids.doi_relpath(doi)


def _digest(path, algo):
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def verified(path, entry):
    """True when the file matches the entry's size and checksum (cached in <file>.ok while the file is unchanged)."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size != int(entry.get("size", -1)):
        return False
    st = path.stat()
    ok = path.with_name(path.name + ".ok")
    algo, want = ("sha256", entry["sha256"]) if entry.get("sha256") else ("md5", entry.get("md5"))
    try:
        rec = json.loads(ok.read_text())
        if rec.get("mtime") == st.st_mtime and rec.get("size") == st.st_size and rec.get(algo) == want:
            return True
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    if not want or _digest(path, algo) != want.lower():
        return False
    ok.write_text(json.dumps({"mtime": st.st_mtime, "size": st.st_size, algo: want}))
    return True


def filename(entry):
    return entry.get("filename") or entry["url"].rstrip("/").rsplit("/", 1)[-1]


def _download(url, dest, size, quiet=False):
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"User-Agent": UA, **({"Range": f"bytes={have}-"} if have else {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        if have and r.status != 206:  # server ignored the range: start over
            have = 0
        mode = "ab" if have else "wb"
        t0, last = time.time(), 0
        with open(part, mode) as f:
            got = have
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
                got += len(b)
                if not quiet and time.time() - last > 2:
                    last = time.time()
                    rate = (got - have) / max(1e-6, last - t0) / 1e6
                    print(f"  {dest.name}: {got / 1e6:.0f}/{size / 1e6:.0f} MB ({rate:.1f} MB/s)", file=sys.stderr)
    os.replace(part, dest)


def fetch(pack, only=None, quiet=False, dest_dir=None, **_ignored):
    """Make requested open data files (or all open files when only is None) present and verified. Returns {id: path} and notes."""
    if isinstance(only, str):
        only = None
    dd = Path(dest_dir) if dest_dir else data_dir(pack.doi)
    dd.mkdir(parents=True, exist_ok=True)
    paths, notes = {}, []
    for e in pack.data:
        if only is not None and e["id"] not in only:
            continue
        if e.get("access") == "controlled":
            notes.append(f"{e['id']}: controlled access. {e.get('access_note', 'Apply to the repository named in source; RunPapers never downloads it.')}")
            continue
        dest = dd / filename(e)
        if not verified(dest, e):
            if not quiet:
                print(f"fetching {e['id']} ({int(e['size']) / 1e6:.0f} MB) from {e.get('source', e['url'])}", file=sys.stderr)
            for attempt in range(3):
                try:
                    _download(e["url"], dest, int(e["size"]), quiet)
                    break
                except OSError as ex:  # network hiccup: resume from the .part file
                    if attempt == 2:
                        raise SystemExit(f"download failed for {e['id']}: {ex}")
                    time.sleep(3 * (attempt + 1))
            if not verified(dest, e):
                bad = dest.with_name(dest.name + ".bad")
                os.replace(dest, bad)
                raise SystemExit(f"{e['id']}: checksum or size mismatch after download (kept as {bad}); "
                                 f"the source file may have changed: report it to the pack maintainers")
        paths[e["id"]] = str(dest)
    return paths, notes
