-- Tap hit-testing on the overlay's placed annotations (pinyin_hit.lua),
-- fed by the real page walk, resolver and layout.
local Hit = require("pinyin_hit")
local Layout = require("pinyin_layout")
local Data = require("pinyin_data")
local Resolve = require("pinyin_resolve")
local data = assert(Data.load(PLUGIN_DIR .. "/data"))

local function chars_of(s)
    local t = {}
    for ch in s:gmatch("[%z\1-\127\194-\244][\128-\191]*") do t[#t + 1] = ch end
    return t
end

-- Lay a text out like the engine: characters 40 px wide in 100 px tall line
-- boxes (text 40 px high in the middle), `per_line` characters per line,
-- starting at x = 100. Returns the overlay's placed list and the items.
local CW, LH, TH = 40, 100, 40
local function layout(text, per_line, threshold, pinyin_w)
    local items = {}
    local joined = false
    for _, ch in ipairs(chars_of(text)) do
        if ch == "，" then
            joined = false
        else
            items[#items + 1] = { text = ch, joined = joined }
            joined = true
        end
    end
    for n, it in ipairs(items) do
        local col, row = (n - 1) % per_line, math.floor((n - 1) / per_line)
        it.box = { x = 100 + col * CW, y = row * LH, w = CW, h = LH }
    end
    local measured = {}
    for _, a in ipairs(Resolve.annotate(data, items, threshold or 3500)) do
        local it = items[a.index]
        measured[#measured + 1] = {
            text = a.reading, box = it.box, rank = a.rank, w = pinyin_w or 30,
            gloss = { char = it.text, text = a.reading, match = a.match, index = a.index },
        }
    end
    return Layout.plan(measured, 100 + per_line * CW + 100, 4), items
end

local m = { text_height = TH, ascent = 14, descent = 4, gap = -1 }

local function tap(placed, x, y)
    local e = Hit.find(placed, m, x, y)
    return e and e.item.gloss
end

-- 饕 and 餮 both rare; 之 and 徒 common.
local placed, items = layout("饕餮之徒", 10)
assert(#placed == 2, "饕餮 should both be annotated, got " .. #placed)
-- Hit on the character's glyphs (box 100..140, glyphs y 30..70).
local g = tap(placed, 120, 50)
assert(g and g.char == "饕", "tap on 饕")
-- Hit on its pinyin: drawn just above the glyphs (y < 30).
local pinyin_rect = Hit.rects(placed[1], m)
g = tap(placed, (pinyin_rect[1] + pinyin_rect[3]) / 2, (pinyin_rect[2] + pinyin_rect[4]) / 2)
assert(g and g.char == "饕", "tap on the pinyin above 饕")
assert(pinyin_rect[4] <= 30 + 1, "pinyin should sit above the glyph top")
-- Neighbouring unannotated character 之 (x 180..220): miss.
assert(tap(placed, 200, 50) == nil, "tap on 之 must fall through")
-- Below the glyphs (the next line's pinyin space): miss.
assert(tap(placed, 120, 90) == nil, "tap below 饕's glyphs must fall through")
-- Left of the first character: miss, no sideways padding.
assert(tap(placed, 99, 50) == nil, "tap left of 饕 must fall through")
-- Exactly on the border between 饕 and 餮 belongs to 餮 (boxes are half-open).
g = tap(placed, 140, 50)
assert(g and g.char == "餮", "border pixel belongs to the right-hand character")

-- Miss between characters: the gap between two annotated characters that
-- are not neighbours (饕 ... 饕 with 之 in between is a repeat, so use two
-- different rare characters separated by a common one).
placed = layout("饕之餮", 10)
assert(#placed == 2)
assert(tap(placed, 160, 50) == nil, "tap on 之 between 饕 and 餮 must fall through")
assert(tap(placed, 139, 50).char == "饕" and tap(placed, 180, 50).char == "餮")
assert(tap(placed, 140, 50) == nil and tap(placed, 179, 50) == nil, "edges of 之")

-- A repeat occurrence left bare by the once-per-page rule is not tappable.
placed = layout("饕之饕", 10)
assert(#placed == 1, "repeat should not be annotated")
assert(tap(placed, 120, 50).char == "饕")
assert(tap(placed, 200, 50) == nil, "the repeated 饕 has no pinyin and must fall through")

-- A dropped annotation (crowded line) is not tappable. Pinyin 120 px wide
-- over 40 px characters: three rare characters cannot all fit on a 200 px
-- line, so the most common one is dropped.
placed = layout("饕餮魑", 3, 3500, 120)
local kept = {}
for _, e in ipairs(placed) do kept[e.item.gloss.char] = e end
assert(#placed < 3, "crowded line should drop an annotation")
for n, ch in ipairs({ "饕", "餮", "魑" }) do
    local x = 100 + (n - 1) * CW + CW / 2
    local got = tap(placed, x, 50)
    if kept[ch] then
        assert(got and got.char == ch, "kept " .. ch .. " should be tappable")
    else
        assert(got == nil, "dropped " .. ch .. " must not be tappable")
    end
end

-- A two-line word: 僬侥 with 僬 ending line 1 and 侥 starting line 2. Both
-- halves are tappable on their own line and carry the same word.
placed, items = layout("他住在僬侥之国", 4)
local by_char = {}
for _, e in ipairs(placed) do by_char[e.item.gloss.char] = e.item.gloss end
local yao = assert(by_char["侥"], "侥 annotated")
assert(yao.text == "yáo" and yao.match and yao.match.word == "僬侥", "侥 reading/word")
assert(items[yao.match.start].text == "僬" and yao.match.len == 2, "word span")
assert(items[4].box.y == 0 and items[5].box.y == LH, "僬 on line 1, 侥 on line 2")
g = tap(placed, 100 + CW / 2, LH + 50)
assert(g and g.char == "侥" and g.match.word == "僬侥", "tap 侥 on line 2")
if by_char["僬"] then
    g = tap(placed, 100 + 3 * CW + CW / 2, 50)
    assert(g and g.char == "僬" and g.match.word == "僬侥", "tap 僬 on line 1")
end
-- Right of 僬 at the end of line 1 is empty: miss.
assert(tap(placed, 100 + 4 * CW + 10, 50) == nil, "past the end of line 1")

-- Paint offset is honoured.
placed = layout("饕餮", 10)
m.ox, m.oy = 0, 1000
assert(tap(placed, 120, 50) == nil and tap(placed, 120, 1050).char == "饕", "paint offset")
m.ox, m.oy = nil, nil

assert(Hit.find(nil, m, 1, 1) == nil)
print("hit testing: ok")
