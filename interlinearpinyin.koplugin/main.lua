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
local GAP = 2                          -- pixels reserved above and below the pinyin (line spacing)
-- Pixels between the bottom of the pinyin's descenders and the estimated top
-- of the character. The estimate (textBand) sits a few pixels above the real
-- glyph top, so a small negative value still clears it and brings the pinyin
-- closer; -1 looked right on a Boox Go 7.
local DRAW_GAP = -1

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
        self.overlay = Overlay:new{ glosses = {}, gap = DRAW_GAP }
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
    UIManager:nextTick(function()
        -- KOReader handles SetLineSpace itself and does not pass the event on,
        -- so notice a line-spacing change here, after its re-layout. Re-apply
        -- the style only when it changed (refreshDocumentStyles checks).
        if self:isEnabled() then self:refreshDocumentStyles() end
        self:refreshPage()
    end)
end
InterlinearPinyin.onDocumentPartiallyRerendered = InterlinearPinyin.onDocumentRerendered

function InterlinearPinyin:onCloseDocument()
    if self.overlay then self.overlay:clear() end
end

------------------------------------------------------------------------
-- Line spacing: room for the pinyin between lines
------------------------------------------------------------------------

-- KOReader's "line spacing" setting (percent). crengine multiplies every line
-- height by it, including ones set in CSS.
function InterlinearPinyin:lineSpacingPercent()
    local ui = self.ui
    local configurable = (ui and ui.font and ui.font.configurable)
        or (ui and ui.document and ui.document.configurable)
    local pct = configurable and tonumber(configurable.line_spacing)
    if not pct or pct <= 0 then return 100 end
    return pct
end

-- Line-height (in em, as written in CSS) that leaves room for the pinyin.
--
-- The pinyin is drawn in the whole gap between the characters of one line and
-- those of the line above: CSS splits the extra height (lh - 1) em into half
-- above and half below each line, so that gap is the full (lh - 1) em. It must
-- hold the pinyin itself (about 1.2x its font size counting tone marks and
-- descenders) plus GAP pixels on each side. crengine then scales the result by
-- the line-spacing percentage, so divide by it to get what we actually need.
function InterlinearPinyin.lineHeightFor(font_size, size_pct, spacing_pct)
    font_size = math.max(1, tonumber(font_size) or 16)
    local pinyin_px = font_size * size_pct / 100
    local need = pinyin_px * 1.2 + 2 * GAP
    local lh = (1 + need / font_size) / ((spacing_pct or 100) / 100)
    return math.max(1.0, math.min(3.0, lh))
end

function InterlinearPinyin:gapCss(document)
    local font_size = 16
    local ok, size = pcall(function() return document:getFontSize() end)
    if ok and tonumber(size) then font_size = tonumber(size) end
    local lh = InterlinearPinyin.lineHeightFor(font_size, self:getSizePercent(), self:lineSpacingPercent())
    return string.format("p,li,dd,dt,blockquote,div,td,pre{line-height:%.2f !important;}", lh)
end

function InterlinearPinyin:styleSignature()
    return tostring(self:isEnabled()) .. "|" .. tostring(self:getSizePercent())
        .. "|" .. tostring(self:lineSpacingPercent())
end

-- Re-apply the style sheet when our settings change. The CSS itself is added
-- by hookStyleSheet, so KOReader's own re-layouts keep it too.
--
-- document:setStyleSheet alone only records the CSS; the book is laid out
-- again only on UpdatePos. ApplyStyleSheet is KOReader's own way to do both:
-- ReaderTypeset re-sets its CSS plus the style tweaks (through our hook) and
-- sends UpdatePos. Before the reader is ready (onReadSettings) UpdatePos is a
-- no-op and the first layout picks the style up.
function InterlinearPinyin:refreshDocumentStyles()
    local document = self.ui and self.ui.document
    if not document or not self.ui.typeset or not document.setStyleSheet then return false end
    local signature = self:styleSignature()
    if document._interlinearpinyin_signature == signature then return true end
    document._interlinearpinyin_signature = signature
    local ok, err = pcall(function() self.ui:handleEvent(Event:new("ApplyStyleSheet")) end)
    if not ok then
        logger.warn("interlinearpinyin: applying style sheet failed:", tostring(err))
        document._interlinearpinyin_signature = nil
        return false
    end
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
    for _i, value in ipairs(THRESHOLDS) do
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
    for _i, pct in ipairs(SIZES) do
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
