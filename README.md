# 光机镜头畸变评估工具 V6

导入 Zemax OpticStudio 的 F‑Tan(Theta) 畸变 TXT，按波长查看原始曲线、拟合曲线、最大畸变、拐点数和拟合偏差。可以叠加多组数据，导出 PNG 或 SVG。

## 下载和运行

从 [GitHub Releases](https://github.com/2718056795-tech/optical-distortion-evaluator/releases/latest) 下载 Windows x64 ZIP，完整解压，双击 `光机镜头畸变评估工具V6.exe`。便携包自带 Python 和 Qt，运行时请保持 EXE 与 `_internal` 文件夹在同一目录。

运行依赖系统的 Microsoft Visual C++ v14 x64 运行库。系统缺少该组件时，从 [Microsoft 官网](https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist) 安装 x64 版本。

1. 点击 **载入示例** 体验 440、460、480 nm 的合成数据。
2. 在 Zemax 的 **分析 → 像差分析 → 场曲/畸变 → 文本** 选择 F‑Tan(Theta) 畸变，导出 TXT。可用 **选择文件** 或 **粘贴文本** 导入。
3. 在数据表中选择波长。单击数据行查看该行指标，单击空白处查看当前可见数据的各项最差值。图例控制曲线显隐，**视图 → 全部显示** 可恢复全部数据和曲线。

对 Zemax 角度表，第一列提供视场角，最后一列提供畸变，拟合使用 `r = tan(θ)`。导入时保留单位声明、波长和列标题。程序能识别畸变百分数和小数比例，发现单位缺失或标注冲突时会请你确认。波长可写为 `440 nm` 或 `0.44 μm`，界面统一显示为 nm。

## 源码运行和构建

以下命令在 Windows x64 和 Python 3.9.13 下验证。PySide6 Essentials 6.9.3、NumPy 和 Matplotlib 的版本见依赖文件。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe .\src\qt_app.py
.\.venv\Scripts\python.exe -m unittest discover -s .\src -p 'test_*.py' -v
.\src\build.ps1 -Python (Resolve-Path .\.venv\Scripts\python.exe)
```

构建结果位于 `dist\optical-distortion-evaluator-v6`。

## 第三方组件

便携包使用 Qt、PySide6 Essentials 和 Shiboken 6.9.3。许可证、对应源码和共享库替换方式见 [第三方组件说明](third-party/README.md)。
