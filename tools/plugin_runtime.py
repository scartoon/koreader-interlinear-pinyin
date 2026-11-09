"""Run the plugin's own Lua code (pinyin_data.lua, pinyin_resolve.lua) from Python."""
import os

try:
    from lupa.luajit21 import LuaRuntime
except ImportError:  # some lupa wheels (macOS arm64) have no LuaJIT; it implements Lua 5.1
    from lupa.lua51 import LuaRuntime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PLUGIN = os.path.join(ROOT, "interlinearpinyin.koplugin")

HELPERS = r'''
local Resolve = ...
local function is_item(ch)
    -- Han characters are items; punctuation and anything else breaks a word,
    -- as in the rendering engine.
    return Resolve.single_char(ch) and not ch:match("^\227\128") and not ch:match("^\239\188")
end
local function items_of(text, target)
    local items, joined, pos, target_index = {}, false, 0, nil
    for ch in text:gmatch("[%z\1-\127\194-\244][\128-\191]*") do
        if pos == target and is_item(ch) then target_index = #items + 1 end
        if is_item(ch) then
            items[#items + 1] = { text = ch, joined = joined, on_page = true }
            joined = true
        else
            joined = false
        end
        pos = pos + 1
    end
    return items, target_index
end
local H = {}
-- Full resolution: reading the plugin would show (may be "a/b"), or nil.
function H.reading(data, text, target, mode)
    local items, i = items_of(text, target)
    if not i then return nil end
    if Resolve.reading then return Resolve.reading(data, items, i, mode) end
    -- plugin versions before Resolve.reading existed
    local rank, default = data:char(items[i].text)
    if not rank then return nil end
    return Resolve.word_reading(data, items, i) or default, rank
end
-- The pieces: word reading and word, joined neighbours, default, rank.
function H.analyze(data, text, target)
    local items, i = items_of(text, target)
    if not i then return nil end
    local rank, default = data:char(items[i].text)
    if not rank then return nil end
    local word_reading, word = Resolve.word_reading(data, items, i)
    local left = items[i].joined and items[i - 1] and items[i - 1].text or false
    local right = items[i + 1] and items[i + 1].joined and items[i + 1].text or false
    return { word_reading = word_reading or false, word = word or false, left = left,
             right = right, default = default, rank = rank }
end
-- "char=reading ..." for what would be drawn.
function H.annotate(data, text, threshold, mode)
    local items = items_of(text, -1)
    local out = {}
    for _, a in ipairs(Resolve.annotate(data, items, threshold, mode)) do
        out[#out + 1] = items[a.index].text .. "=" .. a.reading
    end
    return table.concat(out, " ")
end
return H
'''


class Plugin:
    def __init__(self, plugin_dir=DEFAULT_PLUGIN, data_dir=None):
        plugin_dir = os.path.abspath(plugin_dir)
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f'package.path = "{plugin_dir}/?.lua;" .. package.path')
        self.data = self.lua.require("pinyin_data").load(data_dir or os.path.join(plugin_dir, "data"))
        self.h = self.lua.execute(HELPERS, self.lua.require("pinyin_resolve"))

    def reading(self, text, pos, mode="both"):
        """(reading, rank) the plugin gives the character at pos, or None."""
        r = self.h.reading(self.data, text, pos, mode)
        if r is None or (isinstance(r, tuple) and r[0] is None):
            return None
        return r if isinstance(r, tuple) else (r, None)

    def analyze(self, text, pos):
        a = self.h.analyze(self.data, text, pos)
        return None if a is None else {k: (v if v is not False else None) for k, v in a.items()}

    def annotate(self, text, threshold, mode="both"):
        return self.h.annotate(self.data, text, threshold, mode)
