--[[--
Interlinear Pinyin: shows pinyin above rare Chinese characters, like the
Kindle's pinyin display. The book file is never modified.

Forked from WordGloss (https://github.com/GangYe293/wordgloss.koplugin,
GPL-3.0, by GangYe293) in November 2026 and reduced to pinyin only.
Kept from WordGloss: the paint-layer approach, the line-height injection and
the style-sheet hook. New: the Chinese character/word tables and reading logic.

  pinyin_data.lua     loads data/chars.tsv and data/words.tsv
  pinyin_resolve.lua  which characters to annotate, and which reading
  pinyin_page.lua     walks the page through the engine, gets screen boxes
  pinyin_overlay.lua  draws the pinyin
  pinyin_layout.lua   keeps neighbouring pinyin from overlapping
]]

local UIManager = require("ui/uimanager")
local WidgetContainer = require("ui/widget/container/widgetcontainer")
local InfoMessage = require("ui/widget/infomessage")
local Event = require("ui/event")
local logger = require("logger")
local _ = require("gettext")
local T = require("ffi/util").template

local Data = require("pinyin_data")
local Page = require("pinyin_page")
local Overlay = require("pinyin_overlay")

local InterlinearPinyin = WidgetContainer:extend{
    name = "interlinearpinyin",
    is_doc_only = true,
}

InterlinearPinyin.VERSION = "0.1.0"

local PREFIX = "interlinearpinyin_"
local THRESHOLDS = { 1500, 2500, 3500, 5000, 7000 }
local DEFAULT_THRESHOLD = 3500
local SIZES = { 35, 40, 45, 50, 55 }   -- pinyin size, % of body text size
local DEFAULT_SIZE = 40
local GAP = 2                          -- pixels between pinyin and character

------------------------------------------------------------------------
-- Settings
------------------------------------------------------------------------

function InterlinearPinyin:getSetting(key, default)
    local value = G_reader_settings and G_reader_settings:readSetting(PREFIX .. key)
    if value == nil then return default end
    return value
end

-- Settings change only from the menu, so write them straight to disk
-- (KOReader otherwise flushes only on a clean exit).
function InterlinearPinyin:saveSetting(key, value)
    if not G_reader_settings then return end
    G_reader_settings:saveSetting(PREFIX .. key, value)
    if G_reader_settings.flush then pcall(function() G_reader_settings:flush() end) end
end

function InterlinearPinyin:isEnabled()
    return self:getSetting("enabled", false) == true
end

function InterlinearPinyin:getThreshold()
    return tonumber(self:getSetting("threshold", DEFAULT_THRESHOLD)) or DEFAULT_THRESHOLD
end

function InterlinearPinyin:getSizePercent()
    local pct = tonumber(self:getSetting("size_pct", DEFAULT_SIZE)) or DEFAULT_SIZE
    return math.max(20, math.min(80, pct))
end

------------------------------------------------------------------------
-- Lifecycle
------------------------------------------------------------------------

function InterlinearPinyin:init()
    -- Register the menu first: if anything later fails, the entry still shows.
    if self.ui and self.ui.menu then
        pcall(function() self.ui.menu:registerToMainMenu(self) end)
    end
end

-- Only CRE (reflowable) documents have xpointers and style sheets;
-- PDF/DjVu/CBZ are skipped.
function InterlinearPinyin:isCompatibleDocument()
    local document = self.ui and self.ui.document
    return document ~= nil and document.setStyleSheet ~= nil
end

function InterlinearPinyin:loadData()
    if self.data then return self.data end
    local data, err = Data.load(self.path .. "/data")
    if not data then
        logger.err("interlinearpinyin: cannot load data:", err)
        self._data_error = err
        return nil
    end
    self.data = data
    return data
end

function InterlinearPinyin:onReaderReady()
    if not self:isCompatibleDocument() then return end
    if not self.overlay and self.ui and self.ui.view then
        self.overlay = Overlay:new{ glosses = {}, gap = GAP }
        local ok, err = pcall(function() self.ui.view:registerViewModule("interlinearpinyin", self.overlay) end)
        if not ok then logger.warn("interlinearpinyin: registerViewModule failed:", tostring(err)) end
    end
    self:hookStyleSheet()
    if not self:isEnabled() then return end
    UIManager:nextTick(function()
        self:refreshDocumentStyles()
        self:refreshPage()
    end)
end

-- Applying the style while settings are read means it is part of the initial
-- layout, with no extra re-render.
function InterlinearPinyin:onReadSettings()
    if self:isEnabled() and self:isCompatibleDocument() then
        self:hookStyleSheet()
        self:refreshDocumentStyles()
    end
end

-- Compute right away (not on the next tick) so the pinyin is drawn in the same
-- screen refresh as the page turn, avoiding a second e-ink refresh.
function InterlinearPinyin:onPageUpdate() self:refreshPage() end
function InterlinearPinyin:onPosUpdate() self:refreshPage() end

function InterlinearPinyin:onDocumentRerendered()
    if self.overlay then self.overlay.placed = nil end
    UIManager:nextTick(function() self:refreshPage() end)
end
InterlinearPinyin.onDocumentPartiallyRerendered = InterlinearPinyin.onDocumentRerendered

function InterlinearPinyin:onCloseDocument()
    if self.overlay then self.overlay:clear() end
end

------------------------------------------------------------------------
-- Line spacing: room for the pinyin between lines
------------------------------------------------------------------------

-- CSS line-height adds half its extra space above each line and half below, so
-- to fit pinyin of height h above the characters we need (lh - 1) / 2 >= h / F.
function InterlinearPinyin:gapCss(document)
    local font_size = 16
    local ok, size = pcall(function() return document:getFontSize() end)
    if ok and tonumber(size) then font_size = tonumber(size) end
    local pinyin_px = font_size * self:getSizePercent() / 100
    local need = pinyin_px * 1.1 + GAP
    local lh = 1 + 2 * need / math.max(1, font_size)
    lh = math.max(1.5, math.min(3.0, lh))
    return string.format("p,li,dd,dt,blockquote,div,td,pre{line-height:%.2f !important;}", lh)
end

function InterlinearPinyin:styleSignature()
    return tostring(self:isEnabled()) .. "|" .. tostring(self:getSizePercent())
end

-- Re-apply the style sheet when our settings change. The CSS itself is added
-- by hookStyleSheet, so KOReader's own re-layouts keep it too.
function InterlinearPinyin:refreshDocumentStyles()
    local document = self.ui and self.ui.document
    local typeset = self.ui and self.ui.typeset
    if not document or not typeset or not document.setStyleSheet then return false end
    local signature = self:styleSignature()
    if document._interlinearpinyin_signature == signature then return true end
    document._interlinearpinyin_signature = signature
    local css = typeset.css or document.default_css or ""
    local tweaks = self.ui.styletweak and self.ui.styletweak:getCssText() or ""
    local ok = pcall(function() document:setStyleSheet(css, tweaks) end)
    if not ok then
        document._interlinearpinyin_signature = nil
        return false
    end
    UIManager:nextTick(function()
        local ui = self.ui
        if not ui or not ui.view then return end
        pcall(function()
            local page = document:getCurrentPage()
            if page then ui:handleEvent(Event:new("PageUpdate", page)) end
            ui.view:recalculate()
            ui:handleEvent(Event:new("InitScrollPageStates"))
        end)
    end)
    return true
end

-- Wrap document:setStyleSheet so our line-height is appended every time the
-- engine applies styles. Runs in the middle of the engine's styling: only
-- plain Lua here, never calls back into the engine.
function InterlinearPinyin:hookStyleSheet()
    local document = self.ui and self.ui.document
    if not document or document._interlinearpinyin_hooked then return end
    local original = document.setStyleSheet
    if not original then return end
    document._interlinearpinyin_hooked = true
    local plugin = self
    document.setStyleSheet = function(doc, css, tweaks_css)
        local extra = tweaks_css or ""
        if plugin:isEnabled() then
            local ok, more = pcall(function() return plugin:gapCss(doc) end)
            if ok and more then extra = extra .. "\n" .. more end
        end
        return original(doc, css, extra)
    end
end

------------------------------------------------------------------------
-- Current page
------------------------------------------------------------------------

function InterlinearPinyin:refreshPage()
    local document = self.ui and self.ui.document
    if not document or not self.overlay then return end
    if not self:isEnabled() then
        if #self.overlay.glosses > 0 then
            self.overlay:clear()
            UIManager:setDirty(self.ui.view, "ui")
        end
        return
    end
    local data = self:loadData()
    if not data then return end

    local ok, err = pcall(function()
        local font_size = document:getFontSize()
        local page = document:getCurrentPage()
        local glosses, stats = Page.build(document, page, data, self:getThreshold())
        self.overlay.font_size = math.max(8, math.floor(font_size * self:getSizePercent() / 100 + 0.5))
        self.overlay:setGlosses(glosses, font_size)
        self._last_stats = stats
    end)
    if not ok then
        logger.warn("interlinearpinyin: refresh failed:", tostring(err))
        self.overlay:clear()
    end
    UIManager:setDirty(self.ui.view, "ui")
end

function InterlinearPinyin:apply(touchmenu)
    if self.overlay then self.overlay:clear() end
    self:refreshDocumentStyles()
    self:refreshPage()
    if touchmenu and touchmenu.updateItems then touchmenu:updateItems() end
end

------------------------------------------------------------------------
-- Menu
------------------------------------------------------------------------

function InterlinearPinyin:addToMainMenu(menu_items)
    local plugin = self
    local threshold_items = {}
    for _, value in ipairs(THRESHOLDS) do
        threshold_items[#threshold_items + 1] = {
            text = T(_("Outside the %1 most common"), value),
            checked_func = function() return plugin:getThreshold() == value end,
            radio = true,
            keep_menu_open = true,
            callback = function(touchmenu)
                plugin:saveSetting("threshold", value)
                plugin:refreshPage()
            end,
        }
    end
    local size_items = {}
    for _, pct in ipairs(SIZES) do
        size_items[#size_items + 1] = {
            text = T(_("%1% of text size"), pct),
            checked_func = function() return plugin:getSizePercent() == pct end,
            radio = true,
            keep_menu_open = true,
            callback = function(touchmenu)
                plugin:saveSetting("size_pct", pct)
                plugin:apply(touchmenu)
            end,
        }
    end

    menu_items.interlinearpinyin = {
        text = _("Interlinear pinyin"),
        sorting_hint = "tools",
        sub_item_table = {
            {
                text = _("Show pinyin above rare characters"),
                checked_func = function() return plugin:isEnabled() end,
                callback = function(touchmenu)
                    plugin:saveSetting("enabled", not plugin:isEnabled())
                    plugin:apply(touchmenu)
                end,
            },
            {
                text_func = function()
                    return T(_("Which characters: outside the %1 most common"), plugin:getThreshold())
                end,
                sub_item_table = threshold_items,
            },
            {
                text_func = function()
                    return T(_("Pinyin size: %1% of text"), plugin:getSizePercent())
                end,
                sub_item_table = size_items,
            },
            {
                text = _("Status"),
                keep_menu_open = true,
                callback = function()
                    local stats = plugin._last_stats
                    local lines = { T(_("Interlinear pinyin %1"), plugin.VERSION) }
                    if plugin._data_error then
                        lines[#lines + 1] = T(_("Data not loaded: %1"), plugin._data_error)
                    elseif stats then
                        lines[#lines + 1] = T(_("This page: %1 characters read, %2 annotated"),
                            stats.items, stats.annotated)
                    end
                    UIManager:show(InfoMessage:new{ text = table.concat(lines, "\n") })
                end,
            },
        },
    }
end

return InterlinearPinyin
