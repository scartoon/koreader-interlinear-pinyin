"""Unusual readings of common characters ("trap words") for build_data.py.

单于 is chán yú and 冒顿 is mò dú, but 单, 于, 冒 and 顿 are common characters
the plugin never annotates, so a reader sees nothing. This module lists 2-4
character words in which some character takes a reading it rarely has, and
marks the characters whose reading differs from their default.

Outputs (in the plugin's data directory):

  special.tsv        word <TAB> pinyin <TAB> marks <TAB> frequency <TAB> note
                     pinyin: lowercase, tone marks, one syllable per character.
                     marks: one digit per character, 1 = annotate it (its
                     reading here differs from its default).
                     frequency: per billion words (wordfreq), 0 when unknown.
                     note: short gloss from tools/special_curated.tsv, or empty.
  special_guard.tsv  ordinary word <TAB> special word <TAB> offset
                     The ordinary word, starting `offset` characters after the
                     special word's first character (negative: before it),
                     overlaps one of its edges and is the much likelier reading
                     of the text: 订单 at -1 for 单于 in 订单于3日发货. Also
                     dictionary words that contain a special word but read a
                     marked character differently: 九华山 (huá) at -1 for 华山
                     (huà). The plugin then skips the special word.

Automatic candidates come from CC-CEDICT and pypinyin's phrase list: a word
qualifies when one of its characters takes a toned reading with a share below
CUTOFF of that character's use (NAME_CUTOFF for Chinese historical names and
places, which CC-CEDICT capitalizes). Excluded: neutral tones, erhua, 一 and 不
(tone sandhi), dialect and Taiwan-only entries, loanwords and transliterations.

tools/special_curated.tsv (word <TAB> pinyin <TAB> note) always wins; the
pinyin "-" keeps a word out of the automatic list (contested or wrong).
"""
import os
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass

from pinyin_util import is_erhua, is_han, is_toneless, numbered_to_marked, strip_tone

CUTOFF = 0.03        # share of the character's use, ordinary words
NAME_CUTOFF = 0.10   # Chinese historical names, peoples, places
SANDHI = set("一不")
# An ordinary word o crossing a special word w's edge blocks it when splitting
# the text as o + (rest of w) is GUARD_MARGIN times likelier than (rest of o) +
# w, by word frequencies (a unigram segmentation). 订单|于 beats 订|单于 by 800x;
# 单|于是 loses to 单于|是, so 冒顿单于是 still matches. A special word counts as
# at least FREQ_FLOOR per billion words.
GUARD_MARGIN = 3.0
FREQ_FLOOR = 20      # per billion words
CHAR_FLOOR = 1e-8    # frequency of a character wordfreq does not list
GUARD_MIN_FREQ = 100 # per billion: rarer ordinary words are left out of the guard

# Entries describing a regional or foreign word, not a standard reading.
REGIONAL_RE = re.compile(r"\b(Tw|Taiwan(ese)?|Cantonese|Hokkien|Hakka|Shanghainese|Teochew|dialect|"
                         r"Minnan|Min Nan|Wu)\b|\(coll\.\)|\bslang\b")
FOREIGN_RE = re.compile(r"loanword|transliteration|\(Buddhism\)|Sanskrit|Pali|Tibetan|Mongolian|Manchu|"
                        r"Japanese|Korean|Vietnam|Thai|Arabic|Persian|Hebrew|Greek|Latin|English|French|"
                        r"German|Russian|Spanish|Italian|Portuguese|Indian|India\b|Africa|Europe|America|"
                        r"\bUS\b|\bUK\b|Hungar|Poland|Polish|Belgi|Netherlands|Dutch|Austria|Switzerland|Swed|"
                        r"Norw|Denmark|Danish|Finland|Czech|Romania|Bulgaria|Serbia|Croatia|Turkey|Turkish|Iran|"
                        r"Iraq|Israel|Egypt|Morocco|Pakistan|Afghan|Kazakh|Kyrgyz|Uzbek|Tajik|Georgia|Armenia|"
                        r"Azerbaijan|Ukrain|Belarus|Canada|Mexic|Brazil|Argentin|Australia|Indonesia|Malaysia|"
                        r"Philippin|Burm|Myanmar|Cambodia|Laos|Nepal|Bangladesh|Sri Lanka|Siberia|Islam|Christian|"
                        r"\bChrist\b|Bible|biblical|Jesus|Catholic|dioxin|clenbuterol")
# What makes a capitalized CC-CEDICT entry a Chinese historical name or place.
CHINESE_NAME_RE = re.compile(r"[Dd]ynasty|\bBC\b|\bAD\b|ancient|Warring States|Spring and Autumn|"
                             r"Three Kingdoms|Xiongnu|Xianbei|Han\b|Tang\b|Qin\b|Zhou\b|Shang\b|"
                             r"emperor|Emperor|king of|King\b|kingdom|state of|"
                             r"county|County|district|District|prefecture|Prefecture|"
                             r"Hubei|Hunan|Henan|Hebei|Shandong|Shanxi|Shaanxi|Jiangsu|Zhejiang|Anhui|"
                             r"Jiangxi|Fujian|Guangdong|Guangxi|Sichuan|Yunnan|Guizhou|Gansu|Qinghai|"
                             r"Xinjiang|Liaoning|Jilin|Heilongjiang|Hainan|Ningxia|Chongqing|Beijing|"
                             r"Shanghai|Tianjin|Mongolia")
MINOR_RE = re.compile(r"^(old |archaic |)variant of|^used in |^erhua variant")
TECHNICAL_RE = re.compile(r"\((chemistry|medicine|TCM|botany|zoology|math\.|physics|mahjong|onom\.)\)|\bonom\.|"
                          r"\bC\d+H\d+")
SEE_RE = re.compile(r"^see ([^\[|/]+)(?:\|([^\[/]+))?\[")
ALT_PR_RE = re.compile(r"(?:also|colloquial|Taiwan|old|commonly) pr\. \[([^\]]+)\]")
# Colloquial readings CC-CEDICT writes into words without marking them.
COLLOQUIAL = {("熟", "shóu"), ("剋", "kēi"), ("好", "hāo"), ("血", "xiě")}


@dataclass
class Row:
    word: str
    syls: list
    simp: str            # simplified form (wordfreq is simplified only)
    marks: list          # bool per character
    freq: int
    note: str
    source: str          # "curated" or "auto"
    share: float = 1.0   # rarest marked reading's share (auto only)
    detail: str = ""     # why it qualified (for review)


@dataclass
class Result:
    rows: list
    guard: dict
    stats: Counter

    def write(self, out_dir, review_path=None):
        with open(os.path.join(out_dir, "special.tsv"), "w", encoding="utf-8") as f:
            for r in sorted(self.rows, key=lambda r: r.word.encode("utf-8")):
                marks = "".join("1" if m else "0" for m in r.marks)
                f.write(f"{r.word}\t{' '.join(r.syls)}\t{marks}\t{r.freq}\t{r.note}\n")
        with open(os.path.join(out_dir, "special_guard.tsv"), "w", encoding="utf-8") as f:
            for o, w, offset in sorted(self.guard, key=lambda g: (g[0].encode("utf-8"), g[1].encode("utf-8"), g[2])):
                f.write(f"{o}\t{w}\t{offset}\n")
        auto = sum(r.source == "auto" for r in self.rows)
        if review_path:
            os.makedirs(os.path.dirname(review_path), exist_ok=True)
            with open(review_path, "w", encoding="utf-8") as f:
                f.write("# word\tpinyin\tmarked\tfrequency\tsource\trarest share\twhy "
                        "(generated by tools/build_data.py, for review)\n")
                for r in sorted(self.rows, key=lambda r: (r.source, r.share, r.word)):
                    marked = " ".join(f"{ch}={s}" for ch, s, m in zip(r.word, r.syls, r.marks) if m)
                    f.write(f"{r.word}\t{' '.join(r.syls)}\t{marked}\t{r.freq}\t{r.source}\t"
                            f"{r.share:.4f}\t{r.note or r.detail}\n")
        print(f"special.tsv: {len(self.rows)} words ({len(self.rows) - auto} curated, {auto} automatic, "
              f"simplified and traditional forms); special_guard.tsv: {len(self.guard)} overlaps "
              f"({len({g[0] for g in self.guard})} ordinary words)")
        for key in sorted(self.stats):
            print(f"  {key}: {self.stats[key]}")


def load_curated(path):
    """[(word, [syllables] or None to exclude, note, sources)] from tools/special_curated.tsv."""
    out, seen = [], set()
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 2:
                raise SystemExit(f"{path}:{n}: expected word<TAB>pinyin<TAB>note")
            word = fields[0]
            note = fields[2].strip() if len(fields) > 2 else ""
            sources = {x.strip() for x in fields[3].split(",")} - {""} if len(fields) > 3 else set()
            if fields[1].strip() == "-":
                if word in seen:
                    raise SystemExit(f"{path}:{n}: {word} listed twice")
                seen.add(word)
                out.append((word, None, note, sources))
                continue
            syls = unicodedata.normalize("NFC", fields[1]).split()
            if len(syls) != len(word) or not all(is_han(ch) for ch in word) or not 2 <= len(word) <= 4:
                raise SystemExit(f"{path}:{n}: {word}: 2-4 characters, one syllable each")
            if word in seen:
                raise SystemExit(f"{path}:{n}: {word} listed twice")
            seen.add(word)
            out.append((word, syls, note, sources))
    return out


def build(entries, py_phrases, shares_of, default_of, word_freq, wordfreq_dict, curated_path):
    stats = Counter()
    def marks_for(word, syls):
        """Annotate a character when its reading here is toned and is not its default."""
        return [not is_toneless(s) and not is_erhua(s) and s != default_of(ch) for ch, s in zip(word, syls)]

    # Simplified -> traditional, for curated words CC-CEDICT does not have.
    s2t_counts = defaultdict(Counter)
    trad_of = {}
    for trad, simp, _, _ in entries:
        for t, s in zip(trad, simp):
            s2t_counts[s][t] += 1
        if 2 <= len(simp) <= 4:
            trad_of.setdefault(simp, trad)

    def to_traditional(word):
        return trad_of.get(word) or "".join(s2t_counts[ch].most_common(1)[0][0] if ch in s2t_counts else ch
                                            for ch in word)

    rows = {}
    excluded = set()

    # What CC-CEDICT and pypinyin say about a word (for checking the curated
    # list's source column).
    cedict_readings = defaultdict(set)
    for trad, simp, raw, _ in entries:
        cedict_readings[simp].add(tuple(numbered_to_marked(x.lower()) for x in raw))

    # 1. Curated.
    for word, syls, note, sources in load_curated(curated_path):
        if syls is not None:
            agree = set()
            if tuple(syls) in cedict_readings.get(word, ()):
                agree.add("CC-CEDICT")
            if py_phrases.get(word) == syls:
                agree.add("pypinyin")
            if agree != sources:
                others = sorted(" ".join(r) for r in cedict_readings.get(word, ()))
                print(f"  WARNING {os.path.basename(curated_path)}: {word} {' '.join(syls)}: sources column says "
                      f"{sorted(sources) or 'none'}, actually {sorted(agree) or 'none'} "
                      f"(CC-CEDICT: {others or '-'}; pypinyin: {' '.join(py_phrases.get(word) or ['-'])})")
                stats["curated: source column wrong"] += 1
        if syls is None:
            excluded.update({word, to_traditional(word)})
            stats["curated exclusions"] += 1
            continue
        marks = marks_for(word, syls)
        if not any(marks):
            print(f"  WARNING {os.path.basename(curated_path)}: {word} {' '.join(syls)}: "
                  f"no character differs from its default ({' '.join(default_of(ch) for ch in word)}); skipped")
            stats["curated, skipped: nothing to mark"] += 1
            continue
        for form in {word, to_traditional(word)}:
            rows[form] = Row(form, syls, word, marks_for(form, syls), word_freq(form, word), note, "curated")
        stats["curated words"] += 1

    # 2. Automatic: CC-CEDICT, then pypinyin for words CC-CEDICT lacks.
    defs_of = {}            # form -> CC-CEDICT senses (all entries), for following "see X"
    char_entries = defaultdict(list)   # char -> [(marked reading, senses)] single-character entries
    attested = set()        # (char, marked reading) used by some CC-CEDICT entry
    cedict_forms = defaultdict(set)    # form -> set of reading tuples
    for trad, simp, raw, defs in entries:
        syls = tuple(numbered_to_marked(x.lower()) for x in raw)
        for form in {trad, simp}:
            defs_of[form] = defs_of.get(form, "") + "/" + defs
            cedict_forms[form].add(syls)
            for ch, syl in zip(form, syls):
                attested.add((ch, syl))
        if len(simp) == 1:
            for form in {trad, simp}:
                char_entries[form].append((syls[0], defs))

    def explained(defs):
        """Follow 'see 番禺區|番禺区[Pan1 yu2 Qu1]' to the target's senses."""
        m = SEE_RE.match(defs or "")
        if m:
            target = m.group(2) or m.group(1)
            return defs + "/" + defs_of.get(target, "")
        return defs

    def only_alternative(ch, syl):
        """A reading CC-CEDICT gives only as another pronunciation of a common
        meaning ('also pr. [shui2]', 'colloquial pr. [xie3]', 'Taiwan pr.
        [le4]'), never as an entry of its own."""
        own = [d for r, d in char_entries[ch] if r == syl]
        if own:
            return False
        for _, d in char_entries[ch]:
            for m in ALT_PR_RE.finditer(d):
                if any(numbered_to_marked(x.lower()) == syl for x in m.group(1).split()):
                    return True
        return False

    def rare_positions(form, syls, cutoff, script):
        out = []
        for k, (ch, syl) in enumerate(zip(form, syls)):
            if ch in SANDHI or is_toneless(syl) or is_erhua(syl) or syl == default_of(ch):
                continue
            if (ch, syl) in COLLOQUIAL or only_alternative(ch, syl):
                stats_reasons.add((form, "colloquial or alternative pronunciation"))
                continue
            if form.count(ch) > 1:
                stats_reasons.add((form, "reduplication (ABB tone shift)"))
                continue
            # Rare both in this script and overall: 乾坤 is not a trap in
            # simplified text (乾 is always qián there), 杠杆收購 is not one
            # in traditional (杆 gǎn is common overall).
            own, overall = shares_of(ch, script), shares_of(ch)
            if sum(own.values()) <= 0 or sum(overall.values()) <= 0:
                continue
            s = max(own.get(syl, 0.0), overall.get(syl, 0.0))
            if s < cutoff:
                out.append((k, s))
        return out

    stats_reasons = set()

    def consider(form, simp, syls, defs, is_name, source, script):
        if form in rows or form in excluded:
            return
        chinese_name = False
        if defs is not None:
            defs = explained(defs)
            if REGIONAL_RE.search(defs):
                stats["excluded: dialect/Taiwan/colloquial"] += 1
                return
            if FOREIGN_RE.search(defs) or TECHNICAL_RE.search(defs):
                stats["excluded: loanword/foreign/technical"] += 1
                return
            if all(MINOR_RE.search(d) for d in defs.split("/") if d.strip()):
                stats["excluded: variant/used-in only"] += 1
                return
            romanized = "".join(strip_tone(x) for x in syls).replace("ü", "v")
            chinese_name = is_name and (CHINESE_NAME_RE.search(defs) is not None or
                                        ("surname" in defs and romanized in defs.lower().replace("ü", "v")))
        if is_name and not chinese_name:
            if rare_positions(form, syls, NAME_CUTOFF, script):
                stats["excluded: foreign or unexplained name"] += 1
            return
        cutoff = NAME_CUTOFF if chinese_name else CUTOFF
        rare = rare_positions(form, syls, cutoff, script)
        if not rare:
            return
        rows[form] = Row(form, list(syls), simp, marks_for(form, syls), word_freq(form, simp), "", "auto",
                         share=min(x for _, x in rare),
                         detail=f"{source}{' name' if chinese_name else ''}; {(defs or '')[:70]}")
        stats[f"auto: {source}" + (f" Chinese name (cutoff {NAME_CUTOFF:g})" if chinese_name
                                   else f" (cutoff {CUTOFF:g})")] += 1

    for trad, simp, raw, defs in entries:
        if not 2 <= len(simp) <= 4 or not all(is_han(ch) for ch in simp):
            continue
        syls = [numbered_to_marked(x.lower()) for x in raw]
        is_name = any(x[:1].isupper() for x in raw)
        for script, form in (("simp", simp), ("trad", trad)):
            if script == "trad" and trad == simp:
                continue
            # A form with several CC-CEDICT readings (行当 háng dang / xíng dāng)
            # is ambiguous: never a special word.
            if len(cedict_forms[form]) > 1:
                continue
            consider(form, simp, syls, defs, is_name, "CC-CEDICT", script)
    for phrase, syls in py_phrases.items():
        if phrase in cedict_forms or word_freq(phrase) == 0:
            continue
        # pypinyin's phrase list has errors (言之过早 zhì): its rare reading must
        # also occur in CC-CEDICT.
        if not all((ch, s) in attested or s == default_of(ch) or is_toneless(s) for ch, s in zip(phrase, syls)):
            stats["excluded: pypinyin reading not in CC-CEDICT"] += 1 if rare_positions(phrase, syls, CUTOFF, "simp") else 0
            continue
        consider(phrase, phrase, syls, None, False, "pypinyin", "simp")
    reasons = Counter(r for _, r in stats_reasons)
    for r, n in reasons.items():
        stats["excluded readings: " + r] = n

    result_rows = list(rows.values())
    rows_by_word = defaultdict(list)
    for r in result_rows:
        rows_by_word[r.word].append(r)

    def same_reading(a, b):
        """Equal, or a is the neutral-tone form of b."""
        return a == b or (is_toneless(a) and a == strip_tone(b))

    # 3. Overlap guard (see GUARD_MARGIN), computed on simplified forms and
    #    copied to the traditional ones.
    def f(x):
        v = wordfreq_dict.get(x, 0.0)
        if v:
            return v
        p = 1.0
        for ch in x:
            p *= wordfreq_dict.get(ch, CHAR_FLOOR)
        return p

    by_simp = defaultdict(list)
    for r in result_rows:
        by_simp[r.simp].append(r)
    prefixes, suffixes = defaultdict(set), defaultdict(set)   # piece -> simplified special words
    for w in by_simp:
        for k in range(1, len(w)):
            prefixes[w[:k]].add(w)
            suffixes[w[k:]].add(w)
    guard = set()
    for o, fo in wordfreq_dict.items():
        if fo * 1e9 < GUARD_MIN_FREQ or not 2 <= len(o) <= 4 or o in by_simp or not all(is_han(ch) for ch in o):
            continue
        for k in range(1, len(o)):
            # o's tail is w's head: o = rest_o + w[:len(o)-k], offset -k.
            for w in prefixes.get(o[k:], ()):
                rest_o, rest_w, offset = o[:k], w[len(o) - k:], -k
                if fo * f(rest_w) > GUARD_MARGIN * max(f(w), FREQ_FLOOR / 1e9) * f(rest_o):
                    for r in by_simp[w]:
                        guard.add((to_traditional(o) if r.word != w else o, r.word, offset))
            # o's head is w's tail: o = w[len(w)-k:] + rest_o, offset len(w)-k.
            for w in suffixes.get(o[:k], ()):
                rest_o, rest_w, offset = o[k:], w[:len(w) - k], len(w) - k
                if fo * f(rest_w) > GUARD_MARGIN * max(f(w), FREQ_FLOOR / 1e9) * f(rest_o):
                    for r in by_simp[w]:
                        guard.add((to_traditional(o) if r.word != w else o, r.word, offset))
    # 4. Longer dictionary words containing a special word with another
    #    reading of a marked character: 九华山 Jiǔhuá Shān contains 华山 Huà Shān.
    containing = 0
    longer = [(form, syls) for form, readings in cedict_forms.items() for syls in readings]
    longer += [(phrase, tuple(syls)) for phrase, syls in py_phrases.items()]
    for o, o_syls in longer:
        if not 3 <= len(o) <= 4:
            continue
        for k in range(len(o)):
            for n in range(2, len(o) - k + 1):
                if n == len(o):
                    continue
                for r in rows_by_word.get(o[k:k + n], ()):
                    if any(m and not same_reading(o_syls[k + j], r.syls[j])
                           for j, m in enumerate(r.marks)):
                        if (o, r.word, -k) not in guard:
                            guard.add((o, r.word, -k))
                            containing += 1
    stats["guard: longer words with another reading"] = containing
    return Result(result_rows, guard, stats)


