-- Build the plugin's menu against stub KOReader modules and evaluate every
-- label, so errors that only show up when KOReader builds the menu (such as a
-- loop variable shadowing gettext's `_`) are caught offline.
local function stub(name, value)
    package.loaded[name] = value
end

local Extendable = {}
function Extendable:extend(o)
    o = o or {}
    setmetatable(o, self)
    self.__index = self
    return o
end
Extendable.new = Extendable.extend

stub("gettext", function(s) return s end)
stub("logger", { err = function() end, warn = function() end, info = function() end, dbg = function() end })
stub("ffi/util", { template = function(s, ...)
    local args = { ... }
    return (s:gsub("%%(%d)", function(n) return tostring(args[tonumber(n)]) end))
end })
stub("ui/uimanager", { nextTick = function() end, setDirty = function() end, show = function() end })
stub("ui/event", { new = function(_, ...) return { ... } end })
stub("ui/widget/container/widgetcontainer", Extendable)
stub("ui/widget/infomessage", Extendable)
stub("ui/widget/widget", Extendable)
stub("ffi/blitbuffer", { COLOR_BLACK = 0 })
stub("ui/font", {})
stub("ui/rendertext", {})
stub("ui/size", { span = { horizontal_small = 2 } })
stub("device", { screen = { scaleBySize = function(_, v) return v end } })

local settings = {}
G_reader_settings = {
    readSetting = function(_, k) return settings[k] end,
    saveSetting = function(_, k, v) settings[k] = v end,
    flush = function() end,
}

local Plugin = dofile(PLUGIN_DIR .. "/main.lua")
local plugin = Plugin:new{ path = PLUGIN_DIR }

local menu_items = {}
plugin:addToMainMenu(menu_items)
local entry = assert(menu_items.interlinearpinyin, "menu entry not registered")
assert(entry.sorting_hint == "tools")

local count = 0
local function walk(items)
    for _i, item in ipairs(items) do
        local text = item.text or (item.text_func and item.text_func())
        assert(type(text) == "string" and text ~= "", "menu item without a label")
        if item.checked_func then item.checked_func() end
        count = count + 1
        if item.sub_item_table then walk(item.sub_item_table) end
    end
end
walk(entry.sub_item_table)
assert(count == 5 + 5 + 5 + 3, "unexpected menu size " .. count)

-- Choosing a threshold saves it and the label follows.
entry.sub_item_table[2].sub_item_table[1].callback()
assert(entry.sub_item_table[2].text_func():find("1500"), "threshold label not updated")

-- "When the reading is uncertain": default both, choices saved.
assert(plugin:getUncertainMode() == "both")
assert(entry.sub_item_table[4].text_func():find("show both"))
entry.sub_item_table[4].sub_item_table[2].callback()
assert(plugin:getUncertainMode() == "best", "uncertain mode not saved")
assert(entry.sub_item_table[4].text_func():find("best guess"))
entry.sub_item_table[4].sub_item_table[3].callback()
assert(plugin:getUncertainMode() == "skip")

-- Line-height: room for 1.2x the pinyin plus 2px either side in the gap
-- between lines, undoing KOReader's line-spacing scale.
local lh = Plugin.lineHeightFor(64, 40, 100)
assert(math.abs(lh - (1 + (64 * 0.4 * 1.2 + 4) / 64)) < 1e-9, "line height " .. lh)
assert(math.abs(Plugin.lineHeightFor(64, 40, 85) - lh / 0.85) < 1e-9, "line spacing not compensated")
assert(Plugin.lineHeightFor(64, 80, 50) == 3.0, "line height not capped")

G_reader_settings = nil
print("menu: ok")
