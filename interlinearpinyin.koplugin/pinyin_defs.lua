-- CC-CEDICT definitions for the tap popup (pure Lua, no KOReader
-- dependencies, so it can be tested offline).
--
-- data/defs.tsv has one line per key (a character or a 2-4 character word):
--   key <TAB> frequency <TAB> pinyin <TAB> senses [<TAB> pinyin <TAB> senses ...]
-- senses are '/'-separated. Lines are sorted by the key's bytes, so a key is
-- found by binary search with seek(): the 7-8 MB file is never loaded, and
-- nothing is read until the first tap.

local Resolve = require("pinyin_resolve")

local Defs = {}
Defs.__index = Defs

-- Open the file (nothing is read yet). nil, err when it is missing.
function Defs.open(path)
    local f = io.open(path, "rb")
    if not f then return nil, "missing " .. path end
    local size = f:seek("end")
    return setmetatable({ file = f, size = size, cache = {} }, Defs)
end

function Defs:close()
    if self.file then self.file:close() end
    self.file = nil
end

-- Byte-wise comparison, independent of the C library's collation locale
-- (plain `<` on strings uses strcoll in PUC Lua).
local function less(a, b)
    local n = math.min(#a, #b)
    for k = 1, n do
        local x, y = a:byte(k), b:byte(k)
        if x ~= y then return x < y end
    end
    return #a < #b
end

-- The raw line for key, or nil.
function Defs:line(key)
    local f = self.file
    if not f then return nil end
    -- Invariant: if key's line exists, it starts in [lo, hi).
    local lo, hi = 0, self.size
    while lo < hi do
        local mid = math.floor((lo + hi) / 2)
        local start = 0
        if mid > 0 then
            f:seek("set", mid - 1)
            f:read("*l")             -- rest of the line containing byte mid-1
            start = f:seek("cur")    -- first line start >= mid
        else
            f:seek("set", 0)
        end
        if start >= hi then
            hi = mid
        else
            local line = f:read("*l")
            if not line then
                hi = mid
            else
                local k = line:match("^([^\t]*)")
                if k == key then return line end
                if less(k, key) then
                    lo = start + #line + 1
                else
                    hi = mid
                end
            end
        end
    end
    return nil
end

local function split(s, sep)
    local out = {}
    for part in (s .. sep):gmatch("(.-)" .. sep) do out[#out + 1] = part end
    return out
end

-- { freq=, entries = { {pinyin="Dà Yuān", senses={...}}, ... } } or false.
function Defs:lookup(key)
    local cached = self.cache[key]
    if cached ~= nil then return cached end
    local line = self:line(key)
    local result = false
    if line then
        local fields = split(line, "\t")
        result = { freq = tonumber(fields[2]) or 0, entries = {} }
        for k = 3, #fields - 1, 2 do
            result.entries[#result.entries + 1] = { pinyin = fields[k], senses = split(fields[k + 1], "/") }
        end
    end
    self.cache[key] = result
    return result
end

------------------------------------------------------------------------
-- Popup content
------------------------------------------------------------------------

-- Lowercase pinyin, including capital vowels with tone marks.
local UPPER = {
    ["Ā"] = "ā", ["Á"] = "á", ["Ǎ"] = "ǎ", ["À"] = "à", ["Ē"] = "ē", ["É"] = "é", ["Ě"] = "ě", ["È"] = "è",
    ["Ī"] = "ī", ["Í"] = "í", ["Ǐ"] = "ǐ", ["Ì"] = "ì", ["Ō"] = "ō", ["Ó"] = "ó", ["Ǒ"] = "ǒ", ["Ò"] = "ò",
    ["Ū"] = "ū", ["Ú"] = "ú", ["Ǔ"] = "ǔ", ["Ù"] = "ù", ["Ǖ"] = "ǖ", ["Ǘ"] = "ǘ", ["Ǚ"] = "ǚ", ["Ǜ"] = "ǜ",
    ["Ü"] = "ü",
}
-- (string.lower depends on the C locale: in some UTF-8 locales it changes
-- bytes >= 0x80 and breaks multi-byte characters, so only A-Z are mapped.)
local function lower(s)
    s = s:gsub("[\195-\199][\128-\191]", UPPER)
    s = s:gsub("[A-Z]", function(c) return string.char(c:byte() + 32) end)
    return s
end
Defs.lower = lower

-- Tone marks removed (after lower()); ü keeps its dots: "lǜ" -> "lü".
local PLAIN = {
    ["ā"] = "a", ["á"] = "a", ["ǎ"] = "a", ["à"] = "a", ["ē"] = "e", ["é"] = "e", ["ě"] = "e", ["è"] = "e",
    ["ī"] = "i", ["í"] = "i", ["ǐ"] = "i", ["ì"] = "i", ["ō"] = "o", ["ó"] = "o", ["ǒ"] = "o", ["ò"] = "o",
    ["ū"] = "u", ["ú"] = "u", ["ǔ"] = "u", ["ù"] = "u", ["ǖ"] = "ü", ["ǘ"] = "ü", ["ǚ"] = "ü", ["ǜ"] = "ü",
}
local function strip_tones(s)
    return (s:gsub("[\195-\199][\128-\191]", PLAIN))
end
Defs.strip_tones = strip_tones

-- Does a CC-CEDICT syllable stand for the reading shown above a character?
-- Equal, or CC-CEDICT's neutral tone of it: words give 鼓捣 as "gǔ dao"
-- where 捣 is shown as dǎo. Erhua "r" stands for no reading. Both lowercase.
local function syllable_matches(syllable, shown)
    if syllable == shown then return true end
    return syllable ~= "r" and syllable == strip_tones(syllable) and syllable == strip_tones(shown)
end

-- The same for a whole reading ("gǔ dao" for "gǔ dǎo"), syllable by syllable.
local function pinyin_matches(pinyin, shown)
    if pinyin == shown then return true end
    local a, b = split(pinyin, " "), split(shown, " ")
    if #a ~= #b then return false end
    for k = 1, #a do
        if not syllable_matches(a[k], b[k]) then return false end
    end
    return true
end
Defs.pinyin_matches = pinyin_matches

-- Is syllable one of the readings shown (text may be a pair "chéng/shèng")?
local function matches_shown(syllable, text)
    for reading in lower(text or ""):gmatch("[^/]+") do
        if syllable_matches(syllable, reading) then return true end
    end
    return false
end
Defs.matches_shown = matches_shown

-- Entries grouped by reading (case-insensitive: "Wǎn" surname and "wǎn"
-- merge), the chosen readings first and marked, then CC-CEDICT's order.
-- A chosen reading matches CC-CEDICT's own form of it (an exact match first,
-- else a neutral-tone one: "dā" marks 瘩's "da"), which keeps its spelling.
-- A chosen reading CC-CEDICT does not list is still shown, with no senses.
local function group(entries, chosen)
    local groups, by_key = {}, {}
    for _, e in ipairs(entries or {}) do
        local key = lower(e.pinyin)
        local g = by_key[key]
        if not g then
            g = { pinyin = key, senses = {}, seen = {} }
            by_key[key] = g
            groups[#groups + 1] = g
        end
        for _, s in ipairs(e.senses) do
            if s ~= "" and not g.seen[s] then
                g.seen[s] = true
                g.senses[#g.senses + 1] = s
            end
        end
    end
    local out = {}
    for _, reading in ipairs(chosen or {}) do
        local key = lower(reading)
        local g = by_key[key]
        if not g then
            for _, candidate in ipairs(groups) do
                if pinyin_matches(candidate.pinyin, key) then
                    g = candidate
                    break
                end
            end
        end
        if not g then
            g = { pinyin = key, senses = {} }
            by_key[key] = g
        end
        if not g.chosen then
            g.chosen = true
            out[#out + 1] = g
        end
    end
    for _, g in ipairs(groups) do
        if not g.chosen then out[#out + 1] = g end
    end
    for _, g in ipairs(out) do g.seen = nil end
    return out
end
Defs.group = group

local function word_section(defs, word, pinyin, note)
    local found = defs:lookup(word)
    return {
        text = word,
        pinyin = pinyin,
        groups = found and group(found.entries, pinyin and { pinyin } or nil) or {},
        found = found and true or false,
        note = note,
    }
end

-- Fallback for characters whose reading did not come from a word (all
-- monophonic characters: words.tsv only lists words with a polyphonic
-- character, so the resolver never sees 饕餮). Run the resolver's own word
-- matching (longest word, then most frequent) over CC-CEDICT's words in the
-- same context, and keep the word only when its reading of this character
-- is the one shown above it (or either of a pair), or that reading's neutral
-- tone (see syllable_matches).
local function find_word(defs, gloss)
    local ctx = gloss.context
    if not ctx then return nil end
    local items = {}
    for _, t in ipairs(ctx.left or {}) do items[#items + 1] = { text = t, joined = true } end
    local i = #items + 1
    items[i] = { text = gloss.char, joined = true }
    for _, t in ipairs(ctx.right or {}) do items[#items + 1] = { text = t, joined = true } end
    if #items < 2 then return nil end
    local adapter = { max_word_len = 4 }
    function adapter:word(word)
        local found = defs:lookup(word)
        if not found then return nil end
        local n = Resolve.utf8_len(word)
        for _, e in ipairs(found.entries) do
            local syllables = split(lower(e.pinyin), " ")
            if #syllables == n then return syllables, found.freq end
        end
        return nil
    end
    local reading, word, _start, others = Resolve.word_reading(adapter, items, i)
    if not reading or not matches_shown(reading, gloss.text) then return nil end
    local function pinyin_of(w)
        local syllables = adapter:word(w)
        return syllables and table.concat(syllables, " ")
    end
    local match = { word = word, pinyin = pinyin_of(word), others = {} }
    for _, o in ipairs(others or {}) do
        match.others[#match.others + 1] = { word = o.word, pinyin = pinyin_of(o.word) }
    end
    return match
end
Defs.find_word = find_word

--[[--
What the popup shows for a tapped annotation.

  gloss: { char="宛", text="yuān" (the pinyin drawn, maybe "chéng/shèng"),
           match = { word="大宛", pinyin="dà yuān", others={ {word=, pinyin=} },
                     note="..." (special words, tools/special_curated.tsv) } or nil,
           context = { left={...}, right={...} } }

Returns {
  char = "宛", char_found = bool,
  readings = { {pinyin=, chosen=bool, senses={...}}, ... },
  word = { text=, pinyin=, groups={...}, found=bool, note= } or nil,
  others = { same as word, ... },
  word_from_resolver = bool,
}
]]
function Defs.describe(defs, gloss)
    local model = { char = gloss.char, others = {} }
    local found = defs:lookup(gloss.char)
    local chosen = {}
    for reading in (gloss.text or ""):gmatch("[^/]+") do chosen[#chosen + 1] = reading end
    model.char_found = found and true or false
    model.readings = group(found and found.entries, chosen)

    local match = gloss.match
    model.word_from_resolver = match ~= nil
    if not match then match = find_word(defs, gloss) end
    if match then
        model.word = word_section(defs, match.word, match.pinyin, match.note)
        for _, o in ipairs(match.others or {}) do
            model.others[#model.others + 1] = word_section(defs, o.word, o.pinyin)
        end
    end
    return model
end

-- True when neither the character nor the word has a CC-CEDICT entry (or a
-- note): the plugin then skips its popup and uses KOReader's dictionary lookup.
function Defs.empty(model)
    return not model.char_found and not (model.word and (model.word.found or model.word.note))
end

--[[--
Popup text. bold_start/bold_end are KOReader's TextBoxWidget PTF markers
(empty strings for plain text in tests).
]]
function Defs.render(model, bold_start, bold_end)
    local B, b = bold_start or "", bold_end or ""
    local lines = {}
    local function add(s) lines[#lines + 1] = s end
    -- Senses as one wrapped paragraph, separated like CC-CEDICT itself.
    local function senses(g)
        if #g.senses > 0 then add(table.concat(g.senses, " / ")) end
    end
    local MARK = "   (shown above)"

    -- The marker only means something when there is a choice to point at.
    local several_readings = #model.readings > 1
    for k, g in ipairs(model.readings) do
        if k > 1 then add("") end
        add(B .. g.pinyin .. b .. ((g.chosen and several_readings) and MARK or ""))
        if #g.senses == 0 then
            add(model.char_found and "no separate CC-CEDICT entry for this reading"
                or "no CC-CEDICT entry for this character")
        end
        senses(g)
    end

    local function word(w, label)
        add("")
        add(label .. B .. w.text .. b .. (w.pinyin and ("  " .. w.pinyin) or ""))
        if not w.found then
            -- A special word CC-CEDICT lacks (冒顿) has a hand-written note.
            add(w.note or "no definition in CC-CEDICT")
            return
        end
        local several = #w.groups > 1
        for _, g in ipairs(w.groups) do
            if several then add(B .. g.pinyin .. b .. (g.chosen and MARK or "")) end
            senses(g)
        end
    end
    if model.word then
        word(model.word, "Word: ")
        for _, o in ipairs(model.others) do word(o, "Also possible: ") end
    end
    return table.concat(lines, "\n")
end

return Defs
