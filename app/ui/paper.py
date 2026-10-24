from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QFrame

from app.database import COLORS


PAPER_PALETTES = {
    "yellow": ("#FFF1B8", "#F4DE8A", "#403719", "#6E5D32", "#D0B95F"),
    "pink": ("#FFE0E8", "#F0C0D0", "#442D36", "#765B65", "#D69AAE"),
    "mint": ("#DCF3DF", "#BFE2C8", "#293C30", "#587260", "#91C29D"),
    "blue": ("#DFEFFB", "#C4DDF0", "#2B3945", "#5A7183", "#91B8D5"),
    "lavender": ("#EAE2FC", "#D2C6ED", "#393247", "#685F78", "#ADA0D4"),
    "peach": ("#FFECDE", "#F2D2B9", "#44362E", "#765D4D", "#D7A47D"),
    "gray": ("#F0EFEB", "#DEDCD4", "#34332F", "#66645B", "#B7B2A5"),
    "graphite": ("#555360", "#343440", "#F7F2E9", "#D1C8D4", "#8D849F"),
    "cream": ("#FFF4DF", "#F1E1C5", "#413729", "#71634D", "#D5BE92"),
    "dark": ("#454352", "#302F3C", "#F6F1E9", "#CCC5D6", "#9F91C6"),
}


def paper_palette(color: str, custom_color: str = "#E9D5FF") -> dict[str, str]:
    if color in PAPER_PALETTES:
        top, bottom, foreground, muted, accent = PAPER_PALETTES[color]
        return {
            "top": top,
            "bottom": bottom,
            "foreground": foreground,
            "muted": muted,
            "accent": accent,
            "border": QColor(bottom).darker(112).name(),
        }

    base = QColor(custom_color)
    if not base.isValid():
        base = QColor(COLORS["yellow"])
    is_dark = base.lightness() < 128
    foreground = "#F7F3EC" if is_dark else "#302B3D"
    muted = "#D0C9D7" if is_dark else "#665F70"
    return {
        "top": base.lighter(108).name(),
        "bottom": base.darker(106).name(),
        "foreground": foreground,
        "muted": muted,
        "accent": base.darker(115).name() if not is_dark else base.lighter(135).name(),
        "border": base.darker(118).name() if not is_dark else base.lighter(125).name(),
    }


class PaperSurface(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._palette = paper_palette("yellow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def set_paper(self, color: str, custom_color: str = "#E9D5FF"):
        self._palette = paper_palette(color, custom_color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        gradient = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
        gradient.setColorAt(0, QColor(self._palette["top"]))
        gradient.setColorAt(1, QColor(self._palette["bottom"]))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(self._palette["border"]), 1))
        painter.drawRoundedRect(bounds, 5, 5)

        grain = QColor(self._palette["foreground"])
        grain.setAlpha(10)
        painter.setPen(QPen(grain, 1))
        width = max(1, self.width() - 12)
        height = max(1, self.height() - 12)
        for index in range(52):
            x = 6 + (index * 47 + 13) % width
            y = 6 + (index * 83 + 29) % height
            painter.drawLine(x, y, x + 3 + index % 9, y)
