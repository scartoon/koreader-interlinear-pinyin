-- CC-CEDICT lookups (binary search in data/defs.tsv) and popup content.
local Defs = require("pinyin_defs")
local Data = require("pinyin_data")
local Resolve = require("pinyin_resolve")
local data = assert(Data.load(PLUGIN_DIR .. "/data"))
local defs = assert(Defs.open(PLUGIN_DIR .. "/data/defs.tsv"))

-- Binary search: every line of a sample is found, absent keys are not.
do
    local f = assert(io.open(PLUGIN_DIR .. "/data/defs.tsv", "rb"))
    local n, checked, first, last = 0, 0, nil, nil
    for line in f:lines() do
        n = n + 1
        local key = line:match("^([^\t]*)")
        first = first or key
        last = key
        if n % 997 == 1 then
            assert(defs:line(key) == line, "binary search missed " .. key)
            checked = checked + 1
        end
    end
    f:close()
    assert(defs:line(first) and defs:line(last), "first/last line")
    assert(checked > 50)
    for _, absent in ipairs({ "", "a", "的", "\255", "饕餮饕餮饕" }) do
        assert(not defs:line(absent), "found absent key " .. absent)
    end
end

local function entry(key)
    local e = assert(defs:lookup(key), "no entry for " .. key)
    return e
end
assert(entry("饕").entries[1].pinyin == "tāo")
assert(entry("饕餮").freq > 0)
assert(entry("僥").entries[1], "traditional form present")

-- Cross-references are readable; a character's own variant line is dropped.
local function all_senses(key)
    local out = {}
    for _, e in ipairs(entry(key).entries) do
        for _, s in ipairs(e.senses) do out[#out + 1] = s end
    end
    return table.concat(out, " | ")
end
assert(not all_senses("乘"):find("variant of 乘"), "self-reference kept: " .. all_senses("乘"))
assert(not all_senses("乘"):find("%["), "raw [pinyin] left in 乘")

local function gloss(text, char, threshold)
    -- Resolve a phrase and return the gloss for `char`, as Page.build makes it.
    local items = {}
    for ch in text:gmatch("[%z\1-\127\194-\244][\128-\191]*") do
        items[#items + 1] = { text = ch, joined = #items > 0 }
    end
    for _, a in ipairs(Resolve.annotate(data, items, threshold or 3500)) do
        local it = items[a.index]
        if it.text == char then
            local m = a.match
            local match
            if m then
                local function py(w) return table.concat(data:word(w), " ") end
                match = { word = m.word, pinyin = py(m.word), others = {} }
                for _, o in ipairs(m.others) do match.others[#match.others + 1] = { word = o.word, pinyin = py(o.word) } end
            end
            local left, right = {}, {}
            for k = math.max(1, a.index - 3), a.index - 1 do left[#left + 1] = items[k].text end
            for k = a.index + 1, math.min(#items, a.index + 3) do right[#right + 1] = items[k].text end
            return { char = it.text, text = a.reading, match = match, context = { left = left, right = right } }
        end
    end
    error(char .. " not annotated in " .. text)
end

-- Overlapping words: 宛如 wins over 大宛, which is "also possible".
local g = gloss("声音很大宛如雷鸣", "宛", 2500)
assert(g.text == "wǎn" and g.match.word == "宛如", "宛如 wins")
local model = Defs.describe(defs, g)
assert(model.readings[1].pinyin == "wǎn" and model.readings[1].chosen, "chosen reading first")
local text = Defs.render(model)
-- One reading (the surname entry merges into wǎn), so no "(shown above)".
assert(text:find("^wǎn\nsurname Wan / winding / as if"), text)
assert(text:find("Word: 宛如  wǎn rú\nto be just like"), text)
assert(text:find("Also possible: 大宛  dà yuān\nancient state of central Asia"), text)
assert(text:find("Word:") < text:find("Also possible:"))

-- A reading CC-CEDICT lists only inside a word: shown first, marked, noted.
g = gloss("张骞出使大宛", "宛", 2500)
assert(g.text == "yuān" and g.match.word == "大宛" and #g.match.others == 0)
model = Defs.describe(defs, g)
assert(model.readings[1].pinyin == "yuān" and model.readings[1].chosen)
assert(model.readings[2].pinyin == "wǎn" and not model.readings[2].chosen)
text = Defs.render(model)
assert(text:find("^yuān   %(shown above%)\nno separate CC%-CEDICT entry for this reading"), text)
assert(text:find("Word: 大宛  dà yuān") and not text:find("Also possible"), text)
assert(not Defs.empty(model))

-- Monophonic rare character: the word comes from CC-CEDICT with the
-- resolver's own matching (words.tsv has no 饕餮).
g = gloss("饕餮之徒", "饕")
assert(g.match == nil)
model = Defs.describe(defs, g)
assert(model.word and model.word.text == "饕餮之徒" and not model.word_from_resolver, "fallback word (longest)")
assert(Defs.render(model):find("Word: 饕餮之徒  tāo tiè zhī tú"))
g = gloss("饕餮盛宴", "饕")
assert(Defs.describe(defs, g).word.text == "饕餮")
-- ... but not when the word's reading of the character differs from the
-- one shown: no word section.
g = { char = "饕", text = "tǎo", context = { left = {}, right = { "餮" } } }
assert(Defs.describe(defs, g).word == nil, "contradicting word must not be shown")
-- Alone: no word section.
g = { char = "饕", text = "tāo", context = { left = {}, right = {} } }
assert(Defs.describe(defs, g).word == nil)

-- Uncertain pair: both readings marked, most likely first.
model = Defs.describe(defs, { char = "乘", text = "chéng/shèng", context = {} })
assert(model.readings[1].pinyin == "chéng" and model.readings[1].chosen)
assert(model.readings[2].pinyin == "shèng" and model.readings[2].chosen)

-- A word with no CC-CEDICT entry (e.g. from pypinyin's phrase list).
model = Defs.describe(defs, { char = "饕", text = "tāo", match = { word = "饕饕", pinyin = "tāo tāo", others = {} } })
assert(model.word and not model.word.found)
assert(Defs.render(model):find("Word: 饕饕  tāo tāo\nno definition in CC%-CEDICT"))
assert(not Defs.empty(model), "character still has an entry")

-- Neither character nor word in CC-CEDICT: KOReader's lookup is used instead.
model = Defs.describe(defs, { char = "\240\170\154\178", text = "x", match = { word = "\240\170\154\178\240\170\154\178", pinyin = "x x", others = {} } })
assert(Defs.empty(model), "no data should fall back to KOReader")

-- A single reading is not marked: there is nothing to choose between.
text = Defs.render(Defs.describe(defs, { char = "饕", text = "tāo", context = { left = {}, right = {} } }))
assert(text:find("^tāo\n") and not text:find("shown above"), text)

-- Capital tone vowels lower-case properly.
assert(Defs.lower("Ēr Ǎ") == "ēr ǎ")

defs:close()
print("definitions: ok")
