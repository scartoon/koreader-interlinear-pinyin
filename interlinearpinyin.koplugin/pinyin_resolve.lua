-- Decide which characters on a page get pinyin, and which reading
-- (pure Lua, no KOReader dependencies, so it can be tested offline).
--
-- Input is the page as a sequence of items, one per visible "word" the
-- rendering engine reports. The engine treats every CJK character as a
-- one-character word, so a run of Chinese text is one item per character.
--
--   items[i] = {
--       text   = "饕",        -- the item's text
--       joined = true,        -- directly follows items[i-1] (no punctuation,
--                             -- space or element boundary in between)
--       on_page = true,       -- false for context items before/after the page
--   }
--
-- Readings: each character has a default (its most frequent reading). When the
-- character sits inside a dictionary word of 2-4 characters, that word's
-- reading wins, longest word first. This is what turns 侥 into jiǎo in 侥幸
-- but yáo in 僬侥.

local Resolve = {}

-- Is this item a single Han character?
local function single_char(text)
    if not text then return false end
    -- One UTF-8 code point of 3 or 4 bytes.
    local len = #text
    if len ~= 3 and len ~= 4 then return false end
    local b = text:byte(1)
    if len == 3 then return b >= 0xE3 and b <= 0xEF end
    return b == 0xF0
end
Resolve.single_char = single_char

-- Is items[a..b] one contiguous run of characters?
local function contiguous(items, a, b)
    if a < 1 or b > #items then return false end
    for k = a, b do
        if not single_char(items[k].text) then return false end
        if k > a and not items[k].joined then return false end
    end
    return true
end

-- Reading of items[i] taken from the longest dictionary word around it, or nil.
-- When several words of that length cover it (大宛 and 宛如 in 很大宛如), the
-- more frequent word wins; the leftmost one on a tie.
function Resolve.word_reading(data, items, i)
    local max_len = math.min(data.max_word_len or 4, 4)
    for len = max_len, 2, -1 do
        local best, best_freq
        for start = i - len + 1, i do
            local stop = start + len - 1
            if contiguous(items, start, stop) then
                local parts = {}
                for k = start, stop do parts[#parts + 1] = items[k].text end
                local syllables, freq = data:word(table.concat(parts))
                freq = freq or 0
                if syllables and #syllables == len and (not best or freq > best_freq) then
                    best, best_freq = syllables[i - start + 1], freq
                end
            end
        end
        if best then return best end
    end
    return nil
end

--[[--
Annotations for the on-page items.

  threshold: characters ranked above this (or unranked) are annotated.

Each character is annotated only the first time it appears on the page with a
given reading: later repeats are left bare, but a repeat with a different
reading (刨 páo in 刨根, then bào in 刨子) is annotated again.

Returns { {index=i, reading="tāo", rank=4396}, ... } in page order.
]]
function Resolve.annotate(data, items, threshold)
    local out, seen = {}, {}
    for i, item in ipairs(items) do
        if item.on_page ~= false and single_char(item.text) then
            local rank, reading = data:char(item.text)
            if rank and (rank == 0 or rank > threshold) then
                reading = Resolve.word_reading(data, items, i) or reading
                local key = item.text .. "\t" .. reading
                if not seen[key] then
                    seen[key] = true
                    -- Rarity used to decide what to drop when a line is crowded:
                    -- unranked characters count as rarest.
                    out[#out + 1] = { index = i, reading = reading, rank = (rank == 0) and math.huge or rank }
                end
            end
        end
    end
    return out
end

return Resolve
