"""Download the corpus listed in data/manifest.json and verify every file's sha256.

data/ is git-ignored except for the manifest, so a fresh clone has the *list*
of files and their expected hashes but not the files. `make corpus` runs this
script: it downloads whatever is missing, then checks every file, so a
truncated download or a silently changed upstream file fails loudly instead of
skewing every later measurement.

    python scripts/fetch_corpus.py            # download missing files, verify all
    python scripts/fetch_corpus.py --pin      # first time only: record hashes of what was downloaded
"""

import hashlib
import json
import ssl
import sys
import urllib.request
from pathlib import Path

import certifi

REPO = Path(__file__).resolve().parents[1]
# The python.org build of Python on macOS ships without a CA bundle
# (its default cafile, .../etc/openssl/cert.pem, does not exist), so every HTTPS
# request fails with CERTIFICATE_VERIFY_FAILED. certifi's bundle is pinned in
# requirements.txt, which keeps the fix inside the project instead of changing
# the system Python.
TLS = ssl.create_default_context(cafile=certifi.where())
DATA = REPO / "data"
MANIFEST = DATA / "manifest.json"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "rag-assistant-corpus-fetch"})
    with urllib.request.urlopen(request, timeout=120, context=TLS) as response, tmp.open("wb") as out:
        while block := response.read(1 << 20):
            out.write(block)
    # Rename only after the whole body arrived, so an interrupted download never
    # leaves a file that looks complete.
    tmp.replace(dest)


def entries(manifest: dict) -> list[dict]:
    return manifest["documents"] + manifest["auxiliary"]


def main(argv: list[str]) -> int:
    pin = "--pin" in argv
    manifest = json.loads(MANIFEST.read_text())
    problems = []
    for entry in entries(manifest):
        path = DATA / entry["path"]
        if not path.exists():
            print(f"downloading {entry['path']} ← {entry['source_url']}")
            download(entry["source_url"], path)
        actual = sha256_of(path)
        if pin:
            entry["sha256"] = actual
            entry["bytes"] = path.stat().st_size
        elif actual != entry["sha256"]:
            problems.append(f"{entry['path']}: sha256 {actual} != expected {entry['sha256']}")
    if pin:
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"pinned {len(entries(manifest))} hashes in {MANIFEST.relative_to(REPO)}")
        return 0
    if problems:
        print("corpus verification FAILED:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    print(f"corpus OK: {len(entries(manifest))} files verified against data/manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
