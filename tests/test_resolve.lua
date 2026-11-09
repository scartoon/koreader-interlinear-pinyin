-- Offline tests for the character/word tables and reading logic.
-- Run with:  python3 tests/run.py   (needs `pip install lupa`)

local Data = require("pinyin_data")
local Resolve = require("pinyin_resolve")

local data = assert(Data.load(PLUGIN_DIR .. "/data"))

-- Turn a string into engine-like items: one item per Han character;
-- punctuation and spaces are not items but break the "joined" chain,
-- as they do in the rendering engine. "|" marks the page start/end.
local function items_of(text)
    local items, joined, on_page = {}, false, true
    if text:find("|", 1, true) then on_page = false end
    for ch in text:gmatch("[%z\1-\127\194-\244][\128-\191]*") do
        if ch == "|" then
            on_page = not on_page
            -- a page boundary does not break a word
        elseif Resolve.single_char(ch) and not ch:match("^[\227][\128][\128-\191]$") and ch ~= "，" and ch ~= "。" and ch ~= "！" and ch ~= "？" and ch ~= "；" and ch ~= "：" then
            items[#items + 1] = { text = ch, joined = joined, on_page = on_page }
            joined = true
        else
            joined = false
        end
    end
    return items
end

local function readings(text, threshold)
    local items = items_of(text)
    local out = {}
    for _, a in ipairs(Resolve.annotate(data, items, threshold or 3500)) do
        out[#out + 1] = items[a.index].text .. "=" .. a.reading
    end
    return table.concat(out, " ")
end

-- Parsing must not depend on the locale: "à" ends in byte 0xA0, which some
-- C locales treat as a space.
do
    local syllables, freq = data:word("大宛")
    assert(syllables and #syllables == 2 and syllables[1] == "dà" and syllables[2] == "yuān",
        "大宛 parsed as " .. table.concat(syllables or {}, "|"))
    assert(freq and freq > 0, "大宛 has no frequency")
    syllables = data:word("刨子")
    assert(syllables and #syllables == 2 and syllables[1] == "bào", "刨子 parsed wrongly")
end

local failures, passed = 0, 0
local function expect(text, threshold, want)
    local got = readings(text, threshold)
    if got == want then
        passed = passed + 1
    else
        failures = failures + 1
        print(("FAIL  %s  (threshold %d)\n      want: %s\n      got:  %s"):format(text, threshold, want, got))
    end
end

-- Rare monophonic characters: default reading.
expect("饕餮之徒", 3500, "饕=tāo 餮=tiè")
expect("踟蹰不前", 3500, "踟=chí 蹰=chú")
expect("踟躕不前", 3500, "踟=chí 躕=chú")            -- traditional
expect("岁月蹉跎", 3500, "蹉=cuō 跎=tuó")

-- Polyphonic rare characters resolved by the word around them.
expect("他侥幸逃脱了", 3500, "侥=jiǎo")
expect("僬侥之国", 3500, "僬=jiāo 侥=yáo")
expect("莞尔一笑", 2500, "莞=wǎn")
expect("他住在东莞", 2500, "莞=guǎn")
expect("吐蕃王朝", 2500, "蕃=bō")
expect("刨根问底", 3500, "刨=páo")
expect("用刨子刨平", 3500, "刨=bào")                 -- second 刨, same reading: not repeated

-- Once per page: a repeated character is annotated only the first time,
-- unless it has a different reading the second time.
expect("饕餮之徒，饕餮之徒", 3500, "饕=tāo 餮=tiè")
expect("刨根问底，用刨子", 3500, "刨=páo 刨=bào")
expect("刨根问底，用刨子，刨根", 3500, "刨=páo 刨=bào")
-- Only on-page occurrences count: one in the context before the page does not
-- stop the first on-page one from being annotated.
expect("饕|饕餮|", 3500, "饕=tāo 餮=tiè")

-- Overlapping words of the same length: the more frequent one wins
-- (宛如 over 大宛), not the leftmost.
expect("声音很大宛如雷鸣", 2500, "宛=wǎn")
expect("张骞出使大宛", 2500, "骞=qiān 宛=yuān")

-- Neutral tones in CC-CEDICT (刺猬 cì wei) give way to the character's own tone.
expect("一只刺猬", 3500, "猬=wèi")

-- Words from pypinyin's phrase list that CC-CEDICT lacks or reads differently.
expect("澹台灭明", 3500, "澹=tán")

-- Punctuation breaks a word: 侥。幸 must not match 侥幸.
expect("僬侥。幸", 3500, "僬=jiāo 侥=yáo")

-- Common text: nothing at the default threshold.
expect("臣闻求木之长者，必固其根本", 3500, "")

-- Threshold: 莞 (rank ~2700) appears only when the threshold is below it.
expect("莞尔一笑", 3500, "")

-- Page boundary: context outside the page resolves the word but is not annotated.
expect("他侥|幸逃脱|", 3500, "")
expect("僬|侥之国|", 3500, "侥=yáo")

print(("%d passed, %d failed"):format(passed, failures))
if failures > 0 then error("tests failed") end
