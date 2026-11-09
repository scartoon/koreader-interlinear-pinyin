#!/usr/bin/env python3
"""Build the plugin's data files from CC-CEDICT, wordfreq and pypinyin.

Outputs (tab-separated UTF-8 text, parsed by the plugin at load time):

  <plugin>/data/chars.tsv   char <TAB> rank <TAB> default reading
                   rank = frequency rank of the character in modern written Chinese
                   (traditional characters take the rank of their simplified form);
                   0 = not in the frequency list (treat as very rare).
  <plugin>/data/words.tsv   word <TAB> reading of each syllable, space-separated
                   <TAB> frequency (occurrences per billion words, from wordfreq;
                   traditional forms take the frequency of their simplified form)
                   Only words (2-4 characters, simplified and traditional forms)
                   that contain a polyphonic character which can ever be annotated.
                   Words come from CC-CEDICT and from pypinyin's phrase list.

tools/overrides.tsv holds hand-checked readings that win over both sources:
one character replaces its default reading, 2-4 characters add or replace a word.

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
from pypinyin.phrases_dict import phrases_dict
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


def is_erhua(syl):
    return syl.lower() in ("r", "r5")


TONE_MARKS = "\u0304\u0301\u030c\u0300"  # macron, acute, caron, grave (not ü's diaeresis)


def strip_tone(marked):
    """'lǜ' -> 'lü', 'zhuàng' -> 'zhuang'."""
    nfd = unicodedata.normalize("NFD", marked)
    return unicodedata.normalize("NFC", "".join(c for c in nfd if c not in TONE_MARKS))


def is_toneless(marked):
    return strip_tone(marked) == marked


def only_neutral_differs(cedict_syls, pypinyin_syls):
    """True when the readings differ only where CC-CEDICT has a neutral tone and
    pypinyin has the same syllable with a tone (刺猬 cì wei / cì wèi)."""
    if len(cedict_syls) != len(pypinyin_syls) or cedict_syls == pypinyin_syls:
        return False
    for c, p in zip(cedict_syls, pypinyin_syls):
        if c != p and not (is_toneless(c) and not is_toneless(p) and strip_tone(p) == c):
            return False
    return True


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


def load_overrides(path):
    """form -> list of marked syllables, from tools/overrides.tsv."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 2:
                raise SystemExit(f"{path}:{n}: expected form<TAB>reading")
            form, reading = fields[0], unicodedata.normalize("NFC", fields[1])
            syls = reading.split()
            if len(syls) != len(form) or not all(is_han(ch) for ch in form):
                raise SystemExit(f"{path}:{n}: {form} has {len(form)} characters but {len(syls)} syllables")
            if form in out:
                raise SystemExit(f"{path}:{n}: {form} listed twice")
            out[form] = syls
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cedict", required=True)
    ap.add_argument("--out", default="interlinearpinyin.koplugin/data")
    ap.add_argument("--overrides", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "overrides.tsv"))
    args = ap.parse_args()
    overrides = load_overrides(args.overrides)

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

    def to_simplified(form):
        return "".join(t2s_counts[ch].most_common(1)[0][0] if ch in t2s_counts and ch not in simp_rank
                       else ch for ch in form)

    def word_freq(form, simp=None):
        """Occurrences per billion words. wordfreq keys are simplified only."""
        f = freq.get(simp or form)
        if f is None:
            f = freq.get(to_simplified(form), 0.0)
        return round(f * 1e9)

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
    # Hand-checked default readings.
    char_overrides = {form: syls[0] for form, syls in overrides.items() if len(form) == 1}
    rows = [(ch, rank, char_overrides.get(ch, reading)) for ch, rank, reading in rows]

    defaults = {ch: reading for ch, _, reading in rows}

    def toned_readings(ch):
        """The character's toned readings, default first, then by frequency."""
        out = [defaults[ch]] if ch in defaults else []
        for syl, _ in weights[ch].most_common():
            marked = numbered_to_marked(syl)
            if marked not in out:
                out.append(marked)
        return out

    def fix_neutral(form, marked_syls):
        """CC-CEDICT writes spoken neutral tones (刺猬 cì wei). Above a rare
        character we want its own tone, so a toneless syllable of an
        annotatable character takes that character's toned reading with the
        same letters (the default when it matches): wei -> wèi, and 冷颤 zhan
        -> zhàn even though 颤's default is chàn. With no such reading it is
        left as written (萝卜 bo: 卜 is otherwise only bǔ). Erhua 'r' is left
        alone."""
        out = []
        for ch, syl in zip(form, marked_syls):
            if is_toneless(syl) and not is_erhua(syl) and ch in defaults:
                for reading in toned_readings(ch):
                    if strip_tone(reading) == syl and reading != syl:
                        syl = reading
                        break
            out.append(syl)
        return out

    # 4. pypinyin's phrase list (built for polyphone disambiguation): first
    #    reading of each syllable, 2-4 character phrases only.
    py_phrases = {}
    for phrase, readings in phrases_dict.items():
        if not 2 <= len(phrase) <= MAX_WORD_LEN or not all(is_han(ch) for ch in phrase):
            continue
        if len(readings) != len(phrase) or not all(readings):
            continue
        py_phrases[phrase] = [unicodedata.normalize("NFC", r[0]) for r in readings]

    # 5. Polyphonic annotatable characters: those with several toned readings in
    #    CC-CEDICT, plus those whose reading in some pypinyin phrase differs from
    #    their default.
    poly = {ch for ch in all_chars
            if annotatable(ch) and len({numbered_to_marked(s) for s in weights[ch]}) > 1}
    cedict_poly = len(poly)
    for phrase, syls in py_phrases.items():
        for ch, syl in zip(phrase, fix_neutral(phrase, syls)):
            if ch in defaults and syl != defaults[ch]:
                poly.add(ch)

    # 6. Words that disambiguate them. CC-CEDICT first; prefer an ordinary word
    #    over a proper-name reading of the same form, and keep the first entry
    #    otherwise.
    words = {}   # form -> [syllables (raw marked), is_name, simplified form]
    for trad, simp, syls, _ in entries:
        if not 2 <= len(simp) <= MAX_WORD_LEN:
            continue
        marked = [numbered_to_marked(s) for s in syls]
        is_name = any(s[:1].isupper() for s in syls)
        for form in (simp, trad):
            if not any(ch in poly for ch in form):
                continue
            if form in words and (words[form][1] is False or is_name):
                continue
            words[form] = [marked, is_name, simp]

    # Merge pypinyin. Where both have the word and they disagree, keep
    # CC-CEDICT unless the only difference is CC-CEDICT's neutral tones.
    stats = Counter()
    for phrase, syls in py_phrases.items():
        if not any(ch in poly for ch in phrase):
            continue
        if phrase not in words:
            words[phrase] = [syls, False, None]
            stats["pypinyin added"] += 1
        elif words[phrase][0] != syls:
            stats["disagree"] += 1
            if only_neutral_differs(words[phrase][0], syls):
                words[phrase][0] = syls
                stats["disagree: took pypinyin (neutral tone)"] += 1
            else:
                stats["disagree: kept CC-CEDICT"] += 1

    # Hand-checked words win over both sources.
    for form, syls in overrides.items():
        if len(form) > 1:
            stats["overrides: " + ("replaced" if form in words else "added")] += 1
            words[form] = [syls, False, None]

    neutral_fixed = set()
    word_rows = []
    for form in sorted(words):
        syls, _, simp = words[form]
        fixed = fix_neutral(form, syls)
        neutral_fixed.update(ch for ch, a, b in zip(form, syls, fixed) if a != b)
        word_rows.append((form, " ".join(fixed), word_freq(form, simp)))

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "chars.tsv"), "w", encoding="utf-8") as f:
        for ch, rank, reading in rows:
            f.write(f"{ch}\t{rank}\t{reading}\n")
    with open(os.path.join(args.out, "words.tsv"), "w", encoding="utf-8") as f:
        for form, reading, wf in word_rows:
            f.write(f"{form}\t{reading}\t{wf}\n")

    print(f"chars.tsv: {len(rows)} characters "
          f"({sum(1 for r in rows if r[1])} ranked, {len(poly)} polyphonic: "
          f"{cedict_poly} from CC-CEDICT, {len(poly) - cedict_poly} more from pypinyin)")
    print(f"words.tsv: {len(word_rows)} words "
          f"({sum(1 for r in word_rows if r[2])} with a frequency)")
    for key in sorted(stats):
        print(f"  {key}: {stats[key]}")
    print(f"  neutral tones replaced for {len(neutral_fixed)} annotatable characters")


if __name__ == "__main__":
    main()
