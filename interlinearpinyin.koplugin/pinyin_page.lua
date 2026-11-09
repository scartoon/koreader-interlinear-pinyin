-- Walk the current page through the rendering engine and turn the
-- annotations into screen positions.
--
-- Based on wordgloss_page.lua from WordGloss (GPL-3.0, GangYe293), changed to:
--   * read a few characters of context before and after the page, so a word
--     split across a page turn still resolves (and the first character of the
--     page is not skipped: the engine's next-word-start never returns the
--     position it starts from);
--   * decide what to annotate first and only then ask for screen boxes, since a
--     Chinese page has hundreds of one-character "words" and box lookups are the
--     expensive part.

local Resolve = require("pinyin_resolve")

local Page = {}

Page.MAX_ITEMS = 3000
Page.CONTEXT = 3     -- characters of context kept on each side of the page

local function call(object, method, ...)
    if not object or not object[method] then return nil end
    local ok, value = pcall(object[method], object, ...)
    if not ok then return nil end
    return value
end

local function visible_pages(document)
    local count = call(document, "getVisiblePageCount")
    if type(count) ~= "number" or count < 1 then return 1 end
    return count
end

-- Items for the page plus context, each { text=, ws=, we=, joined=, on_page= }.
function Page.collect(document, page)
    if not document then return {} end
    page = page or call(document, "getCurrentPage") or 1
    local start_xp = call(document, "getPageXPointer", page)
    if not start_xp then return {} end
    local end_xp = call(document, "getPageXPointer", page + visible_pages(document))

    -- Step back a few words so the first on-page character is not skipped and
    -- has its left-hand context.
    local xp = start_xp
    for _ = 1, Page.CONTEXT + 1 do
        local prev = call(document, "getPrevVisibleWordStart", xp)
        if not prev then break end
        xp = prev
    end
    -- getNextVisibleWordStart skips a word starting exactly at xp, so begin one
    -- step earlier still when possible.
    local before = call(document, "getPrevVisibleChar", xp)
    if before then xp = before end

    local items, seen_page, past_end = {}, false, 0
    for _ = 1, Page.MAX_ITEMS do
        local ws = call(document, "getNextVisibleWordStart", xp)
        if not ws then break end
        local we = call(document, "getNextVisibleWordEnd", ws)
        if not we then break end
        local text = call(document, "getTextFromXPointers", ws, we)
        -- compareXPointers(a, b) is 1 when b is after a, 0 when equal, -1 otherwise.
        local on_page = call(document, "compareXPointers", start_xp, ws) ~= -1
        if on_page and end_xp and call(document, "compareXPointers", ws, end_xp) ~= 1 then
            on_page = false
        end
        if text and text ~= "" then
            local prev = items[#items]
            items[#items + 1] = {
                text = text, ws = ws, we = we, on_page = on_page,
                joined = prev ~= nil and prev.we == ws,
            }
            if on_page then
                seen_page = true
            elseif seen_page then
                past_end = past_end + 1
                if past_end >= Page.CONTEXT then break end
            end
        end
        xp = we
    end
    return items
end

-- Screen boxes for one item; nil when it is not on screen.
local function boxes_for(document, item)
    local boxes = call(document, "getScreenBoxesFromPositions", item.ws, item.we, false)
    for _, box in ipairs(boxes or {}) do
        if box and box.w and box.w > 0 and box.h and box.h > 0 then
            return box
        end
    end
    return nil
end

--[[--
Annotations for the current page, ready for the overlay:
  { {text="tāo", box={x,y,w,h}, rank=4396, char="饕"}, ... }
plus stats { items=, annotated= }.
]]
function Page.build(document, page, data, threshold)
    local items = Page.collect(document, page)
    local stats = { items = #items, annotated = 0 }
    local glosses = {}
    for _, a in ipairs(Resolve.annotate(data, items, threshold)) do
        local item = items[a.index]
        local box = boxes_for(document, item)
        if box then
            glosses[#glosses + 1] = { text = a.reading, box = box, rank = a.rank, word = item.text }
        end
    end
    stats.annotated = #glosses
    return glosses, stats
end

return Page
