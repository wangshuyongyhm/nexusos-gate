"""_gitcmd.py — git 调用共享层（Task1552 S2，1545 审查发现的 quotePath 家族缺陷收口）。

不做插件（下划线前缀被 gate_engine 加载器跳过，同 _vaultlink 先例），纯函数库：
  run_git(args, cwd, timeout) -> (rc, stdout, stderr)
  diff_b_path(plus_line) -> str   — 解析 diff `+++ b/...` 头的单一真源

单一真源约定：凡 gate 检查器调 git diff 输出做路径解析，必须经本模块——
`-c core.quotePath=false` 统一在此注入（1545 实证：默认转义让中文路径带
引号+八进制，grep 后缀/前缀匹配全失配——C1 误拦 REJECT、C14/C15 漏检）。
"""
import subprocess

# 超时默认与各插件原值一致（15-20s 量级）
_DEFAULT_TIMEOUT = 20


def run_git(args: list, cwd=None, timeout: int = _DEFAULT_TIMEOUT) -> tuple:
    """跑 git（恒带 -c core.quotePath=false，拿 UTF-8 原始路径）。

    返回 (rc, stdout, stderr)。异常映射与各插件旧私有实现一致：
    TimeoutExpired→124 / FileNotFoundError→127 / 其他→1。
    """
    cmd = ["git", "-c", "core.quotePath=false"] + list(args)
    try:
        r = subprocess.run(
            cmd,
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "git timeout"
    except FileNotFoundError:
        return 127, "", "git not found"
    except Exception as e:
        return 1, "", f"{type(e).__name__}: {e}"


def diff_b_path(plus_line: str) -> str:
    """解析 diff 文件头（`+++ b/path` 或 `+++ "b/path"`）→ 仓库相对路径。

    S1 根修（1545）：原 comment_out_detection 用 lstrip("b/")（字符集语义）——
    引号形态剥不动致 b/ 前缀残留、b 开头文件名被啃。git 的引号包裹整个 "b/path"
    （含 b/），故顺序必须是：先剥包裹引号，再 removeprefix("b/")——1545 复审
    实证反序时引号形态的 b/ 残留（S1 同款复发，1552 单测首跑抓回）。
    /dev/null 返回原样（调用方自判）。
    """
    s = plus_line.strip()
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    return s.removeprefix("b/")
