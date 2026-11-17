"""_checks/tests 自举：未安装/任意 cwd 也能直接跑（C5 staged 测试/CI 友好，1959）。

C5 从 PROJECT_ROOT 跑 staged 测试时 nexusos_gate 可能解析到全局 editable
（=main 树旧码）——此处把本包 src 插到 sys.path 首位，保证测的是本树代码。

2611111776 追加：Vault 根锚定——fixture 依赖 NEXUS_VAULT_ROOT，裸跑无 env 时
假红（1773 实测）。从 __file__ 向上推导（05-System+AGENTS.md 双锚），
setdefault 写入（显式 env 优先不覆盖）。
"""
import os
import sys
from pathlib import Path

_src = Path(__file__).resolve().parents[5]
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))


def _derive_vault_root() -> str:
    """从 conftest 所在目录向上找 Vault 根（05-System/ 与 AGENTS.md 双锚）。"""
    here = Path(__file__).resolve().parent
    for p in [here, *here.parents]:
        if (p / "05-System").is_dir() and (p / "AGENTS.md").is_file():
            return str(p)
    return ""


_vault = _derive_vault_root()
if _vault:
    os.environ.setdefault("NEXUS_VAULT_ROOT", _vault)
