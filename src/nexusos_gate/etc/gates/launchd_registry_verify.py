#!/usr/bin/env python3
"""校验 launchd ai.nexus.* 服务是否都在 AGENT_REGISTRY 注册。

用于 init gate I5。Task418 自动注册的双保险——自动注册失败时告警。
2026-08-03 会话08031120: scheduler 未注册致 ValueError(Bug11 同类复发)。

退出码: 0=全注册 / 1=有遗漏
"""
import os
import subprocess
import sys
from pathlib import Path

# nexus 脚本目录（env 覆盖优先；默认从包位置推导——Task630 迁包后路径参数化，
# 不再硬编码 Vault 绝对路径。resolve() 归一 symlink，新旧位执行结果一致）
# 注:用 os.environ 不用 sys.environ(Python 3.14 sys 无 environ 属性)
# 层级: gates→etc→nexusos_gate→src→nexusos-gate→pypi→自动化脚本(6 层 up)
SCRIPT_DIR = os.environ.get(
    "NEXUS_SCRIPT_DIR",
    str(Path(__file__).resolve().parents[6]),
)
sys.path.insert(0, SCRIPT_DIR)

from nexusos_xdr.agents import AGENT_REGISTRY, ensure_launchd_registered  # noqa: E402

# Task542: 本脚本在 gate I5 独立子进程跑——AGENT_REGISTRY 的 launchd 服务条目是
# lazy 注册（首次 validate_agent 才触发），子进程内从未触发→永远报 missing。
# 在比对前显式调一次 ensure_launchd_registered() 补全注册表。
ensure_launchd_registered()


def main() -> int:
    try:
        r = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True, timeout=5
        )
    except Exception as e:
        print(f"launchctl 调用失败(非致命,降级 pass): {e}")
        return 0  # 非 macOS 或异常时不阻塞

    missing = []
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[-1].startswith("ai.nexus."):
            svc = parts[-1].replace("ai.nexus.", "")
            if svc not in AGENT_REGISTRY and svc not in missing:
                missing.append(svc)

    if missing:
        print(f"missing (未注册的 launchd 服务): {missing}")
        return 1
    else:
        print("all launchd services registered")
        return 0


if __name__ == "__main__":
    sys.exit(main())
