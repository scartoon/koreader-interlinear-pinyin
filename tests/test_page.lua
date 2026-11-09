-- Page walking against a fake engine with crengine's word-navigation rules:
-- every CJK character is a one-character word, punctuation is skipped, and
-- "next word start" never returns the position it starts from.
local Page = require("pinyin_page")
local Data = require("pinyin_data")
local data = assert(Data.load(PLUGIN_DIR .. "/data"))

local function chars_of(s)
    local t = {}
    for ch in s:gmatch("[%z\1-\127\194-\244][\128-\191]*") do t[#t + 1] = ch end
    return t
end

local function fake_document(text, page_starts)
    local c = chars_of(text)
    local function is_word(i) return c[i] and not c[i]:match("^\227\128") and not c[i]:match("^\239\188") end
    local doc = {}
    function doc:getCurrentPage() return 2 end
    function doc:getVisiblePageCount() return 1 end
    function doc:getPageXPointer(p) return page_starts[p] end
    function doc:getNextVisibleWordStart(xp)
        for i = xp + 1, #c do if is_word(i) then return i end end
    end
    function doc:getNextVisibleWordEnd(ws) return ws + 1 end
    function doc:getPrevVisibleWordStart(xp)
        for i = xp - 1, 1, -1 do if is_word(i) then return i end end
    end
    function doc:getPrevVisibleChar(xp) if xp > 1 then return xp - 1 end end
    function doc:compareXPointers(a, b) if b > a then return 1 elseif b == a then return 0 else return -1 end end
    function doc:getTextFromXPointers(a, b) return table.concat(c, "", a, b - 1) end
    function doc:getScreenBoxesFromPositions(a, b, get_segments)
        -- Word mode would also cover the next character (see boxes_for).
        assert(get_segments == true, "boxes must be requested with get_segments=true")
        return { { x = a * 10, y = 0, w = 10, h = 20 } }
    end
    return doc
end

--            1  2  3  4  5  6  7  8  9  10
local text = "他住在僬侥之国，饕餮之徒"
-- page 2 starts at 侥 (index 5) and ends before 饕 (index 9)
local doc = fake_document(text, { 1, 5, 9 })
local items = Page.collect(doc, 2)
local on, off = {}, {}
for _, it in ipairs(items) do
    if it.on_page then on[#on + 1] = it.text else off[#off + 1] = it.text end
end
local got_on, got_off = table.concat(on), table.concat(off)
assert(got_on == "侥之国", "on-page items: " .. got_on)
assert(got_off == "住在僬饕餮之", "context items: " .. got_off)

local glosses = Page.build(doc, 2, data, 3500)
local out = {}
for _, g in ipairs(glosses) do out[#out + 1] = g.word .. "=" .. g.text end
assert(table.concat(out, " ") == "侥=yáo", "annotations: " .. table.concat(out, " "))
-- Last page: the engine gives "" for the (missing) next page's start.
doc = fake_document(text, { 1, 5, "" })
function doc:getPageXPointer(p) return ({ 1, 9 })[p] or "" end
glosses = Page.build(doc, 2, data, 3500)
out = {}
for _, g in ipairs(glosses) do out[#out + 1] = g.word end
assert(table.concat(out) == "饕餮", "last page annotations: " .. table.concat(out, " "))
print("page walking: ok")
