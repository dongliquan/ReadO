"""
Fetch the 3rd-party assets ReadO bundles, into ./vendor.

ReadO must run with no network access, so Monaco / marked / the webfonts are
served from /vendor instead of a CDN, ripgrep (vendor/rg/rg.exe) powers Find in
Files / usages, and Universal Ctags (vendor/ctags/ctags.exe) powers the symbol
index (go to definition, Ctrl+T, outline). Those files are not committed
(~22 MB), so run this once after cloning and before build.bat.

    python fetch-vendor.py [--force]

An existing vendor/ that predates ripgrep or ctags only gets those added.

Stdlib only - no pip install needed.
"""
import io
import os
import shutil
import sys
import hashlib
import tarfile
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(ROOT, "vendor")

MONACO_VERSION = "0.45.0"
MARKED_VERSION = "12.0.0"
PRETENDARD_TAG = "v1.3.9"
RIPGREP_VERSION = "14.1.1"
# sha256 of the release zip, from the .sha256 file published with the release
RIPGREP_SHA256 = "d0f534024c42afd6cb4d38907c25cd2b249b79bbe6cc1dbee8e3e37c2b6e25a1"
RIPGREP_ZIP = (
    "https://github.com/BurntSushi/ripgrep/releases/download/"
    f"{RIPGREP_VERSION}/ripgrep-{RIPGREP_VERSION}-x86_64-pc-windows-msvc.zip"
)

# Universal Ctags Windows build (github.com/universal-ctags/ctags-win32).
# sha256 = the digest GitHub publishes for the release asset.
CTAGS_VERSION = "p6.2.20260920.0"
CTAGS_SHA256 = "0dd2e964e82ec6bed9337c6d0a1d9d29146b3115dbc27682f8e7b62cafd073db"
CTAGS_ZIP = (
    "https://github.com/universal-ctags/ctags-win32/releases/download/"
    f"{CTAGS_VERSION}/ctags-{CTAGS_VERSION}-x64.zip"
)

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


def fetch_ripgrep():
    """vendor/rg/rg.exe (+ license files). Verified against RIPGREP_SHA256."""
    print(f"== ripgrep {RIPGREP_VERSION} ==")
    blob = get(RIPGREP_ZIP)
    digest = hashlib.sha256(blob).hexdigest()
    if digest != RIPGREP_SHA256:
        raise RuntimeError(f"ripgrep checksum mismatch: {digest}")
    dest = os.path.join(VENDOR, "rg")
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for m in zf.namelist():
            name = m.rsplit("/", 1)[-1]
            if name in ("rg.exe", "COPYING", "LICENSE-MIT", "UNLICENSE"):
                with zf.open(m) as src, open(os.path.join(dest, name), "wb") as f:
                    shutil.copyfileobj(src, f)
    print("  -> rg/rg.exe")


def fetch_ctags():
    """vendor/ctags/ctags.exe (+ license files). Verified against CTAGS_SHA256."""
    print(f"== universal-ctags {CTAGS_VERSION} ==")
    blob = get(CTAGS_ZIP)
    digest = hashlib.sha256(blob).hexdigest()
    if digest != CTAGS_SHA256:
        raise RuntimeError(f"ctags checksum mismatch: {digest}")
    dest = os.path.join(VENDOR, "ctags")
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for m in zf.namelist():
            if m == "ctags.exe" or (m.startswith("license/") and not m.endswith("/")):
                name = m.rsplit("/", 1)[-1]
                with zf.open(m) as src, open(os.path.join(dest, name), "wb") as f:
                    shutil.copyfileobj(src, f)
    print("  -> ctags/ctags.exe")


def main():
    force = "--force" in sys.argv
    loader = os.path.join(VENDOR, "monaco", "vs", "loader.js")
    rg = os.path.join(VENDOR, "rg", "rg.exe")
    ctags = os.path.join(VENDOR, "ctags", "ctags.exe")
    if os.path.exists(loader) and not force:
        if os.path.exists(rg) and os.path.exists(ctags):
            print("vendor/ already populated - nothing to do (use --force to refetch)")
        if not os.path.exists(rg):
            fetch_ripgrep()
        if not os.path.exists(ctags):
            fetch_ctags()
        return 0

    if force and os.path.isdir(VENDOR):
        # keep fonts.css: it is source, not a download
        for name in ("monaco", "fonts", "marked.min.js", "rg", "ctags"):
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

    fetch_ripgrep()
    fetch_ctags()

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
