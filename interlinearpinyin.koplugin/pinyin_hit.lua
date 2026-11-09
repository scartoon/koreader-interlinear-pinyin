-- Which annotation, if any, a tap falls on (pure Lua, testable offline).
--
-- Only annotations the overlay actually drew count: a character whose pinyin
-- was dropped because its line was crowded, and a repeat left bare by the
-- once-per-page rule, are not in the overlay's placed list and so are never
-- hit.
--
-- An annotation's hit area is
--   * its pinyin, as drawn: from the pinyin's left to right edge, from the top
--     of its tone marks to the bottom of its descenders; and
--   * its character's column: the character's screen box, horizontally, with
--     no padding into the neighbours, from the top of the pinyin down to the
--     bottom of the glyphs (not the empty half-line below them, where the next
--     line's pinyin is drawn).
-- Pinyin areas are checked first: pinyin wider than its character may reach
-- over a neighbour's column, and the pinyin there is what the reader sees.

local Layout = require("pinyin_layout")

local Hit = {}

--[[--
Rectangles for one placed annotation.

  entry   { item = {box={x,y,w,h}, w=pinyin width, ...}, x = pinyin left }
          (an element of Layout.plan's result, as kept by the overlay)
  m       { text_height=, ascent=, descent=, gap= } as used to draw it

Returns pinyin_rect, column_rect, each { x0, y0, x1, y1 } (x1/y1 exclusive).
]]
function Hit.rects(entry, m)
    local item = entry.item
    local box = item.box
    local baseline = Layout.pinyinBaseline(box, m.text_height, m.ascent, m.descent, m.gap)
    local top, bottom = baseline - m.ascent, baseline + m.descent
    local _, glyph_bottom = Layout.textBand(box, m.text_height)
    local pinyin = { entry.x, top, entry.x + (item.w or 0), bottom }
    local column = { box.x, top, box.x + box.w, glyph_bottom }
    return pinyin, column
end

local function inside(r, x, y)
    return x >= r[1] and x < r[3] and y >= r[2] and y < r[4]
end

--[[--
The placed entry under screen point (x, y), or nil.

  placed  the overlay's placed list (Layout.plan's result)
  m       metrics, see Hit.rects; m.ox, m.oy: where the overlay was painted
]]
function Hit.find(placed, m, x, y)
    if not placed or not x or not y then return nil end
    x, y = x - (m.ox or 0), y - (m.oy or 0)
    local columns = {}
    for k, entry in ipairs(placed) do
        local pinyin, column = Hit.rects(entry, m)
        if inside(pinyin, x, y) then return entry end
        columns[k] = column
    end
    for k, entry in ipairs(placed) do
        if inside(columns[k], x, y) then return entry end
    end
    return nil
end

return Hit
