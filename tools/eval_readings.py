#!/usr/bin/env python3
"""Measure how often the plugin shows the right reading.

    pip install lupa wordfreq
    python3 tools/eval_readings.py                    # test split, overall estimate, regression lists
    python3 tools/eval_readings.py --errors 30        # also sample mistakes
    python3 tools/eval_readings.py --plugin DIR       # evaluate another copy of the plugin (before/after)

Runs the plugin's own Lua code (pinyin_data.lua, pinyin_resolve.lua).

1. CPP polyphone dataset, **test split only** (see cpp_dataset.py for the data,
   its licence and the split; tools/learn_from_cpp.py learns from the train
   split, nothing here does). Only characters the plugin can annotate count.
   For each threshold:
     best guess   share right when one reading is shown ("Show best guess")
     both shown   share where the right reading is shown, counting either half
                  of a pair ("Show both readings", the default)
     pairs        how often a pair is shown
   and, at --threshold, what the context rules add (the same run with rules
   switched off).

   CPP labels spoken neutral tones (萝卜 bo); the plugin deliberately shows the
   toned reading with the same letters (bó), which counts as right.

2. Estimated overall accuracy: CPP contains only polyphonic characters, so its
   numbers are not what a reader sees. The estimate weights every character the
   plugin would draw at that threshold by how often it occurs in ordinary text
   (wordfreq), counts characters with a single reading as right, and uses each
   polyphonic character's test-split accuracy (or the pooled test accuracy at
   that threshold if the test split has no example of it). CPP is built to
   have many examples of each reading, so it over-represents minority
   readings, and the estimate leans pessimistic. (Re-weighting by how often
   each reading occurs was tried, but the dictionary-based reading shares are
   too noisy: they put 蹲 at 44% cún.)

3. Unusual readings (data/special.tsv): every test-split sentence whose
   labelled character is marked by a special word, common characters
   included, and how often the special reading agrees with the label.

4. tests/eval_cases.tsv (must all pass) and tests/eval_known_unhandled.tsv
   (reported only), at --threshold.

The plugin is run with special words on (its default) when the copy being
evaluated has them; --no-special turns them off.
"""
import argparse
import os
import sys
import unicodedata
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cpp_dataset  # noqa: E402
from learn_from_cpp import load_shares, normalize_label  # noqa: E402
from pinyin_util import is_han  # noqa: E402
from plugin_runtime import DEFAULT_PLUGIN, ROOT, Plugin  # noqa: E402

THRESHOLDS = (1500, 2500, 3500, 5000, 7000)


def shown_ok(label, shown):
    return shown is not None and label in shown.split("/")


def run_test(plugin, shares, mode):
    """[(char, label, rank, shown)] over the test split."""
    out = []
    for text, pos, ch, label in cpp_dataset.load("test"):
        r = plugin.reading(text, pos, mode)
        if r is None:
            # not annotatable, or skipped as uncertain ("skip" mode)
            rank_default = plugin.analyze(text, pos)
            if rank_default is None:
                continue
            rank, shown = rank_default["rank"], None
        else:
            shown, rank = r
        default, dict_shares = shares.get(ch, (None, {}))
        out.append((ch, normalize_label(label, set(dict_shares) | ({default} if default else set())
                                        | set((shown or "").split("/"))), rank, shown))
    return out


def summarize(rows, threshold):
    sel = [r for r in rows if r[2] == 0 or r[2] > threshold]
    n = len(sel)
    drawn = [r for r in sel if r[3] is not None]
    ok = sum(shown_ok(lb, s) for _, lb, _, s in drawn)
    pairs = sum("/" in s for _, _, _, s in drawn)
    return n, len(drawn), ok, pairs


def char_frequencies():
    import wordfreq
    freq = Counter()
    for word, f in wordfreq.get_frequency_dict("zh").items():
        for ch in word:
            if is_han(ch):
                freq[ch] += f
    return freq


def overall_estimate(rows, threshold, freq, chars, shares):
    """See the module docstring, point 2. Returns (accuracy, pair rate, skipped
    rate), weighted by how often each drawable character occurs."""
    sel = [r for r in rows if r[2] == 0 or r[2] > threshold]
    by_char = defaultdict(list)
    for ch, label, _, shown in sel:
        by_char[ch].append((label, shown))

    def rates(examples):
        n = len(examples)
        return (sum(shown_ok(lb, s) for lb, s in examples) / n,
                sum(s is not None and "/" in s for _, s in examples) / n,
                sum(s is None for _, s in examples) / n)

    pooled = rates([(lb, s) for _, lb, _, s in sel]) if sel else (1.0, 0.0, 0.0)
    total = right = pairs = skipped = 0.0
    for ch, (rank, _) in chars.items():
        if not (rank == 0 or rank > threshold):
            continue
        f = freq.get(ch, 0.0)
        if f == 0:
            continue
        total += f
        if ch not in shares:  # one reading: always right
            right += f
            continue
        acc, pr, sk = rates(by_char[ch]) if ch in by_char else pooled
        right += f * acc
        pairs += f * pr
        skipped += f * sk
    return right / total, pairs / total, skipped / total


def special_report(plugin, shares):
    """Point 3 of the module docstring."""
    if plugin.special is None:
        print("  Unusual readings: none (this copy of the plugin has no data/special.tsv, or --no-special)")
        return
    n = ok = 0
    wrong = Counter()
    for text, pos, ch, label in cpp_dataset.load("test"):
        hit = plugin.special_at(text, pos)
        if not hit or not hit[2]:
            continue
        word, reading, _ = hit
        default, dict_shares = shares.get(ch, (None, {}))
        label = normalize_label(label, set(dict_shares) | {reading} | ({default} if default else set()))
        n += 1
        if label == reading:
            ok += 1
        else:
            wrong[(word, ch, reading, label)] += 1
    print(f"  Unusual readings marked on the test split: {n}, agreeing with the label: {ok}"
          + (f" ({100 * ok / n:.1f}%)" if n else ""))
    for (word, ch, reading, label), k in wrong.most_common(10):
        print(f"    {word}: {ch} shown {reading}, labelled {label} ({k}x)")


def check_cases(plugin, path, threshold, label):
    total = passed = 0
    failures = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            sentence, expected = line.split("\t")[:2]
            got = dict(a.split("=", 1) for a in plugin.annotate(sentence, threshold).split())
            for item in expected.split():
                char, want = item.split("=", 1)
                total += 1
                have = got.get(char, "-")
                if have == unicodedata.normalize("NFC", want):
                    passed += 1
                else:
                    failures.append(f"{sentence}: {char} expected {want}, got {have}")
    print(f"{label} ({os.path.relpath(path, ROOT)}, threshold {threshold:,}): {passed}/{total} pass")
    for failure in failures:
        print("  FAIL " + failure)
    return passed, total


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plugin", default=DEFAULT_PLUGIN)
    ap.add_argument("--threshold", type=int, default=2500,
                    help="for the rules comparison, error samples and regression lists (default 2500)")
    ap.add_argument("--errors", type=int, default=0, help="show this many sample errors")
    ap.add_argument("--no-cpp", action="store_true", help="only the regression lists")
    ap.add_argument("--no-special", action="store_true", help="unusual readings (data/special.tsv) off")
    args = ap.parse_args()

    plugin = Plugin(args.plugin, special=not args.no_special)
    if not args.no_cpp:
        shares = load_shares()
        rows = {mode: run_test(plugin, shares, mode) for mode in ("both", "best", "skip")}
        print(f"CPP test split: {len(rows['best']):,} labelled characters the plugin can annotate")
        print()
        print("  threshold    n    best guess   both shown   pairs  | skip uncertain: drawn  right")
        for t in THRESHOLDS:
            n, _, ok_best, _ = summarize(rows["best"], t)
            _, _, ok_both, pairs = summarize(rows["both"], t)
            _, drawn_skip, ok_skip, _ = summarize(rows["skip"], t)
            pct = lambda a, b: f"{100 * a / b:5.1f}%" if b else "   - "  # noqa: E731
            print(f"  {t:>9,}  {n:>5,}   {pct(ok_best, n)}       {pct(ok_both, n)}      {pct(pairs, n)} |"
                  f"         {pct(drawn_skip, n)}  {pct(ok_skip, drawn_skip)}")

        # Rules on/off at --threshold.
        plugin.lua.execute("local d = ...; d.rules = {}", plugin.data)
        no_rules = {mode: run_test(plugin, shares, mode) for mode in ("both", "best")}
        plugin = Plugin(args.plugin, special=not args.no_special)
        n, _, ok_best, _ = summarize(rows["best"], args.threshold)
        _, _, ok_best_nr, _ = summarize(no_rules["best"], args.threshold)
        _, _, ok_both, pairs = summarize(rows["both"], args.threshold)
        _, _, ok_both_nr, pairs_nr = summarize(no_rules["both"], args.threshold)
        print()
        print(f"  Context rules at {args.threshold:,}: best guess {100 * ok_best_nr / n:.1f}% -> {100 * ok_best / n:.1f}%, "
              f"both shown {100 * ok_both_nr / n:.1f}% -> {100 * ok_both / n:.1f}%, "
              f"pairs {100 * pairs_nr / n:.1f}% -> {100 * pairs / n:.1f}%")

        # Overall estimate.
        freq = char_frequencies()
        chars = {}
        lua_chars = plugin.data.chars
        for ch in lua_chars:
            entry = lua_chars[ch]
            chars[ch] = (int(entry[1]), entry[2])
        print()
        print("  Estimated overall accuracy of what is drawn, in ordinary text:")
        print("  threshold   best guess   both shown (pairs)   skip uncertain (skipped)")
        for t in THRESHOLDS:
            cells = []
            for mode in ("best", "both", "skip"):
                cells.append(overall_estimate(rows[mode], t, freq, chars, shares))
            (a1, _, _), (a2, p2, _), (a3, _, s3) = cells
            print(f"  {t:>9,}    {100 * a1:6.2f}%      {100 * a2:6.2f}% ({100 * p2:4.2f}%)"
                  f"      {100 * a3 / (1 - s3):6.2f}% ({100 * s3:4.2f}%)")

        if args.errors:
            print()
            print(f"  Sample errors at {args.threshold:,}, both shown (char, expected, shown):")
            shown_n = 0
            for ch, label, rank, shown in rows["both"]:
                if (rank == 0 or rank > args.threshold) and not shown_ok(label, shown):
                    print(f"    {ch}  {label:<7} {shown}")
                    shown_n += 1
                    if shown_n >= args.errors:
                        break
        print()
        special_report(plugin, shares)
        print()

    check_cases(plugin, os.path.join(ROOT, "tests", "eval_cases.tsv"), args.threshold, "Regression list")
    check_cases(plugin, os.path.join(ROOT, "tests", "eval_known_unhandled.tsv"), args.threshold,
                "Known, not handled")


if __name__ == "__main__":
    main()
