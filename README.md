# Image 3D Viewer

A lightweight desktop image viewer for Linux with red-cyan anaglyph 3D support. Built for viewing Fujifilm FinePix (and compatible) MPO and JPS stereo images with a red-cyan glasses, while also handling everyday image formats.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![PySide6](https://img.shields.io/badge/PySide6-Qt6-green)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## Features

### 3D Viewing
- Opens **MPO** (Multi Picture Object, e.g. Fujifilm FinePix Real 3D) and **JPS** (side-by-side stereo JPEG) files
- Two anaglyph modes for red-cyan glasses:
  - **Simple** – grayscale red-cyan, strong 3D depth
  - **Optimized** – Dubois-inspired algorithm, preserves some color
- 3D mode is remembered when navigating between stereo images, and automatically resets when a non-stereo image is shown

### Supported Formats
| Format | View | Edit (R/C/S) | Transparency |
|--------|------|--------------|--------------|
| JPG / JPEG | ✅ | ✅ | — |
| PNG | ✅ | ✅ | ✅ checkerboard |
| WebP | ✅ | ✅ | ✅ checkerboard |
| AVIF | ✅ | ✅ | ✅ checkerboard |
| MPO | ✅ 3D | — | — |
| JPS | ✅ 3D | — | — |

### Navigation
- Browse all images in a folder with arrow keys or buttons
- Drag & drop files from any file manager (e.g. Dolphin, Nautilus)
- Open via file dialog or command-line argument

### Image Editing
- **Rotate** 90° clockwise
- **Crop** with an adjustable rectangle (drag corners); applied on save
- **Save** overwrites the original file (only when changes exist)
- **Rename** without leaving the app (extension preserved)
- **Move to trash** without confirmation (uses system trash via `send2trash`)

### Display
- Fit-to-window by default; toggle 100% zoom with key `1`
- Zoom with mouse wheel; pan by dragging with left mouse button
- Zoom centres on mouse pointer position
- Fullscreen toggle
- Transparent PNG/WebP/AVIF shown with grey checkerboard background
- Top bar shows: filename · resolution · capture date (EXIF) · navigation position · zoom % · current mode

---


## Requirements

- Linux (tested on Pop!_OS 24 LTS / Ubuntu 24.04)
- Python 3.10+
- The following Python packages:

```
pyside6
pillow
numpy
send2trash
```

---

## Installation

```bash
# Install dependencies (user-space, no conda, no venv needed)
pip install --user --break-system-packages pyside6 pillow numpy send2trash

# Clone or download the repo
git clone https://github.com/tardigrada78/img3Dviewer.git
cd img3Dviewer

# Place the script somewhere on your path (optional)
mkdir -p ~/bin
cp img3Dviewer.py ~/bin/
```

### Desktop Integration (app launcher / taskbar)

```bash
# Install the .desktop file so the app appears in your app overview
cp stereo-viewer.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications/
```

You can then pin «Image 3D Viewer» to your taskbar. Files can also be opened directly from a file manager via right-click → Open With.

### Other Distributions

**Fedora / RHEL:**
```bash
sudo dnf install python3-pip
pip install --user pyside6 pillow numpy send2trash
```

**Arch / Manjaro:**
```bash
sudo pacman -S python-pip
pip install --user pyside6 pillow numpy send2trash
```

> Note: `--break-system-packages` is required on Ubuntu 23.04+ and Pop!_OS 24+, but not on Fedora or Arch.

---

## Usage

```bash
# Open with no file (drag & drop or press O)
python3 img3Dviewer.py

# Open a specific file directly
python3 img3Dviewer.py /path/to/image.mpo
```

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `O` | Open file dialog |
| `←` / `→` | Previous / next image in folder |
| `D` | Cycle display mode: 2D → 3D simple → 3D optimized (stereo files only) |
| `R` | Rotate 90° clockwise (JPG/PNG/WebP/AVIF only) |
| `C` | Enter crop mode – draw rectangle, drag corners to adjust |
| `S` | Save changes (overwrites original, no confirmation) |
| `N` | Rename current file (extension preserved) |
| `1` | Toggle between 100% zoom and fit-to-window |
| `Del` | Move to trash (no confirmation) |
| `F` | Toggle fullscreen |
| `Q` / `Esc` | Quit (Esc also exits fullscreen or crop mode first) |
| `Ctrl+Scroll` | _(removed – scroll wheel now always zooms)_ |

**Mouse:**
| Action | Effect |
|--------|--------|
| Scroll wheel | Zoom in/out (centred on cursor) |
| Left drag | Pan image (when zoomed in) |
| Draw in crop mode | Define crop rectangle |
| Drag corner handles | Adjust crop rectangle |

---

## Notes on 3D Format Support

**MPO:** The viewer uses Pillow's built-in MPO multi-frame parser (`img.seek()`), which correctly reads the EXIF APP2 offsets. This is more reliable than manual JPEG marker scanning, which fails on files containing embedded thumbnails (like Fujifilm FinePix Real 3D W1/W3 output).

**JPS:** Assumes standard left-eye/right-eye side-by-side layout (left half = left eye). Files are split at the horizontal midpoint.

---

## License

MIT License – do whatever you like with it.
