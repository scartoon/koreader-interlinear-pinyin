-- Paint layer: draws pinyin above characters, after the page itself is drawn.
--
-- Based on wordgloss_overlay.lua from WordGloss (GPL-3.0, GangYe293), which in
-- turn follows omer-faruq/inlinehints.koplugin. Underlines and the "below"
-- mode are removed; placement above the glyph is unchanged.
--
-- KOReader's ReaderView paints every registered view module onto the same
-- buffer after the page (that is how highlights work), so we get the page's
-- screen coordinates and can draw in the gap between lines without touching
-- the book. main.lua injects a line-height so that gap exists.

local Blitbuffer = require("ffi/blitbuffer")
local Device = require("device")
local Font = require("ui/font")
local RenderText = require("ui/rendertext")
local Size = require("ui/size")
local Widget = require("ui/widget/widget")

local Hit = require("pinyin_hit")
local Layout = require("pinyin_layout")

local Overlay = Widget:extend{
    glosses = nil,      -- { {text=, box={x=,y=,w=,h=}, rank=}, ... }
    font_size = 12,     -- pixels
    font_face = nil,    -- nil/"auto" = KOReader's UI font, which has tone marks
    text_height = nil,  -- body font size in pixels, to find the glyph band in the line box
    gap = 1,            -- pixels between pinyin and the character below it
    dim = nil,
}

function Overlay:init()
    self.glosses = self.glosses or {}
    self.placed = nil
end

function Overlay:resolveFaceName()
    if self.font_face and self.font_face ~= "" and self.font_face ~= "auto" then
        return self.font_face
    end
    return "cfont"
end

-- Font:getFace scales its size argument by the screen DPI (scaleBySize), but
-- font_size here is already in screen pixels (from the book's font size), so
-- undo that scaling. Without this the pinyin came out about 2x too big on a
-- 300 dpi screen.
local function unscaled(px)
    local ok, scaled = pcall(function() return Device.screen:scaleBySize(1000) end)
    if not ok or not tonumber(scaled) or scaled <= 0 then return px end
    return px * 1000 / scaled
end

-- Font objects are cached per (face, size): changing either takes effect at once.
function Overlay:face()
    local name = self:resolveFaceName()
    local key = tostring(name) .. "|" .. tostring(self.font_size)
    if self._face and self._face_key == key then return self._face end
    local size = unscaled(self.font_size)
    local ok, face = pcall(Font.getFace, Font, name, size)
    if not ok or not face then
        ok, face = pcall(Font.getFace, Font, "cfont", size)
    end
    if not ok or not face then return nil end
    self._face_key, self._face = key, face
    -- Fixed vertical metrics for the face, measured once, so every syllable on a
    -- line shares one baseline whether or not it has a descender or a tone mark.
    -- Measured on lowercase only: pinyin has no capitals, and an accented
    -- capital is much taller than anything that will be drawn.
    local ok_d, d = pcall(RenderText.sizeUtf8Text, RenderText, 0, 10000, face, "gjpqyǚ", true, false)
    local ok_a, a = pcall(RenderText.sizeUtf8Text, RenderText, 0, 10000, face, "ǘǚǜǖhlbdkt", true, false)
    self._descent = (ok_d and d and d.y_bottom) or math.floor(self.font_size * 0.25)
    self._ascent = (ok_a and a and a.y_top) or self.font_size
    return face
end

function Overlay:setGlosses(list, text_height)
    self.glosses = list or {}
    if text_height then self.text_height = text_height end
    self.placed = nil
end

function Overlay:clear()
    self.glosses = {}
    self.placed = nil
end

-- Horizontal placement of the current glosses (cached until they change).
-- The paint and the tap hit-test share it, so a tap is tested against
-- exactly what is drawn.
function Overlay:plan(max_x)
    if self.placed then return self.placed end
    local face = self:face()
    if not face then return nil end
    local measured = {}
    for _, item in ipairs(self.glosses or {}) do
        if item.box and item.text and item.text ~= "" then
            local ok, size = pcall(RenderText.sizeUtf8Text, RenderText, 0, max_x, face,
                item.text, true, false)
            if ok and size then
                measured[#measured + 1] = {
                    text = item.text, box = item.box, rank = item.rank,
                    w = size.x, gloss = item,
                }
            end
        end
    end
    self.placed = Layout.plan(measured, max_x, Size.span.horizontal_small)
    return self.placed
end

function Overlay:paintTo(bb, x, y)
    if self.dim or not self.glosses or #self.glosses == 0 then return end
    local face = self:face()
    if not face then return end

    local max_x = bb:getWidth()
    self._max_x = max_x
    self:plan(max_x)

    self._paint_x, self._paint_y = x, y
    local color = self.color or Blitbuffer.COLOR_BLACK
    for _, entry in ipairs(self.placed) do
        local item = entry.item
        local descent, ascent = self._descent or 0, self._ascent or self.font_size
        local baseline = Layout.pinyinBaseline(item.box, self.text_height, ascent, descent, self.gap)
        pcall(RenderText.renderUtf8Text, RenderText, bb,
            x + math.floor(entry.x), y + math.floor(baseline), face, item.text, true, false, color)
    end
end

-- The gloss drawn under screen point (x, y), or nil (see pinyin_hit.lua).
-- Uses the same placement as the paint, so dropped pinyin is not tappable.
function Overlay:hitTest(x, y)
    if self.dim or not self.glosses or #self.glosses == 0 then return nil end
    local max_x = self._max_x
    if not max_x then
        local ok, w = pcall(function() return Device.screen:getWidth() end)
        max_x = ok and w or 10000
    end
    local placed = self:plan(max_x)
    if not placed or #placed == 0 then return nil end
    local entry = Hit.find(placed, {
        text_height = self.text_height, ascent = self._ascent or self.font_size,
        descent = self._descent or 0, gap = self.gap,
        ox = self._paint_x or 0, oy = self._paint_y or 0,
    }, x, y)
    return entry and entry.item.gloss
end

return Overlay
