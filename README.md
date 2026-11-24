# 炮王专业抠图

面向电商产品图的 Windows 本地 AI 批量抠图工具。默认生成透明 PNG，并在模型输出后进行边缘颜色净化、蒙版内缩和轻柔化，减少白底商品图放到深色背景时出现的白边。

## 主要功能

- 图片或文件夹拖放、批量处理
- 默认输出透明 PNG，可选白底 JPG 和黑底边缘检查图
- BiRefNet General、General Lite、Portrait 三种模型
- 去白边强度、边缘内缩、边缘柔化
- 自动记住输出与边缘设置
- 原图/透明结果双预览与棋盘格边缘检查
- 产品图、毛发、透明材质、硬边四种边缘预设
- 可停止批量队列，当前图片仍会安全保存
- 可选拖入后自动开始
- 输出到源图旁边的“原文件名_抠图”文件夹，或指定统一输出文件夹
- 统一输出时自动保护同名文件，避免静默覆盖
- 自动跳过既有“_抠图”目录和生成结果，避免重复套娃处理
- 显示单张耗时与预计剩余时间，失败项可一键重新载入
- NVIDIA CUDA 加速，缺少 CUDA 时自动使用 CPU

## Windows 安装

建议使用 Python 3.11–3.13：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pythonw.exe app.py
```

CUDA 13 显卡加速组件：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-gpu-cu13.txt
```

## 模型下载

软件会在首次选择模型时自动下载，无需手工放置。官方文件地址：

- [BiRefNet General（默认，约 930MB）](https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-epoch_244.onnx)
- [BiRefNet General Lite](https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx)
- [BiRefNet Portrait](https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-portrait-epoch_150.onnx)

默认模型缓存位置：

```text
C:\Users\你的用户名\.rembg\models\
```

模型文件没有提交到本仓库，避免 GitHub 文件大小限制。下载完成后可以离线使用。

## 项目结构

- `app.py`：桌面界面、拖放和批量任务
- `engine.py`：推理、透明边缘净化与输出
- `assets/`：应用图标

## 开源组件与模型

- [rembg](https://github.com/danielgatis/rembg) — MIT
- [BiRefNet](https://github.com/ZhengPeng7/BiRefNet) — MIT；模型权重以其发布说明为准
- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) — MIT
- [tkinterdnd2](https://github.com/pmgagne/tkinterdnd2) — MIT

本仓库不重新分发 BiRefNet 模型权重。
