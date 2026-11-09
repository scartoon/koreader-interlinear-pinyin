#!/usr/bin/env python3
"""Run a book through the plugin offline and report the unusual readings it
marks (data/special.tsv): how many per chapter, and the most frequent matches
with a sentence of context, to spot false alarms.

    python3 tools/scan_special.py BOOK.epub [--threshold 2500] [--top 40]

Uses the plugin's own Lua code (plugin_runtime.py). Each paragraph is treated
as one page for the once-per-page rule, so counts are close to, not exactly,
what the reader shows.
"""
import argparse
import html
import os
import posixpath
import re
import sys
import zipfile
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plugin_runtime import Plugin  # noqa: E402

BLOCK_RE = re.compile(r"<(?:p|div|h[1-6]|li|br|tr|blockquote)\b[^>]*>", re.I)
TAG_RE = re.compile(r"<[^>]+>")
SENTENCE_END = "。！？；!?;"


def spine(z):
    """[(href, title)] in reading order."""
    container = z.read("META-INF/container.xml").decode("utf-8")
    opf_path = re.search(r'full-path="([^"]+)"', container).group(1)
    opf = z.read(opf_path).decode("utf-8")
    base = posixpath.dirname(opf_path)
    manifest = {m.group(1): m.group(2) for m in re.finditer(
        r'<item\b[^>]*\bid="([^"]+)"[^>]*\bhref="([^"]+)"', opf)}
    manifest.update({m.group(2): m.group(1) for m in re.finditer(
        r'<item\b[^>]*\bhref="([^"]+)"[^>]*\bid="([^"]+)"', opf)})
    out = []
    for idref in re.findall(r'<itemref\b[^>]*\bidref="([^"]+)"', opf):
        href = manifest.get(idref)
        if href:
            out.append(posixpath.normpath(posixpath.join(base, html.unescape(href))))
    return out


def paragraphs(xhtml):
    body = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", xhtml)
    title = re.search(r"(?is)<h[1-3][^>]*>(.*?)</h[1-3]>", body)
    title = html.unescape(TAG_RE.sub("", title.group(1))).strip() if title else ""
    parts = [html.unescape(TAG_RE.sub("", p)).strip() for p in BLOCK_RE.split(body)]
    return title, [p for p in parts if p]


def sentence_around(text, pos):
    start = max((text.rfind(c, 0, pos) for c in SENTENCE_END), default=-1) + 1
    ends = [i for i in (text.find(c, pos) for c in SENTENCE_END) if i >= 0]
    end = min(ends) + 1 if ends else len(text)
    s = text[start:end].strip()
    return s if len(s) <= 80 else text[max(0, pos - 30):pos + 30].strip() + "…"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("book")
    ap.add_argument("--threshold", type=int, default=2500)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--plugin", default=None)
    args = ap.parse_args()
    plugin = Plugin(args.plugin) if args.plugin else Plugin()

    per_chapter = []
    matches = Counter()
    examples = {}
    chars = annotations = 0
    with zipfile.ZipFile(args.book) as z:
        for href in spine(z):
            try:
                title, paras = paragraphs(z.read(href).decode("utf-8", "replace"))
            except KeyError:
                continue
            n = 0
            for para in paras:
                chars += len(para)
                for pos, ch, reading, special, word in plugin.details(para, args.threshold):
                    annotations += 1
                    if not special:
                        continue
                    n += 1
                    key = (word, ch, reading)
                    matches[key] += 1
                    examples.setdefault(key, sentence_around(para, pos))
            if paras:
                per_chapter.append((title or (paras[0][:20] if paras else href), n))

    total = sum(n for _, n in per_chapter)
    print(f"{os.path.basename(args.book)}: {chars:,} characters, {annotations:,} annotations at "
          f"{args.threshold:,}, {total} unusual readings ({total / chars * 1e5:.1f} per 100,000 characters), "
          f"{len(matches)} distinct")
    print()
    print("Per chapter (unusual readings):")
    for title, n in per_chapter:
        print(f"  {n:4d}  {title[:40]}")
    print()
    print(f"Most frequent matches (top {args.top}):")
    for (word, ch, reading), n in matches.most_common(args.top):
        print(f"  {n:4d}  {word}  {ch}={reading}   {examples[(word, ch, reading)]}")


if __name__ == "__main__":
    main()
