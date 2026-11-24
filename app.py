from __future__ import annotations

import ctypes
import json
import queue
import subprocess
import threading
import time
import traceback
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageOps, ImageTk
from engine import active_provider, remove_background, save_outputs

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    DND_FILES = None
    TkinterDnD = None


APP = "炮王专业抠图"
APP_VERSION = "1.1.0"
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
FONT = "Microsoft YaHei UI"

# Design tokens — professional ecommerce desktop tool
NAVY = "#111827"        # sidebar
PAGE = "#F1F5F9"        # page background
CARD = "#FFFFFF"        # card background
INK = "#0F172A"         # primary text
SUB = "#64748B"         # secondary text
BRAND = "#2563EB"       # primary blue
BRAND_HOVER = "#1D4ED8"
OK = "#16A34A"          # success
WARN = "#F59E0B"        # warning / CPU
ERR = "#DC2626"         # error
LINE = "#E2E8F0"
SOFT = "#F8FAFC"


def write_error_log(title, error):
    log = Path(__file__).with_name("error.log")
    details = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    try:
        with log.open("a", encoding="utf-8") as stream:
            stream.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] {title}\n{details}")
    except OSError:
        pass
    return log


def normalize_output_mode(value):
    """Map historical output_mode values onto the two current labels."""
    if value in ("source", "源图旁边", "旁边", ""):
        return "源图旁边"
    if value in ("folder", "统一文件夹", "统一"):
        return "统一文件夹"
    return "源图旁边"


class App:
    def __init__(self):
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        if hasattr(ctypes, "windll"):
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "Paowang.ProfessionalCutout.1")
            except Exception:
                pass
        self.root = TkinterDnD.Tk() if TkinterDnD else ctk.CTk()
        self.root.title(APP)
        self.root.report_callback_exception = self.report_callback_error
        icon = Path(__file__).with_name("assets") / "app.ico"
        if icon.exists():
            try:
                self.root.iconbitmap(str(icon))
            except Exception:
                pass
        icon_png = Path(__file__).with_name("assets") / "app.png"
        if icon_png.exists():
            try:
                self.taskbar_icon = ImageTk.PhotoImage(Image.open(icon_png))
                self.root.iconphoto(True, self.taskbar_icon)
            except Exception:
                pass
        # Roomy default, but never so large that controls get clipped on
        # scaled displays. CustomTkinter applies OS DPI scaling automatically.
        self.root.geometry("1360x980")
        self.root.minsize(1100, 760)

        self.files = []
        self.running = False
        self.stop_event = threading.Event()
        self.events = queue.Queue()
        self.preview_images = {}
        self.last_result_thumb = None
        self.last_result_path = None
        self.current_source_path = None
        self.last_output_dir = None
        self.failed_files = []
        self._last_drop = ("", 0.0)
        self.file_rows = {}       # lowercased path -> {frame,status,thumb,size}
        self.file_states = {}     # lowercased path -> state label
        self._stats = {}
        self.provider_known = False
        self._large_windows = []

        self.settings_path = Path(__file__).with_name("settings.json")
        self.settings = self._load_settings()
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._poll)
        self.root.after(250, self._detect_provider_async)

    # ------------------------------------------------------------------ errors
    def report_callback_error(self, exc_type, exc_value, exc_traceback):
        from tkinter import messagebox
        log = write_error_log("界面操作异常", exc_value)
        messagebox.showerror(APP, f"操作失败：{exc_value}\n\n错误记录：{log}")

    # ---------------------------------------------------------------- settings
    def _load_settings(self):
        defaults = {
            "model": "birefnet-general", "decon": 80, "shrink": 1,
            "feather": 0.4, "transparent": True,
            "white": False, "black": False, "auto_start": True,
            "output_mode": "源图旁边", "output_dir": "",
            "drag_behavior_version": 1,
        }
        try:
            saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
            defaults.update({key: saved[key] for key in defaults if key in saved})
            if saved.get("drag_behavior_version", 0) < 1:
                defaults["auto_start"] = True
            defaults["output_mode"] = normalize_output_mode(defaults["output_mode"])
        except (OSError, ValueError, TypeError):
            pass
        return defaults

    def save_settings(self):
        values = {
            "model": self.model.get(), "decon": self.decon.get(),
            "shrink": self.shrink.get(), "feather": self.feather.get(),
            "transparent": self.transparent.get(), "white": self.white.get(),
            "black": self.black.get(), "auto_start": self.auto_start.get(),
            "output_mode": self.output_mode.get(), "output_dir": self.output_dir.get(),
            "drag_behavior_version": 1,
        }
        try:
            self.settings_path.write_text(
                json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------- build: shell
    def _build(self):
        root = self.root
        root.configure(bg=PAGE)
        self._build_sidebar(root)
        self._build_main(root)

    def _build_sidebar(self, root):
        side = ctk.CTkFrame(root, width=258, corner_radius=0, fg_color=NAVY)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        # Brand block — intentionally compact
        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(fill="x", padx=22, pady=(22, 4))
        try:
            self.brand_icon = ctk.CTkImage(
                Image.open(Path(__file__).with_name("assets") / "app.png"), size=(46, 46))
            ctk.CTkLabel(brand, text="", image=self.brand_icon).pack(side="left", padx=(0, 12))
        except Exception:
            ctk.CTkLabel(brand, text="PW", width=46, height=46, corner_radius=13,
                         fg_color=BRAND, text_color="white",
                         font=(FONT, 18, "bold")).pack(side="left", padx=(0, 12))
        brand_text = ctk.CTkFrame(brand, fg_color="transparent")
        brand_text.pack(side="left")
        ctk.CTkLabel(brand_text, text=APP, text_color="white",
                     font=(FONT, 17, "bold")).pack(anchor="w")
        ctk.CTkLabel(brand_text, text="专业电商抠图工作台", text_color="#94A3B8",
                     font=(FONT, 10)).pack(anchor="w")
        ctk.CTkFrame(side, height=1, fg_color="#1F2937").pack(fill="x", padx=22, pady=(14, 14))

        # Model
        self.model = ctk.StringVar(value=self.settings["model"])
        ctk.CTkLabel(side, text="抠图模型", text_color="#E2E8F0",
                     font=(FONT, 12, "bold")).pack(anchor="w", padx=22)
        ctk.CTkOptionMenu(
            side, variable=self.model,
            values=["birefnet-general", "birefnet-general-lite", "birefnet-portrait"],
            width=214, height=34, fg_color="#1F2937", button_color="#2563EB",
            button_hover_color=BRAND_HOVER,
            command=lambda _v: self.status.set("模型已切换，处理下一张时生效"),
        ).pack(padx=22, pady=(7, 4))
        ctk.CTkLabel(side, text="默认 BiRefNet General · 首次使用自动下载",
                     justify="left", text_color="#64748B",
                     font=(FONT, 9)).pack(anchor="w", padx=22, pady=(0, 16))

        # Output location
        self.output_mode = ctk.StringVar(value=self.settings["output_mode"])
        self.output_dir = ctk.StringVar(value=self.settings["output_dir"])
        self.auto_start = ctk.BooleanVar(value=self.settings["auto_start"])
        ctk.CTkLabel(side, text="输出位置", text_color="#E2E8F0",
                     font=(FONT, 12, "bold")).pack(anchor="w", padx=22)
        ctk.CTkSegmentedButton(
            side, values=["源图旁边", "统一文件夹"], variable=self.output_mode,
            width=214, height=32, selected_color=BRAND,
            selected_hover_color=BRAND_HOVER, fg_color="#1F2937",
            command=lambda _v: self.save_settings(),
        ).pack(padx=22, pady=(7, 7))
        ctk.CTkButton(
            side, text="选择统一文件夹", width=214, height=32,
            fg_color="#1F2937", hover_color="#334155", text_color="#CBD5E1",
            command=self.pick_output_dir,
        ).pack(padx=22)
        self.output_dir_label = ctk.CTkLabel(
            side, textvariable=self.output_dir, wraplength=210, justify="left",
            text_color="#64748B", font=(FONT, 9),
        )
        self.output_dir_label.pack(anchor="w", padx=22, pady=(5, 14))

        # Auto start
        ctk.CTkSwitch(
            side, text="拖入后立即自动抠图", variable=self.auto_start,
            text_color="#CBD5E1", font=(FONT, 11),
            progress_color=BRAND, command=self._on_auto_toggle,
        ).pack(anchor="w", padx=22)

        # GPU status card (green dot for CUDA, orange for CPU)
        gpu = ctk.CTkFrame(side, fg_color="#1F2937", corner_radius=12, height=58)
        gpu.pack(fill="x", padx=18, pady=(18, 8))
        gpu.pack_propagate(False)
        self.gpu_dot = ctk.CTkLabel(gpu, text="●", text_color=WARN,
                                    font=(FONT, 16))
        self.gpu_dot.pack(side="left", padx=(14, 8))
        gpu_text = ctk.CTkFrame(gpu, fg_color="transparent")
        gpu_text.pack(side="left")
        ctk.CTkLabel(gpu_text, text="加速状态", text_color="#64748B",
                     font=(FONT, 9)).pack(anchor="w")
        self.provider_status = ctk.StringVar(value="检测中…")
        ctk.CTkLabel(gpu_text, textvariable=self.provider_status, text_color="#E2E8F0",
                     font=(FONT, 11, "bold")).pack(anchor="w")

        # Settings entry at the bottom
        ctk.CTkFrame(side, fg_color="transparent").pack(fill="both", expand=True)
        ctk.CTkFrame(side, height=1, fg_color="#1F2937").pack(fill="x", padx=22, pady=(0, 8))
        ctk.CTkButton(
            side, text="⚙  偏好设置", width=214, height=34,
            fg_color="#1F2937", hover_color="#334155", text_color="#CBD5E1",
            font=(FONT, 11), anchor="w", command=self.open_settings,
        ).pack(padx=18, pady=(0, 10))
        ctk.CTkLabel(side, text=f"v{APP_VERSION} · 本地离线运行", text_color="#475569",
                     font=(FONT, 9)).pack(anchor="w", padx=22, pady=(0, 16))

    # ------------------------------------------------------------- build: main
    def _build_main(self, root):
        main = ctk.CTkFrame(root, fg_color=PAGE, corner_radius=0)
        main.pack(side="left", fill="both", expand=True)

        # Header
        header = ctk.CTkFrame(main, fg_color="transparent")
        header.pack(fill="x", padx=30, pady=(22, 10))
        ctk.CTkLabel(header, text="专业抠图工作台", text_color=INK,
                     font=(FONT, 25, "bold")).pack(side="left")
        privacy = ctk.CTkFrame(header, fg_color="#DCFCE7", corner_radius=16, height=28)
        privacy.pack(side="right", padx=(8, 0))
        ctk.CTkLabel(privacy, text="🔒  本地处理 · 图片不会上传", text_color="#15803D",
                     font=(FONT, 10, "bold")).pack(padx=12, pady=4)
        self.status = ctk.StringVar(value="等待图片 · 拖入或点击选择产品图")
        self.header_status = ctk.CTkLabel(header, textvariable=self.status,
                                          text_color=SUB, font=(FONT, 11))
        self.header_status.pack(side="right", padx=16)

        # Status cards strip
        self._build_status_strip(main)

        # Drop zone
        self._build_dropzone(main)

        # Content: preview + queue (left) / params + actions (right)
        content = ctk.CTkFrame(main, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=30, pady=(14, 20))
        left = ctk.CTkFrame(content, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True)
        right = ctk.CTkFrame(content, width=352, fg_color="transparent")
        right.pack(side="right", fill="y", padx=(16, 0))
        right.pack_propagate(False)
        self._build_queue(left)
        self._build_preview(left)
        self._build_actions(right)
        self._build_params(right)

    def _build_status_strip(self, main):
        strip = ctk.CTkFrame(main, fg_color=CARD, corner_radius=14, height=82)
        strip.pack(fill="x", padx=30)
        strip.pack_propagate(False)
        self.stat_vars = {
            "current": ctk.StringVar(value="—"),
            "progress": ctk.StringVar(value="0 / 0"),
            "ok": ctk.StringVar(value="0"),
            "fail": ctk.StringVar(value="0"),
            "elapsed": ctk.StringVar(value="0s"),
            "eta": ctk.StringVar(value="—"),
        }
        cards = [
            ("当前文件", "current", INK),
            ("总进度", "progress", BRAND),
            ("成功", "ok", OK),
            ("失败", "fail", ERR),
            ("已用时间", "elapsed", INK),
            ("预计剩余", "eta", INK),
        ]
        for i, (title, key, color) in enumerate(cards):
            cell = ctk.CTkFrame(strip, fg_color=SOFT, corner_radius=10)
            cell.grid(row=0, column=i, sticky="nsew", padx=(6, 6), pady=10)
            strip.grid_columnconfigure(i, weight=1)
            ctk.CTkLabel(cell, text=title, text_color=SUB,
                         font=(FONT, 9)).pack(anchor="w", padx=12, pady=(8, 0))
            lbl = ctk.CTkLabel(cell, textvariable=self.stat_vars[key], text_color=color,
                               font=(FONT, 13, "bold"), anchor="w")
            lbl.pack(anchor="w", padx=12, pady=(2, 8))
            if key == "current":
                self.current_stat_label = lbl

    def _build_dropzone(self, main):
        self.drop = ctk.CTkFrame(
            main, height=168, corner_radius=18, border_width=2,
            border_color="#93C5FD", fg_color="#EFF6FF",
        )
        self.drop.pack(fill="x", padx=30, pady=(14, 0))
        self.drop.pack_propagate(False)

        inner = ctk.CTkFrame(self.drop, fg_color="transparent")
        inner.pack(expand=True, fill="both")
        # Upload icon drawn as vector-ish glyph to avoid extra assets
        ctk.CTkLabel(inner, text="⬆", text_color=BRAND,
                     font=(FONT, 42, "bold")).pack(pady=(14, 0))
        ctk.CTkLabel(inner, text="将产品图或文件夹拖到这里", text_color=BRAND,
                     font=(FONT, 17, "bold")).pack(pady=(2, 0))
        ctk.CTkLabel(inner, text="也可以点击此区域选择图片", text_color="#3B82F6",
                     font=(FONT, 11)).pack()
        hint = ctk.CTkFrame(inner, fg_color="transparent")
        hint.pack(pady=(6, 12))
        ctk.CTkLabel(hint, text="支持 JPG · PNG · WEBP · BMP · TIFF", text_color=SUB,
                     font=(FONT, 10)).pack(side="left", padx=(0, 14))
        self.auto_hint = ctk.StringVar(
            value="拖入后自动开始" if self.auto_start.get() else "拖入后手动开始")
        ctk.CTkLabel(hint, textvariable=self.auto_hint, text_color=BRAND,
                     font=(FONT, 10, "bold")).pack(side="left")

        # Whole area clickable
        self._bind_click_recursive(self.drop)
        # Hover feedback
        self.drop.bind("<Enter>", lambda _e: self._drop_hover(True))
        self.drop.bind("<Leave>", lambda _e: self._drop_hover(False))
        # Drag & drop registration on multiple widgets so drops anywhere work.
        self.drop_widgets = (self.root, main, self.drop, inner)
        for widget in self.drop_widgets:
            if DND_FILES:
                try:
                    widget.drop_target_register(DND_FILES)
                    widget.dnd_bind("<<Drop>>", self.on_drop)
                except Exception as exc:
                    self.root.after(0, lambda message=str(exc):
                                    self.status.set(f"拖放初始化失败：{message}"))
                # Optional drag-hover events (tkinterdnd2 >= 0.4)
                for ev, state in (("<<DropEnter>>", True), ("<<DropLeave>>", False)):
                    try:
                        widget.dnd_bind(ev, lambda _e, s=state: self._drop_hover(s))
                    except Exception:
                        pass

    def _build_preview(self, parent):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14)
        card.pack(fill="both", expand=True)
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(head, text="结果预览", text_color=INK,
                     font=(FONT, 14, "bold")).pack(side="left")
        self.preview_bg = ctk.StringVar(value="透明")
        ctk.CTkSegmentedButton(
            head, values=["透明", "白底", "黑底"], width=186, height=28,
            variable=self.preview_bg, selected_color=BRAND,
            selected_hover_color=BRAND_HOVER,
            command=lambda _v: self.render_result_preview(),
        ).pack(side="right")
        ctk.CTkLabel(head, text="点击查看大图", text_color=SUB,
                     font=(FONT, 9)).pack(side="right", padx=12)

        views = ctk.CTkFrame(card, fg_color="transparent")
        views.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.before_preview = ctk.CTkLabel(
            views, text="选择文件查看原图", fg_color="#E2E8F0", corner_radius=10,
            text_color=SUB, font=(FONT, 11))
        self.before_preview.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.before_preview.bind("<Button-1>", lambda _e: self.open_large_preview("before"))
        self.after_preview = ctk.CTkLabel(
            views, text="抠图完成后显示结果", fg_color="#E2E8F0", corner_radius=10,
            text_color=SUB, font=(FONT, 11))
        self.after_preview.pack(side="right", fill="both", expand=True, padx=(6, 0))
        self.after_preview.bind("<Button-1>", lambda _e: self.open_large_preview("after"))

    def _build_queue(self, parent):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14, height=190)
        card.pack(side="bottom", fill="x", pady=(12, 0))
        card.pack_propagate(False)
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(10, 4))
        self.file_count = ctk.StringVar(value="文件队列  0")
        ctk.CTkLabel(head, textvariable=self.file_count, text_color=INK,
                     font=(FONT, 13, "bold")).pack(side="left")
        ctk.CTkButton(head, text="清空", width=54, height=26, fg_color="#F1F5F9",
                      hover_color="#E2E8F0", text_color=SUB,
                      command=self.clear_files).pack(side="right")
        self.queue = ctk.CTkScrollableFrame(card, fg_color="transparent", height=70)
        self.queue.pack(fill="both", expand=True, padx=(10, 6), pady=(0, 10))

    def _build_params(self, parent):
        card = ctk.CTkScrollableFrame(parent, fg_color=CARD, corner_radius=14)
        card.pack(fill="both", expand=True)
        ctk.CTkLabel(card, text="边缘处理", text_color=INK,
                     font=(FONT, 14, "bold")).pack(anchor="w", padx=18, pady=(14, 2))
        ctk.CTkLabel(card, text="快速预设", text_color=SUB,
                     font=(FONT, 10)).pack(anchor="w", padx=18, pady=(6, 0))
        self.preset = ctk.StringVar(value="产品图")
        ctk.CTkSegmentedButton(
            card, values=["产品图", "毛发", "透明材质", "硬边"], variable=self.preset,
            selected_color=BRAND, selected_hover_color=BRAND_HOVER,
            command=self.apply_preset,
        ).pack(fill="x", padx=18, pady=(5, 8))

        self.decon = ctk.IntVar(value=self.settings["decon"])
        self.shrink = ctk.IntVar(value=self.settings["shrink"])
        self.feather = ctk.DoubleVar(value=self.settings["feather"])
        self._slider(card, "去白边强度", "替换边缘受背景污染的像素", self.decon, 0, 100)
        self._slider(card, "边缘内缩", "向内收紧蒙版，消除白边", self.shrink, 0, 3, 3)
        self._slider(card, "边缘柔化", "让边缘过渡更自然", self.feather, 0, 1.5, 15)

        ctk.CTkButton(
            card, text="↺  恢复推荐参数", height=28, fg_color="#EFF6FF",
            hover_color="#DBEAFE", text_color=BRAND, font=(FONT, 10),
            command=lambda: self.apply_preset("产品图", announce=True),
        ).pack(fill="x", padx=18, pady=(2, 8))

        ctk.CTkFrame(card, height=1, fg_color=LINE).pack(fill="x", padx=18, pady=(0, 8))
        ctk.CTkLabel(card, text="输出格式", text_color=INK,
                     font=(FONT, 12, "bold")).pack(anchor="w", padx=18, pady=(0, 4))
        self.transparent = ctk.BooleanVar(value=self.settings["transparent"])
        self.white = ctk.BooleanVar(value=self.settings["white"])
        self.black = ctk.BooleanVar(value=self.settings["black"])
        for text, var in (("透明 PNG（默认）", self.transparent),
                          ("白底 JPG（可选）", self.white),
                          ("黑底检查图", self.black)):
            ctk.CTkCheckBox(card, text=text, variable=var,
                            font=(FONT, 11), checkbox_height=16, checkbox_width=16,
                            ).pack(anchor="w", padx=18, pady=3)

    def _build_actions(self, parent):
        box = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14)
        box.pack(side="bottom", fill="x", pady=(12, 0))
        self.progress = ctk.CTkProgressBar(box, height=8, progress_color=BRAND)
        self.progress.pack(fill="x", padx=18, pady=(14, 10))
        self.progress.set(0)
        self.start_btn = ctk.CTkButton(
            box, text="开始专业抠图", height=46, font=(FONT, 14, "bold"),
            fg_color=BRAND, hover_color=BRAND_HOVER, command=self.start,
        )
        self.start_btn.pack(fill="x", padx=18, pady=(0, 8))
        self._refresh_start_label()

        row1 = ctk.CTkFrame(box, fg_color="transparent")
        row1.pack(fill="x", padx=18, pady=(0, 6))
        self.stop_btn = ctk.CTkButton(
            row1, text="■ 停止", height=32, fg_color="#FEE2E2", hover_color="#FECACA",
            text_color="#B91C1C", state="disabled", command=self.stop)
        self.stop_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.retry_btn = ctk.CTkButton(
            row1, text="重试失败项", height=32, fg_color="#FFF7ED", hover_color="#FFEDD5",
            text_color="#C2410C", state="disabled", command=self.retry_failed)
        self.retry_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.open_btn = ctk.CTkButton(
            box, text="打开结果文件夹", height=32, fg_color="#F1F5F9",
            hover_color="#E2E8F0", text_color="#334155", state="disabled",
            command=self.open_output)
        self.open_btn.pack(fill="x", padx=18, pady=(0, 14))

    # ------------------------------------------------------------------ helpers
    def _bind_click_recursive(self, widget):
        widget.bind("<Button-1>", lambda _e: self.pick())
        for child in widget.winfo_children():
            try:
                self._bind_click_recursive(child)
            except Exception:
                pass

    def _drop_hover(self, active):
        if active:
            self.drop.configure(border_color=BRAND, fg_color="#DBEAFE")
        else:
            self.drop.configure(border_color="#93C5FD", fg_color="#EFF6FF")

    def _on_auto_toggle(self):
        self._refresh_start_label()
        self.auto_hint.set("拖入后自动开始" if self.auto_start.get() else "拖入后手动开始")
        self.save_settings()

    def _refresh_start_label(self):
        if not hasattr(self, "start_btn"):
            return
        self.start_btn.configure(
            text="拖入后自动处理" if self.auto_start.get() else "开始专业抠图")

    def _slider(self, parent, text, desc, var, low, high, steps=100):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(6, 0))
        fmt = (lambda v: f"{float(v):.1f}") if isinstance(var, ctk.DoubleVar) \
            else (lambda v: str(int(v)))
        value = ctk.CTkLabel(row, text=fmt(var.get()), width=38, text_color=BRAND,
                             font=(FONT, 11, "bold"))
        value.pack(side="right")
        ctk.CTkLabel(row, text=text, text_color=INK,
                     font=(FONT, 11, "bold")).pack(side="left")
        ctk.CTkSlider(
            parent, from_=low, to=high, number_of_steps=steps, variable=var,
            progress_color=BRAND, button_color=BRAND,
            command=lambda v: value.configure(text=fmt(v)),
        ).pack(fill="x", padx=18, pady=(2, 0))
        ctk.CTkLabel(parent, text=desc, text_color=SUB,
                     font=(FONT, 9)).pack(anchor="w", padx=18, pady=(0, 2))
        var.trace_add("write", lambda *_: value.configure(text=fmt(var.get())))

    def apply_preset(self, name, announce=False):
        presets = {
            "产品图": (80, 1, 0.4),
            "毛发": (35, 0, 0.8),
            "透明材质": (15, 0, 0.3),
            "硬边": (95, 2, 0.0),
        }
        decon, shrink, feather = presets.get(name, presets["产品图"])
        self.decon.set(decon)
        self.shrink.set(shrink)
        self.feather.set(feather)
        self.status.set(f"已应用「{name}」预设 · 去白边 {decon} / 内缩 {shrink} / 柔化 {feather}")

    # --------------------------------------------------------------- queue rows
    def _make_row(self, path):
        key = str(path).lower()
        row = ctk.CTkFrame(self.queue, fg_color=SOFT, corner_radius=8, height=46)
        row.pack(fill="x", pady=2)
        row.pack_propagate(False)
        thumb = ctk.CTkLabel(row, text="▣", fg_color="#E2E8F0", corner_radius=6,
                             width=34, height=34, text_color=SUB)
        thumb.pack(side="left", padx=(8, 8), pady=6)
        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(info, text=path.name, text_color=INK, font=(FONT, 10, "bold"),
                     anchor="w").pack(anchor="w", pady=(5, 0))
        size_lbl = ctk.CTkLabel(info, text="读取尺寸…", text_color=SUB,
                                font=(FONT, 9), anchor="w")
        size_lbl.pack(anchor="w")
        state_lbl = ctk.CTkLabel(row, text="等待", text_color=SUB,
                                 font=(FONT, 10, "bold"), width=52)
        state_lbl.pack(side="right", padx=(2, 4))
        ctk.CTkButton(row, text="✕", width=24, height=24, fg_color="transparent",
                      hover_color="#FEE2E2", text_color=SUB, font=(FONT, 12),
                      command=lambda p=path: self.remove_one(p)).pack(side="right", padx=(0, 4))
        self.file_rows[key] = {"frame": row, "thumb": thumb, "size": size_lbl,
                               "state": state_lbl}

    def _refresh_files(self):
        for widget in self.queue.winfo_children():
            widget.destroy()
        self.file_rows.clear()
        self.file_states.clear()
        for p in self.files:
            key = str(p).lower()
            self._make_row(p)
            self._set_file_state(p, "等待")
            self._enqueue_thumb(p)
        self.file_count.set(f"文件队列  {len(self.files)}")

    def _set_file_state(self, path, state):
        key = str(path).lower()
        self.file_states[key] = state
        style = {
            "等待": (SUB, "等待"),
            "处理中": (BRAND, "处理中"),
            "完成": (OK, "完成"),
            "失败": (ERR, "失败"),
        }.get(state, (SUB, state))
        row = self.file_rows.get(key)
        if row:
            row["state"].configure(text=style[1], text_color=style[0])

    def _enqueue_thumb(self, path):
        def task():
            try:
                with Image.open(path) as im:
                    im = ImageOps.exif_transpose(im)
                    size = im.size
                    im = im.convert("RGB")
                    im.thumbnail((34, 34), Image.Resampling.LANCZOS)
                    thumb = im.copy()
                self.events.put(("meta", (str(path).lower(), size, thumb)))
            except Exception:
                pass
        threading.Thread(target=task, daemon=True).start()

    # ------------------------------------------------------------- file actions
    def pick(self):
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(
            title="选择图片",
            filetypes=[("图片", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff")])
        self.add(paths)

    def pick_output_dir(self):
        from tkinter import filedialog
        selected = filedialog.askdirectory(
            title="选择统一输出文件夹", initialdir=self.output_dir.get() or None)
        if selected:
            self.output_dir.set(selected)
            self.output_mode.set("统一文件夹")
            self.save_settings()

    def on_drop(self, event):
        # Critical Windows path handling: keep this exactly intact.
        # Tcl escapes backslashes in bare paths (no spaces), so try the raw
        # path first, then fall back to Tk's list parser for brace-wrapped,
        # space-containing or multi-file payloads.
        drop_data = str(event.data)
        now = time.monotonic()
        if drop_data == self._last_drop[0] and now - self._last_drop[1] < 0.5:
            return "copy"
        self._last_drop = (drop_data, now)
        if self.running:
            self.status.set("当前图片处理中，请完成后再拖入")
            return "copy"
        if self.auto_start.get():
            self.clear_files()
        direct_path = drop_data.strip().strip("{}\"")
        if Path(direct_path).exists():
            paths = (direct_path,)
        else:
            try:
                paths = self.root.tk.splitlist(drop_data)
            except Exception:
                paths = (direct_path,)
        _added, rejected = self.add(paths)
        if not self.files:
            detail = f"，已跳过 {rejected} 个损坏文件" if rejected else ""
            self.status.set(f"没有识别到可用图片{detail}")
        elif self.auto_start.get():
            detail = f"，跳过 {rejected} 个损坏文件" if rejected else ""
            self.status.set(f"已识别 {len(self.files)} 张{detail}，正在自动开始…")
            self.root.after(150, self.start)
        return "copy"

    @staticmethod
    def _is_readable_image(path):
        try:
            if not path.is_file() or path.stat().st_size <= 0:
                return False
            with Image.open(path) as image:
                return image.width > 0 and image.height > 0
        except (OSError, ValueError):
            return False

    def add(self, paths):
        existing = {str(p).lower() for p in self.files}
        candidates = []
        for raw in paths:
            p = Path(raw)
            if p.is_dir():
                candidates.extend(
                    x for x in p.rglob("*")
                    if x.suffix.lower() in EXTS
                    and not any(parent.name.endswith("_抠图") for parent in x.parents)
                    and not x.stem.endswith(("_透明", "_白底", "_黑底预览"))
                )
            elif p.suffix.lower() in EXTS:
                candidates.append(p)
        found = [p for p in candidates if self._is_readable_image(p)]
        rejected = len(candidates) - len(found)
        added = 0
        for p in found:
            if str(p).lower() not in existing:
                self.files.append(p)
                existing.add(str(p).lower())
                added += 1
        self._refresh_files()
        detail = f"，跳过 {rejected} 个损坏文件" if rejected else ""
        self.status.set(f"已加入 {len(self.files)} 张图片{detail}")
        return added, rejected

    def remove_one(self, path):
        if self.running:
            return
        self.files = [p for p in self.files if p != path]
        self._refresh_files()
        self.status.set(f"已加入 {len(self.files)} 张图片" if self.files else "等待图片")

    def remove_selected(self):
        if self.running:
            return
        # Rows do not expose Tk selection; removal is via per-row button.
        self.status.set("点击每行右侧 ✕ 可移除单个文件")

    def clear_files(self):
        if not self.running:
            self.files.clear()
            self._refresh_files()
            self.progress.set(0)
            self.status.set("等待图片 · 拖入或点击选择产品图")
            self._set_stats(current="—", progress="0 / 0", ok="0", fail="0",
                            elapsed="0s", eta="—")

    # --------------------------------------------------------------- previews
    def show_selected(self, path):
        self.current_source_path = path
        try:
            with Image.open(path) as source:
                preview = self._preview_image(source.convert("RGBA"), checker=False)
            self.preview_images["before"] = ctk.CTkImage(preview, size=preview.size)
            self.before_preview.configure(image=self.preview_images["before"], text="")
        except Exception as exc:
            self.before_preview.configure(image=None, text=f"无法预览\n{exc}")

    @staticmethod
    def _preview_image(image, checker=True, box=(360, 220), background=None):
        image = image.copy()
        image.thumbnail(box, Image.Resampling.LANCZOS)
        if background == "白底":
            canvas = Image.new("RGBA", box, (255, 255, 255, 255))
        elif background == "黑底":
            canvas = Image.new("RGBA", box, (15, 23, 42, 255))
        else:
            canvas = Image.new("RGBA", box, (241, 245, 249, 255))
        if checker and background not in ("白底", "黑底"):
            draw = ImageDraw.Draw(canvas)
            cell = 12
            for y in range(0, box[1], cell):
                for x in range(0, box[0], cell):
                    color = (226, 232, 240, 255) if (x // cell + y // cell) % 2 else (248, 250, 252, 255)
                    draw.rectangle((x, y, x + cell, y + cell), fill=color)
        x = (box[0] - image.width) // 2
        y = (box[1] - image.height) // 2
        canvas.alpha_composite(image, (x, y))
        return canvas

    def render_result_preview(self):
        if self.last_result_thumb is None:
            return
        preview = self._preview_image(
            self.last_result_thumb, checker=True, background=self.preview_bg.get())
        self.preview_images["after"] = ctk.CTkImage(preview, size=preview.size)
        self.after_preview.configure(image=self.preview_images["after"], text="")

    def open_large_preview(self, kind):
        path = self.current_source_path if kind == "before" else self.last_result_path
        if not path or not Path(path).exists():
            return
        try:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im).convert("RGBA")
                im.thumbnail((900, 900), Image.Resampling.LANCZOS)
            box = (max(240, im.width), max(240, im.height))
            preview = self._preview_image(
                im, checker=(kind == "after"), box=box,
                background=self.preview_bg.get() if kind == "after" else None)
            top = ctk.CTkToplevel(self.root)
            top.title("查看大图")
            top.geometry(f"{preview.width + 40}x{preview.height + 60}")
            top.lift()
            ctk.CTkLabel(top, text=Path(path).name, text_color=SUB,
                         font=(FONT, 11)).pack(pady=(12, 4))
            img = ctk.CTkImage(preview, size=preview.size)
            holder = ctk.CTkLabel(top, image=img, text="")
            holder.image = img
            holder.pack(padx=20, pady=(0, 16))
            self._large_windows.append(top)
            top.protocol("WM_DELETE_WINDOW",
                         lambda w=top: (w.destroy(),
                                        self._large_windows.remove(w)
                                        if w in self._large_windows else None))
        except Exception as exc:
            self.status.set(f"打开大图失败：{exc}")

    # -------------------------------------------------------------- processing
    def start(self):
        if self.running or not self.files:
            self.status.set("请先拖入图片" if not self.files else "正在处理")
            return
        if not any((self.transparent.get(), self.white.get(), self.black.get())):
            self.status.set("请至少选择一种输出格式")
            return
        if self.output_mode.get() == "统一文件夹" and not self.output_dir.get():
            self.status.set("请先选择统一输出文件夹")
            self.pick_output_dir()
            if not self.output_dir.get():
                return
        self.save_settings()
        self.running = True
        self.stop_event.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.header_status.configure(text_color=SUB)
        self._set_stats(progress=f"0 / {len(self.files)}", ok="0", fail="0",
                        elapsed="0s", eta="—")
        # Capture a stable snapshot on the UI thread; the worker never touches
        # Tk variables from the background thread.
        job = {
            "files": list(self.files),
            "model": self.model.get(),
            "decon": self.decon.get(),
            "shrink": self.shrink.get(),
            "feather": self.feather.get(),
            "transparent": self.transparent.get(),
            "white": self.white.get(),
            "black": self.black.get(),
            "output_dir": self.output_dir.get() if self.output_mode.get() == "统一文件夹" else None,
        }
        threading.Thread(target=self.worker, args=(job,), daemon=True).start()

    def stop(self):
        if self.running:
            self.stop_event.set()
            self.stop_btn.configure(state="disabled")
            self.status.set("正在停止：当前图片完成后结束队列")

    def retry_failed(self):
        if self.running or not self.failed_files:
            return
        self.files = list(self.failed_files)
        self.failed_files = []
        self.retry_btn.configure(state="disabled")
        self._refresh_files()
        self.progress.set(0)
        self.status.set(f"已载入 {len(self.files)} 个失败项，准备重试")

    def open_output(self):
        if self.last_output_dir and Path(self.last_output_dir).exists():
            subprocess.Popen(["explorer", str(self.last_output_dir)])

    def close(self):
        self.save_settings()
        self.root.destroy()

    # ------------------------------------------------------------- preferences
    def open_settings(self):
        top = ctk.CTkToplevel(self.root)
        top.title("偏好设置")
        top.geometry("460x360")
        top.resizable(False, False)
        top.lift()
        cache = Path.home() / ".rembg" / "models"
        ctk.CTkLabel(top, text="偏好设置", text_color=INK,
                     font=(FONT, 18, "bold")).pack(anchor="w", padx=24, pady=(20, 4))
        ctk.CTkLabel(top, text=f"模型缓存：{cache}", text_color=SUB,
                     font=(FONT, 10), wraplength=410, justify="left").pack(anchor="w", padx=24)
        ctk.CTkLabel(top, text="设置会在关闭软件或开始处理时自动保存。",
                     text_color=SUB, font=(FONT, 10)).pack(anchor="w", padx=24, pady=(2, 14))
        ctk.CTkButton(top, text="打开模型缓存文件夹", height=34, fg_color="#EFF6FF",
                      hover_color="#DBEAFE", text_color=BRAND,
                      command=lambda: subprocess.Popen(["explorer", str(cache)])
                      if cache.exists() else self.status.set("模型缓存目录尚不存在")).pack(
                          fill="x", padx=24, pady=3)
        ctk.CTkButton(top, text="打开错误日志", height=34, fg_color="#F1F5F9",
                      hover_color="#E2E8F0", text_color="#334155",
                      command=lambda: subprocess.Popen(
                          ["explorer", "/select,", str(Path(__file__).with_name("error.log"))])
                      ).pack(fill="x", padx=24, pady=3)
        ctk.CTkButton(top, text="恢复默认设置", height=34, fg_color="#FFF7ED",
                      hover_color="#FFEDD5", text_color="#C2410C",
                      command=lambda: self._reset_settings(top)).pack(fill="x", padx=24, pady=3)
        ctk.CTkButton(top, text="关闭", height=34, fg_color=BRAND,
                      hover_color=BRAND_HOVER, command=top.destroy).pack(
                          fill="x", padx=24, pady=(14, 20))

    def _reset_settings(self, top):
        try:
            self.settings_path.unlink(missing_ok=True)
        except OSError:
            pass
        top.destroy()
        self.status.set("设置已恢复默认，重新启动软件后生效")

    # --------------------------------------------------------------- background
    def _detect_provider_async(self):
        def task():
            try:
                import onnxruntime as ort
                available = ort.get_available_providers()
                text = "CUDA 已启用" if "CUDAExecutionProvider" in available else "CPU 模式"
                self.events.put(("provider_hint", text))
            except Exception:
                pass
        threading.Thread(target=task, daemon=True).start()

    def worker(self, job):
        files = job["files"]
        total = len(files)
        failed = []
        output_dirs = set()
        completed = 0
        cancelled = False
        failed_paths = []
        provider_sent = False
        batch_started = time.perf_counter()
        for index, path in enumerate(files, 1):
            if self.stop_event.is_set():
                cancelled = True
                break
            item_started = time.perf_counter()
            self.events.put(("file", (str(path).lower(), "处理中")))
            self.events.put(("status", f"{index}/{total} 正在处理：{path.name}"))
            self.events.put(("stats", {"current": path.name,
                                       "progress": f"{index - 1}/{total}"}))
            try:
                result = remove_background(path, job["model"], job["decon"],
                                           job["shrink"], job["feather"])
                outputs = save_outputs(result, path, job["transparent"],
                                       job["white"], job["black"], job["output_dir"])
                output_dirs.update(p.parent for p in outputs)
                thumb = result.copy()
                thumb.thumbnail((360, 220), Image.Resampling.LANCZOS)
                self.events.put(("preview", (thumb, str(outputs[0]) if outputs else None,
                                             str(path))))
                self.events.put(("file", (str(path).lower(), "完成")))
                if not provider_sent:
                    try:
                        self.events.put(("provider", active_provider(job["model"])))
                    except Exception:
                        pass
                    provider_sent = True
            except Exception as exc:
                failed.append(f"{path.name}: {exc}")
                failed_paths.append(path)
                self.events.put(("file", (str(path).lower(), "失败")))
            completed = index
            item_seconds = time.perf_counter() - item_started
            average = (time.perf_counter() - batch_started) / completed
            eta = max(0, total - completed) * average
            self.events.put(("status", f"{completed}/{total} 已完成 · 本张 {item_seconds:.1f} 秒 · 预计剩余 {eta:.0f} 秒"))
            self.events.put(("progress", index / total))
            self.events.put(("stats", {
                "progress": f"{completed}/{total}",
                "ok": str(completed - len(failed)),
                "fail": str(len(failed)),
                "elapsed": f"{time.perf_counter() - batch_started:.0f}s",
                "eta": f"{eta:.0f}s",
            }))
        elapsed = time.perf_counter() - batch_started
        self.events.put(("done", (completed, failed, failed_paths, output_dirs, cancelled, elapsed)))

    # -------------------------------------------------------------- UI polling
    def _set_stats(self, **kwargs):
        for key, value in kwargs.items():
            if key in self.stat_vars:
                self.stat_vars[key].set(value)

    def _poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "status":
                    self.status.set(data)
                elif kind == "progress":
                    self.progress.set(data)
                elif kind == "stats":
                    self._set_stats(**data)
                elif kind == "file":
                    key, state = data
                    row = self.file_rows.get(key)
                    self.file_states[key] = state
                    if row:
                        style = {"等待": SUB, "处理中": BRAND, "完成": OK, "失败": ERR}.get(state, SUB)
                        row["state"].configure(text=state, text_color=style)
                elif kind == "meta":
                    key, size, thumb = data
                    row = self.file_rows.get(key)
                    if row:
                        row["size"].configure(text=f"{size[0]} × {size[1]}")
                        img = ctk.CTkImage(thumb, size=thumb.size)
                        self.preview_images[f"thumb_{key}"] = img
                        row["thumb"].configure(image=img, text="")
                elif kind == "preview":
                    thumb, result_path, source_path = data
                    self.last_result_thumb = thumb
                    self.last_result_path = result_path
                    self.current_source_path = source_path
                    self.render_result_preview()
                    self.show_selected(Path(source_path))
                elif kind == "provider":
                    name = "CUDA 已启用" if data == "CUDAExecutionProvider" else "CPU 模式"
                    self.provider_status.set(name)
                    self.gpu_dot.configure(text_color=OK if name.startswith("CUDA") else WARN)
                    self.provider_known = True
                elif kind == "provider_hint":
                    if not self.provider_known:
                        self.provider_status.set(data)
                        self.gpu_dot.configure(text_color=OK if "CUDA" in data else WARN)
                elif kind == "done":
                    completed, failed, failed_paths, dirs, cancelled, elapsed = data
                    self.running = False
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.failed_files = failed_paths
                    self.retry_btn.configure(state="normal" if failed_paths else "disabled")
                    ok = completed - len(failed)
                    if cancelled:
                        self.status.set(f"已停止：成功 {ok}，失败 {len(failed)} · 用时 {elapsed:.1f} 秒")
                    elif failed:
                        self.status.set(f"完成：成功 {ok}，失败 {len(failed)} · 用时 {elapsed:.1f} 秒")
                    else:
                        self.status.set(f"✓ 全部完成 · 成功处理 {ok} 张 · 用时 {elapsed:.1f} 秒")
                    self.header_status.configure(text_color=OK if not failed else WARN)
                    self._set_stats(elapsed=f"{elapsed:.0f}s", eta="0s")
                    if dirs:
                        self.last_output_dir = next(iter(dirs))
                        self.open_btn.configure(state="normal")
                        subprocess.Popen(["explorer", str(self.last_output_dir)])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    try:
        App().run()
    except Exception as exc:
        log = write_error_log("启动异常", exc)
        try:
            from tkinter import messagebox
            messagebox.showerror(APP, f"软件启动失败：{exc}\n\n错误记录：{log}")
        except Exception:
            pass
