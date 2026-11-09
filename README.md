# koreader-interlinear-pinyin

A KOReader plugin that shows pinyin directly above rare Chinese characters, like the Kindle's pinyin display. Turn it on and off from the menu. The book file is never modified.

![Pinyin above the rare characters of 桃花源记 on a Boox Go 7](docs/screenshot.png)

<sub>桃花源记 on a Boox Go 7, showing characters outside the 2,500 most common. The text is in the bundled sample book, [`samples/guwen.epub`](samples/guwen.epub).</sub>

Status: **0.2.0**, tested on a Boox Go 7 (Android, 300 dpi) with KOReader v2026.07.1. Other devices should work but haven't been tried yet; reports are welcome.

## What it does

- Annotates only characters outside the N most common (choose 1,500 / 2,500 / 3,500 / 5,000 / 7,000; default 3,500). Simplified and traditional both work: a traditional character is ranked by its simplified form.
- Picks the reading from the surrounding word when the character has more than one reading: 侥 is *jiǎo* in 侥幸 but *yáo* in 僬侥; 莞 is *guǎn* in 东莞 but *wǎn* in 莞尔. When two words overlap (大宛 and 宛如 in 很大宛如雷鸣), the more common word wins. Otherwise it uses the character's most frequent reading.
- Shows the character's own tone where everyday speech uses a neutral tone: 刺猬 gives *wèi* over 猬, not *wei*.
- Annotates each character once per page: if 郡 appears five times on a page, only the first gets *jùn*. A repeat with a different reading is annotated again (刨 *páo* in 刨根, then *bào* in 刨子).
- Makes room between lines only while it is on. Turning it off restores the book's own spacing (KOReader re-lays out the book, which takes a moment).

### Choosing a threshold

The default (3,500) suits fluent readers: in typical modern prose most pages get no pinyin at all, and only genuinely rare characters are marked. Learners will probably prefer 1,500 or 2,500. Classical texts such as the sample book get many more annotations at every setting.

### Line spacing

The pinyin goes in the space between lines, so the plugin sets a line height that leaves room for it at the chosen pinyin size, taking KOReader's own line-spacing setting into account. What that costs depends on the book:

![The same page with the plugin off (left) and on (right)](docs/off-on.png)

<sub>Left: plugin off. Right: plugin on. The sample book sets no line height of its own, so the page loses about one line in thirteen.</sub>

- Books with tight or default spacing get noticeably more pages; how many depends on the pinyin size.
- Books that already set generous spacing can end up with *tighter* lines and fewer pages, because the plugin replaces the book's line height rather than adding to it. (A test book with `line-height: 2` went from 2,560 to 2,321 pages.)

## Install

1. Copy the `interlinearpinyin.koplugin` folder into KOReader's `plugins/` folder. On a Boox or other Android device that is `/storage/emulated/0/koreader/plugins/`; the final path must be `plugins/interlinearpinyin.koplugin/main.lua`.
2. Fully quit and restart KOReader.
3. Open an EPUB, then top menu → Tools (🔧) → **Interlinear pinyin** → **Show pinyin above rare characters**. The entry may be on the second page of the Tools menu.

To try it without a book of your own, copy [`samples/guwen.epub`](samples/guwen.epub) (古文三篇: 桃花源记, 陋室铭 and 爱莲说, all public domain) to the device.

## Menu

| Item | |
|---|---|
| Show pinyin above rare characters | On / off |
| Which characters | Frequency threshold (see above) |
| Pinyin size | 35–55% of the body text size (default 40%) |
| Status | Version, and how many characters on the current page were read and annotated |

## How it works

KOReader's rendering engine treats every CJK character as a one-character "word", so the plugin walks the page character by character (plus a few characters of context across the page edges), decides which characters are rare, resolves their readings, and only then asks the engine for their screen positions. This takes about 15–25 ms per page turn on a Boox Go 7. A paint layer draws the pinyin in the space between lines; that space comes from a `line-height` rule appended to the book's styles while the plugin is on.

Readings come from two tables in `interlinearpinyin.koplugin/data/`:

- `chars.tsv`: every annotatable character with its frequency rank and default (most frequent) reading.
- `words.tsv`: 2–4 character words containing a character with more than one reading, with each word's frequency. The longest word around a character decides its reading; among words of the same length, the more frequent one. The words come from CC-CEDICT and from pypinyin's phrase list, which adds names and literary words such as 冒顿 *mò dú* and 澹台 *tán tái*.

Rebuild them with `tools/build_data.py` (instructions in the script). Hand-checked corrections go in `tools/overrides.tsv`, which wins over both sources.

## Known limitations

- A character that stands alone, outside any dictionary word, gets its most frequent reading. This matters most in classical Chinese, where single-character words are common.
- Words split by markup (e.g. a character in its own `<span>`) are not matched across the boundary.
- The plugin replaces the book's line height instead of keeping it when it is already large enough (see [Line spacing](#line-spacing)).
- When a line is too crowded for all its pinyin, the most common characters' pinyin is dropped first. If that drops a character's first appearance on the page, later repeats are not annotated instead.
- PDFs and other fixed-layout formats are not supported.

## Tests

```
pip install lupa
python3 tests/run.py
```

The tests run under LuaJIT, the Lua that KOReader uses. Some `lupa` builds (for example on Apple Silicon Macs) don't include LuaJIT; the runner then falls back to Lua 5.1, which LuaJIT is compatible with, and says so.

The sample book is generated by `tools/make_sample_epub.py`.

## Credits and licenses

This plugin is a modified fork of **[WordGloss](https://github.com/GangYe293/wordgloss.koplugin)** by GangYe293 (GPL-3.0), forked and reduced to pinyin only in November 2026. The paint layer, layout and line-height injection come from WordGloss (`pinyin_overlay.lua`, `pinyin_layout.lua`, parts of `main.lua`, `pinyin_page.lua`). WordGloss credits its inline-gloss rendering approach to [inlinehints.koplugin](https://github.com/omer-faruq/inlinehints.koplugin) by omer-faruq.

The code is licensed under the **GNU General Public License v3.0**; see `LICENSE`.

The data files in `interlinearpinyin.koplugin/data/` are derived from:

- **[CC-CEDICT](https://www.mdbg.net/chinese/dictionary?page=cc-cedict)** (readings and words), © MDBG and contributors, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
- **[wordfreq](https://github.com/rspeer/wordfreq)** by Robyn Speer (character frequencies), data under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
- **[pypinyin](https://github.com/mozillazg/python-pinyin)** by mozillazg (its phrase list, for words CC-CEDICT lacks; and fallback readings for characters CC-CEDICT lacks), MIT License.

The data files are therefore distributed under **CC BY-SA 4.0**.

The texts in the sample book (陶渊明, 刘禹锡, 周敦颐) are in the public domain.
