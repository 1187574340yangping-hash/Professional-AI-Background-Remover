from __future__ import annotations

import json
import queue
import subprocess
import threading
import ctypes
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageTk
from engine import remove_background, save_outputs

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    DND_FILES = None
    TkinterDnD = None


APP = "炮王专业抠图"
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


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
        self.root.geometry("1180x790")
        self.root.minsize(940, 650)
        self.files = []
        self.running = False
        self.events = queue.Queue()
        self.preview_photo = None
        self.settings_path = Path(__file__).with_name("settings.json")
        self.settings = self._load_settings()
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._poll)

    def _load_settings(self):
        defaults = {
            "model": "birefnet-general", "decon": 80, "shrink": 1,
            "feather": 0.4, "transparent": True,
            "white": False, "black": False,
        }
        try:
            saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
            defaults.update({key: saved[key] for key in defaults if key in saved})
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
                     justify="left", text_color="#94a3b8").pack(anchor="w", padx=24)

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
            if DND_FILES:
                try:
                    widget.drop_target_register(DND_FILES)
                    widget.dnd_bind("<<Drop>>", self.on_drop)
                except Exception:
                    pass

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

        ctk.CTkLabel(right, text="边缘处理", font=("Microsoft YaHei UI", 15, "bold"),
                     text_color="#0f172a").pack(anchor="w", padx=18, pady=(16, 8))
        self.decon = ctk.IntVar(value=self.settings["decon"])
        self.shrink = ctk.IntVar(value=self.settings["shrink"])
        self.feather = ctk.DoubleVar(value=self.settings["feather"])
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

    def pick(self):
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(title="选择图片", filetypes=[("图片", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff")])
        self.add(paths)

    def on_drop(self, event):
        self.add(self.root.tk.splitlist(event.data))
        return "copy"

    def add(self, paths):
        existing = {str(p).lower() for p in self.files}
        found = []
        for raw in paths:
            p = Path(raw)
            if p.is_dir():
                found.extend(x for x in p.rglob("*") if x.suffix.lower() in EXTS)
            elif p.suffix.lower() in EXTS:
                found.append(p)
        for p in found:
            if str(p).lower() not in existing:
                self.files.append(p)
                existing.add(str(p).lower())
        self._refresh_files()
        self.status.set(f"已加入 {len(self.files)} 张图片")

    def show_selected(self, _event=None):
        pass

    def start(self):
        if self.running or not self.files:
            self.status.set("请先拖入图片" if not self.files else "正在处理")
            return
        if not any((self.transparent.get(), self.white.get(), self.black.get())):
            self.status.set("请至少选择一种输出格式")
            return
        self.save_settings()
        self.running = True
        self.start_btn.configure(state="disabled")
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
        }
        threading.Thread(target=self.worker, args=(job,), daemon=True).start()

    def save_settings(self):
        values = {
            "model": self.model.get(), "decon": self.decon.get(),
            "shrink": self.shrink.get(), "feather": self.feather.get(),
            "transparent": self.transparent.get(), "white": self.white.get(),
            "black": self.black.get(),
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
        for index, path in enumerate(files, 1):
            try:
                self.events.put(("status", f"{index}/{total} 正在处理：{path.name}\n首次运行会下载模型，请稍候"))
                result = remove_background(path, job["model"], job["decon"],
                                           job["shrink"], job["feather"])
                outputs = save_outputs(result, path, job["transparent"],
                                       job["white"], job["black"])
                output_dirs.update(p.parent for p in outputs)
            except Exception as exc:
                failed.append(f"{path.name}: {exc}")
            self.events.put(("progress", index / total))
        self.events.put(("done", (total, failed, output_dirs)))

    def _poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "status": self.status.set(data)
                elif kind == "progress": self.progress.set(data)
                elif kind == "done":
                    total, failed, dirs = data
                    self.running = False
                    self.start_btn.configure(state="normal")
                    self.status.set(f"完成：成功 {total-len(failed)}，失败 {len(failed)}" + ("\n" + "\n".join(failed[:3]) if failed else ""))
                    if dirs:
                        subprocess.Popen(["explorer", str(next(iter(dirs)))])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
