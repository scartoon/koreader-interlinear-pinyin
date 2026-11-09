-- Unusual readings of common characters (data/special.tsv): matching, the
-- overlap guard, annotation and the popup.
local Data = require("pinyin_data")
local Resolve = require("pinyin_resolve")
local Defs = require("pinyin_defs")
local data = assert(Data.load(PLUGIN_DIR .. "/data"))
local special = assert(Data.loadSpecial(PLUGIN_DIR .. "/data"))
assert(special.count > 100 and special.guard_count > 1000, "special data looks empty")
assert(Data.loadSpecial(PLUGIN_DIR .. "/data") == special, "loaded once per session")
assert(Data.loadSpecial("/nonexistent") == nil, "missing file must not raise")

local function items_of(text)
    local items = {}
    for ch in text:gmatch("[%z\1-\127\194-\244][\128-\191]*") do
        local han = Resolve.single_char(ch) and not ch:match("^\227\128") and not ch:match("^\239\188")
        if han then
            items[#items + 1] = { text = ch, joined = #items > 0 and items[#items].han_run_end == nil }
        else
            -- punctuation, digits, Latin: break the run
            if #items > 0 then items[#items].han_run_end = true end
        end
    end
    return items
end

-- "char=reading" for what is drawn ("*" after an unusual reading).
local function annotate(text, threshold, sp)
    local items = items_of(text)
    local out = {}
    for _, a in ipairs(Resolve.annotate(data, items, threshold or 2500, nil, sp == nil and special or sp or nil)) do
        out[#out + 1] = items[a.index].text .. "=" .. a.reading .. (a.special and "*" or "")
    end
    return table.concat(out, " ")
end

local function expect(text, want, threshold)
    local got = annotate(text, threshold)
    assert(got == want, string.format("%s: expected '%s', got '%s'", text, want, got))
end

-- Only the characters whose reading is unusual: nothing over 于.
expect("冒顿单于", "冒=mò* 顿=dú* 单=chán*")
expect("公元前200年冒顿单于率40万骑兵南下", "冒=mò* 顿=dú* 单=chán*")
expect("匈奴单于", "单=chán*")
expect("单于率", "单=chán*")
-- 于是 crosses 单于 but the split 单于|是 is far likelier than 单|于是.
expect("冒顿单于是匈奴的首领", "冒=mò* 顿=dú* 单=chán*")
expect("大可汗", "可=kè* 汗=hán*")

-- The overlap guard: 订单 + 于, not 订 + 单于.
expect("订单于3日发货", "")
expect("名单于", "")
expect("菜单于", "")
expect("简单于", "")
expect("事情很简单于是我们走了", "")
expect("他去洗马桶", "")
expect("太子洗马", "洗=xiǎn*")

-- Rare characters inside a special word are annotated as usual (郦 lì, 磾 dī),
-- with the special word's reading; common ones only when marked.
expect("郦食其", "郦=lì 食=yì* 其=jī*")
expect("金日磾", "日=mì* 磾=dī")
expect("会稽山", "会=kuài* 稽=jī")

-- Marked characters are annotated at any threshold.
expect("冒顿单于", "冒=mò* 顿=dú* 单=chán*", 1500)
expect("冒顿单于", "冒=mò* 顿=dú* 单=chán*", 7000)

-- Setting off (no special table): nothing changes from before.
assert(annotate("冒顿单于", 2500, false) == "", "special words used with the setting off")

-- Once per page per (character, reading), as for other annotations.
expect("单于来了，单于走了", "单=chán*")

-- Logic on a hand-made table: a rare character inside a special word takes
-- the special word's reading, not the resolver's; the longest word wins.
do
    local function entry(word, pinyin, marks, freq)
        local chars, syllables, flags = {}, {}, {}
        for ch in word:gmatch("[%z\1-\127\194-\244][\128-\191]*") do chars[#chars + 1] = ch end
        for syl in pinyin:gmatch("[^ ]+") do syllables[#syllables + 1] = syl end
        for k = 1, #marks do flags[k] = marks:sub(k, k) == "1" end
        return { word = word, chars = chars, syllables = syllables, marks = flags, freq = freq or 0 }
    end
    local fake = { by_first = {}, guard = {}, max_len = 3, count = 3 }
    local function add(e)
        fake.by_first[e.chars[1]] = fake.by_first[e.chars[1]] or {}
        table.insert(fake.by_first[e.chars[1]], e)
    end
    add(entry("饕餮", "tǎo tiè", "10"))          -- 饕 is rare: tāo normally
    add(entry("大学", "dài xué", "10"))
    add(entry("大学生", "dà xué shēng", "000"))  -- longer, nothing marked
    local items = items_of("饕餮")
    local a = Resolve.annotate(data, items, 2500, nil, fake)
    assert(a[1].reading == "tǎo" and a[1].special and a[1].match.special.word == "饕餮")
    assert(a[2].reading == "tiè" and not a[2].special)
    -- 大学生: the longer word covers 大 and marks nothing, so 大 stays bare.
    assert(#Resolve.annotate(data, items_of("大学生"), 2500, nil, fake) == 0)
    assert(Resolve.annotate(data, items_of("大学"), 2500, nil, fake)[1].reading == "dài")
    -- The guard blocks only at the offset it names.
    fake.guard["上大\t大学\t-1"] = true
    assert(#Resolve.annotate(data, items_of("上大学"), 2500, nil, fake) == 0, "guard at -1")
    assert(#Resolve.annotate(data, items_of("大学上大"), 2500, nil, fake) == 1, "guard elsewhere")
end

-- The popup: CC-CEDICT's entry when it has one (单于 is in defs.tsv although
-- 单 and 于 are common), else the curated note (CC-CEDICT has no 冒顿).
local defs = assert(Defs.open(PLUGIN_DIR .. "/data/defs.tsv"))
local function gloss_for(text, char)
    local items = items_of(text)
    for _, a in ipairs(Resolve.annotate(data, items, 2500, nil, special)) do
        if items[a.index].text == char then
            local m = a.match
            local left, right = {}, {}
            for k = math.max(1, a.index - 3), a.index - 1 do left[#left + 1] = items[k].text end
            for k = a.index + 1, math.min(#items, a.index + 3) do right[#right + 1] = items[k].text end
            return { char = char, text = a.reading, special = a.special,
                     match = m and m.special and { word = m.word, others = {}, note = m.special.note,
                                                   pinyin = table.concat(m.special.syllables, " ") },
                     context = { left = left, right = right } }
        end
    end
    error(char .. " not annotated in " .. text)
end
local g = gloss_for("匈奴单于", "单")
local model = Defs.describe(defs, g)
assert(model.word and model.word.text == "单于" and model.word.found, "单于 from CC-CEDICT")
local text = Defs.render(model)
assert(text:find("Word: 单于  chán yú\nking of the Xiongnu"), text)
assert(model.char_found and model.readings[1].pinyin == "chán" and model.readings[1].chosen, text)
g = gloss_for("冒顿单于", "冒")
-- the longest special word wins: 冒顿单于 (curated, with a note)
model = Defs.describe(defs, g)
text = Defs.render(model)
assert(model.word.text == "冒顿单于" and not model.word.found, text)
assert(text:find("Word: 冒顿单于  mò dú chán yú\nModu Chanyu, Xiongnu ruler"), text)
assert(not Defs.empty(model))
g = gloss_for("冒顿", "顿")
text = Defs.render(Defs.describe(defs, g))
assert(text:find("Word: 冒顿  mò dú\nModu, Xiongnu ruler"), text)
defs:close()

print("special readings: ok")
