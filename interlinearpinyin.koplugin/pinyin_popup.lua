-- The definitions popup shown when an annotated character is tapped.
--
-- Built from KOReader's own widgets (TitleBar, ScrollTextWidget, ButtonTable)
-- so it looks native and uses KOReader's UI fonts, whose CJK fallback covers
-- the characters and whose Noto Sans has the tone marks. Bold uses
-- TextBoxWidget's PTF markers. Sized to its content and placed above or
-- below the tapped character's line, whichever has more room (at most 60% of
-- the screen high; it scrolls beyond that), so the character stays visible. Shown and
-- closed with a partial "ui" refresh of its own area, never a full flash.

local Blitbuffer = require("ffi/blitbuffer")
local ButtonTable = require("ui/widget/buttontable")
local CenterContainer = require("ui/widget/container/centercontainer")
local Device = require("device")
local Font = require("ui/font")
local FrameContainer = require("ui/widget/container/framecontainer")
local Geom = require("ui/geometry")
local GestureRange = require("ui/gesturerange")
local InputContainer = require("ui/widget/container/inputcontainer")
local ScrollTextWidget = require("ui/widget/scrolltextwidget")
local Size = require("ui/size")
local TextBoxWidget = require("ui/widget/textboxwidget")
local TitleBar = require("ui/widget/titlebar")
local UIManager = require("ui/uimanager")
local VerticalGroup = require("ui/widget/verticalgroup")
local Screen = Device.screen

local Popup = InputContainer:extend{
    title = nil,       -- the character
    text = nil,        -- PTF text (see pinyin_defs.lua Defs.render)
    buttons = nil,     -- ButtonTable rows
    anchor = nil,      -- screen box of the tapped character {x, y, w, h}
}

Popup.BOLD_START = TextBoxWidget.PTF_BOLD_START
Popup.BOLD_END = TextBoxWidget.PTF_BOLD_END

function Popup:init()
    local screen_w, screen_h = Screen:getWidth(), Screen:getHeight()
    self.dimen = Geom:new{ x = 0, y = 0, w = screen_w, h = screen_h }
    -- Wider in landscape, where height is scarce.
    self.width = math.floor(screen_w * (screen_w > screen_h and 0.8 or 0.86))
    local margin = Size.margin.default

    if Device:hasKeys() then
        self.key_events = { Close = { { Device.input.group.Back } } }
    end
    if Device:isTouchDevice() then
        self.ges_events = {
            TapClose = { GestureRange:new{ ges = "tap", range = self.dimen } },
        }
    end

    self.titlebar = TitleBar:new{
        width = self.width,
        align = "left",
        with_bottom_line = true,
        title = self.title,
        title_face = Font:getFace("x_smalltfont", 26),
        title_top_padding = Size.padding.default,
        bottom_v_padding = Size.padding.default,
        show_parent = self,
    }
    self.button_table = ButtonTable:new{
        width = self.width - 2 * Size.padding.default,
        buttons = self.buttons,
        zero_sep = true,
        show_parent = self,
    }

    -- Room: the larger of the spaces above and below the tapped character's
    -- line, at most 60% of the screen. When neither side has a third of the
    -- screen, the popup is centred and may cover the line.
    local box = self.anchor
    local above = box and (box.y - margin) or 0
    local below = box and (screen_h - box.y - box.h - margin) or 0
    local room = math.min(math.floor(screen_h * 0.6), math.max(above, below))
    local side = above > below and "above" or "below"
    if room < screen_h / 3 then
        room, side = math.floor(screen_h * 0.6), "centre"
    end

    -- Text area: as tall as the text, up to what the room leaves.
    local face = Font:getFace("x_smallinfofont")
    local padding = Size.padding.large
    local text = TextBoxWidget.PTF_HEADER .. (self.text or "")
    local text_w = self.width - 2 * padding
    local scroll_bar = ScrollTextWidget.scroll_bar_width + ScrollTextWidget.text_scroll_span
    local measure = TextBoxWidget:new{
        text = text, face = face, width = text_w - scroll_bar, for_measurement_only = true,
    }
    local text_h = measure:getSize().h
    measure:free()
    local max_h = room - self.titlebar:getHeight() - self.button_table:getSize().h
        - 2 * padding - 2 * Size.border.window
    max_h = math.max(max_h, face.size * 3)
    self.scroll = ScrollTextWidget:new{
        text = text,
        face = face,
        width = text_w,
        height = math.min(text_h, max_h),
        dialog = self,
    }

    self.frame = FrameContainer:new{
        radius = Size.radius.window,
        bordersize = Size.border.window,
        padding = 0,
        margin = 0,
        background = Blitbuffer.COLOR_WHITE,
        VerticalGroup:new{
            align = "left",
            self.titlebar,
            FrameContainer:new{ padding = padding, bordersize = 0, margin = 0, self.scroll },
            CenterContainer:new{
                dimen = Geom:new{ w = self.width, h = self.button_table:getSize().h },
                self.button_table,
            },
        },
    }
    self[1] = self.frame

    -- Position: keep the tapped character visible.
    local size = self.frame:getSize()
    self.frame_x = math.floor((screen_w - size.w) / 2)
    local y
    if side == "below" then
        y = box.y + box.h + margin
    elseif side == "above" then
        y = box.y - size.h - margin
    else
        y = math.floor((screen_h - size.h) / 2)
    end
    self.frame_y = math.max(0, math.min(y, screen_h - size.h))
end

function Popup:paintTo(bb, x, y)
    self.frame:paintTo(bb, x + self.frame_x, y + self.frame_y)
end

function Popup:onShow()
    UIManager:setDirty(self, function() return "ui", self.frame.dimen end)
    return true
end

function Popup:onClose()
    UIManager:close(self, "ui", self.frame.dimen)
    return true
end

-- A tap outside the popup closes it (and goes no further: it does not also
-- turn the page). Taps inside that no button took are ignored.
function Popup:onTapClose(_, ges)
    if self.frame.dimen and ges.pos:notIntersectWith(self.frame.dimen) then
        self:onClose()
    end
    return true
end

return Popup
