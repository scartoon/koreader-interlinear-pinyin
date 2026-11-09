-- Horizontal placement of annotations on each line (pure Lua, testable offline).
--
-- From wordgloss_layout.lua in WordGloss (GPL-3.0, GangYe293); logic unchanged,
-- comments translated.
--
-- Each annotation is centred over its character. Pinyin is usually wider than
-- the character, so neighbours on the same line can overlap and are pushed
-- right. If a line still cannot fit everything, the most common character's
-- annotation is dropped first and the rarest kept.

local Layout = {}

Layout.DEFAULT_MARGIN = 6

--[[--
Place the annotations of one line.

  line   { {box={x=,w=}, w=annotation width, rank=rarity}, ... }
  max_x  right edge (screen width)
  margin minimum gap between neighbouring annotations

Returns { {item=..., x=...}, ... } sorted by x.
]]
function Layout.placeLine(line, max_x, margin)
    margin = margin or Layout.DEFAULT_MARGIN
    local remaining = {}
    for index = 1, #line do remaining[index] = line[index] end

    while #remaining > 0 do
        local placed, cursor, fits = {}, 0, true
        for index = 1, #remaining do
            local item = remaining[index]
            local box = item.box
            local text_x = box.x + (box.w - item.w) / 2
            if text_x < cursor then text_x = cursor end
            if text_x < 0 then text_x = 0 end
            if text_x + item.w > max_x then
                fits = false
                break
            end
            placed[index] = { item = item, x = text_x }
            cursor = text_x + item.w + margin
        end
        if fits then return placed end
        -- Does not fit: drop the most common one (smallest rank).
        local worst, worst_rank = 1, nil
        for index = 1, #remaining do
            local rank = remaining[index].rank
            if rank == nil then rank = 0 end
            if worst_rank == nil or rank < worst_rank then
                worst, worst_rank = index, rank
            end
        end
        table.remove(remaining, worst)
    end
    return {}
end

--[[--
Group by line (same box y) and place each line.

  items { {box={x=,y=,w=,h=}, w=annotation width, rank=...}, ... }
Returns { {item=..., x=...}, ... }
]]
function Layout.plan(items, max_x, margin)
    local lines, order = {}, {}
    for _, item in ipairs(items or {}) do
        local key = item.box and item.box.y
        if key then
            if not lines[key] then
                lines[key] = {}
                order[#order + 1] = key
            end
            lines[key][#lines[key] + 1] = item
        end
    end
    local placed = {}
    for _, key in ipairs(order) do
        local line = lines[key]
        table.sort(line, function(a, b) return a.box.x < b.box.x end)
        for _, entry in ipairs(Layout.placeLine(line, max_x, margin)) do
            placed[#placed + 1] = entry
        end
    end
    return placed
end

--[[--
Vertical band the glyphs actually occupy within a line box: the extra line
height is split evenly above and below the text, so the box top is not the top
of the characters.
]]
function Layout.textBand(box, text_height)
    local height = text_height or box.h
    if height > box.h then height = box.h end
    local half_leading = (box.h - height) / 2
    return box.y + half_leading, box.y + box.h - half_leading
end

--[[--
Baseline for the pinyin above a character.

The bottom of the pinyin (descenders included) sits `gap` pixels above the top
of the character. The pinyin may use the whole space between this line's
characters and the line above's, which is both half-leadings, not only the
part inside this line box. Its top never rises past the line above's
characters (the same half-leading above this line box); if there is not enough
room it is pushed down onto its own character rather than onto the line above.
]]
function Layout.pinyinBaseline(box, text_height, ascent, descent, gap)
    local text_top = Layout.textBand(box, text_height)
    local half_leading = text_top - box.y
    local baseline = text_top - gap - descent
    local min_baseline = box.y - half_leading + gap + ascent
    if baseline < min_baseline then baseline = min_baseline end
    return baseline
end

return Layout
