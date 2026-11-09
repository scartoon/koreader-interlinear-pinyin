#!/usr/bin/env python3
"""Learn context rules and reading confidence from the CPP *train* split.

    pip install lupa
    python3 tools/build_data.py --cedict ...     # first: chars.tsv, words.tsv, reading_shares.tsv
    python3 tools/learn_from_cpp.py              # writes data/rules.tsv and data/uncertain.tsv
    python3 tools/eval_readings.py               # then: accuracy on the test split only

Only the train split is read (see cpp_dataset.py for the dataset and its
licence). It is used for:

1. Context rules (data/rules.tsv). For each polyphonic character the plugin can
   annotate, and each character immediately to its left or right, count the
   readings in sentences where no dictionary word decides. A rule is kept when
   it has at least --rule-min examples and at least --rule-purity of them agree.
   At run time: dictionary word first, then a rule, then the default.

2. Confidence (data/uncertain.tsv). Where neither a word nor a rule decides,
   how often is the default reading right? CPP is built to have many examples
   of every reading, so it over-represents minority readings; the train share
   is therefore blended with the dictionary's estimate of how the readings
   split in ordinary text (tools/generated/reading_shares.tsv), worth
   --prior-weight examples:
       confidence = (n_default + K * dict_share_default) / (n + K)
   Characters below --cutoff are listed with their two most likely readings,
   most likely first; the plugin can then show both ("chéng/shèng") or the
   first alone. (A default below 50% is not the most likely reading, so it
   is never kept silently: either it was hand-checked in overrides.tsv and
   the evidence agrees, or a pair is shown.)

3. Review lists, printed only (nothing is changed automatically): characters
   whose default disagrees with a strong train majority, and dictionary words
   whose reading disagrees with most train examples. CPP labels are sometimes
   wrong (黄陂 is Huángpí, not bēi), so every candidate needs checking against
   standard Mandarin before it goes into tools/overrides.tsv.

CPP labels spoken neutral tones (萝卜 bo); the plugin shows the toned reading
with the same letters (bó). Such a label counts as that toned reading here.
"""
import argparse
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cpp_dataset  # noqa: E402
from pinyin_util import is_toneless, strip_tone  # noqa: E402
from plugin_runtime import DEFAULT_PLUGIN, ROOT, Plugin  # noqa: E402

SHARES = os.path.join(ROOT, "tools", "generated", "reading_shares.tsv")


def load_shares(path=SHARES):
    """char -> (default, {reading: share}) for polyphonic annotatable characters."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            ch, default, pairs = line.rstrip("\n").split("\t")
            shares = {}
            for pair in pairs.split():
                r, v = pair.rsplit(":", 1)
                shares[r] = float(v)
            out[ch] = (default, shares)
    return out


def normalize_label(label, known):
    """A neutral-tone label (bo) counts as the toned reading with the same
    letters (bó), when the character has exactly one such reading."""
    if not is_toneless(label):
        return label
    matches = [r for r in known if r != label and strip_tone(r) == label]
    return matches[0] if len(matches) == 1 else label


def confidence(default, counts, dict_shares, k):
    """Blended share of the default, and the two most likely readings (most
    likely first); see the module docstring."""
    n = sum(counts.values())
    readings = set(counts) | set(dict_shares) | {default}
    prior = dict_shares or {default: 1.0}
    blended = {r: (counts.get(r, 0) + k * prior.get(r, 0.0)) / (n + k) for r in readings}
    # Ties keep the default first.
    ranked = sorted(readings, key=lambda r: (-blended[r], r != default))
    return blended.get(default, 0.0), ranked[0], (ranked[1] if len(ranked) > 1 else None)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plugin", default=DEFAULT_PLUGIN)
    ap.add_argument("--rule-min", type=int, default=5)
    ap.add_argument("--rule-purity", type=float, default=0.95)
    ap.add_argument("--prior-weight", type=float, default=20.0, help="K in the confidence formula")
    ap.add_argument("--cutoff", type=float, default=0.75,
                    help="list characters below this confidence (0.75: chosen from the train sweep, see README)")
    ap.add_argument("--no-write", action="store_true", help="report only")
    args = ap.parse_args()

    plugin = Plugin(args.plugin)
    shares = load_shares()
    data_dir = os.path.join(os.path.abspath(args.plugin), "data")

    examples = []           # (char, label, analysis)
    word_votes = defaultdict(Counter)
    for text, pos, ch, label in cpp_dataset.load("train"):
        a = plugin.analyze(text, pos)
        if not a:
            continue
        default, dict_shares = shares.get(ch, (a["default"], {}))
        label = normalize_label(label, set(dict_shares) | {default})
        examples.append((ch, label, a))
        if a["word"]:
            word_votes[(a["word"], ch, a["word_reading"])][label] += 1

    # 1. Context rules, from examples no dictionary word decides.
    side_counts = defaultdict(Counter)
    for ch, label, a in examples:
        if a["word"] or ch not in shares:
            continue
        if a["left"]:
            side_counts[(ch, "L", a["left"])][label] += 1
        if a["right"]:
            side_counts[(ch, "R", a["right"])][label] += 1
    rules = {}
    for key, counts in side_counts.items():
        n = sum(counts.values())
        reading, top = counts.most_common(1)[0]
        if n >= args.rule_min and top / n >= args.rule_purity:
            rules[key] = (reading, n)

    def rule_for(ch, a):
        l = rules.get((ch, "L", a["left"])) if a["left"] else None
        r = rules.get((ch, "R", a["right"])) if a["right"] else None
        if l and r and l[0] != r[0]:
            return r[0] if r[1] > l[1] else l[0]
        return (l or r)[0] if (l or r) else None

    # 2. Confidence where neither a word nor a rule decides.
    rest = defaultdict(Counter)
    for ch, label, a in examples:
        if not a["word"] and not rule_for(ch, a):
            rest[ch][label] += 1
    conf = {}
    for ch in set(rest) | set(shares):
        default, dict_shares = shares.get(ch, (None, {}))
        if default is None:
            # Not polyphonic in the dictionaries, but CPP labels it: use the
            # plugin's default with the dictionary prior on it.
            default = next(a["default"] for c, _, a in examples if c == ch)
        c, first, second = confidence(default, rest.get(ch, Counter()), dict_shares, args.prior_weight)
        if second:
            conf[ch] = (c, first, second)

    # Cutoff sweep on train (in-sample, so optimistic; the test split is the
    # honest measure).
    print("Confidence cutoff on train, where no word or rule decides "
          f"({sum(sum(c.values()) for c in rest.values()):,} examples):")
    print("  cutoff   correct shown   pairs shown")
    for cutoff in (0.0, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95):
        n = ok = pairs = 0
        for ch, counts in rest.items():
            c, first, second = conf.get(ch, (1.0, None, None))
            default = shares.get(ch, (None,))[0]
            pair = c < cutoff and second is not None
            for label, k in counts.items():
                n += k
                pairs += k * pair
                shown = {first, second} if pair else {default}
                ok += k * (label in shown or default is None)
        print(f"  {cutoff:6.2f}     {100 * ok / n:5.1f}%        {100 * pairs / n:5.1f}%")

    uncertain = sorted((ch, c, first, second) for ch, (c, first, second) in conf.items() if c < args.cutoff)
    print(f"\nContext rules: {len(rules):,} (min {args.rule_min} examples, purity {args.rule_purity:.0%}); "
          f"{sum(1 for (ch, _, _), (r, _) in rules.items() if r != shares[ch][0]):,} differ from the default")
    print(f"Uncertain characters (confidence < {args.cutoff:.0%}): {len(uncertain):,}")

    # 3. Review lists.
    print("\nDefault readings contradicted by train (>= 20 examples, >= 70% one other reading):")
    for ch, counts in sorted(rest.items(), key=lambda kv: -sum(kv[1].values())):
        n = sum(counts.values())
        top, k = counts.most_common(1)[0]
        default = shares.get(ch, (None,))[0] or next(a["default"] for c, _, a in examples if c == ch)
        if n >= 20 and k / n >= 0.7 and top != default:
            print(f"  {ch}  default {default:<7} train: " + ", ".join(f"{r} {v}" for r, v in counts.most_common(3))
                  + f"   dictionary shares: " + ", ".join(f"{r} {v:.2f}" for r, v in
                                                       sorted(shares.get(ch, (0, {}))[1].items(), key=lambda kv: -kv[1])[:3]))
    print("\nDictionary words contradicted by train (>= 3 examples, <= 30% agree):")
    for (word, ch, reading), counts in sorted(word_votes.items(), key=lambda kv: -sum(kv[1].values())):
        n = sum(counts.values())
        if n >= 3 and counts[reading] / n <= 0.3:
            print(f"  {word} ({ch} {reading}): " + ", ".join(f"{r} {v}" for r, v in counts.most_common(3)))

    if not args.no_write:
        with open(os.path.join(data_dir, "rules.tsv"), "w", encoding="utf-8") as f:
            for (ch, side, nb), (reading, n) in sorted(rules.items()):
                f.write(f"{ch}\t{side}\t{nb}\t{reading}\t{n}\n")
        with open(os.path.join(data_dir, "uncertain.tsv"), "w", encoding="utf-8") as f:
            for ch, c, first, second in uncertain:
                f.write(f"{ch}\t{c:.3f}\t{first}\t{second}\n")
        print(f"\nwrote {os.path.relpath(data_dir, ROOT)}/rules.tsv and uncertain.tsv")


if __name__ == "__main__":
    main()
