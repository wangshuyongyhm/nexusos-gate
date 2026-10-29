#!/usr/bin/env python3
"""_vault_root — gate 插件的 vault 根参数化助手（Task1597 顺手项）。

为什么存在：此前 6+ 处插件把 vault 根硬编码成本机绝对路径
作缺省——换机器/开源用户拿到包后这些路径指向别人的盘，检查要么静默
跑错目录要么报出莫名路径。参数化铁律（PARAMETERIZATION-GUIDE）：env
优先，仓内可相对推导（沿 parents 找含 05-System 的目录=vault 根），
仓外（wheel 装到陌生环境）返回空串让调用方自然报"文件不存在"，
而不是指向一台不存在的机器。

插件加载形态兼容（同 _gitcmd/_vaultlink 先例）：
    try:    import _vault_root
    except ImportError: from . import _vault_root
"""
import os
from pathlib import Path

from nexusos_common import auto_scripts_dir


def vault_root() -> str:
    """vault 根解析：NEXUS_ROOT env > 哨兵推导（nexusos-common 单源，1957）。

    空串不是错误值——下游 file_exists 等检查拿它拼路径会得到不存在的
    路径，按原逻辑报「文件不存在」，这比指向别人机器的假路径诚实。
    """
    env = os.environ.get("NEXUS_ROOT")
    if env:
        return env
    auto_dir = auto_scripts_dir(Path(__file__))
    return str(auto_dir.parents[1]) if auto_dir is not None else ""
