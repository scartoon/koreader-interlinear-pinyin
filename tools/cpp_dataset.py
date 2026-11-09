"""The CPP polyphone dataset, downloaded on demand (never stored in this repo).

CPP ("Chinese Polyphones with Pinyin") comes from Park & Lee, "A Neural
Grapheme-to-Phoneme Conversion Package for Mandarin Chinese Based on a New Open
Benchmark Dataset", Interspeech 2020, https://github.com/kakaobrain/g2pM (the
g2pW project downloads the same files from there).

Licence: the g2pM repository is Apache-2.0, but the dataset's sentences were
collected from Chinese Wikipedia (CC BY-SA) and the repository states no
separate licence for the data. Because that is not clearly permissive, the
files are downloaded at run time into ~/.cache/interlinear-pinyin/cpp and are
not committed.

Each sentence has one polyphonic character between ▁ marks and a numbered-pinyin
label. The dataset has an official split, which we keep strictly apart:
  train (79,117 sentences)  everything we learn or tune: tools/learn_from_cpp.py
  test  (10,254 sentences)  the only split accuracy is reported on: tools/eval_readings.py
  dev   ( 9,893 sentences)  unused
"""
import os
import sys
import unicodedata
import urllib.request

from pinyin_util import numbered_to_marked

URL = "https://github.com/kakaobrain/g2pM/raw/master/data/{name}"
CACHE = os.path.join(os.path.expanduser("~"), ".cache", "interlinear-pinyin", "cpp")
MARK = "▁"


def fetch(split):
    os.makedirs(CACHE, exist_ok=True)
    for ext in ("sent", "lb"):
        path = os.path.join(CACHE, f"{split}.{ext}")
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            print(f"downloading CPP {split}.{ext} ...", file=sys.stderr)
            urllib.request.urlretrieve(URL.format(name=f"{split}.{ext}"), path + ".part")
            os.replace(path + ".part", path)


def load(split):
    """Yield (sentence, index of the labelled character, character, marked reading)."""
    fetch(split)
    with open(os.path.join(CACHE, f"{split}.sent"), encoding="utf-8") as f:
        sents = [line.rstrip("\n") for line in f]
    with open(os.path.join(CACHE, f"{split}.lb"), encoding="utf-8") as f:
        labels = [line.strip() for line in f]
    assert len(sents) == len(labels), f"{split}: {len(sents)} sentences but {len(labels)} labels"
    for sent, label in zip(sents, labels):
        before, char, after = sent.split(MARK)
        yield before + char + after, len(before), char, unicodedata.normalize("NFC", numbered_to_marked(label))
