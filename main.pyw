#!/usr/bin/env python3
"""
OCR แปลภาษา - ใช้ Claude AI สำหรับ OCR และแปลภาษา
รองรับ: อังกฤษ → ไทย, ญี่ปุ่น → ไทย (และอื่นๆ)
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import base64
import io
import os
import json
import threading
import sys

try:
    from PIL import Image, ImageGrab, ImageTk
except ImportError:
    print("กรุณาติดตั้ง: pip install Pillow")
    sys.exit(1)

try:
    import anthropic
except ImportError:
    print("กรุณาติดตั้ง: pip install anthropic")
    sys.exit(1)

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

# ── Constants ──────────────────────────────────────────────────────────────────

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

MODELS = ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]

THEMES: dict[str, dict] = {
    "Light": {
        "bg": "#f0f0f0",   "fg": "#1a1a1a",
        "text_bg": "#ffffff", "text_fg": "#1a1a1a",
        "frame_bg": "#e0e0e0", "border": "#b0b0b0",
        "select_bg": "#0078d4", "select_fg": "#ffffff",
        "button_bg": "#e1e1e1",
    },
    "Dark": {
        "bg": "#1e1e1e",   "fg": "#d4d4d4",
        "text_bg": "#252526", "text_fg": "#d4d4d4",
        "frame_bg": "#2d2d30", "border": "#3f3f46",
        "select_bg": "#264f78", "select_fg": "#ffffff",
        "button_bg": "#3c3c3c",
    },
    "Dracula": {
        "bg": "#282a36",   "fg": "#f8f8f2",
        "text_bg": "#21222c", "text_fg": "#f8f8f2",
        "frame_bg": "#343746", "border": "#6272a4",
        "select_bg": "#bd93f9", "select_fg": "#282a36",
        "button_bg": "#44475a",
    },
    "Monokai": {
        "bg": "#272822",   "fg": "#f8f8f2",
        "text_bg": "#1e1f1c", "text_fg": "#f8f8f2",
        "frame_bg": "#3e3d32", "border": "#75715e",
        "select_bg": "#a6e22e", "select_fg": "#272822",
        "button_bg": "#49483e",
    },
    "Solarized": {
        "bg": "#002b36",   "fg": "#839496",
        "text_bg": "#073642", "text_fg": "#93a1a1",
        "frame_bg": "#073642", "border": "#586e75",
        "select_bg": "#268bd2", "select_fg": "#fdf6e3",
        "button_bg": "#073642",
    },
}

# Actions for regular (app-focus) hotkeys
HOTKEY_ACTIONS: dict[str, str] = {
    "capture":    "📷 จับภาพหน้าจอ",
    "open_file":  "📁 เปิดไฟล์ภาพ",
    "paste_clip": "📋 วางคลิปบอร์ด",
    "ocr":        "🔍 OCR อย่างเดียว",
    "translate":  "🌐 แปลข้อความ OCR",
    "both":       "⚡ OCR + แปล",
}

# Global hotkey — works even when app is in background
GLOBAL_HOTKEY_DEFAULT = {"display": "Alt+Q", "binding": "<Alt-q>"}

# Note: uppercase letter in binding = Shift held (e.g. <Control-S> = Ctrl+Shift+S)
DEFAULT_HOTKEYS: dict[str, dict] = {
    "capture":    {"display": "Ctrl+Shift+S", "binding": "<Control-S>"},
    "open_file":  {"display": "Ctrl+Shift+O", "binding": "<Control-O>"},
    "paste_clip": {"display": "Ctrl+Shift+P", "binding": "<Control-P>"},
    "ocr":        {"display": "F5",           "binding": "<F5>"},
    "translate":  {"display": "F6",           "binding": "<F6>"},
    "both":       {"display": "F7",           "binding": "<F7>"},
    "quick":      GLOBAL_HOTKEY_DEFAULT,
}

DEFAULT_CONFIG: dict = {
    "api_key": "",
    "model": "claude-opus-4-6",
    "target_lang": "ไทย",
    "theme": "Light",
    "hotkeys": {k: dict(v) for k, v in DEFAULT_HOTKEYS.items()},
}

# ── Config I/O ─────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = {**DEFAULT_CONFIG, **data}
            hk = {**{k: dict(v) for k, v in DEFAULT_HOTKEYS.items()},
                  **merged.get("hotkeys", {})}
            merged["hotkeys"] = hk
            return merged
        except Exception:
            pass
    return {k: (dict(v) if k == "hotkeys" else v) for k, v in DEFAULT_CONFIG.items()}


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ── Screenshot Overlay ─────────────────────────────────────────────────────────

class ScreenshotOverlay(tk.Toplevel):
    def __init__(self, on_select, on_cancel=None):
        super().__init__()
        self.on_select = on_select
        self.on_cancel = on_cancel
        self.start_x = self.start_y = 0
        self.rect = None

        self.overrideredirect(True)
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{sw}x{sh}+0+0")
        self.attributes("-alpha", 0.25)
        self.attributes("-topmost", True)
        self.configure(bg="black")
        self.lift()
        self.focus_force()

        self.canvas = tk.Canvas(self, cursor="cross", bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(
            self.winfo_screenwidth() // 2, 40,
            text="ลากเมาส์เพื่อเลือกพื้นที่   |   Esc = ยกเลิก",
            fill="white", font=("Tahoma", 15, "bold"),
        )
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Escape>", self._on_esc)

    def _on_press(self, e):
        self.start_x, self.start_y = e.x, e.y
        if self.rect:
            self.canvas.delete(self.rect)

    def _on_drag(self, e):
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, e.x, e.y,
            outline="#FF4444", width=2, fill="white", stipple="gray25",
        )

    def _on_release(self, e):
        x1, y1 = min(self.start_x, e.x), min(self.start_y, e.y)
        x2, y2 = max(self.start_x, e.x), max(self.start_y, e.y)
        self.destroy()
        if x2 - x1 > 5 and y2 - y1 > 5:
            self.on_select(x1, y1, x2, y2)
        else:
            if self.on_cancel:
                self.on_cancel()

    def _on_esc(self, _):
        self.destroy()
        if self.on_cancel:
            self.on_cancel()


# ── Hotkey Recorder ────────────────────────────────────────────────────────────

class HotkeyRecorder(tk.Toplevel):
    def __init__(self, parent, action_label: str, current: dict, on_save, is_global=False):
        super().__init__(parent)
        self.on_save = on_save
        self._display = current.get("display", "")
        self._binding = current.get("binding", "")

        self.title("ตั้ง Hotkey")
        self.geometry("340x195")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        ttk.Label(self, text=f"ฟังก์ชัน: {action_label}",
                  font=("Tahoma", 10, "bold")).pack(pady=(14, 2))

        note = "★ Global — ใช้งานได้ตลอดแม้แอปอยู่เบื้องหลัง" if is_global else "ใช้งานได้เมื่อหน้าต่างแอปมีโฟกัส"
        ttk.Label(self, text=note, foreground="#888888").pack()
        ttk.Label(self, text="กด Hotkey ที่ต้องการ:").pack(pady=(6, 0))

        self._lbl = ttk.Label(self, text=self._display or "—",
                               font=("Consolas", 14, "bold"))
        self._lbl.pack(pady=8)

        bf = ttk.Frame(self)
        bf.pack()
        ttk.Button(bf, text="ตกลง",  command=self._ok,     width=8).pack(side="left", padx=4)
        ttk.Button(bf, text="ล้าง",   command=self._clear,  width=6).pack(side="left", padx=4)
        ttk.Button(bf, text="ยกเลิก", command=self.destroy, width=8).pack(side="left", padx=4)

        self.bind("<KeyPress>", self._record)
        self.focus_force()

    def _record(self, event):
        if event.keysym in ("Control_L", "Control_R", "Shift_L", "Shift_R",
                             "Alt_L", "Alt_R", "Super_L", "Super_R"):
            return
        d_mods = []
        if event.state & 0x4: d_mods.append("Ctrl")
        if event.state & 0x1: d_mods.append("Shift")
        if event.state & 0x8: d_mods.append("Alt")
        d_key = event.keysym.upper() if len(event.keysym) == 1 else event.keysym
        self._display = "+".join(d_mods + [d_key])

        b_mods = []
        if event.state & 0x4: b_mods.append("Control")
        if event.state & 0x8: b_mods.append("Alt")
        if event.state & 0x1 and len(event.keysym) > 1:
            b_mods.append("Shift")
        self._binding = "<" + "-".join(b_mods + [event.keysym]) + ">"
        self._lbl.configure(text=self._display)

    def _clear(self):
        self._display = ""
        self._binding = ""
        self._lbl.configure(text="—")

    def _ok(self):
        if self._binding:
            self.on_save({"display": self._display, "binding": self._binding})
        self.destroy()


# ── Hotkey Settings Dialog ─────────────────────────────────────────────────────

class HotkeyDialog(tk.Toplevel):
    def __init__(self, parent, hotkeys: dict, on_save):
        super().__init__(parent)
        self.hotkeys = {k: dict(v) for k, v in hotkeys.items()}
        self.on_save = on_save

        self.title("ตั้งค่า Hotkeys")
        self.geometry("500x420")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        ttk.Label(self, text="ตั้งค่า Hotkeys",
                  font=("Tahoma", 11, "bold")).pack(pady=(12, 6))

        # ── Global hotkey section ──
        gf = ttk.LabelFrame(self, text=" ★ Global Hotkey — ใช้งานได้ตลอดแม้แอปอยู่เบื้องหลัง ", padding=8)
        gf.pack(fill="x", padx=16, pady=(0, 8))

        if not HAS_KEYBOARD:
            ttk.Label(gf, text="⚠  ต้องติดตั้งก่อน: pip install keyboard",
                      foreground="#cc4444").grid(row=0, column=0, columnspan=3, sticky="w")

        hk_q = self.hotkeys.get("quick", GLOBAL_HOTKEY_DEFAULT)
        self._quick_var = tk.StringVar(value=hk_q.get("display", "Alt+Q"))

        ttk.Label(gf, text="⚡🌐 Quick OCR+แปล:").grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Label(gf, textvariable=self._quick_var,
                  font=("Consolas", 11, "bold"), width=16).grid(row=1, column=1, sticky="w")
        ttk.Button(gf, text="เปลี่ยน", width=7,
                   command=lambda: self._edit_global()).grid(row=1, column=2, padx=(8, 0))

        # ── App hotkeys section ──
        af = ttk.LabelFrame(self, text=" Hotkeys ในแอป (ต้องคลิกที่หน้าต่างแอปก่อน) ", padding=8)
        af.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        ttk.Label(af, text="ฟังก์ชัน",        font=("Tahoma", 9, "bold")).grid(row=0, column=0, sticky="w", padx=5, pady=2)
        ttk.Label(af, text="Hotkey ปัจจุบัน", font=("Tahoma", 9, "bold")).grid(row=0, column=1, sticky="w", padx=5, pady=2)
        ttk.Separator(af, orient="horizontal").grid(row=1, column=0, columnspan=3, sticky="ew", pady=3)

        self._vars: dict[str, tk.StringVar] = {}
        for i, (action, label) in enumerate(HOTKEY_ACTIONS.items(), start=2):
            hk = self.hotkeys.get(action, DEFAULT_HOTKEYS.get(action, {}))
            ttk.Label(af, text=label).grid(row=i, column=0, sticky="w", padx=5, pady=4)
            var = tk.StringVar(value=hk.get("display", "—"))
            self._vars[action] = var
            ttk.Label(af, textvariable=var, width=18,
                      font=("Consolas", 10)).grid(row=i, column=1, sticky="w", padx=5)
            ttk.Button(af, text="เปลี่ยน", width=7,
                       command=lambda a=action, lbl=label: self._edit(a, lbl)
                       ).grid(row=i, column=2, padx=5)

        # ── Buttons ──
        bf = ttk.Frame(self)
        bf.pack(pady=10)
        ttk.Button(bf, text="บันทึก", command=self._save,  width=9).pack(side="left", padx=5)
        ttk.Button(bf, text="รีเซ็ต",  command=self._reset, width=9).pack(side="left", padx=5)
        ttk.Button(bf, text="ปิด",     command=self.destroy, width=9).pack(side="left", padx=5)

    def _edit_global(self):
        current = self.hotkeys.get("quick", GLOBAL_HOTKEY_DEFAULT)
        HotkeyRecorder(self, "⚡🌐 Quick OCR+แปล", current,
                       lambda hk: self._update_global(hk), is_global=True)

    def _update_global(self, hk: dict):
        self.hotkeys["quick"] = hk
        self._quick_var.set(hk.get("display", "—"))

    def _edit(self, action: str, label: str):
        current = self.hotkeys.get(action, DEFAULT_HOTKEYS.get(action, {}))
        HotkeyRecorder(self, label, current, lambda hk: self._update(action, hk))

    def _update(self, action: str, hk: dict):
        self.hotkeys[action] = hk
        self._vars[action].set(hk.get("display", "—"))

    def _reset(self):
        for action, hk in DEFAULT_HOTKEYS.items():
            self.hotkeys[action] = dict(hk)
            if action == "quick":
                self._quick_var.set(hk["display"])
            elif action in self._vars:
                self._vars[action].set(hk["display"])

    def _save(self):
        self.on_save(self.hotkeys)
        self.destroy()


# ── Main App ───────────────────────────────────────────────────────────────────

class OCRTranslatorApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("OCR แปลภาษา  —  Claude AI")
        self.root.geometry("1050x780")
        self.root.minsize(800, 600)

        self.cfg = load_config()
        self.current_image: Image.Image | None = None
        self._photo_ref = None
        self._busy = False
        self._quick_active = False
        self._global_hk_combo: str | None = None
        self._active_bindings: list[str] = []
        self._text_widgets: list[tk.Text] = []

        self._build_ui()
        self._apply_config()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        outer = ttk.Frame(self.root, padding=8)
        outer.grid(sticky="nsew")
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(3, weight=1)

        # ── Row 0: Settings ──
        sf = ttk.LabelFrame(outer, text=" API & การตั้งค่า ", padding=6)
        sf.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        sf.grid_columnconfigure(1, weight=1)

        ttk.Label(sf, text="API Key:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self._api_var = tk.StringVar()
        self._api_entry = ttk.Entry(sf, textvariable=self._api_var, show="*", width=50)
        self._api_entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(sf, text="แสดง/ซ่อน", command=self._toggle_key_visible, width=9).grid(
            row=0, column=2, padx=(4, 2))
        ttk.Button(sf, text="บันทึก", command=self._save_settings, width=7).grid(
            row=0, column=3, padx=(2, 0))

        ttk.Label(sf, text="โมเดล:").grid(row=1, column=0, sticky="w", padx=(0, 4), pady=(5, 0))
        self._model_var = tk.StringVar()
        ttk.Combobox(sf, textvariable=self._model_var, values=MODELS,
                     state="readonly", width=28).grid(row=1, column=1, sticky="w", pady=(5, 0))

        right_row1 = ttk.Frame(sf)
        right_row1.grid(row=1, column=2, columnspan=2, sticky="e", pady=(5, 0))

        ttk.Label(right_row1, text="ธีม:").pack(side="left", padx=(0, 4))
        self._theme_var = tk.StringVar()
        theme_cb = ttk.Combobox(right_row1, textvariable=self._theme_var,
                                 values=list(THEMES.keys()), state="readonly", width=11)
        theme_cb.pack(side="left", padx=(0, 8))
        theme_cb.bind("<<ComboboxSelected>>",
                      lambda _: self._apply_theme(self._theme_var.get()))

        ttk.Button(right_row1, text="⌨  Hotkeys",
                   command=self._open_hotkey_dialog, width=11).pack(side="left")

        # ── Row 1: Toolbar ──
        tb = ttk.Frame(outer)
        tb.grid(row=1, column=0, sticky="ew", pady=4)

        ttk.Button(tb, text="📷  จับภาพหน้าจอ", command=self._capture).pack(side="left", padx=2)
        ttk.Button(tb, text="📁  เปิดไฟล์ภาพ",  command=self._open_file).pack(side="left", padx=2)
        ttk.Button(tb, text="📋  วางคลิปบอร์ด", command=self._paste_clip).pack(side="left", padx=2)

        ttk.Separator(tb, orient="vertical").pack(side="left", fill="y", padx=8, pady=2)

        self._btn_ocr  = ttk.Button(tb, text="🔍 OCR",            command=self._run_ocr,      state="disabled")
        self._btn_tr   = ttk.Button(tb, text="🌐 แปลข้อความ OCR", command=self._run_translate, state="disabled")
        self._btn_both = ttk.Button(tb, text="⚡ OCR + แปล",      command=self._run_both,      state="disabled")
        self._btn_ocr.pack(side="left", padx=2)
        self._btn_tr.pack(side="left", padx=2)
        self._btn_both.pack(side="left", padx=2)

        ttk.Separator(tb, orient="vertical").pack(side="left", fill="y", padx=8, pady=2)
        ttk.Label(tb, text="แปลเป็น:").pack(side="left", padx=(0, 2))
        self._lang_var = tk.StringVar(value="ไทย")
        ttk.Combobox(tb, textvariable=self._lang_var,
                     values=["ไทย", "อังกฤษ", "ญี่ปุ่น", "จีน", "เกาหลี"],
                     state="readonly", width=8).pack(side="left")

        # ── Row 2: Image Preview ──
        pf = ttk.LabelFrame(outer, text=" ภาพที่เลือก ", padding=4)
        pf.grid(row=2, column=0, sticky="ew", pady=4)
        self._img_lbl = ttk.Label(pf, text="[ ยังไม่มีภาพ — ใช้ปุ่มด้านบน ]",
                                   anchor="center", foreground="#888888")
        self._img_lbl.pack(fill="both", ipady=28)

        # ── Row 3: Text panels ──
        tp = ttk.Frame(outer)
        tp.grid(row=3, column=0, sticky="nsew", pady=4)
        tp.grid_columnconfigure(0, weight=1)
        tp.grid_columnconfigure(1, weight=1)
        tp.grid_rowconfigure(0, weight=1)

        lf = ttk.LabelFrame(tp, text=" ข้อความ OCR  (แก้ไขได้) ", padding=4)
        lf.grid(row=0, column=0, sticky="nsew", padx=(0, 3))
        lf.grid_rowconfigure(0, weight=1)
        lf.grid_columnconfigure(0, weight=1)
        self._ocr_box = scrolledtext.ScrolledText(lf, wrap="word", font=("Consolas", 10), height=12)
        self._ocr_box.grid(row=0, column=0, sticky="nsew")
        ob = ttk.Frame(lf)
        ob.grid(row=1, column=0, sticky="ew", pady=(3, 0))
        ttk.Button(ob, text="ล้าง",   width=6, command=lambda: self._ocr_box.delete("1.0", "end")).pack(side="left", padx=2)
        ttk.Button(ob, text="คัดลอก", width=8, command=lambda: self._copy(self._ocr_box)).pack(side="left", padx=2)

        rf = ttk.LabelFrame(tp, text=" คำแปล ", padding=4)
        rf.grid(row=0, column=1, sticky="nsew", padx=(3, 0))
        rf.grid_rowconfigure(0, weight=1)
        rf.grid_columnconfigure(0, weight=1)
        self._tr_box = scrolledtext.ScrolledText(rf, wrap="word",
                                                  font=(self._detect_thai_font(), 11), height=12)
        self._tr_box.grid(row=0, column=0, sticky="nsew")
        tb2 = ttk.Frame(rf)
        tb2.grid(row=1, column=0, sticky="ew", pady=(3, 0))
        ttk.Button(tb2, text="ล้าง",   width=6, command=lambda: self._tr_box.delete("1.0", "end")).pack(side="left", padx=2)
        ttk.Button(tb2, text="คัดลอก", width=8, command=lambda: self._copy(self._tr_box)).pack(side="left", padx=2)

        # ── Row 4: Status bar ──
        sb = ttk.Frame(outer)
        sb.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        sb.grid_columnconfigure(0, weight=1)
        self._status = tk.StringVar(value="พร้อมใช้งาน")
        ttk.Label(sb, textvariable=self._status, relief="sunken",
                  anchor="w", padding=(6, 2)).grid(row=0, column=0, sticky="ew")
        self._progress = ttk.Progressbar(sb, mode="indeterminate", length=120)
        self._progress.grid(row=0, column=1, padx=(6, 0))

        self._text_widgets = [self._ocr_box, self._tr_box]

    @staticmethod
    def _detect_thai_font() -> str:
        import tkinter.font as tkf
        families = set(tkf.families())
        for f in ["TH Sarabun New", "Leelawadee UI", "Leelawadee", "Cordia New", "Tahoma"]:
            if f in families:
                return f
        return "Tahoma"

    # ── Theme ──────────────────────────────────────────────────────────────────

    def _apply_theme(self, name: str):
        if name not in THEMES:
            name = "Light"
        t = THEMES[name]
        bg, fg = t["bg"], t["fg"]
        tbg, tfg = t["text_bg"], t["text_fg"]
        fbg, brd = t["frame_bg"], t["border"]
        sbg, sfg = t["select_bg"], t["select_fg"]
        btn = t["button_bg"]

        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".",
            background=bg, foreground=fg, fieldbackground=tbg,
            troughcolor=fbg, bordercolor=brd, darkcolor=fbg, lightcolor=fbg,
            insertcolor=fg, selectbackground=sbg, selectforeground=sfg,
        )
        s.configure("TFrame",      background=bg)
        s.configure("TLabelframe", background=bg, bordercolor=brd)
        s.configure("TLabelframe.Label", background=bg, foreground=fg)
        s.configure("TLabel",      background=bg, foreground=fg)
        s.configure("TSeparator",  background=brd)
        s.configure("TProgressbar", background=sbg, troughcolor=fbg, bordercolor=brd)
        s.configure("TButton",
            background=btn, foreground=fg, bordercolor=brd, focuscolor=btn, padding=(6, 3))
        s.map("TButton",
            background=[("active", sbg), ("pressed", sbg), ("disabled", bg)],
            foreground=[("disabled", brd)])
        s.configure("TEntry", fieldbackground=tbg, foreground=tfg, bordercolor=brd, insertcolor=fg)
        s.configure("TCombobox",
            fieldbackground=tbg, foreground=tfg, bordercolor=brd,
            arrowcolor=fg, selectbackground=sbg, selectforeground=sfg)
        s.map("TCombobox",
            fieldbackground=[("readonly", tbg)],
            foreground=[("readonly", tfg)],
            selectbackground=[("readonly", sbg)])
        s.configure("TScrollbar",
            background=fbg, troughcolor=bg, bordercolor=brd, arrowcolor=fg)

        self.root.configure(bg=bg)
        for w in self._text_widgets:
            w.configure(bg=tbg, fg=tfg, insertbackground=fg,
                        selectbackground=sbg, selectforeground=sfg)
        self.cfg["theme"] = name

    # ── Hotkeys ────────────────────────────────────────────────────────────────

    def _bind_hotkeys(self):
        # Remove old app-local bindings
        for b in self._active_bindings:
            try:
                self.root.unbind(b)
            except Exception:
                pass
        self._active_bindings = []

        action_map = {
            "capture":    self._capture,
            "open_file":  self._open_file,
            "paste_clip": self._paste_clip,
            "ocr":        self._run_ocr,
            "translate":  self._run_translate,
            "both":       self._run_both,
        }
        hotkeys = self.cfg.get("hotkeys", DEFAULT_HOTKEYS)
        for action, fn in action_map.items():
            hk = hotkeys.get(action, DEFAULT_HOTKEYS.get(action, {}))
            binding = hk.get("binding", "")
            if binding:
                try:
                    self.root.bind(binding, lambda _e, f=fn: f())
                    self._active_bindings.append(binding)
                except Exception:
                    pass

        # Register global hotkey separately
        self._register_global_hotkey()

    def _register_global_hotkey(self):
        """ลงทะเบียน global hotkey ผ่าน keyboard library"""
        # Remove old global hotkey
        if self._global_hk_combo and HAS_KEYBOARD:
            try:
                keyboard.remove_hotkey(self._global_hk_combo)
            except Exception:
                pass
        self._global_hk_combo = None

        if not HAS_KEYBOARD:
            return

        hk = self.cfg.get("hotkeys", {}).get("quick", GLOBAL_HOTKEY_DEFAULT)
        display = hk.get("display", "Alt+Q")
        if not display or display == "—":
            return

        # Convert "Alt+Q" → "alt+q" (keyboard library format)
        combo = "+".join(p.lower() for p in display.split("+"))
        try:
            keyboard.add_hotkey(combo,
                                lambda: self.root.after(0, self._quick_capture_start),
                                suppress=True)
            self._global_hk_combo = combo
            self._status.set(f"พร้อมใช้งาน  |  Global hotkey: {display}")
        except Exception as e:
            self._status.set(f"ลงทะเบียน global hotkey ไม่สำเร็จ: {e}")

    def _open_hotkey_dialog(self):
        hotkeys = self.cfg.get("hotkeys", {k: dict(v) for k, v in DEFAULT_HOTKEYS.items()})
        HotkeyDialog(self.root, hotkeys, self._on_hotkeys_saved)

    def _on_hotkeys_saved(self, hotkeys: dict):
        self.cfg["hotkeys"] = hotkeys
        save_config(self.cfg)
        self._bind_hotkeys()
        self._status.set("บันทึก Hotkeys แล้ว ✓")

    # ── Quick Capture (Global hotkey flow) ────────────────────────────────────

    def _quick_capture_start(self):
        """เรียกจาก global hotkey — ซ่อนแอป เปิด overlay แล้ว OCR+แปลอัตโนมัติ"""
        if self._quick_active or self._busy:
            return
        self._quick_active = True
        self.root.withdraw()  # ซ่อนหน้าต่าง
        self.root.after(250, lambda: ScreenshotOverlay(
            on_select=self._quick_on_region,
            on_cancel=self._quick_cancel,
        ))

    def _quick_on_region(self, x1: int, y1: int, x2: int, y2: int):
        self.root.after(100, lambda: self._quick_grab(x1, y1, x2, y2))

    def _quick_grab(self, x1: int, y1: int, x2: int, y2: int):
        try:
            img = ImageGrab.grab(bbox=(x1, y1, x2, y2))
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            self.current_image = img
            # Enable buttons (even though window is hidden)
            self._btn_ocr.configure(state="normal")
            self._btn_both.configure(state="normal")
            # Start OCR+translate, show window when done
            threading.Thread(target=self._t_both, kwargs={"show_after": True}, daemon=True).start()
        except Exception as e:
            self._quick_active = False
            self.root.deiconify()
            messagebox.showerror("ข้อผิดพลาด", f"จับภาพไม่สำเร็จ:\n{e}")

    def _quick_cancel(self):
        self._quick_active = False
        self.root.deiconify()

    def _show_window(self):
        """เด้งหน้าต่างขึ้นมาพร้อมผลลัพธ์"""
        self._quick_active = False
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        # ลอยขึ้นมาด้านบนชั่วคราว แล้วกลับสู่ปกติ
        self.root.attributes("-topmost", True)
        self.root.after(400, lambda: self.root.attributes("-topmost", False))
        # อัปเดต preview ภาพ
        if self.current_image:
            self._set_image(self.current_image)

    # ── Config ─────────────────────────────────────────────────────────────────

    def _apply_config(self):
        self._api_var.set(self.cfg.get("api_key", ""))
        model = self.cfg.get("model", MODELS[0])
        self._model_var.set(model if model in MODELS else MODELS[0])
        self._lang_var.set(self.cfg.get("target_lang", "ไทย"))

        theme = self.cfg.get("theme", "Light")
        self._theme_var.set(theme if theme in THEMES else "Light")
        self._apply_theme(self._theme_var.get())

        self._bind_hotkeys()

    def _save_settings(self):
        self.cfg["api_key"]     = self._api_var.get().strip()
        self.cfg["model"]       = self._model_var.get()
        self.cfg["target_lang"] = self._lang_var.get()
        self.cfg["theme"]       = self._theme_var.get()
        save_config(self.cfg)
        self._status.set("บันทึกการตั้งค่าแล้ว ✓")

    def _toggle_key_visible(self):
        self._api_entry.config(show="" if self._api_entry.cget("show") == "*" else "*")

    # ── Image loading ──────────────────────────────────────────────────────────

    def _set_image(self, img: Image.Image):
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        self.current_image = img
        preview = img.copy()
        preview.thumbnail((max(self.root.winfo_width() - 60, 600), 220), Image.LANCZOS)
        self._photo_ref = ImageTk.PhotoImage(preview)
        self._img_lbl.configure(image=self._photo_ref, text="")
        self._btn_ocr.configure(state="normal")
        self._btn_both.configure(state="normal")
        self._status.set(f"โหลดภาพแล้ว: {img.width} × {img.height} px")

    def _capture(self):
        self.root.iconify()
        self.root.after(350, lambda: ScreenshotOverlay(
            on_select=self._on_region,
            on_cancel=lambda: self.root.deiconify(),
        ))

    def _on_region(self, x1, y1, x2, y2):
        self.root.after(150, lambda: self._grab(x1, y1, x2, y2))

    def _grab(self, x1, y1, x2, y2):
        self.root.deiconify()
        self.root.lift()
        try:
            self._set_image(ImageGrab.grab(bbox=(x1, y1, x2, y2)))
        except Exception as e:
            messagebox.showerror("ข้อผิดพลาด", f"จับภาพไม่สำเร็จ:\n{e}")

    def _open_file(self):
        path = filedialog.askopenfilename(
            title="เลือกไฟล์ภาพ",
            filetypes=[("ไฟล์ภาพ", "*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp *.avif"),
                       ("ทุกไฟล์", "*.*")],
        )
        if path:
            try:
                self._set_image(Image.open(path))
            except Exception as e:
                messagebox.showerror("ข้อผิดพลาด", f"เปิดไฟล์ไม่สำเร็จ:\n{e}")

    def _paste_clip(self):
        try:
            img = ImageGrab.grabclipboard()
            if isinstance(img, Image.Image):
                self._set_image(img)
            elif isinstance(img, list) and img:
                self._set_image(Image.open(img[0]))
            else:
                messagebox.showwarning("แจ้งเตือน", "ไม่พบภาพในคลิปบอร์ด")
        except Exception as e:
            messagebox.showerror("ข้อผิดพลาด", f"วางภาพไม่สำเร็จ:\n{e}")

    # ── API helpers ────────────────────────────────────────────────────────────

    def _get_client(self) -> anthropic.Anthropic:
        key = self._api_var.get().strip()
        if not key:
            raise ValueError("กรุณาใส่ Anthropic API Key แล้วกด 'บันทึก'")
        return anthropic.Anthropic(api_key=key)

    def _img_b64(self) -> str:
        buf = io.BytesIO()
        img = self.current_image
        if img.mode == "RGBA":
            img = img.convert("RGB")
        img.save(buf, format="PNG")
        return base64.standard_b64encode(buf.getvalue()).decode()

    # ── Processing ─────────────────────────────────────────────────────────────

    def _set_busy(self, busy: bool, msg: str = ""):
        self._busy = busy
        has_img = self.current_image is not None
        has_txt = bool(self._ocr_box.get("1.0", "end").strip())
        self._btn_ocr.configure(state="disabled" if (busy or not has_img) else "normal")
        self._btn_both.configure(state="disabled" if (busy or not has_img) else "normal")
        self._btn_tr.configure(state="disabled" if (busy or not has_txt) else "normal")
        if busy:
            self._progress.start(10)
            self._status.set(msg)
        else:
            self._progress.stop()

    def _run_ocr(self):
        if not self.current_image or self._busy:
            return
        threading.Thread(target=self._t_ocr, daemon=True).start()

    def _t_ocr(self):
        self.root.after(0, lambda: self._set_busy(True, "กำลังอ่านข้อความ (OCR)..."))
        try:
            client = self._get_client()
            result = client.messages.create(
                model=self._model_var.get(), max_tokens=4096,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64",
                     "media_type": "image/png", "data": self._img_b64()}},
                    {"type": "text", "text": (
                        "โปรดอ่านและพิมพ์ข้อความทั้งหมดในภาพนี้ "
                        "รักษาโครงสร้าง การขึ้นบรรทัดใหม่ และการเยื้องเดิมไว้ "
                        "ตอบเฉพาะข้อความที่อ่านได้ ไม่ต้องอธิบายหรือแปล"
                    )},
                ]}],
            )
            text = result.content[0].text
            self.root.after(0, lambda: self._put_ocr(text))
        except Exception as e:
            self.root.after(0, lambda: self._on_error(str(e)))
        finally:
            self.root.after(0, lambda: self._set_busy(False, "OCR เสร็จแล้ว ✓"))

    def _run_translate(self):
        txt = self._ocr_box.get("1.0", "end").strip()
        if not txt or self._busy:
            return
        threading.Thread(target=self._t_translate, args=(txt,), daemon=True).start()

    def _t_translate(self, text: str):
        lang = self._lang_var.get()
        lang_full = {"ไทย": "ภาษาไทย", "อังกฤษ": "ภาษาอังกฤษ", "ญี่ปุ่น": "ภาษาญี่ปุ่น",
                     "จีน": "ภาษาจีน (ตัวย่อ)", "เกาหลี": "ภาษาเกาหลี"}.get(lang, f"ภาษา{lang}")
        self.root.after(0, lambda: self._set_busy(True, f"กำลังแปลเป็น{lang}..."))
        try:
            client = self._get_client()
            result = client.messages.create(
                model=self._model_var.get(), max_tokens=4096,
                messages=[{"role": "user", "content": (
                    f"โปรดแปลข้อความต่อไปนี้เป็น{lang_full} "
                    f"รักษาความหมาย น้ำเสียง และโครงสร้างย่อหน้าให้ตรงกับต้นฉบับ "
                    f"ตอบเฉพาะคำแปลเท่านั้น:\n\n{text}"
                )}],
            )
            self.root.after(0, lambda: self._put_tr(result.content[0].text))
        except Exception as e:
            self.root.after(0, lambda: self._on_error(str(e)))
        finally:
            self.root.after(0, lambda: self._set_busy(False, f"แปลเป็น{lang}เสร็จแล้ว ✓"))

    def _run_both(self):
        if not self.current_image or self._busy:
            return
        threading.Thread(target=self._t_both, daemon=True).start()

    def _t_both(self, show_after: bool = False):
        """OCR + แปล — ถ้า show_after=True จะเด้งหน้าต่างขึ้นมาเมื่อเสร็จ"""
        lang = self._lang_var.get()
        lang_full = {"ไทย": "ภาษาไทย", "อังกฤษ": "ภาษาอังกฤษ", "ญี่ปุ่น": "ภาษาญี่ปุ่น",
                     "จีน": "ภาษาจีน (ตัวย่อ)", "เกาหลี": "ภาษาเกาหลี"}.get(lang, f"ภาษา{lang}")
        self.root.after(0, lambda: self._set_busy(True, "กำลัง OCR + แปลภาษา..."))
        try:
            client = self._get_client()
            prompt = (
                f"โปรดทำ 2 ขั้นตอน:\n"
                f"1. อ่านและพิมพ์ข้อความทั้งหมดในภาพ — รักษาโครงสร้างเดิม\n"
                f"2. แปลข้อความนั้นเป็น{lang_full}\n\n"
                f"ตอบในรูปแบบนี้เท่านั้น:\n"
                f"===OCR===\n[ข้อความจากภาพ]\n===TRANSLATE===\n[คำแปล]"
            )
            result = client.messages.create(
                model=self._model_var.get(), max_tokens=8192,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64",
                     "media_type": "image/png", "data": self._img_b64()}},
                    {"type": "text", "text": prompt},
                ]}],
            )
            ocr_text, tr_text = self._parse_both(result.content[0].text)
            self.root.after(0, lambda: self._put_ocr(ocr_text))
            self.root.after(0, lambda: self._put_tr(tr_text))
        except Exception as e:
            self.root.after(0, lambda: self._on_error(str(e)))
            if show_after:
                self.root.after(0, self._show_window)
            return
        finally:
            self.root.after(0, lambda: self._set_busy(False, "OCR + แปลเสร็จแล้ว ✓"))

        if show_after:
            self.root.after(100, self._show_window)

    @staticmethod
    def _parse_both(raw: str) -> tuple[str, str]:
        if "===OCR===" in raw and "===TRANSLATE===" in raw:
            parts = raw.split("===TRANSLATE===")
            return parts[0].replace("===OCR===", "").strip(), parts[1].strip()
        return raw.strip(), ""

    # ── UI updates (main thread) ───────────────────────────────────────────────

    def _put_ocr(self, text: str):
        self._ocr_box.delete("1.0", "end")
        self._ocr_box.insert("1.0", text)
        self._btn_tr.configure(state="normal")

    def _put_tr(self, text: str):
        self._tr_box.delete("1.0", "end")
        self._tr_box.insert("1.0", text)

    def _copy(self, widget: scrolledtext.ScrolledText):
        text = widget.get("1.0", "end").strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._status.set("คัดลอกข้อความแล้ว ✓")

    def _on_error(self, msg: str):
        self._status.set(f"ข้อผิดพลาด: {msg[:80]}")
        messagebox.showerror("ข้อผิดพลาด", msg)

    # ── Run ────────────────────────────────────────────────────────────────────

    def run(self):
        try:
            self.root.mainloop()
        finally:
            # Cleanup global hotkey
            if HAS_KEYBOARD and self._global_hk_combo:
                try:
                    keyboard.remove_hotkey(self._global_hk_combo)
                except Exception:
                    pass


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = OCRTranslatorApp()
    app.run()
