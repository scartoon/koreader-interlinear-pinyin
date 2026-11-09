#!/usr/bin/env python3
"""Build the plugin's data files from CC-CEDICT, wordfreq and pypinyin.

Outputs (tab-separated UTF-8 text, parsed by the plugin at load time):

  <plugin>/data/chars.tsv   char <TAB> rank <TAB> default reading
                   rank = frequency rank of the character in modern written Chinese
                   (traditional characters take the rank of their simplified form);
                   0 = not in the frequency list (treat as very rare).
  <plugin>/data/words.tsv   word <TAB> reading of each syllable, space-separated
                   Only words (2-4 characters, simplified and traditional forms)
                   that contain a polyphonic character which can ever be annotated.

Usage:
  pip install wordfreq pypinyin
  python3 tools/build_data.py --cedict cedict_1_0_ts_utf-8_mdbg.txt.gz --out interlinearpinyin.koplugin/data

CC-CEDICT: https://www.mdbg.net/chinese/dictionary?page=cc-cedict
"""

import argparse
import gzip
import os
import re
import unicodedata
from collections import Counter, defaultdict

import wordfreq
from pypinyin.pinyin_dict import pinyin_dict

# Characters ranked at or above this are never annotated by any menu setting,
# so the data files leave them out.
MIN_ANNOTATABLE_RANK = 1000
MAX_WORD_LEN = 4

LINE_RE = re.compile(r"^(\S+) (\S+) \[([^\]]*)\] /(.*)/\s*$")
VOWELS = "aeiouü"
MARKS = {
    "a": "āáǎà", "e": "ēéěè", "i": "īíǐì",
    "o": "ōóǒò", "u": "ūúǔù", "ü": "ǖǘǚǜ",
}


def is_han(ch):
    cp = ord(ch)
    return (0x3400 <= cp <= 0x4DBF or 0x4E00 <= cp <= 0x9FFF or
            0xF900 <= cp <= 0xFAFF or 0x20000 <= cp <= 0x3134F)


def numbered_to_marked(syl):
    """'lu:4' -> 'lǜ', 'zhuang4' -> 'zhuàng', 'ma5' -> 'ma'."""
    syl = syl.lower().replace("u:", "ü").replace("v", "ü")
    tone = 5
    if syl and syl[-1].isdigit():
        tone = int(syl[-1])
        syl = syl[:-1]
    if tone in (5, 0) or not syl:
        return syl
    # Standard placement: a or e take the mark; in "ou" the o does;
    # otherwise the last vowel.
    if "a" in syl:
        idx = syl.index("a")
    elif "e" in syl:
        idx = syl.index("e")
    elif "ou" in syl:
        idx = syl.index("o")
    else:
        idx = max((i for i, c in enumerate(syl) if c in VOWELS), default=-1)
        if idx < 0:  # 'm2', 'ng2', 'r5' ...
            return syl
    return syl[:idx] + MARKS[syl[idx]][tone - 1] + syl[idx + 1:]


def is_neutral(syl):
    return not syl[-1:].isdigit() or syl[-1] in "50"


def load_cedict(path):
    opener = gzip.open if path.endswith(".gz") else open
    entries = []
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            m = LINE_RE.match(line.strip())
            if not m:
                continue
            trad, simp, py, defs = m.groups()
            syls = py.split()
            if len(syls) != len(simp) or len(trad) != len(simp):
                continue
            entries.append((trad, simp, syls, defs))  # original case: capitals mark names
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cedict", required=True)
    ap.add_argument("--out", default="interlinearpinyin.koplugin/data")
    args = ap.parse_args()

    freq = wordfreq.get_frequency_dict("zh")  # simplified-only keys

    # 1. Character frequency rank (modern written Chinese, simplified).
    char_freq = Counter()
    for w, f in freq.items():
        for ch in w:
            if is_han(ch):
                char_freq[ch] += f
    simp_rank = {ch: i + 1 for i, (ch, _) in enumerate(char_freq.most_common())}

    entries = load_cedict(args.cedict)

    # 2. Traditional -> simplified mapping, from CEDICT's aligned pairs.
    t2s_counts = defaultdict(Counter)
    for trad, simp, _, _ in entries:
        for t, s in zip(trad, simp):
            if is_han(t) and is_han(s):
                t2s_counts[t][s] += 1

    def rank_of(ch):
        if ch in simp_rank:
            return simp_rank[ch]
        if ch in t2s_counts:
            s = t2s_counts[ch].most_common(1)[0][0]
            return simp_rank.get(s, 0)
        return 0

    # 3. Readings per character, weighted by how often the words using each
    #    reading occur. Neutral tones only count when nothing else exists.
    weights = defaultdict(Counter)
    neutral = defaultdict(Counter)
    single_entry_reading = {}
    for trad, simp, syls, _ in entries:
        wf = freq.get(simp, 0.0) + 1e-9
        syls = [s.lower() for s in syls]
        for form in {trad, simp}:
            for ch, syl in zip(form, syls):
                if not is_han(ch):
                    continue
                if is_neutral(syl):
                    neutral[ch][syl] += wf
                else:
                    weights[ch][syl] += wf
            if len(form) == 1 and form not in single_entry_reading and not is_neutral(syls[0]):
                single_entry_reading[form] = syls[0]

    def default_reading(ch):
        if weights[ch]:
            return numbered_to_marked(weights[ch].most_common(1)[0][0])
        if ch in single_entry_reading:
            return numbered_to_marked(single_entry_reading[ch])
        py = pinyin_dict.get(ord(ch))
        if py:
            return unicodedata.normalize("NFC", py.split(",")[0])
        if neutral[ch]:
            return numbered_to_marked(neutral[ch].most_common(1)[0][0])
        return None

    def annotatable(ch):
        r = rank_of(ch)
        return r == 0 or r > MIN_ANNOTATABLE_RANK

    all_chars = set(weights) | set(neutral) | set(single_entry_reading)
    all_chars |= {chr(cp) for cp in pinyin_dict if is_han(chr(cp))}

    rows = []
    for ch in all_chars:
        if not annotatable(ch):
            continue
        reading = default_reading(ch)
        if reading:
            rows.append((ch, rank_of(ch), reading))
    rows.sort(key=lambda r: (r[1] == 0, r[1], r[0]))

    # 4. Polyphonic annotatable characters, and the words that disambiguate them.
    poly = {ch for ch in all_chars
            if annotatable(ch) and len({numbered_to_marked(s) for s in weights[ch]}) > 1}

    words = {}
    for trad, simp, syls, _ in entries:
        if not 2 <= len(simp) <= MAX_WORD_LEN:
            continue
        marked = " ".join(numbered_to_marked(s) for s in syls)
        is_name = any(s[:1].isupper() for s in syls)
        for form in (simp, trad):
            if not any(ch in poly for ch in form):
                continue
            # Prefer an ordinary word over a proper-name reading of the same form,
            # and keep the first entry otherwise.
            if form in words and (words[form][1] is False or is_name):
                continue
            words[form] = (marked, is_name)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "chars.tsv"), "w", encoding="utf-8") as f:
        for ch, rank, reading in rows:
            f.write(f"{ch}\t{rank}\t{reading}\n")
    with open(os.path.join(args.out, "words.tsv"), "w", encoding="utf-8") as f:
        for form in sorted(words):
            f.write(f"{form}\t{words[form][0]}\n")

    print(f"chars.tsv: {len(rows)} characters "
          f"({sum(1 for r in rows if r[1])} ranked, {len(poly)} polyphonic)")
    print(f"words.tsv: {len(words)} words")


if __name__ == "__main__":
    main()
