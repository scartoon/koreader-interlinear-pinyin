-- Vertical placement of the pinyin and the line-height needed for it.
local Layout = require("pinyin_layout")

local function near(a, b) return math.abs(a - b) < 0.01 end

-- Measured on a Boox Go 7: 64 px text, line box 105 px (line-height 1.94 at
-- 85% line spacing). Pinyin ascent 20, descent 6, gap 2.
local box = { x = 0, y = 32, w = 64, h = 105 }
local top = Layout.textBand(box, 64)
assert(near(top, 52.5), "text top " .. top)
local baseline = Layout.pinyinBaseline(box, 64, 20, 6, 2)
assert(near(baseline, 44.5), "baseline " .. baseline)
-- Pinyin top (24.5) is below the line above's characters (32 - 20.5 = 11.5)
-- and its bottom (50.5) clears this line's characters (52.5).
assert(baseline - 20 > box.y - (top - box.y))
assert(baseline + 6 <= top - 2 + 0.01)

-- Cramped line: no room, so the pinyin is pushed down onto its own character
-- instead of up onto the line above.
local tight = { x = 0, y = 32, w = 64, h = 70 }
local b2 = Layout.pinyinBaseline(tight, 64, 20, 6, 2)
assert(near(b2, 32 - 3 + 2 + 20), "tight baseline " .. b2)

print("layout: ok")
