# 第三方组件

Windows 便携包使用 Qt 6.9.3、Qt for Python（PySide6 Essentials 6.9.3）和 Shiboken 6.9.3。均通过共享库动态加载，按 GNU LGPL v3 的条款使用。随附 [LGPL v3](LGPL-3.0-only.txt) 和 [GPL v3](GPL-3.0-only.txt) 文本。

可在 `_internal\PySide6` 和 `_internal\shiboken6` 中替换 ABI 兼容的 Qt DLL、Qt 插件及对应的 Python 扩展模块后重新运行 EXE。许可允许为调试这些库的替换或修改开展逆向工程。上游提供这些组件的对应源码：

- [Qt 6.9.3 完整源码](https://download.qt.io/archive/qt/6.9/6.9.3/single/)
- [Qt for Python 6.9.3 源码（含 PySide6 和 Shiboken）](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.9.3-src/)
- [Qt for Python 第三方许可说明](https://doc.qt.io/qtforpython-6/licenses.html)

界面与图表使用 Adobe [思源宋体 2.003](https://github.com/adobe-fonts/source-han-serif/tree/2.003R/OTF/SimplifiedChinese)，随附 [SIL Open Font License 1.1](OFL-Source-Han-Serif.txt)。运行时也包含 Python、Matplotlib、NumPy、Pillow、PyInstaller 引导程序及其依赖。便携包 `third-party/runtime-licenses` 附带运行时声明。

Python 许可文件包含随包提供的 libffi 许可。程序使用 Windows 系统中的 [Microsoft 官方 Visual C++ v14 x64 运行库](https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist)。
