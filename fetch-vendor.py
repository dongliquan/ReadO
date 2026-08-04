"""
Fetch the 3rd-party assets ReadO bundles, into ./vendor.

ReadO must run with no network access, so Monaco / marked / the webfonts are
served from /vendor instead of a CDN. Those files are not committed (~15 MB),
so run this once after cloning and before build.bat.

    python fetch-vendor.py [--force]

Stdlib only - no pip install needed.
"""
import io
import os
import shutil
import sys
import tarfile
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(ROOT, "vendor")

MONACO_VERSION = "0.45.0"
MARKED_VERSION = "12.0.0"
PRETENDARD_TAG = "v1.3.9"

NPM = "https://registry.npmjs.org"
JSD = "https://cdn.jsdelivr.net/gh"

FONTS = {
    "PretendardVariable.woff2":
        f"{JSD}/orioncactus/pretendard@{PRETENDARD_TAG}"
        "/packages/pretendard/dist/web/variable/woff2/PretendardVariable.woff2",
    "d2coding-subset.woff2":
        f"{JSD}/wan2land/d2coding/fonts/d2coding-subset.woff2",
    "d2coding-bold-subset.woff2":
        f"{JSD}/wan2land/d2coding/fonts/d2coding-bold-subset.woff2",
}


def get(url):
    print(f"  GET {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "reado-fetch-vendor"})
    with urllib.request.urlopen(req, timeout=120) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status} for {url}")
        return r.read()


def extract_one_from_tgz(blob, member, dest_file):
    """Copy a single named file out of an npm tarball to dest_file."""
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        src = tf.extractfile(member)
        if src is None:
            raise RuntimeError(f"{member} not found in archive")
        os.makedirs(os.path.dirname(dest_file), exist_ok=True)
        with open(dest_file, "wb") as f:
            shutil.copyfileobj(src, f)


def extract_from_tgz(blob, members_prefix, dest):
    """Copy every file under members_prefix (a directory) out of a tarball into dest."""
    count = 0
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for m in tf.getmembers():
            if not m.isfile() or not m.name.startswith(members_prefix):
                continue
            rel = m.name[len(members_prefix):].lstrip("/")
            out = os.path.join(dest, rel.replace("/", os.sep))
            # tarball paths are vendor-controlled, but verify anyway
            if not os.path.abspath(out).startswith(os.path.abspath(dest)):
                raise RuntimeError(f"unsafe path in archive: {m.name}")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            src = tf.extractfile(m)
            if src is None:
                continue
            with open(out, "wb") as f:
                shutil.copyfileobj(src, f)
            count += 1
    return count


def main():
    force = "--force" in sys.argv
    loader = os.path.join(VENDOR, "monaco", "vs", "loader.js")
    if os.path.exists(loader) and not force:
        print("vendor/ already populated - nothing to do (use --force to refetch)")
        return 0

    if force and os.path.isdir(VENDOR):
        # keep fonts.css: it is source, not a download
        for name in ("monaco", "fonts", "marked.min.js"):
            p = os.path.join(VENDOR, name)
            shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else (
                os.path.exists(p) and os.remove(p))

    os.makedirs(os.path.join(VENDOR, "fonts"), exist_ok=True)

    print(f"== monaco-editor {MONACO_VERSION} ==")
    blob = get(f"{NPM}/monaco-editor/-/monaco-editor-{MONACO_VERSION}.tgz")
    n = extract_from_tgz(blob, "package/min/vs", os.path.join(VENDOR, "monaco", "vs"))
    print(f"  -> {n} files")

    print(f"== marked {MARKED_VERSION} ==")
    blob = get(f"{NPM}/marked/-/marked-{MARKED_VERSION}.tgz")
    extract_one_from_tgz(blob, "package/marked.min.js",
                         os.path.join(VENDOR, "marked.min.js"))
    print("  -> marked.min.js")

    print("== webfonts ==")
    for name, url in FONTS.items():
        data = get(url)
        with open(os.path.join(VENDOR, "fonts", name), "wb") as f:
            f.write(data)
        print(f"  -> fonts/{name} ({len(data) // 1024} KB)")

    if not os.path.exists(os.path.join(VENDOR, "fonts.css")):
        print("[warn] vendor/fonts.css is missing - it is source and should be committed")

    total = sum(
        os.path.getsize(os.path.join(dp, f))
        for dp, _, fs in os.walk(VENDOR) for f in fs
    )
    print(f"\ndone: vendor/ is {total / 1048576:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
