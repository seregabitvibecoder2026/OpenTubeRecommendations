#!/usr/bin/env python3
"""Check that every installed dependency is under an OSI-approved license.

    .venv/bin/python scripts/check_licenses.py            # check, exit 1 on problems
    .venv/bin/python scripts/check_licenses.py --write    # also regenerate THIRD_PARTY_LICENSES

Reads package metadata (License-Expression, License, classifiers). Packages whose metadata is
ambiguous are listed in OVERRIDES after manual verification of their LICENSE file.
"""
from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# SPDX ids (OSI-approved) we accept.
OSI = {
    "MIT", "MIT-0", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "0BSD", "ISC", "PSF-2.0", "Python-2.0",
    "MPL-2.0", "LGPL-2.1-only", "LGPL-2.1-or-later", "LGPL-3.0-only", "LGPL-3.0-or-later", "GPL-2.0-only",
    "GPL-2.0-or-later", "GPL-3.0-only", "GPL-3.0-or-later", "Unlicense", "Zlib", "EPL-2.0", "AFL-3.0",
    "BSL-1.0", "CC0-1.0", "HPND", "UPL-1.0", "NCSA",
}
# Free-text / classifier spellings -> SPDX
ALIASES = {
    "mit": "MIT", "mit license": "MIT", "the mit license": "MIT", "expat": "MIT",
    "apache 2.0": "Apache-2.0", "apache-2.0": "Apache-2.0", "apache software license": "Apache-2.0",
    "apache license 2.0": "Apache-2.0", "apache license, version 2.0": "Apache-2.0", "apache 2": "Apache-2.0",
    "apache": "Apache-2.0", "bsd": "BSD-3-Clause", "bsd license": "BSD-3-Clause", "new bsd": "BSD-3-Clause",
    "bsd-3-clause": "BSD-3-Clause", "3-clause bsd": "BSD-3-Clause", "modified bsd": "BSD-3-Clause",
    "bsd-2-clause": "BSD-2-Clause", "isc": "ISC", "isc license": "ISC", "isc license (iscl)": "ISC",
    "python software foundation license": "PSF-2.0", "psf": "PSF-2.0", "psf-2.0": "PSF-2.0",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0", "mpl-2.0": "MPL-2.0", "mpl 2.0": "MPL-2.0",
    "the unlicense (unlicense)": "Unlicense", "unlicense": "Unlicense", "public domain": "Unlicense",
    "gnu lesser general public license v3 (lgplv3)": "LGPL-3.0-only",
    "gnu lesser general public license v2 or later (lgplv2+)": "LGPL-2.1-or-later",
    "gnu general public license v3 (gplv3)": "GPL-3.0-only", "zlib/libpng license": "Zlib", "hpnd": "HPND",
    "historical permission notice and disclaimer (hpnd)": "HPND", "0bsd": "0BSD", "cc0 1.0 universal (cc0 1.0) public domain dedication": "CC0-1.0",
    "boost software license 1.0 (bsl-1.0)": "BSL-1.0", "university of illinois/ncsa open source license": "NCSA",
}
# Manually verified packages (metadata missing or confusing). name -> SPDX expression
OVERRIDES = {
    "yt-dlp": "Unlicense",
    "langdetect": "Apache-2.0",
    "pillow": "MIT-CMU",  # HPND variant, OSI-approved (as HPND)
}
# Transitive packages that are allowed despite not being OSI: none by default.
# PyTorch CUDA wheels pull NVIDIA runtime libraries (proprietary, redistributable). They are installed
# ONLY by the optional "embed" extra on explicit user action and never shipped in the release archive.
OPTIONAL_NONFREE_PREFIXES = ("nvidia-", "triton")

HPND_LIKE = {"MIT-CMU"}


def normalize(expr: str) -> list[str]:
    expr = expr.strip()
    parts = re.split(r"\s+(?:OR|AND|or|and)\s+|\s*/\s*|;\s*", expr.strip("() "))
    out = []
    for p in parts:
        p = p.strip("() ").strip()
        if not p:
            continue
        out.append(ALIASES.get(p.lower(), p))
    return out


def license_of(dist: metadata.Distribution) -> tuple[str, str]:
    name = (dist.metadata["Name"] or "").lower()
    if name in OVERRIDES:
        return OVERRIDES[name], "override"
    expr = dist.metadata.get("License-Expression")
    if expr:
        return expr, "License-Expression"
    lic = (dist.metadata.get("License") or "").strip()
    if lic and len(lic) < 100 and lic.upper() != "UNKNOWN":
        return lic, "License"
    cls = [c.split("::")[-1].strip() for c in dist.metadata.get_all("Classifier") or [] if c.startswith("License ::")]
    cls = [c for c in cls if c != "OSI Approved"]
    if cls:
        return " OR ".join(cls), "classifier"
    if lic:
        first = lic.splitlines()[0][:80]
        return first, "License(text)"
    return "UNKNOWN", "-"


def ok(expr: str) -> bool:
    ids = normalize(expr)
    if not ids:
        return False
    if " OR " in expr or " or " in expr:
        return any(i in OSI or i in HPND_LIKE for i in ids)
    return all(i in OSI or i in HPND_LIKE for i in ids)


def main() -> int:
    write = "--write" in sys.argv
    rows, bad, optional = [], [], []
    for d in sorted(metadata.distributions(), key=lambda d: (d.metadata["Name"] or "").lower()):
        name = d.metadata["Name"]
        if not name or name.lower() in ("OpenTubeRecommendations", "pip", "setuptools", "wheel"):
            continue
        expr, src = license_of(d)
        if name.lower().startswith(OPTIONAL_NONFREE_PREFIXES):
            optional.append((name, d.version, expr))
            continue
        rows.append((name, d.version, expr, src))
        if not ok(expr):
            bad.append((name, d.version, expr, src))
    for r in rows:
        print(f"{'OK ' if ok(r[2]) else 'BAD'} {r[0]}=={r[1]}: {r[2]} [{r[3]}]")
    for r in optional:
        print(f"OPT {r[0]}=={r[1]}: {r[2]} (опциональная зависимость PyTorch CUDA, не входит в архив)")
    if write:
        lines = ["Third-party software used by OpenTubeRecommendations (installed by uv from PyPI, not bundled).",
                 "Generated by scripts/check_licenses.py. Vendored: app/static/htmx.min.js — htmx 2.0.4, 0BSD.", ""]
        lines += [f"{n} {v}: {e}" for n, v, e, _ in rows]
        if optional:
            lines += ["", "Optional (installed only by the 'embed' extra on explicit user action; never in the release archive):"]
            lines += [f"{n} {v}: {e}" for n, v, e in optional]
        (ROOT / "THIRD_PARTY_LICENSES").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("THIRD_PARTY_LICENSES written")
    if bad:
        print("\nНе-OSI или неизвестные лицензии:", file=sys.stderr)
        for r in bad:
            print(f"  {r[0]}=={r[1]}: {r[2]} [{r[3]}]", file=sys.stderr)
        return 1
    print(f"\nOK: {len(rows)} пакетов, все лицензии OSI-одобрены")
    return 0


if __name__ == "__main__":
    sys.exit(main())
