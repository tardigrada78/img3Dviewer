#!/usr/bin/env python3
"""
MPO/JPS/JPG/PNG Viewer with Red-Cyan Anaglyph support
Requires: pip install --user --break-system-packages pyside6 pillow numpy send2trash
"""

import sys
import os
import struct
import numpy as np
from pathlib import Path
from PIL import Image

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QSizePolicy, QRubberBand, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem
)
from PySide6.QtCore import (
    Qt, QSize, QRect, QPoint, QRectF, QTimer, Signal, QObject
)
from PySide6.QtGui import (
    QPixmap, QImage, QKeySequence, QShortcut, QCursor, QPainter,
    QPen, QColor, QBrush, QFont, QFontDatabase, QIcon, QTransform,
    QWheelEvent, QDragEnterEvent, QDropEvent
)

# ─── Supported file types ────────────────────────────────────────────────────
SUPPORTED_EXTS = {'.jpg', '.jpeg', '.png', '.mpo', '.jps', '.webp', '.avif'}
EDITABLE_EXTS  = {'.jpg', '.jpeg', '.png', '.webp', '.avif'}
STEREO_EXTS    = {'.mpo', '.jps'}

# ─── Anaglyph modes ──────────────────────────────────────────────────────────
MODE_2D       = 0
MODE_SIMPLE   = 1
MODE_OPTIMIZED = 2

MODE_LABELS = {
    MODE_2D:        "2D",
    MODE_SIMPLE:    "3D simple",
    MODE_OPTIMIZED: "3D optimized",
}

# ─── MPO Parsing ─────────────────────────────────────────────────────────────

def parse_mpo(data: bytes):
    """Extract left and right images from MPO using Pillow's built-in MPO support."""
    from io import BytesIO
    from PIL import ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True

    img = Image.open(BytesIO(data))
    if img.format != 'MPO':
        raise ValueError(f"Not an MPO file (format: {img.format})")

    frames = []
    try:
        img.seek(0)
        frames.append(img.copy().convert("RGB"))
        img.seek(1)
        frames.append(img.copy().convert("RGB"))
    except EOFError:
        pass

    if len(frames) < 2:
        raise ValueError(f"MPO file only contains {len(frames)} frame(s), need 2")

    return frames[0], frames[1]


def parse_jps(img: Image.Image):
    """Split a side-by-side JPS image into left and right halves."""
    w, h = img.size
    left  = img.crop((0, 0, w // 2, h))
    right = img.crop((w // 2, 0, w, h))
    return left.convert("RGB"), right.convert("RGB")


# ─── Anaglyph Rendering ──────────────────────────────────────────────────────

def make_anaglyph_simple(left: Image.Image, right: Image.Image) -> Image.Image:
    """Classic grayscale red-cyan anaglyph."""
    l = np.array(left,  dtype=np.float32)
    r = np.array(right, dtype=np.float32)

    l_gray = 0.299*l[...,0] + 0.587*l[...,1] + 0.114*l[...,2]
    r_gray = 0.299*r[...,0] + 0.587*r[...,1] + 0.114*r[...,2]

    out = np.zeros_like(l)
    out[..., 0] = l_gray
    out[..., 1] = r_gray
    out[..., 2] = r_gray

    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def make_anaglyph_optimized(left: Image.Image, right: Image.Image) -> Image.Image:
    """Optimized anaglyph preserving some color (Dubois-inspired)."""
    l = np.array(left,  dtype=np.float32)
    r = np.array(right, dtype=np.float32)

    out = np.zeros_like(l)
    # Red channel: weighted mix of left RGB
    out[..., 0] = np.clip(0.4154*l[...,0] + 0.4710*l[...,1] + 0.1669*l[...,2], 0, 255)
    # Green channel: right image
    out[..., 1] = np.clip(-0.0458*r[...,0] + 0.3786*r[...,1] + 0.0203*r[...,2], 0, 255)
    # Blue channel: right image
    out[..., 2] = np.clip(-0.0574*r[...,0] + 0.0271*r[...,1] + 1.0602*r[...,2], 0, 255)

    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


# ─── Image Loading ───────────────────────────────────────────────────────────

class LoadedImage:
    def __init__(self, path: Path):
        self.path    = path
        self.ext     = path.suffix.lower()
        self.is_stereo = self.ext in STEREO_EXTS
        self.is_editable = self.ext in EDITABLE_EXTS

        self._left  = None
        self._right = None
        self._flat  = None   # PIL Image for 2D display / editing

        self._load()

    def _load(self):
        if self.ext == '.mpo':
            data = self.path.read_bytes()
            self._left, self._right = parse_mpo(data)
            self._flat = self._left.copy()
        elif self.ext == '.jps':
            img = Image.open(self.path).convert("RGB")
            self._left, self._right = parse_jps(img)
            self._flat = self._left.copy()
        else:
            img = Image.open(self.path)
            # Preserve alpha for formats that support transparency
            if img.mode in ('RGBA', 'LA', 'PA'):
                self._flat = img.convert("RGBA")
            else:
                self._flat = img.convert("RGB")

    def get_display(self, mode: int) -> Image.Image:
        if self.is_stereo:
            if mode == MODE_SIMPLE:
                return make_anaglyph_simple(self._left, self._right)
            elif mode == MODE_OPTIMIZED:
                return make_anaglyph_optimized(self._left, self._right)
        return self._flat

    def rotate_cw(self):
        if self.is_editable:
            self._flat = self._flat.rotate(-90, expand=True)

    def crop(self, rect: QRect, display_size: QSize, orig_size: tuple):
        """Crop based on display coordinates, mapping back to original."""
        if not self.is_editable:
            return
        ow, oh = orig_size
        dw, dh = display_size.width(), display_size.height()
        sx = ow / dw
        sy = oh / dh
        x1 = int(rect.left()   * sx)
        y1 = int(rect.top()    * sy)
        x2 = int(rect.right()  * sx)
        y2 = int(rect.bottom() * sy)
        x1, x2 = max(0,min(x1,ow)), max(0,min(x2,ow))
        y1, y2 = max(0,min(y1,oh)), max(0,min(y2,oh))
        if x2 > x1 and y2 > y1:
            self._flat = self._flat.crop((x1, y1, x2, y2))

    def save(self):
        if self.is_editable:
            self._flat.save(str(self.path))

    @property
    def size(self):
        if self._flat:
            return self._flat.size
        if self._left:
            return self._left.size
        return (0, 0)

    @property
    def capture_date(self) -> str | None:
        """Return EXIF DateTimeOriginal as readable string, or None."""
        try:
            src = self._flat or self._left
            if src is None:
                return None
            exif = src._getexif() if hasattr(src, '_getexif') else None
            if exif is None:
                # Try via getexif() (Pillow ≥ 6)
                info = src.getexif() if hasattr(src, 'getexif') else {}
                # Tag 36867 = DateTimeOriginal, 306 = DateTime
                for tag in (36867, 36868, 306):
                    val = info.get(tag)
                    if val:
                        return self._fmt_date(val)
                return None
            for tag in (36867, 36868, 306):
                val = exif.get(tag)
                if val:
                    return self._fmt_date(val)
        except Exception:
            pass
        return None

    @staticmethod
    def _fmt_date(raw: str) -> str:
        """Convert '2012:07:14 15:32:00' → '14.07.2012  15:32'."""
        try:
            from datetime import datetime
            dt = datetime.strptime(raw.strip(), "%Y:%m:%d %H:%M:%S")
            return dt.strftime("%d.%m.%Y  %H:%M")
        except Exception:
            return raw


# ─── PIL → QPixmap ───────────────────────────────────────────────────────────

def pil_to_qpixmap(img: Image.Image) -> tuple[QPixmap, bool]:
    """Convert PIL image to QPixmap. Returns (pixmap, has_alpha)."""
    has_alpha = img.mode in ('RGBA', 'LA', 'PA')
    if has_alpha:
        img_rgba = img.convert("RGBA")
        data  = img_rgba.tobytes("raw", "RGBA")
        qimg  = QImage(data, img_rgba.width, img_rgba.height,
                       img_rgba.width * 4, QImage.Format.Format_RGBA8888)
    else:
        img_rgb = img.convert("RGB")
        data  = img_rgb.tobytes("raw", "RGB")
        qimg  = QImage(data, img_rgb.width, img_rgb.height,
                       img_rgb.width * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg), has_alpha


# ─── Crop Overlay ────────────────────────────────────────────────────────────

HANDLE_SIZE = 10

class CropOverlay(QWidget):
    cropChanged = Signal(QRect)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self._rect    = QRect()
        self._active  = False
        self._drawing = False
        self._drag_handle = None
        self._drag_start  = QPoint()
        self._orig_rect   = QRect()
        self._origin      = QPoint()

    def activate(self):
        self._active = True
        self._rect   = QRect()
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()

    def deactivate(self):
        self._active  = False
        self._drawing = False
        self._rect    = QRect()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def current_rect(self) -> QRect:
        return self._rect.normalized()

    def _handle_rects(self):
        r = self._rect.normalized()
        s = HANDLE_SIZE
        return {
            'tl': QRect(r.left()-s//2,      r.top()-s//2,     s, s),
            'tr': QRect(r.right()-s//2,     r.top()-s//2,     s, s),
            'bl': QRect(r.left()-s//2,      r.bottom()-s//2,  s, s),
            'br': QRect(r.right()-s//2,     r.bottom()-s//2,  s, s),
        }

    def _hit_handle(self, pos):
        for key, rect in self._handle_rects().items():
            if rect.contains(pos):
                return key
        return None

    def mousePressEvent(self, event):
        if not self._active:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if self._rect.normalized().isValid():
                h = self._hit_handle(pos)
                if h:
                    self._drag_handle = h
                    self._drag_start  = pos
                    self._orig_rect   = self._rect.normalized()
                    return
            self._drawing = True
            self._origin  = pos
            self._rect    = QRect(pos, QSize())

    def mouseMoveEvent(self, event):
        if not self._active:
            return
        pos = event.position().toPoint()
        if self._drawing:
            self._rect = QRect(self._origin, pos)
            self.update()
        elif self._drag_handle:
            dx = pos.x() - self._drag_start.x()
            dy = pos.y() - self._drag_start.y()
            r  = QRect(self._orig_rect)
            if 't' in self._drag_handle:
                r.setTop(r.top() + dy)
            if 'b' in self._drag_handle:
                r.setBottom(r.bottom() + dy)
            if 'l' in self._drag_handle:
                r.setLeft(r.left() + dx)
            if 'r' in self._drag_handle:
                r.setRight(r.right() + dx)
            self._rect = r
            self.update()
        else:
            h = self._hit_handle(pos)
            cursors = {
                'tl': Qt.CursorShape.SizeFDiagCursor,
                'br': Qt.CursorShape.SizeFDiagCursor,
                'tr': Qt.CursorShape.SizeBDiagCursor,
                'bl': Qt.CursorShape.SizeBDiagCursor,
            }
            self.setCursor(cursors.get(h, Qt.CursorShape.CrossCursor))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drawing     = False
            self._drag_handle = None
            self.cropChanged.emit(self._rect.normalized())

    def paintEvent(self, event):
        if not self._active or not self._rect.normalized().isValid():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        r = self._rect.normalized()
        # Dim outside
        dimmed = QColor(0, 0, 0, 110)
        painter.fillRect(0, 0, self.width(), r.top(),          dimmed)
        painter.fillRect(0, r.bottom(), self.width(), self.height(), dimmed)
        painter.fillRect(0, r.top(), r.left(), r.height(),     dimmed)
        painter.fillRect(r.right(), r.top(), self.width()-r.right(), r.height(), dimmed)

        # Border
        painter.setPen(QPen(QColor(255, 255, 255, 220), 1.5, Qt.PenStyle.DashLine))
        painter.drawRect(r)

        # Handles
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.setBrush(QBrush(QColor(80, 180, 255, 230)))
        for hr in self._handle_rects().values():
            painter.drawRoundedRect(hr, 2, 2)

        painter.end()


# ─── Image Canvas ────────────────────────────────────────────────────────────

class ImageCanvas(QWidget):
    zoomChanged = Signal()   # emitted whenever zoom level changes

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # prevent arrow keys being eaten
        self._pixmap     = None
        self._zoom       = 1.0
        self._offset     = QPoint(0, 0)
        self._fit        = True

        # Transparency
        self._has_alpha  = False

        # Pan state
        self._pan_active = False
        self._pan_start  = QPoint()
        self._pan_offset_start = QPoint()

        # Crop overlay
        self._crop_overlay = CropOverlay(self)
        self._crop_overlay.hide()
        self._crop_mode = False

    def set_pixmap(self, pixmap: QPixmap):
        self._pixmap = pixmap
        self._fit    = True
        self._zoom   = 1.0
        self._offset = QPoint(0, 0)
        self._crop_overlay.deactivate()
        self._crop_overlay.hide()
        self._crop_mode = False
        self.update()

    def enter_crop_mode(self):
        if self._pixmap is None:
            return
        self._crop_mode = True
        self._crop_overlay.setGeometry(self.rect())
        self._crop_overlay.show()
        self._crop_overlay.activate()

    def exit_crop_mode(self):
        self._crop_mode = False
        self._crop_overlay.deactivate()
        self._crop_overlay.hide()

    def get_crop_rect_in_image(self) -> QRect:
        """Return crop rect mapped to actual image pixels."""
        if self._pixmap is None:
            return QRect()
        cr = self._crop_overlay.current_rect()
        if not cr.isValid():
            return QRect()
        img_rect = self._image_rect()
        # Map from widget coords to image coords
        x1 = cr.left()   - img_rect.left()
        y1 = cr.top()    - img_rect.top()
        x2 = cr.right()  - img_rect.left()
        y2 = cr.bottom() - img_rect.top()
        scale = self._pixmap.width() / img_rect.width()
        return QRect(int(x1*scale), int(y1*scale), int((x2-x1)*scale), int((y2-y1)*scale))

    def get_display_image_size(self) -> QSize:
        r = self._image_rect()
        return QSize(r.width(), r.height())

    def zoom_percent(self) -> int:
        """Return current effective zoom as integer percent."""
        if self._pixmap is None:
            return 100
        if self._fit:
            pw, ph = self._pixmap.width(), self._pixmap.height()
            cw, ch = self.width(), self.height()
            if pw == 0 or ph == 0:
                return 100
            scale = min(cw / pw, ch / ph)
            return int(scale * 100)
        return int(self._zoom * 100)

    def is_fit(self) -> bool:
        return self._fit

    def _image_rect(self) -> QRect:
        if self._pixmap is None:
            return QRect()
        pw, ph = self._pixmap.width(), self._pixmap.height()
        if self._fit:
            cw, ch = self.width(), self.height()
            scale = min(cw/pw, ch/ph)
            nw, nh = int(pw*scale), int(ph*scale)
            x = (cw - nw) // 2
            y = (ch - nh) // 2
            return QRect(x, y, nw, nh)
        else:
            nw = int(pw * self._zoom)
            nh = int(ph * self._zoom)
            x = (self.width()  - nw) // 2 + self._offset.x()
            y = (self.height() - nh) // 2 + self._offset.y()
            return QRect(x, y, nw, nh)

    def _clamp_offset(self):
        """Keep image from being panned completely off screen."""
        if self._pixmap is None:
            return
        pw, ph = self._pixmap.width(), self._pixmap.height()
        nw = int(pw * self._zoom)
        nh = int(ph * self._zoom)
        cw, ch = self.width(), self.height()
        # Allow panning until at least 40px of image remains visible
        margin = 40
        max_x = nw // 2 + cw // 2 - margin
        max_y = nh // 2 + ch // 2 - margin
        ox = max(-max_x, min(max_x, self._offset.x()))
        oy = max(-max_y, min(max_y, self._offset.y()))
        self._offset = QPoint(ox, oy)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._crop_overlay:
            self._crop_overlay.setGeometry(self.rect())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # Dark background always
        painter.fillRect(self.rect(), QColor(18, 18, 22))
        if self._pixmap:
            r = self._image_rect()
            # Draw checkerboard under image area (visible through transparent pixels)
            if self._has_alpha:
                tile = 12
                c1 = QColor(80, 80, 80)
                c2 = QColor(50, 50, 50)
                for row in range(r.top(), r.bottom(), tile):
                    for col in range(r.left(), r.right(), tile):
                        dark = ((row // tile) + (col // tile)) % 2 == 0
                        painter.fillRect(
                            col, row,
                            min(tile, r.right()  - col),
                            min(tile, r.bottom() - row),
                            c1 if dark else c2
                        )
            painter.drawPixmap(r, self._pixmap)
        painter.end()

    def set_has_alpha(self, value: bool):
        self._has_alpha = value

    def mousePressEvent(self, event):
        if self._crop_mode:
            super().mousePressEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton and not self._fit:
            self._pan_active = True
            self._pan_start  = event.position().toPoint()
            self._pan_offset_start = QPoint(self._offset)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._crop_mode:
            super().mouseMoveEvent(event)
            return
        if self._pan_active:
            delta = event.position().toPoint() - self._pan_start
            self._offset = self._pan_offset_start + delta
            self._clamp_offset()
            self.update()
            self.zoomChanged.emit()

    def mouseReleaseEvent(self, event):
        if self._crop_mode:
            super().mouseReleaseEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._pan_active = False
            if not self._fit:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def wheelEvent(self, event: QWheelEvent):
        if self._pixmap is None:
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return

        # Zoom toward mouse position (no modifier needed)
        mouse_pos = event.position().toPoint()
        old_rect  = self._image_rect()

        if delta > 0:
            self._zoom = min(self._zoom * 1.15, 20.0)
        else:
            self._zoom = max(self._zoom / 1.15, 0.05)
        self._fit = False

        # Adjust offset so zoom centres on mouse pointer
        if old_rect.isValid() and old_rect.width() > 0:
            new_rect = self._image_rect()
            sx = new_rect.width()  / old_rect.width()
            sy = new_rect.height() / old_rect.height()
            dx = (mouse_pos.x() - old_rect.center().x()) * (sx - 1)
            dy = (mouse_pos.y() - old_rect.center().y()) * (sy - 1)
            self._offset = QPoint(self._offset.x() - int(dx), self._offset.y() - int(dy))
            self._clamp_offset()

        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.update()
        self.zoomChanged.emit()

    def reset_zoom(self):
        self._fit    = True
        self._zoom   = 1.0
        self._offset = QPoint(0, 0)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()


# ─── Folder Navigator ────────────────────────────────────────────────────────

class FolderNavigator:
    def __init__(self):
        self._files  = []
        self._index  = -1

    def load_folder(self, path: Path, current: Path = None):
        self._files = sorted(
            [f for f in path.iterdir() if f.suffix.lower() in SUPPORTED_EXTS],
            key=lambda f: f.name.lower()
        )
        if current and current in self._files:
            self._index = self._files.index(current)
        elif self._files:
            self._index = 0

    def current(self) -> Path:
        if 0 <= self._index < len(self._files):
            return self._files[self._index]
        return None

    def next(self) -> Path:
        if not self._files:
            return None
        self._index = (self._index + 1) % len(self._files)
        return self.current()

    def prev(self) -> Path:
        if not self._files:
            return None
        self._index = (self._index - 1) % len(self._files)
        return self.current()

    def remove_current(self):
        if 0 <= self._index < len(self._files):
            self._files.pop(self._index)
            if self._index >= len(self._files):
                self._index = len(self._files) - 1

    @property
    def count(self):
        return len(self._files)

    @property
    def index(self):
        return self._index


# ─── Main Window ─────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image 3D Viewer")
        self.setMinimumSize(800, 600)
        self.resize(1100, 750)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._loaded     : LoadedImage | None = None
        self._mode       : int  = MODE_2D
        self._dirty      : bool = False
        self._navigator  = FolderNavigator()
        self._crop_active: bool = False

        self._build_ui()
        self._apply_style()
        self._update_info()

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ──────────────────────────────────────────────────────────
        self._topbar = QWidget()
        self._topbar.setFixedHeight(36)
        self._topbar.setObjectName("topbar")
        top_layout = QHBoxLayout(self._topbar)
        top_layout.setContentsMargins(16, 0, 16, 0)
        top_layout.setSpacing(20)

        self._lbl_filename = QLabel("—")
        self._lbl_filename.setObjectName("topLabel")
        self._lbl_res      = QLabel("")
        self._lbl_res.setObjectName("topLabelDim")
        self._lbl_date     = QLabel("")
        self._lbl_date.setObjectName("topLabelDim")
        self._lbl_zoom     = QLabel("")
        self._lbl_zoom.setObjectName("topLabelDim")
        self._lbl_mode     = QLabel("")
        self._lbl_mode.setObjectName("modeLabel")
        self._lbl_nav      = QLabel("")
        self._lbl_nav.setObjectName("topLabelDim")

        top_layout.addWidget(self._lbl_filename)
        top_layout.addWidget(self._lbl_res)
        top_layout.addWidget(self._lbl_date)
        top_layout.addStretch()
        top_layout.addWidget(self._lbl_nav)
        top_layout.addWidget(self._lbl_zoom)
        top_layout.addWidget(self._lbl_mode)
        root.addWidget(self._topbar)

        # ── Canvas ───────────────────────────────────────────────────────────
        self._canvas = ImageCanvas()
        self._canvas._crop_overlay.cropChanged.connect(self._on_crop_changed)
        self._canvas.zoomChanged.connect(self._update_info)
        root.addWidget(self._canvas, 1)

        # ── Bottom bar ───────────────────────────────────────────────────────
        self._bottombar = QWidget()
        self._bottombar.setFixedHeight(52)
        self._bottombar.setObjectName("bottombar")
        bot_layout = QHBoxLayout(self._bottombar)
        bot_layout.setContentsMargins(20, 0, 20, 0)
        bot_layout.setSpacing(6)

        btn_defs = [
            ("open_btn",   "⊕  Open",   "O – Open file",           self._action_open),
            ("prev_btn",   "◀",          "← – Previous image",      self._action_prev),
            ("next_btn",   "▶",          "→ – Next image",          self._action_next),
            (None, None, None, None),  # spacer
            ("mode_btn",   "⊙  2D",      "D – Toggle 2D/3D mode",   self._action_toggle_mode),
            (None, None, None, None),
            ("rot_btn",    "↻  Rotate",  "R – Rotate 90° CW",       self._action_rotate),
            ("crop_btn",   "⊡  Crop",    "C – Crop mode",           self._action_crop),
            ("save_btn",   "↓  Save",    "S – Save changes",        self._action_save),
            (None, None, None, None),
            ("del_btn",    "⊗  Delete",  "Del – Move to trash",     self._action_delete),
            (None, None, None, None),
            ("full_btn",   "⛶  Full",   "F – Fullscreen",          self._action_fullscreen),
        ]

        self._buttons = {}
        for item in btn_defs:
            obj_name, label, tooltip, callback = item
            if obj_name is None:
                spacer = QWidget()
                spacer.setFixedWidth(8)
                bot_layout.addWidget(spacer)
                continue
            btn = QPushButton(label)
            btn.setObjectName(obj_name)
            btn.setToolTip(tooltip)
            btn.setFixedHeight(36)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # don't steal arrow keys
            btn.clicked.connect(callback)
            bot_layout.addWidget(btn)
            self._buttons[obj_name] = btn

        root.addWidget(self._bottombar)

        # ── Status message (overlay on canvas) ───────────────────────────────
        self._status_lbl = QLabel("", self._canvas)
        self._status_lbl.setObjectName("statusMsg")
        self._status_lbl.hide()
        self._status_timer = QTimer()
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._status_lbl.hide)

    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #12121a;
                color: #e8e8f0;
                font-family: 'Cantarell', 'Noto Sans', 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            #topbar {
                background: #1a1a26;
                border-bottom: 1px solid #2a2a3a;
            }
            #topbar QLabel {
                background: transparent;
            }
            #topLabel {
                color: #d8d8ec;
                font-weight: 600;
                font-size: 13px;
                letter-spacing: 0.02em;
            }
            #topLabelDim {
                color: #6868a0;
                font-size: 12px;
            }
            #modeLabel {
                color: #7eb8f7;
                font-size: 12px;
                font-weight: 600;
                letter-spacing: 0.05em;
                padding: 2px 8px;
                border: 1px solid #3a4a7a;
                border-radius: 10px;
                background: #1e2440;
            }
            #bottombar {
                background: #16161f;
                border-top: 1px solid #2a2a3a;
            }
            QPushButton {
                background: #22223a;
                color: #c8c8e8;
                border: 1px solid #32326a;
                border-radius: 7px;
                padding: 0 14px;
                font-size: 12px;
                font-weight: 500;
                letter-spacing: 0.03em;
            }
            QPushButton:hover {
                background: #2e2e50;
                border-color: #5858aa;
                color: #eeeeff;
            }
            QPushButton:pressed {
                background: #3a3a6a;
            }
            #del_btn {
                color: #e07070;
                border-color: #5a3232;
            }
            #del_btn:hover {
                background: #3a1c1c;
                border-color: #e07070;
                color: #ff9090;
            }
            #save_btn {
                color: #70d0a0;
                border-color: #2a5a3a;
            }
            #save_btn:hover {
                background: #1a3a28;
                border-color: #70d0a0;
            }
            #crop_btn[active="true"] {
                background: #2a3a5a;
                border-color: #7eb8f7;
                color: #7eb8f7;
            }
            #statusMsg {
                background: rgba(20,20,40,0.85);
                color: #b8d8ff;
                font-size: 13px;
                padding: 7px 18px;
                border-radius: 8px;
                border: 1px solid #3a4a7a;
            }
        """)

    # ── Status flash ─────────────────────────────────────────────────────────

    def _flash(self, msg: str, ms: int = 1800):
        self._status_lbl.setText(msg)
        self._status_lbl.adjustSize()
        # Center horizontally, place near bottom of canvas
        x = (self._canvas.width()  - self._status_lbl.width())  // 2
        y =  self._canvas.height() - self._status_lbl.height() - 20
        self._status_lbl.move(x, y)
        self._status_lbl.show()
        self._status_timer.start(ms)

    # ── Info update ──────────────────────────────────────────────────────────

    def _update_info(self):
        if self._loaded is None:
            self._lbl_filename.setText("Drop an image here or press O")
            self._lbl_res.setText("")
            self._lbl_date.setText("")
            self._lbl_zoom.setText("")
            self._lbl_mode.setText("")
            self._lbl_nav.setText("")
        else:
            name = self._loaded.path.name
            self._lbl_filename.setText(name)
            w, h = self._loaded.size
            self._lbl_res.setText(f"{w} × {h}")
            self._lbl_date.setText(self._loaded.capture_date or "")
            self._lbl_zoom.setText(f"{self._canvas.zoom_percent()}%")
            self._lbl_mode.setText(MODE_LABELS[self._mode])
            n = self._navigator.count
            i = self._navigator.index + 1
            self._lbl_nav.setText(f"{i} / {n}" if n else "")
            # Update mode button label
            self._buttons['mode_btn'].setText(f"⊙  {MODE_LABELS[self._mode]}")
            # Dim save button if nothing to save
            self._buttons['save_btn'].setEnabled(self._dirty)

    def _refresh_display(self):
        if self._loaded is None:
            self._canvas.set_pixmap(None)
            return
        img = self._loaded.get_display(self._mode)
        pixmap, has_alpha = pil_to_qpixmap(img)
        self._canvas.set_pixmap(pixmap)
        self._canvas.set_has_alpha(has_alpha)
        self._update_info()

    # ── File loading ─────────────────────────────────────────────────────────

    def _load_file(self, path: Path):
        try:
            prev_mode = self._mode  # remember current mode
            self._loaded  = LoadedImage(path)
            self._dirty   = False
            self._crop_active = False
            self._buttons['crop_btn'].setProperty("active", "false")
            self._buttons['crop_btn'].style().unpolish(self._buttons['crop_btn'])
            self._buttons['crop_btn'].style().polish(self._buttons['crop_btn'])
            # Keep 3D mode if new image is also stereo, otherwise reset to 2D
            if self._loaded.is_stereo and prev_mode != MODE_2D:
                self._mode = prev_mode
            else:
                self._mode = MODE_2D
            self._navigator.load_folder(path.parent, path)
            self._refresh_display()
        except Exception as e:
            self._flash(f"Error: {e}", 3000)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _action_rename(self):
        if self._loaded is None:
            return
        from PySide6.QtWidgets import QInputDialog
        old_path = self._loaded.path
        stem     = old_path.stem
        suffix   = old_path.suffix  # keep extension
        new_stem, ok = QInputDialog.getText(
            self, "Rename", "New filename (without extension):",
            text=stem
        )
        if not ok or not new_stem.strip():
            return
        new_stem = new_stem.strip()
        # Sanitise: remove path separators
        new_stem = new_stem.replace('/', '').replace('\\', '')
        if not new_stem:
            return
        new_path = old_path.parent / (new_stem + suffix)
        if new_path == old_path:
            return
        if new_path.exists():
            self._flash(f"File already exists: {new_path.name}", 3000)
            return
        try:
            old_path.rename(new_path)
            self._loaded.path = new_path
            # Update navigator list
            self._navigator.load_folder(new_path.parent, new_path)
            self._update_info()
            self._flash(f"Renamed → {new_path.name}")
        except Exception as e:
            self._flash(f"Rename error: {e}", 3000)

    def _action_toggle_100(self):
        if self._loaded is None:
            return
        if not self._canvas._fit and self._canvas._zoom == 1.0:
            # Already at 100% → back to fit
            self._canvas.reset_zoom()
        else:
            # Go to 100%, centred
            self._canvas._fit    = False
            self._canvas._zoom   = 1.0
            self._canvas._offset = QPoint(0, 0)
            self._canvas.setCursor(Qt.CursorShape.OpenHandCursor)
            self._canvas.update()
        self._update_info()

    def _action_open(self):
        start = str(self._loaded.path.parent) if self._loaded else os.path.expanduser("~")
        fname, _ = QFileDialog.getOpenFileName(
            self, "Open Image", start,
            "Images (*.jpg *.jpeg *.png *.mpo *.jps *.webp *.avif)"
        )
        if fname:
            self._load_file(Path(fname))

    def _action_prev(self):
        p = self._navigator.prev()
        if p:
            self._load_file(p)

    def _action_next(self):
        p = self._navigator.next()
        if p:
            self._load_file(p)

    def _action_toggle_mode(self):
        if self._loaded and self._loaded.is_stereo:
            self._mode = (self._mode + 1) % 3
        else:
            return
        self._refresh_display()

    def _action_rotate(self):
        if self._loaded and self._loaded.is_editable:
            self._loaded.rotate_cw()
            self._dirty = True
            self._refresh_display()
        elif self._loaded:
            self._flash("Rotate not available for 3D files")

    def _action_crop(self):
        if not self._loaded:
            return
        if not self._loaded.is_editable:
            self._flash("Crop not available for 3D files")
            return
        self._crop_active = not self._crop_active
        if self._crop_active:
            self._canvas.enter_crop_mode()
            self._buttons['crop_btn'].setProperty("active", "true")
            self._flash("Draw crop rectangle · drag corners to adjust", 2500)
        else:
            self._canvas.exit_crop_mode()
            self._buttons['crop_btn'].setProperty("active", "false")
        self._buttons['crop_btn'].style().unpolish(self._buttons['crop_btn'])
        self._buttons['crop_btn'].style().polish(self._buttons['crop_btn'])

    def _on_crop_changed(self, rect: QRect):
        pass  # Crop is applied on S

    def _apply_crop(self):
        if not self._loaded or not self._crop_active:
            return False
        cr = self._canvas.get_crop_rect_in_image()
        if not cr.isValid() or cr.width() < 4 or cr.height() < 4:
            return False
        # Build a QRect in pixel coords relative to original image
        img_w, img_h = self._loaded.size
        disp_rect = self._canvas._image_rect()
        disp_size = QSize(disp_rect.width(), disp_rect.height())
        crop_overlay_rect = self._canvas._crop_overlay.current_rect()
        # Map overlay rect (widget coords) → image pixel coords
        if not crop_overlay_rect.isValid():
            return False
        ox = disp_rect.left()
        oy = disp_rect.top()
        sx = img_w / disp_rect.width()
        sy = img_h / disp_rect.height()
        x1 = int((crop_overlay_rect.left()   - ox) * sx)
        y1 = int((crop_overlay_rect.top()    - oy) * sy)
        x2 = int((crop_overlay_rect.right()  - ox) * sx)
        y2 = int((crop_overlay_rect.bottom() - oy) * sy)
        x1 = max(0, min(x1, img_w)); x2 = max(0, min(x2, img_w))
        y1 = max(0, min(y1, img_h)); y2 = max(0, min(y2, img_h))
        if x2 <= x1 or y2 <= y1:
            return False
        from PIL import Image as PILImage
        self._loaded._flat = self._loaded._flat.crop((x1, y1, x2, y2))
        self._canvas.exit_crop_mode()
        self._crop_active = False
        self._buttons['crop_btn'].setProperty("active", "false")
        self._buttons['crop_btn'].style().unpolish(self._buttons['crop_btn'])
        self._buttons['crop_btn'].style().polish(self._buttons['crop_btn'])
        return True

    def _action_save(self):
        if not self._loaded or not self._loaded.is_editable:
            return
        if not self._dirty and not self._crop_active:
            self._flash("No changes to save")
            return
        if self._crop_active:
            if not self._apply_crop():
                self._flash("Draw a crop area first")
                return
        self._loaded.save()
        self._dirty = False
        self._refresh_display()
        self._flash(f"Saved ✓")

    def _action_delete(self):
        if not self._loaded:
            return
        try:
            from send2trash import send2trash
            path = str(self._loaded.path)
            self._navigator.remove_current()
            send2trash(path)
            next_path = self._navigator.current()
            if next_path:
                self._load_file(next_path)
            else:
                self._loaded = None
                self._canvas.set_pixmap(None)
                self._update_info()
            self._flash("Moved to trash")
        except Exception as e:
            self._flash(f"Trash error: {e}", 3000)

    def _action_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    # ── Drag & Drop ──────────────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = Path(urls[0].toLocalFile())
            if path.suffix.lower() in SUPPORTED_EXTS:
                self._load_file(path)
            else:
                self._flash("Unsupported file type")

    # ── Keyboard ─────────────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        key  = event.key()
        mods = event.modifiers()

        if key == Qt.Key.Key_O and not mods:
            self._action_open()
        elif key == Qt.Key.Key_Q:
            QApplication.quit()
        elif key == Qt.Key.Key_N:
            self._action_rename()
        elif key == Qt.Key.Key_1:
            self._action_toggle_100()
        elif key == Qt.Key.Key_Left:
            self._action_prev()
        elif key == Qt.Key.Key_Right:
            self._action_next()
        elif key == Qt.Key.Key_Delete:
            self._action_delete()
        elif key == Qt.Key.Key_F:
            self._action_fullscreen()
        elif key == Qt.Key.Key_D:
            self._action_toggle_mode()
        elif key == Qt.Key.Key_R:
            self._action_rotate()
        elif key == Qt.Key.Key_C:
            self._action_crop()
        elif key == Qt.Key.Key_S and not mods:
            self._action_save()
        elif key == Qt.Key.Key_Escape:
            if self.isFullScreen():
                self.showNormal()
            elif self._crop_active:
                self._canvas.exit_crop_mode()
                self._crop_active = False
                self._buttons['crop_btn'].setProperty("active", "false")
                self._buttons['crop_btn'].style().unpolish(self._buttons['crop_btn'])
                self._buttons['crop_btn'].style().polish(self._buttons['crop_btn'])
            else:
                QApplication.quit()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Reposition status label if visible
        if self._status_lbl.isVisible():
            x = (self._canvas.width()  - self._status_lbl.width())  // 2
            y =  self._canvas.height() - self._status_lbl.height() - 20
            self._status_lbl.move(x, y)


# ─── Entry Point ─────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Image 3D Viewer")

    win = MainWindow()
    win.show()

    # If a file was passed on the command line
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if p.exists() and p.suffix.lower() in SUPPORTED_EXTS:
            win._load_file(p)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
