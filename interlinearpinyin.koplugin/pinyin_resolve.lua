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
-- Number of UTF-8 code points in s.
local function utf8_len(s)
    local _, n = s:gsub("[^\128-\191]", "")
    return n
end
Resolve.utf8_len = utf8_len

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

-- Reading of items[i] taken from the longest dictionary word around it, or
-- nil. Also returns the word, the index of its first item, and the other
-- words of the same length that also cover items[i] (for the tap popup's
-- "also possible"), as { {word=, start=}, ... }.
-- When several words of that length cover it (大宛 and 宛如 in 很大宛如), the
-- more frequent word wins; the leftmost one on a tie.
function Resolve.word_reading(data, items, i)
    local max_len = math.min(data.max_word_len or 4, 4)
    for len = max_len, 2, -1 do
        local best, best_freq, best_word, best_start
        local others = {}
        for start = i - len + 1, i do
            local stop = start + len - 1
            if contiguous(items, start, stop) then
                local parts = {}
                for k = start, stop do parts[#parts + 1] = items[k].text end
                local word = table.concat(parts)
                local syllables, freq = data:word(word)
                freq = freq or 0
                if syllables and #syllables == len then
                    if not best or freq > best_freq then
                        if best then others[#others + 1] = { word = best_word, start = best_start } end
                        best, best_freq, best_word, best_start = syllables[i - start + 1], freq, word, start
                    else
                        others[#others + 1] = { word = word, start = start }
                    end
                end
            end
        end
        if best then return best, best_word, best_start, others end
    end
    return nil
end

-- What to do when a character's reading is uncertain (see Resolve.reading).
Resolve.UNCERTAIN_BOTH = "both"   -- "chéng/shèng", most likely first
Resolve.UNCERTAIN_BEST = "best"   -- the most likely reading alone (may differ from the default)
Resolve.UNCERTAIN_SKIP = "skip"   -- no annotation

-- Reading for items[i] and the character's rank (0 = unranked), or nil when
-- the character is not annotated (common, not a Han character, or uncertain
-- with mode "skip"). A third value, when a dictionary word decided the
-- reading: { word=, start=, len=, others={ {word=, start=}, ... } }.
--
-- In order: the longest dictionary word around it; a context rule for the
-- character right before or after it; its default reading. For a character
-- whose default is known to be unreliable (data:uncertainty), the two most
-- likely readings are shown together, the most likely alone, or nothing,
-- depending on `uncertain`.
function Resolve.reading(data, items, i, uncertain)
    local item = items[i]
    if not item or not single_char(item.text) then return nil end
    local rank, default = data:char(item.text)
    if not rank then return nil end
    local reading, word, start, others = Resolve.word_reading(data, items, i)
    if reading then
        return reading, rank, { word = word, start = start, len = utf8_len(word), others = others }
    end
    if data.rule then
        local left = item.joined and items[i - 1] and items[i - 1].text or nil
        local after = items[i + 1]
        local right = after and after.joined and after.text or nil
        reading = data:rule(item.text, left, right)
        if reading then return reading, rank end
    end
    local first, second
    if data.uncertainty then first, second = data:uncertainty(item.text) end
    if first and second and first ~= second then
        uncertain = uncertain or Resolve.UNCERTAIN_BOTH
        if uncertain == Resolve.UNCERTAIN_SKIP then return nil end
        if uncertain == Resolve.UNCERTAIN_BEST then return first, rank end
        return first .. "/" .. second, rank
    end
    return default, rank
end

--[[--
Annotations for the on-page items.

  threshold: characters ranked above this (or unranked) are annotated.
  uncertain: Resolve.UNCERTAIN_BOTH (default), _BEST or _SKIP; see Resolve.reading.

Each character is annotated only the first time it appears on the page with a
given reading: later repeats are left bare, but a repeat with a different
reading (刨 páo in 刨根, then bào in 刨子) is annotated again.

Returns { {index=i, reading="tāo", rank=4396, match=...}, ... } in page
order; match is the word that decided the reading (see Resolve.reading), or nil.
]]
function Resolve.annotate(data, items, threshold, uncertain)
    local out, seen = {}, {}
    for i, item in ipairs(items) do
        if item.on_page ~= false then
            local reading, rank, match = Resolve.reading(data, items, i, uncertain)
            if reading and (rank == 0 or rank > threshold) then
                local key = item.text .. "\t" .. reading
                if not seen[key] then
                    seen[key] = true
                    -- Rarity used to decide what to drop when a line is crowded:
                    -- unranked characters count as rarest.
                    out[#out + 1] = { index = i, reading = reading, rank = (rank == 0) and math.huge or rank,
                                      match = match }
                end
            end
        end
    end
    return out
end

return Resolve
