# koreader-interlinear-pinyin

A KOReader plugin that shows pinyin directly above rare Chinese characters, like the Kindle's pinyin display. Turn it on and off from the menu. The book file is never modified.

Status: **0.1.0, untested on a device.** The reading logic is tested offline; how it looks on an e-ink screen still needs tuning.

## What it does

- Annotates only characters outside the N most common (choose 1,500 / 2,500 / 3,500 / 5,000 / 7,000; default 3,500). Simplified and traditional both work: a traditional character is ranked by its simplified form.
- Picks the reading from the surrounding word when the character has more than one reading: 侥 is *jiǎo* in 侥幸 but *yáo* in 僬侥; 莞 is *guǎn* in 东莞 but *wǎn* in 莞尔. Otherwise it uses the character's most frequent reading.
- Adds line spacing only while it is on. Turning it off restores the book's normal spacing (KOReader re-lays out the book, which takes a moment).

## Install

1. Copy the `interlinearpinyin.koplugin` folder into KOReader's `plugins/` folder. On a Boox or other Android device that is `/storage/emulated/0/koreader/plugins/`; the final path must be `plugins/interlinearpinyin.koplugin/main.lua`.
2. Fully quit and restart KOReader.
3. Open an EPUB, then top menu → Tools → **Interlinear pinyin** → **Show pinyin above rare characters**.

## Menu

| Item | |
|---|---|
| Show pinyin above rare characters | On / off |
| Which characters | Frequency threshold |
| Pinyin size | 35–55% of the body text size |
| Status | Version, and how many characters on the current page were read and annotated |

## How it works

KOReader's rendering engine treats every CJK character as a one-character "word", so the plugin walks the page character by character (plus a few characters of context across the page edges), decides which characters are rare, resolves their readings, and only then asks the engine for their screen positions. A paint layer draws the pinyin in the space between lines; that space comes from a `line-height` rule appended to the book's styles while the plugin is on.

Readings come from two tables in `interlinearpinyin.koplugin/data/`:

- `chars.tsv`: every annotatable character with its frequency rank and default (most frequent) reading.
- `words.tsv`: 2–4 character words containing a character with more than one reading. The longest word around a character decides its reading.

Rebuild them with `tools/build_data.py` (instructions in the script).

## Known limitations

- A character that stands alone, outside any dictionary word, gets its most frequent reading. This matters most in classical Chinese, where single-character words are common.
- Words split by markup (e.g. a character in its own `<span>`) are not matched across the boundary.
- PDFs and other fixed-layout formats are not supported.

## Tests

```
pip install lupa
python3 tests/run.py
```

## Credits and licenses

This plugin is a modified fork of **[WordGloss](https://github.com/GangYe293/wordgloss.koplugin)** by GangYe293 (GPL-3.0), forked and reduced to pinyin only in November 2026. The paint layer, layout and line-height injection come from WordGloss (`pinyin_overlay.lua`, `pinyin_layout.lua`, parts of `main.lua`, `pinyin_page.lua`). WordGloss credits its inline-gloss rendering approach to [inlinehints.koplugin](https://github.com/omer-faruq/inlinehints.koplugin) by omer-faruq.

The code is licensed under the **GNU General Public License v3.0**; see `LICENSE`.

The data files in `interlinearpinyin.koplugin/data/` are derived from:

- **[CC-CEDICT](https://www.mdbg.net/chinese/dictionary?page=cc-cedict)** (readings and words), © MDBG and contributors, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
- **[wordfreq](https://github.com/rspeer/wordfreq)** by Robyn Speer (character frequencies), data under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
- **[pypinyin](https://github.com/mozillazg/python-pinyin)** by mozillazg (fallback readings for characters CC-CEDICT lacks), MIT License.

The data files are therefore distributed under **CC BY-SA 4.0**.
