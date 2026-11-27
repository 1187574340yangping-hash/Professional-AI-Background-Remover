from __future__ import annotations

from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageTk


FONT = "Microsoft YaHei UI"
BRAND = "#2563EB"
INK = "#0F172A"
SUB = "#64748B"


class MagicWandEditor:
    """Small, model-free connected-colour selector for manual cutout repair."""

    def __init__(self, master, source_path, on_saved=None):
        self.source_path = Path(source_path)
        self.on_saved = on_saved
        with Image.open(self.source_path) as opened:
            self.original = ImageOps.exif_transpose(opened).convert("RGBA")
        self.selection = Image.new("L", self.original.size, 0)  # white = remove
        self.history = []
        self.mode = ctk.StringVar(value="移除区域")
        self.tolerance = ctk.IntVar(value=28)
        self.overlay = ctk.BooleanVar(value=True)

        self.top = ctk.CTkToplevel(master)
        self.top.title(f"魔法棒精修 · {self.source_path.name}")
        self.top.geometry("1180x820")
        self.top.minsize(900, 650)
        self.top.configure(fg_color="#F1F5F9")
        self.top.lift()

        self.toolbar = ctk.CTkFrame(self.top, fg_color="white", corner_radius=0)
        self.toolbar.pack(fill="x")
        ctk.CTkLabel(self.toolbar, text="魔法棒精修", text_color=INK,
                     font=(FONT, 18, "bold")).pack(side="left", padx=(20, 12), pady=14)
        ctk.CTkSegmentedButton(self.toolbar, values=["移除区域", "恢复区域"],
                               variable=self.mode, width=190,
                               selected_color=BRAND).pack(side="left", padx=8)
        ctk.CTkLabel(self.toolbar, text="颜色容差", text_color=SUB,
                     font=(FONT, 11)).pack(side="left", padx=(18, 4))
        self.slider = ctk.CTkSlider(self.toolbar, from_=0, to=100, number_of_steps=100,
                                    variable=self.tolerance, width=150,
                                    command=lambda v: self.tol_label.configure(text=str(int(v))))
        self.slider.pack(side="left")
        self.tol_label = ctk.CTkLabel(self.toolbar, text=str(self.tolerance.get()), width=34,
                                      text_color=BRAND, font=(FONT, 11, "bold"))
        self.tol_label.pack(side="left")
        ctk.CTkCheckBox(self.toolbar, text="红色选区预览", variable=self.overlay,
                        command=self.redraw, font=(FONT, 11)).pack(side="left", padx=12)

        self.canvas = ctk.CTkCanvas(self.top, bg="#CBD5E1", highlightthickness=0,
                                    cursor="crosshair")
        self.canvas.pack(fill="both", expand=True, padx=18, pady=(16, 8))
        self.canvas.bind("<Button-1>", self.click)
        self.canvas.bind("<Configure>", lambda _e: self.redraw())

        foot = ctk.CTkFrame(self.top, fg_color="white", corner_radius=0)
        foot.pack(fill="x")
        self.status = ctk.StringVar(value="点击背景或要删除的颜色区域；容差越大，选中的相近颜色越多")
        ctk.CTkLabel(foot, textvariable=self.status, text_color=SUB,
                     font=(FONT, 11)).pack(side="left", padx=20, pady=13)
        ctk.CTkButton(foot, text="撤销", width=76, fg_color="#E2E8F0",
                      hover_color="#CBD5E1", text_color=INK,
                      command=self.undo).pack(side="right", padx=4)
        ctk.CTkButton(foot, text="清空选区", width=88, fg_color="#E2E8F0",
                      hover_color="#CBD5E1", text_color=INK,
                      command=self.clear).pack(side="right", padx=4)
        ctk.CTkButton(foot, text="反选", width=70, fg_color="#E2E8F0",
                      hover_color="#CBD5E1", text_color=INK,
                      command=self.invert).pack(side="right", padx=4)
        ctk.CTkButton(foot, text="导出透明 PNG + 蒙版", width=180,
                      fg_color=BRAND, command=self.export).pack(side="right", padx=(8, 20))
        self.top.after(80, self.redraw)

    def _display_geometry(self):
        cw = max(300, self.canvas.winfo_width())
        ch = max(300, self.canvas.winfo_height())
        scale = min((cw - 32) / self.original.width, (ch - 32) / self.original.height, 1.0)
        w, h = max(1, int(self.original.width * scale)), max(1, int(self.original.height * scale))
        return scale, w, h, (cw - w) // 2, (ch - h) // 2

    def redraw(self):
        if not self.canvas.winfo_exists():
            return
        scale, w, h, ox, oy = self._display_geometry()
        shown = self.original.copy()
        if self.overlay.get():
            red = Image.new("RGBA", shown.size, (239, 68, 68, 150))
            shown = Image.composite(red, shown, self.selection)
        shown.thumbnail((w, h), Image.Resampling.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(shown)
        self.canvas.delete("all")
        self.canvas.create_image(ox, oy, anchor="nw", image=self.tk_image)
        self.canvas.create_rectangle(ox, oy, ox + w, oy + h, outline="#94A3B8")

    def click(self, event):
        scale, w, h, ox, oy = self._display_geometry()
        if not (ox <= event.x < ox + w and oy <= event.y < oy + h):
            return
        x = min(self.original.width - 1, max(0, int((event.x - ox) / scale)))
        y = min(self.original.height - 1, max(0, int((event.y - oy) / scale)))
        self.history.append(self.selection.copy())
        if len(self.history) > 15:
            self.history.pop(0)

        # Pillow performs the connected flood fill in native code and remains
        # responsive on large ecommerce images without another dependency.
        work = self.original.convert("RGB")
        marker = (1, 2, 3)
        ImageDraw.floodfill(work, (x, y), marker,
                            thresh=int(self.tolerance.get()))
        r, g, b = work.split()
        region = Image.eval(r, lambda v: 255 if v == marker[0] else 0)
        # Exclude accidental matches by checking all marker channels.
        region = Image.composite(region, Image.new("L", region.size, 0),
                                 Image.eval(g, lambda v: 255 if v == marker[1] else 0))
        region = Image.composite(region, Image.new("L", region.size, 0),
                                 Image.eval(b, lambda v: 255 if v == marker[2] else 0))
        if self.mode.get() == "移除区域":
            # selection 中白色=待移除；新增选区用取亮合并（并集）。
            self.selection = ImageChops.lighter(self.selection, region)
        else:
            # 恢复区域：在选区中扣掉该颜色区域。
            self.selection = ImageChops.darker(self.selection, ImageOps.invert(region))
        self.status.set(f"已选择坐标 {x}, {y} · 容差 {self.tolerance.get()} · 可继续点击追加区域")
        self.redraw()

    def undo(self):
        if self.history:
            self.selection = self.history.pop()
            self.redraw()

    def clear(self):
        self.history.append(self.selection.copy())
        self.selection = Image.new("L", self.original.size, 0)
        self.redraw()

    def invert(self):
        self.history.append(self.selection.copy())
        self.selection = ImageOps.invert(self.selection)
        self.redraw()

    def export(self):
        out_dir = self.source_path.parent / f"{self.source_path.stem}_魔法棒"
        out_dir.mkdir(exist_ok=True)
        alpha = ImageChops.darker(self.original.getchannel("A"), ImageOps.invert(self.selection))
        result = self.original.copy()
        result.putalpha(alpha)
        png_path = out_dir / f"{self.source_path.stem}_透明.png"
        mask_path = out_dir / f"{self.source_path.stem}_黑白蒙版.png"
        result.save(png_path, "PNG", optimize=True)
        ImageOps.invert(self.selection).save(mask_path, "PNG", optimize=True)
        self.status.set(f"已导出：{out_dir}")
        if self.on_saved:
            self.on_saved(png_path, out_dir)
        messagebox.showinfo("魔法棒精修", f"已导出透明 PNG 和黑白蒙版：\n{out_dir}", parent=self.top)

