"""Pinyin helpers shared by build_data.py and eval_readings.py (no dependencies)."""
import unicodedata


def is_han(ch):
    cp = ord(ch)
    return (0x3400 <= cp <= 0x4DBF or 0x4E00 <= cp <= 0x9FFF or
            0xF900 <= cp <= 0xFAFF or 0x20000 <= cp <= 0x3134F)


VOWELS = "aeiouü"
MARKS = {
    "a": "āáǎà", "e": "ēéěè", "i": "īíǐì",
    "o": "ōóǒò", "u": "ūúǔù", "ü": "ǖǘǚǜ",
}


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
