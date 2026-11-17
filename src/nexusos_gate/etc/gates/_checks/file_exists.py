"""检查类型: file_exists — 文件/目录是否存在(支持 glob)。
通用插件,后续场景(P1 会话日志/D1 任务书等)复用。

Task535 修复4(P1-7) 锚定统一: 相对路径补 Vault 根（复刻 files_exist.py 的
_resolve_path 兜底）——原只 expanduser，CWD≠vault 时 dispatch.yaml/persist.yaml
的相对路径必误判"不存在"。
"""

# Task1597 参数化：vault 根经 env/仓内推导解析，不再硬编码本机路径
try:
    from _vault_root import vault_root
except ImportError:  # 包模式加载（gate_engine 以子包形态 import 时）
    from ._vault_root import vault_root

import glob as globmod
import os
from pathlib import Path

_VAULT_ROOT = vault_root()


def _resolve_path(fpath):
    """补全相对路径为绝对路径（与 files_exist.py 同模式）。

    绝对路径 / ~ 开头：原样返回（expanduser 处理 ~）。
    相对路径：统一补 Vault 根（gate 检查的路径语义都相对 vault）。
    """
    if os.path.isabs(fpath) or fpath.startswith("~"):
        return Path(fpath).expanduser()
    return Path(_VAULT_ROOT) / fpath


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params:
      path: 单个路径
      path_glob: glob 模式(如 "03-Daily/{date}/*会话*.md")
    返回: (passed, detail)
    """
    pattern = params.get("path_glob") or params.get("path", "")
    if not pattern:
        return False, "未提供 path/path_glob 参数"
    pattern = str(_resolve_path(pattern))
    if any(c in pattern for c in "*?["):
        # glob 模式
        matches = globmod.glob(pattern)
        passed = len(matches) > 0
        detail = f"匹配 {len(matches)} 个: {matches[:3]}" if matches else f"无匹配: {pattern}"
    else:
        # 单路径
        exists = Path(pattern).exists()
        passed = exists
        detail = f"存在: {pattern}" if exists else f"不存在: {pattern}"
    return passed, detail
