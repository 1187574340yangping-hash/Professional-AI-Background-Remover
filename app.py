from __future__ import annotations

import json
import queue
import subprocess
import threading
import ctypes
import time
import traceback
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageTk
from engine import active_provider, remove_background, save_outputs

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    DND_FILES = None
    TkinterDnD = None


APP = "炮王专业抠图"
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def write_error_log(title, error):
    log = Path(__file__).with_name("error.log")
    details = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    try:
        with log.open("a", encoding="utf-8") as stream:
            stream.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] {title}\n{details}")
    except OSError:
        pass
    return log


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
        self.root.geometry("1180x850")
        self.root.minsize(940, 650)
        self.files = []
        self.running = False
        self.stop_event = threading.Event()
        self.events = queue.Queue()
        self.preview_images = {}
        self.last_result_thumb = None
        self.last_output_dir = None
        self.failed_files = []
        self._last_drop = ("", 0.0)
        self.settings_path = Path(__file__).with_name("settings.json")
        self.settings = self._load_settings()
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._poll)

    def report_callback_error(self, exc_type, exc_value, exc_traceback):
        from tkinter import messagebox
        log = write_error_log("界面操作异常", exc_value)
        messagebox.showerror(APP, f"操作失败：{exc_value}\n\n错误记录：{log}")

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
        except (OSError, ValueError, TypeError):
            pass
        return defaults

    def _build(self):
        root = self.root
        root.configure(bg="#eef2f7")
        side = ctk.CTkFrame(root, width=230, corner_radius=0, fg_color="#111827")
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        try:
            self.brand_icon = ctk.CTkImage(Image.open(Path(__file__).with_name("assets") / "app.png"), size=(64, 64))
            ctk.CTkLabel(side, text="", image=self.brand_icon).pack(anchor="w", padx=22, pady=(26, 10))
        except Exception:
            ctk.CTkLabel(side, text="PW", width=56, height=56, corner_radius=16,
                         fg_color="#2563eb", text_color="white",
                         font=("Segoe UI", 22, "bold")).pack(anchor="w", padx=24, pady=(28, 10))
        ctk.CTkLabel(side, text=APP, text_color="white",
                     font=("Microsoft YaHei UI", 19, "bold")).pack(anchor="w", padx=24)
        ctk.CTkLabel(side, text="本地 AI · 批量 · 自动去白边", text_color="#94a3b8",
                     font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=24, pady=(4, 24))

        self.model = ctk.StringVar(value=self.settings["model"])
        ctk.CTkLabel(side, text="抠图模型", text_color="#cbd5e1").pack(anchor="w", padx=24)
        ctk.CTkOptionMenu(side, variable=self.model,
                          values=["birefnet-general", "birefnet-general-lite", "birefnet-portrait"],
                          width=182).pack(padx=24, pady=(6, 18))
        ctk.CTkLabel(side, text="完整版约 930MB\n首次使用自动下载\n之后可完全离线",
                     justify="left", text_color="#94a3b8").pack(anchor="w", padx=24, pady=(0, 20))

        self.output_mode = ctk.StringVar(value=self.settings["output_mode"])
        self.output_dir = ctk.StringVar(value=self.settings["output_dir"])
        self.auto_start = ctk.BooleanVar(value=self.settings["auto_start"])
        ctk.CTkLabel(side, text="输出位置", text_color="#cbd5e1").pack(anchor="w", padx=24)
        ctk.CTkSegmentedButton(side, values=["源图旁边", "统一文件夹"],
                               variable=self.output_mode, width=182).pack(padx=24, pady=(6, 8))
        ctk.CTkButton(side, text="选择统一文件夹", width=182, height=32,
                      fg_color="#1e293b", hover_color="#334155",
                      command=self.pick_output_dir).pack(padx=24)
        self.output_dir_label = ctk.CTkLabel(side, textvariable=self.output_dir,
                                             wraplength=178, justify="left",
                                             text_color="#64748b", font=("Microsoft YaHei UI", 9))
        self.output_dir_label.pack(anchor="w", padx=24, pady=(5, 14))
        ctk.CTkSwitch(side, text="拖入立即自动抠图", variable=self.auto_start,
                      text_color="#cbd5e1").pack(anchor="w", padx=24)
        self.provider_status = ctk.StringVar(value="加速状态：等待首次处理")
        ctk.CTkLabel(side, textvariable=self.provider_status, wraplength=180,
                     justify="left", text_color="#64748b",
                     font=("Microsoft YaHei UI", 9)).pack(side="bottom", anchor="w", padx=24, pady=22)

        main = ctk.CTkFrame(root, fg_color="#eef2f7", corner_radius=0)
        main.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(main, text="专业抠图工作台", text_color="#0f172a",
                     font=("Microsoft YaHei UI", 25, "bold")).pack(anchor="w", padx=28, pady=(24, 2))
        ctk.CTkLabel(main, text="默认输出透明 PNG · 批量处理 · 自动净化白边",
                     text_color="#64748b").pack(anchor="w", padx=29, pady=(0, 16))

        self.drop = ctk.CTkFrame(main, height=178, corner_radius=18, border_width=2,
                                 border_color="#3b82f6", fg_color="#eff6ff")
        self.drop.pack(fill="x", padx=28)
        self.drop.pack_propagate(False)
        drop_label = ctk.CTkLabel(self.drop, text="⇧\n将产品图或文件夹拖到这里\n也可以点击选择图片",
                                  text_color="#2563eb", font=("Microsoft YaHei UI", 16, "bold"))
        drop_label.pack(expand=True, fill="both")
        for widget in (self.drop, drop_label):
            widget.bind("<Button-1>", lambda _e: self.pick())
        self.drop_widgets = (self.root, main, self.drop, drop_label)
        for widget in self.drop_widgets:
            if DND_FILES:
                try:
                    widget.drop_target_register(DND_FILES)
                    widget.dnd_bind("<<Drop>>", self.on_drop)
                except Exception as exc:
                    self.root.after(0, lambda message=str(exc):
                                    self.status.set(f"拖放初始化失败：{message}"))

        content = ctk.CTkFrame(main, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=28, pady=16)
        left = ctk.CTkFrame(content, fg_color="white", corner_radius=16)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        right = ctk.CTkFrame(content, width=320, fg_color="white", corner_radius=16)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        list_head = ctk.CTkFrame(left, height=48, fg_color="transparent")
        list_head.pack(fill="x", padx=16, pady=(12, 0))
        self.file_count = ctk.StringVar(value="待处理文件  0")
        ctk.CTkLabel(list_head, textvariable=self.file_count,
                     font=("Microsoft YaHei UI", 14, "bold"), text_color="#0f172a").pack(side="left")
        ctk.CTkButton(list_head, text="清空", width=62, height=30, fg_color="#f1f5f9",
                      hover_color="#e2e8f0", text_color="#475569", command=self.clear_files).pack(side="right")
        ctk.CTkButton(list_head, text="移除", width=62, height=30, fg_color="#f1f5f9",
                      hover_color="#e2e8f0", text_color="#475569", command=self.remove_selected).pack(side="right", padx=8)
        self.listbox = __import__("tkinter").Listbox(left, bd=0, highlightthickness=0,
                                                     selectbackground="#dbeafe", selectforeground="#1d4ed8",
                                                     activestyle="none", font=("Microsoft YaHei UI", 11))
        self.listbox.pack(fill="both", expand=True, padx=16, pady=(6, 16))
        self.listbox.bind("<<ListboxSelect>>", self.show_selected)

        preview = ctk.CTkFrame(left, height=210, fg_color="#f8fafc", corner_radius=12)
        preview.pack(fill="x", padx=16, pady=(0, 16))
        preview.pack_propagate(False)
        preview_head = ctk.CTkFrame(preview, fg_color="transparent")
        preview_head.pack(fill="x", padx=14, pady=(8, 2))
        ctk.CTkLabel(preview_head, text="预览检查", font=("Microsoft YaHei UI", 13, "bold"),
                     text_color="#0f172a").pack(side="left")
        self.preview_bg = ctk.StringVar(value="透明")
        ctk.CTkSegmentedButton(preview_head, values=["透明", "白底", "黑底"],
                               width=150, height=26, variable=self.preview_bg,
                               command=lambda _v: self.render_result_preview()).pack(side="right")
        views = ctk.CTkFrame(preview, fg_color="transparent")
        views.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.before_preview = ctk.CTkLabel(views, text="选择文件查看原图", fg_color="#e2e8f0",
                                           corner_radius=10, text_color="#64748b")
        self.before_preview.pack(side="left", fill="both", expand=True, padx=(0, 5))
        self.after_preview = ctk.CTkLabel(views, text="完成后显示透明结果", fg_color="#e2e8f0",
                                          corner_radius=10, text_color="#64748b")
        self.after_preview.pack(side="right", fill="both", expand=True, padx=(5, 0))

        ctk.CTkLabel(right, text="边缘处理", font=("Microsoft YaHei UI", 15, "bold"),
                     text_color="#0f172a").pack(anchor="w", padx=18, pady=(16, 8))
        self.decon = ctk.IntVar(value=self.settings["decon"])
        self.shrink = ctk.IntVar(value=self.settings["shrink"])
        self.feather = ctk.DoubleVar(value=self.settings["feather"])
        self.preset = ctk.StringVar(value="产品图")
        ctk.CTkLabel(right, text="快速预设", text_color="#475569").pack(anchor="w", padx=18)
        ctk.CTkSegmentedButton(right, values=["产品图", "毛发", "透明材质", "硬边"],
                               variable=self.preset, command=self.apply_preset).pack(fill="x", padx=18, pady=(5, 8))
        self._slider(right, "去白边强度", self.decon, 0, 100)
        self._slider(right, "边缘内缩", self.shrink, 0, 3, 4)
        self._slider(right, "柔化边缘", self.feather, 0, 1.5, 16)
        ctk.CTkFrame(right, height=1, fg_color="#e2e8f0").pack(fill="x", padx=18, pady=(8, 10))
        ctk.CTkLabel(right, text="输出格式", font=("Microsoft YaHei UI", 14, "bold"),
                     text_color="#0f172a").pack(anchor="w", padx=18, pady=(0, 6))
        self.transparent = ctk.BooleanVar(value=self.settings["transparent"])
        self.white = ctk.BooleanVar(value=self.settings["white"])
        self.black = ctk.BooleanVar(value=self.settings["black"])
        for text, var in (("透明 PNG（默认）", self.transparent), ("白底 JPG（可选）", self.white),
                          ("黑底检查图", self.black)):
            ctk.CTkCheckBox(right, text=text, variable=var).pack(anchor="w", padx=18, pady=4)

        self.status = ctk.StringVar(value="等待图片")
        ctk.CTkLabel(right, textvariable=self.status, wraplength=270,
                     text_color="#475569").pack(anchor="w", padx=18, pady=(16, 8))
        self.progress = ctk.CTkProgressBar(right, width=274)
        self.progress.pack(padx=18)
        self.progress.set(0)
        self.start_btn = ctk.CTkButton(right, text="开始专业抠图", height=44,
                                       font=("Microsoft YaHei UI", 14, "bold"),
                                       command=self.start)
        self.start_btn.pack(side="bottom", padx=18, pady=18, fill="x")
        self.stop_btn = ctk.CTkButton(right, text="停止队列", height=36,
                                      fg_color="#fee2e2", hover_color="#fecaca",
                                      text_color="#b91c1c", state="disabled", command=self.stop)
        self.stop_btn.pack(side="bottom", padx=18, fill="x")
        self.open_btn = ctk.CTkButton(right, text="打开结果文件夹", height=34,
                                      fg_color="#f1f5f9", hover_color="#e2e8f0",
                                      text_color="#334155", state="disabled",
                                      command=self.open_output)
        self.open_btn.pack(side="bottom", padx=18, pady=(0, 8), fill="x")
        self.retry_btn = ctk.CTkButton(right, text="重试失败项", height=34,
                                       fg_color="#fff7ed", hover_color="#ffedd5",
                                       text_color="#c2410c", state="disabled",
                                       command=self.retry_failed)
        self.retry_btn.pack(side="bottom", padx=18, pady=(0, 8), fill="x")

    def _refresh_files(self):
        self.listbox.delete(0, "end")
        for p in self.files:
            self.listbox.insert("end", f"  {p.name}")
        self.file_count.set(f"待处理文件  {len(self.files)}")

    def remove_selected(self):
        selected = set(self.listbox.curselection())
        if selected and not self.running:
            self.files = [p for i, p in enumerate(self.files) if i not in selected]
            self._refresh_files()
            self.status.set(f"已加入 {len(self.files)} 张图片" if self.files else "等待图片")

    def clear_files(self):
        if not self.running:
            self.files.clear()
            self._refresh_files()
            self.progress.set(0)
            self.status.set("等待图片")

    def _slider(self, parent, text, var, low, high, steps=100):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=5)
        value = ctk.CTkLabel(row, text=str(var.get()), width=38, text_color="#2563eb")
        value.pack(side="right")
        ctk.CTkLabel(row, text=text, text_color="#475569").pack(side="left")
        slider = ctk.CTkSlider(parent, from_=low, to=high, number_of_steps=steps,
                               variable=var, command=lambda v: value.configure(text=f"{v:.1f}" if isinstance(var, ctk.DoubleVar) else str(int(v))))
        slider.pack(fill="x", padx=18, pady=(0, 6))
        var.trace_add("write", lambda *_: value.configure(
            text=f"{var.get():.1f}" if isinstance(var, ctk.DoubleVar) else str(int(var.get()))))

    def apply_preset(self, name):
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
        self.status.set(f"已应用{name}预设")

    def pick(self):
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(title="选择图片", filetypes=[("图片", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff")])
        self.add(paths)

    def pick_output_dir(self):
        from tkinter import filedialog
        selected = filedialog.askdirectory(title="选择统一输出文件夹",
                                            initialdir=self.output_dir.get() or None)
        if selected:
            self.output_dir.set(selected)
            self.output_mode.set("统一文件夹")
            self.save_settings()

    def on_drop(self, event):
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
        self.add(paths)
        if not self.files:
            self.status.set("没有识别到图片，请拖入 JPG、PNG、WEBP、BMP 或 TIFF")
        elif self.auto_start.get():
            self.status.set(f"已识别 {len(self.files)} 张，正在自动开始…")
            self.root.after(150, self.start)
        return "copy"

    def add(self, paths):
        existing = {str(p).lower() for p in self.files}
        found = []
        for raw in paths:
            p = Path(raw)
            if p.is_dir():
                found.extend(
                    x for x in p.rglob("*")
                    if x.suffix.lower() in EXTS
                    and not any(parent.name.endswith("_抠图") for parent in x.parents)
                    and not x.stem.endswith(("_透明", "_白底", "_黑底预览"))
                )
            elif p.suffix.lower() in EXTS:
                found.append(p)
        for p in found:
            if str(p).lower() not in existing:
                self.files.append(p)
                existing.add(str(p).lower())
        self._refresh_files()
        self.status.set(f"已加入 {len(self.files)} 张图片")

    def show_selected(self, _event=None):
        selected = self.listbox.curselection()
        if not selected:
            return
        path = self.files[selected[0]]
        try:
            with Image.open(path) as source:
                preview = self._preview_image(source.convert("RGBA"), checker=False)
            self.preview_images["before"] = ctk.CTkImage(preview, size=preview.size)
            self.before_preview.configure(image=self.preview_images["before"], text="")
        except Exception as exc:
            self.before_preview.configure(image=None, text=f"无法预览\n{exc}")

    @staticmethod
    def _preview_image(image, checker=True, box=(250, 150), background=None):
        image = image.copy()
        image.thumbnail(box, Image.Resampling.LANCZOS)
        if background == "白底":
            canvas = Image.new("RGBA", box, (255, 255, 255, 255))
        elif background == "黑底":
            canvas = Image.new("RGBA", box, (15, 23, 42, 255))
        else:
            canvas = Image.new("RGBA", box, (241, 245, 249, 255))
        if checker and background not in ("白底", "黑底"):
            from PIL import ImageDraw
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
        # Tk variables must only be read on the UI thread.  Capture a stable
        # job snapshot so a model/edge setting cannot change halfway through
        # a batch and the worker never calls Tcl from a background thread.
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

    def close(self):
        self.save_settings()
        self.root.destroy()

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
            try:
                item_started = time.perf_counter()
                self.events.put(("status", f"{index}/{total} 正在处理：{path.name}\n首次运行会下载模型，请稍候"))
                result = remove_background(path, job["model"], job["decon"],
                                           job["shrink"], job["feather"])
                outputs = save_outputs(result, path, job["transparent"],
                                       job["white"], job["black"], job["output_dir"])
                output_dirs.update(p.parent for p in outputs)
                thumb = result.copy()
                thumb.thumbnail((250, 150), Image.Resampling.LANCZOS)
                self.events.put(("preview", thumb))
                if not provider_sent:
                    try:
                        self.events.put(("provider", active_provider(job["model"])))
                    except Exception:
                        pass
                    provider_sent = True
            except Exception as exc:
                failed.append(f"{path.name}: {exc}")
                failed_paths.append(path)
            completed = index
            item_seconds = time.perf_counter() - item_started
            average = (time.perf_counter() - batch_started) / completed
            eta = max(0, total - completed) * average
            self.events.put(("status", f"{completed}/{total} 已完成 · 本张 {item_seconds:.1f} 秒 · 预计剩余 {eta:.0f} 秒"))
            self.events.put(("progress", index / total))
        elapsed = time.perf_counter() - batch_started
        self.events.put(("done", (completed, failed, failed_paths, output_dirs, cancelled, elapsed)))

    def _poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "status": self.status.set(data)
                elif kind == "progress": self.progress.set(data)
                elif kind == "preview":
                    self.last_result_thumb = data
                    self.render_result_preview()
                elif kind == "provider":
                    name = "NVIDIA CUDA 显卡" if data == "CUDAExecutionProvider" else "CPU"
                    self.provider_status.set(f"加速状态：{name}")
                elif kind == "done":
                    completed, failed, failed_paths, dirs, cancelled, elapsed = data
                    self.running = False
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    prefix = "已停止" if cancelled else "完成"
                    self.failed_files = failed_paths
                    self.retry_btn.configure(state="normal" if failed_paths else "disabled")
                    self.status.set(f"{prefix}：成功 {completed-len(failed)}，失败 {len(failed)} · 用时 {elapsed:.1f} 秒" + ("\n" + "\n".join(failed[:3]) if failed else ""))
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
