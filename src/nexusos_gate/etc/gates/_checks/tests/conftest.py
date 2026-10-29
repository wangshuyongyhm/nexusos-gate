"""_checks/tests 自举：未安装/任意 cwd 也能直接跑（C5 staged 测试/CI 友好，1959）。

C5 从 PROJECT_ROOT 跑 staged 测试时 nexusos_gate 可能解析到全局 editable
（=main 树旧码）——此处把本包 src 插到 sys.path 首位，保证测的是本树代码。
"""
import sys
from pathlib import Path

_src = Path(__file__).resolve().parents[5]
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))
