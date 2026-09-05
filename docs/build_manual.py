#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""build_manual.py -- render docs/USER_MANUAL.md to USER_MANUAL.html and .pdf.

    python docs/build_manual.py

The Markdown is the source of truth; the built HTML (and PDF, when the
tools are present) are committed so readers need no tooling of their own.
Uses pandoc for the HTML and pandoc + a TeX engine for the PDF when they are
on PATH; otherwise falls back to a small stdlib-only Markdown-to-HTML renderer
for the HTML and says plainly that the PDF was skipped. Never raises just
because a tool is missing -- always exits 0.

The PDF is byte-reproducible: a rebuild of an unchanged manual leaves the
tree clean. `SOURCE_DATE_EPOCH` is derived from CITATION.cff's
`date-released` and handed to pandoc and the engine; lualatex is preferred
because xdvipdfmx draws its font subset tags at random on every run (TeX
Live 2026, measured), so a xelatex PDF can never be identical. On
2026-09-05 a rebuild dirtied docs/USER_MANUAL.pdf, which is how this
paragraph came to be written.
"""
from __future__ import annotations

import argparse
import datetime
import html
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_SRC = HERE / "USER_MANUAL.md"

CSS = """body{font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;max-width:860px;
margin:2rem auto;padding:0 1rem;color:#22221f;background:#faf7f0}
h1{font-size:1.6rem;border-bottom:1px solid #999;padding-bottom:.2rem;margin-top:2rem}
h2{font-size:1.25rem;margin-top:1.6rem}h3{font-size:1.05rem;margin-top:1.2rem}
table{border-collapse:collapse;width:100%;font-size:.9rem}
th,td{border:1px solid #bbb;padding:.3rem .5rem;text-align:left;vertical-align:top}th{background:#eeebe2}
pre,code{font-family:ui-monospace,Consolas,monospace;font-size:.86rem}
pre{background:#eeebe2;padding:.6rem;overflow-x:auto}
@media(prefers-color-scheme:dark){body{color:#e9e6dc;background:#14140f}th,pre{background:#201e17}
a{color:#8ab4f8}}"""


def source_date_epoch(root: Path) -> str:
    """Seconds since the epoch of CITATION.cff's `date-released` (UTC
    midnight), so every build of one release stamps the same date. Falls
    back to a fixed epoch rather than to the clock."""
    try:
        text = (root / "CITATION.cff").read_text(encoding="utf-8")
        m = re.search(r"^date-released:\s*(\d{4})-(\d{2})-(\d{2})", text, re.M)
        if m:
            d = datetime.datetime(int(m.group(1)), int(m.group(2)),
                                  int(m.group(3)), tzinfo=datetime.timezone.utc)
            return str(int(d.timestamp()))
    except OSError:
        pass
    return "0"


def _run(cmd, cwd, env=None) -> bool:
    try:
        return subprocess.run(cmd, cwd=str(cwd), capture_output=True,
                               timeout=600, env=env).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _inline(text: str) -> str:
    """Bold, inline code, and links -- applied after HTML-escaping."""
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def _table(lines: list[str]) -> str:
    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    header, _sep, *rows = lines
    out = ["<table>", "<thead><tr>"]
    out += [f"<th>{_inline(c)}</th>" for c in cells(header)]
    out.append("</tr></thead><tbody>")
    for row in rows:
        out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells(row)) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def md_to_html(text: str) -> str:
    """Stdlib-only Markdown -> HTML: headings, paragraphs, fenced code,
    inline code, bold, links, bullet lists, and pipe tables. Enough for
    docs/USER_MANUAL.md; not a general-purpose Markdown implementation.
    """
    lines = text.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    while i < n:
        line = lines[i]

        if line.startswith("```"):
            close_list()
            i += 1
            code_lines = []
            while i < n and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            body = html.escape("\n".join(code_lines), quote=False)
            out.append(f"<pre><code>{body}</code></pre>")
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            close_list()
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue

        if line.strip().startswith("|") and i + 1 < n and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]):
            close_list()
            table_lines = [line]
            i += 1
            while i < n and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            out.append(_table(table_lines))
            continue

        m = re.match(r"^[-*]\s+(.*)$", line)
        if m:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            i += 1
            continue

        if not line.strip():
            close_list()
            i += 1
            continue

        close_list()
        para = [line]
        i += 1
        while i < n and lines[i].strip() and not re.match(r"^(#{1,6})\s|^```|^[-*]\s|^\|", lines[i]):
            para.append(lines[i])
            i += 1
        out.append(f"<p>{_inline(' '.join(para))}</p>")

    close_list()
    return "\n".join(out)


def _fallback_html(text: str) -> str:
    title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "User Manual"
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<title>{html.escape(title)}</title>"
            f"<style>{CSS}</style></head><body>{md_to_html(text)}</body></html>")


def build(src: Path, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    out_html = outdir / (src.stem + ".html")
    out_pdf = outdir / (src.stem + ".pdf")
    text = src.read_text(encoding="utf-8")

    pandoc = shutil.which("pandoc")
    if pandoc:
        css_path = outdir / "_manual.css"
        css_path.write_text(CSS, encoding="utf-8")
        ok = _run([pandoc, str(src), "-s", "--toc", "--css", css_path.name,
                   "--metadata", "pagetitle=acp-cockpit User Manual",
                   "--embed-resources", "-o", str(out_html)], outdir)
        if not ok:  # older pandoc without --embed-resources
            ok = _run([pandoc, str(src), "-s", "--toc", "--css", css_path.name,
                       "--self-contained", "-o", str(out_html)], outdir)
        css_path.unlink(missing_ok=True)
        if ok:
            print(f"wrote {out_html} via pandoc")
        else:
            out_html.write_text(_fallback_html(text), encoding="utf-8")
            print(f"wrote {out_html} via fallback (pandoc invocation failed)")
    else:
        out_html.write_text(_fallback_html(text), encoding="utf-8")
        print(f"wrote {out_html} via fallback (no pandoc)")

    engine = next((e for e in ("lualatex", "xelatex") if shutil.which(e)), None)
    if pandoc and engine:
        env = dict(os.environ)
        env["SOURCE_DATE_EPOCH"] = source_date_epoch(src.resolve().parents[1])
        common = [pandoc, str(src), "--toc", f"--pdf-engine={engine}",
                  "-V", "geometry:margin=22mm", "-V", "colorlinks=true",
                  "-o", str(out_pdf)]
        ok = _run(common[:-2] + ["-V", "mainfont=DejaVu Serif",
                                 "-V", "monofont=DejaVu Sans Mono"] + common[-2:],
                  outdir, env)
        if not ok:  # fonts by family name may be unknown to fontconfig: retry plain
            ok = _run(common, outdir, env)
        if ok:
            print(f"wrote {out_pdf} via {engine} (SOURCE_DATE_EPOCH="
                  f"{env['SOURCE_DATE_EPOCH']})")
        else:
            print(f"PDF build failed (pandoc + {engine}); the HTML and Markdown are complete")
    else:
        print("PDF skipped: pandoc or a TeX engine (lualatex/xelatex) not found")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC,
                         help="source Markdown file (default: docs/USER_MANUAL.md)")
    parser.add_argument("--outdir", type=Path, default=HERE,
                         help="output directory (default: docs/)")
    args = parser.parse_args(argv)
    build(args.src, args.outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
