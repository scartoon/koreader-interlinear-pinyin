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
  <plugin>/data/defs.tsv    key <TAB> frequency <TAB> pinyin <TAB> senses [<TAB> pinyin <TAB> senses ...]
                   CC-CEDICT definitions for the tap popup: every annotatable
                   character and every 2-4 character word containing one, in
                   simplified and traditional forms. One line per key, lines sorted
                   by the key's UTF-8 bytes (the plugin binary-searches the file
                   instead of loading it). pinyin: tone marks, syllables separated
                   by spaces, capitals kept (names). senses: '/'-separated, with
                   cross-references made readable ("variant of 够 gòu", "CL: 个 gè").
                   frequency: the word's frequency as in words.tsv (0 for characters).

tools/overrides.tsv holds hand-checked readings that win over both sources:
one character replaces its default reading, 2-4 characters add or replace a word
(or remove it, with the reading "-").

Also writes tools/generated/reading_shares.tsv (not used by the plugin):
  char <TAB> default reading <TAB> reading:share ... (most common first)
for every polyphonic annotatable character: how its readings split in ordinary
text, estimated from the frequency of the words that use each reading. Used by
tools/learn_from_cpp.py and tools/eval_readings.py.

Usage:
  pip install wordfreq pypinyin
  python3 tools/build_data.py --cedict cedict_1_0_ts_utf-8_mdbg.txt.gz --out interlinearpinyin.koplugin/data

  --only defs writes defs.tsv alone (chars.tsv and words.tsv are left as they are).

CC-CEDICT: https://www.mdbg.net/chinese/dictionary?page=cc-cedict
"""

import argparse
import functools
import gzip
import os
import re
import unicodedata
from collections import Counter, defaultdict

import wordfreq
import special_words
from importlib.metadata import version
from pypinyin.phrases_dict import phrases_dict
from pypinyin.pinyin_dict import pinyin_dict

from pinyin_util import (is_erhua, is_han, is_neutral, is_toneless, numbered_to_marked,
                         only_neutral_differs, strip_tone)

# Characters ranked at or above this are never annotated by any menu setting,
# so the data files leave them out.
MIN_ANNOTATABLE_RANK = 1000
MAX_WORD_LEN = 4

# Single-character CC-CEDICT entries that do not describe an ordinary modern
# reading (for the reading-share estimate only).
MINOR_DEF_RE = re.compile(r"^\((dialect|archaic|old|literary|onom\.)\)|^(old |archaic |)variant of|"
                          r"^see [^/]*\]$|^used in [^/]*\]$")
LINE_RE = re.compile(r"^(\S+) (\S+) \[([^\]]*)\] /(.*)/\s*$")


def cedict_header(path):
    """The '#! key=value' header of a CC-CEDICT file (date, entries, ...)."""
    opener = gzip.open if path.endswith(".gz") else open
    header = {}
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.startswith("#"):
                break
            if line.startswith("#! ") and "=" in line:
                key, value = line[3:].strip().split("=", 1)
                header[key] = value
    return header


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


# Cross-references inside CC-CEDICT senses: 夠|够[gou4], 乘[cheng2], [jue2].
XREF_RE = re.compile(r"(?:([^\x00-\x7f\s\[\]|,;:()/]+)(?:\|([^\x00-\x7f\s\[\]|,;:()/]+))?)?\[([A-Za-z0-9:, ·]+)\]")


def joined_pinyin(numbered):
    """'shen2 me5' -> 'shénme', 'Xi1 an1' -> "Xī'ān" (apostrophe before a, o, e)."""
    if "·" in numbered:  # names: 喬治·奧威爾|乔治·奥威尔[Qiao2 zhi4 · Ao4 wei1 er3]
        return "·".join(joined_pinyin(part) for part in numbered.split("·"))
    out = []
    for i, syl in enumerate(numbered.replace(",", " ").split()):
        capital = syl[:1].isupper()
        marked = numbered_to_marked(syl)
        if capital:
            marked = marked[:1].upper() + marked[1:]
        if i > 0 and capital:  # a new name word: Dong4 wu4 Nong2 chang3 -> Dòngwù Nóngchǎng
            marked = " " + marked
        elif i > 0 and unicodedata.normalize("NFD", marked)[:1].lower() in "aoe":
            marked = "'" + marked
        out.append(marked)
    return "".join(out)


def clean_sense(sense, traditional):
    """Make CC-CEDICT's cross-references readable: 'variant of 夠|够[gou4]' ->
    'variant of 够 gòu' (or 夠 for a traditional key), 'CL:個|个[ge4],隻|只[zhi1]'
    -> 'CL: 个 gè, 只 zhī', 'Taiwan pr. [jue2]' -> 'Taiwan pr. jué'."""
    def repl(m):
        first, second, py = m.groups()
        form = (first if traditional or not second else second) if first else ""
        py = joined_pinyin(py)
        return f"{form} {py}" if form else py
    sense = XREF_RE.sub(repl, sense)
    if sense.startswith("CL:"):
        sense = "CL: " + ", ".join(p.strip() for p in sense[3:].split(","))
    return sense.replace("\t", " ").strip()


def refers_to(sense, form):
    """True for a sense that only points at `form` itself: 椉 乘 [cheng2]
    /old variant of 乘[cheng2]/ describes 椉, not 乘."""
    return any(form in (m.group(1), m.group(2)) for m in XREF_RE.finditer(sense)) and \
        re.search(r"variant of|^see |^used in", sense) is not None


def write_defs(entries, annotatable, word_freq, path, extra_forms=()):
    """defs.tsv: CC-CEDICT entries for every annotatable character and every
    2-4 character word containing one (see the module docstring)."""
    by_key = defaultdict(list)   # key -> [[marked pinyin, [senses]], ...] in CC-CEDICT order
    simp_of = {}
    for trad, simp, syls, defs in entries:
        forms = [simp] if trad == simp else [simp, trad]
        for form in forms:
            if not 1 <= len(form) <= MAX_WORD_LEN or not all(is_han(ch) for ch in form):
                continue
            if not any(annotatable(ch) for ch in form) and form not in extra_forms:
                continue
            pinyin = " ".join(numbered_to_marked(s)[:1].upper() + numbered_to_marked(s)[1:]
                              if s[:1].isupper() else numbered_to_marked(s) for s in syls)
            traditional = form == trad and trad != simp
            senses = [clean_sense(d, traditional) for d in defs.split("/")
                      if d.strip() and not refers_to(d, form)]
            if not senses:
                continue
            groups = by_key[form]
            for group in groups:
                if group[0] == pinyin:
                    group[1].extend(x for x in senses if x not in group[1])
                    break
            else:
                groups.append([pinyin, senses])
            simp_of.setdefault(form, simp)
    keys = sorted(by_key, key=lambda k: k.encode("utf-8"))
    with open(path, "w", encoding="utf-8") as f:
        for key in keys:
            freq = word_freq(key, simp_of[key]) if len(key) > 1 else 0
            fields = [key, str(freq)]
            for pinyin, senses in by_key[key]:
                fields += [pinyin, "/".join(senses)]
            f.write("\t".join(fields) + "\n")
    chars = sum(1 for k in keys if len(k) == 1)
    print(f"defs.tsv: {len(keys)} keys ({chars} characters, {len(keys) - chars} words), "
          f"{os.path.getsize(path) / 1e6:.1f} MB")


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
            if reading == "-":
                if len(form) < 2:
                    raise SystemExit(f"{path}:{n}: only words can be removed")
                if form in out:
                    raise SystemExit(f"{path}:{n}: {form} listed twice")
                out[form] = None
                continue
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
    ap.add_argument("--curated", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "special_curated.tsv"))
    ap.add_argument("--shares-out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                         "generated", "reading_shares.tsv"))
    ap.add_argument("--only", choices=["all", "defs"], default="all",
                    help="defs: write defs.tsv only")
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
    header = cedict_header(args.cedict)
    # Record this in interlinearpinyin.koplugin/data/README.md when the data is rebuilt.
    print(f"CC-CEDICT {header.get('date', '(no date in header)')}, {header.get('entries', '?')} entries; "
          f"wordfreq {getattr(wordfreq, '__version__', None) or version('wordfreq')}, "
          f"pypinyin {version('pypinyin')}")

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
    # The same, counted in simplified forms only and in traditional forms only:
    # 乾 is qián in simplified text but mostly gān (干) in traditional.
    script_weights = {"simp": defaultdict(Counter), "trad": defaultdict(Counter)}
    neutral = defaultdict(Counter)
    single_entry_reading = {}
    for trad, simp, syls, _ in entries:
        wf = freq.get(simp, 0.0) + 1e-9
        syls = [s.lower() for s in syls]
        for script, form in (("simp", simp), ("trad", trad)):
            for ch, syl in zip(form, syls):
                if is_han(ch) and not is_neutral(syl):
                    script_weights[script][ch][syl] += wf
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
    char_overrides = {form: syls[0] for form, syls in overrides.items() if len(form) == 1 and syls}
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
        if len(form) > 1 and syls is None:
            stats["overrides: removed"] += 1 if words.pop(form, None) else 0
        elif len(form) > 1:
            stats["overrides: " + ("replaced" if form in words else "added")] += 1
            words[form] = [syls, False, None]

    neutral_fixed = set()
    word_rows = []
    for form in sorted(words):
        syls, _, simp = words[form]
        fixed = fix_neutral(form, syls)
        neutral_fixed.update(ch for ch, a, b in zip(form, syls, fixed) if a != b)
        word_rows.append((form, " ".join(fixed), word_freq(form, simp)))

    # 7. How each polyphonic character's readings split in ordinary text:
    #    summed frequency of the CC-CEDICT words using each toned reading, plus
    #    readings only pypinyin's phrases have. Readings whose only support is
    #    a single-character entry marked dialect, archaic or a variant (甭 bèng,
    #    "(dialect) very") are left out unless nothing else is left. A
    #    hand-checked default (overrides.tsv) gets a 90% share.
    minor_only = defaultdict(set)    # char -> readings seen only in minor entries
    major = defaultdict(set)
    for trad, simp, syls, defs in entries:
        is_minor = len(simp) == 1 and MINOR_DEF_RE.search(defs)
        for form in {trad, simp}:
            for ch, syl in zip(form, syls):
                if is_han(ch) and not is_neutral(syl.lower()):
                    (minor_only if is_minor else major)[ch].add(numbered_to_marked(syl.lower()))
    phrases_with = defaultdict(list)   # char -> pypinyin phrases containing it, in order
    for phrase in py_phrases:
        for ch in set(phrase):
            phrases_with[ch].append(phrase)

    def default_of(ch):
        """Default reading of any character, annotatable or not."""
        return defaults.get(ch) or default_reading(ch)

    @functools.lru_cache(maxsize=None)
    def shares_of(ch, script=None):
        """reading -> share of ch's use in ordinary text (see above). Works for
        any character, not only the annotatable polyphonic ones. script
        "simp" or "trad" counts only CC-CEDICT words written in that script."""
        w = Counter()
        for syl, f in (script_weights[script] if script else weights)[ch].items():
            marked = numbered_to_marked(syl)
            if marked in minor_only[ch] and marked not in major[ch]:
                continue
            w[marked] += f
        for phrase in phrases_with[ch]:
            for c, syl in zip(phrase, fix_neutral(phrase, py_phrases[phrase])):
                if c == ch and not is_toneless(syl) and syl not in w:
                    w[syl] += word_freq(phrase) / 1e9 + 1e-9
        default = default_of(ch)
        if default and default not in w:
            w[default] = 0.0
        total = sum(w.values()) or 1.0
        shares = {r: f / total for r, f in w.items()}
        if ch in char_overrides:
            rest = sum(v for r, v in shares.items() if r != default)
            shares = {r: (0.9 if r == default else (0.1 * v / rest if rest else 0.0))
                      for r, v in shares.items()}
        return shares

    share_rows = []
    for ch in sorted(poly):
        ordered = sorted(shares_of(ch).items(), key=lambda kv: -kv[1])
        share_rows.append((ch, defaults[ch], " ".join(f"{r}:{v:.4f}" for r, v in ordered)))
    # 8. Unusual readings of common characters in names and historical terms
    #    (data/special.tsv, data/special_guard.tsv); see special_words.py.
    special = special_words.build(
        entries=entries, py_phrases=py_phrases, shares_of=shares_of, default_of=default_of,
        word_freq=word_freq, wordfreq_dict=freq, curated_path=args.curated)

    # defs.tsv also covers the special words and their characters, so the
    # popup has something to show for 单于 although 单 and 于 are common.
    special_forms = {row.word for row in special.rows}
    special_chars = {ch for row in special.rows for ch, m in zip(row.word, row.marks) if m}
    os.makedirs(args.out, exist_ok=True)
    write_defs(entries, annotatable, word_freq, os.path.join(args.out, "defs.tsv"),
               extra_forms=special_forms | special_chars)
    if args.only == "defs":
        return
    special.write(args.out, os.path.join(os.path.dirname(args.shares_out), "special_review.tsv"))

    os.makedirs(os.path.dirname(args.shares_out), exist_ok=True)
    with open(args.shares_out, "w", encoding="utf-8") as f:
        f.write("# char\tdefault\treading:share ... (generated by tools/build_data.py)\n")
        for row in share_rows:
            f.write("\t".join(row) + "\n")

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
