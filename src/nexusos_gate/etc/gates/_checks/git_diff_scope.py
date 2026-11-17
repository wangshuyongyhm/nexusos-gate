"""检查类型: git_diff_scope — 检查本次改动是否都在 task_scope 允许的目录内。
C1 用。设计 §9.1。设计原则:不确定时偏向 WARN(不卡合法工作)。
"""
import fnmatch
from pathlib import Path

try:
    import _gitcmd
except ImportError:
    from . import _gitcmd


def _coerce_list(value, context_key: str, context: dict) -> list:
    """规整成 list[str]。复用 readme_synced 的思路。"""
    import ast
    if value is None:
        v = context.get(context_key) or []
    else:
        v = value
    if isinstance(v, list):
        return [str(x) for x in v if x]
    if isinstance(v, str):
        s = v.strip()
        if not s or "{" in s:
            # 占位符未解析 → 退回 context
            cv = context.get(context_key) or []
            return [str(x) for x in cv if x] if isinstance(cv, list) else []
        if s.startswith("[") and s.endswith("]"):
            try:
                p = ast.literal_eval(s)
                if isinstance(p, list):
                    return [str(x) for x in p if x]
            except Exception:
                pass
            inner = s.strip("[]").strip()
            if not inner:
                return []
            return [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
        return [s]
    return [str(v)] if v else []


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params:
      task_scope: 允许改动的目录/glob 列表(可空,空=不限)
      project_root: git 仓库根目录(可空=当前目录)
    返回: (passed, detail)
    """
    project_root = params.get("project_root") or context.get("project_root") or "."
    if isinstance(project_root, str) and "{" in project_root:
        project_root = context.get("project_root", ".")

    scope = _coerce_list(params.get("task_scope"), "task_scope", context)

    # task_scope 空 → 不做范围限制(合规,通过)
    if not scope:
        return True, "未声明 task_scope,跳过范围检查(任务允许任意改动)"

    # 拿 staged 改动文件名(--name-only)
    # Task531 B7: --cached（只看 staged，和 commit 内容一致）——原 HEAD 含 unstaged
    # Task1552 S2: git 调用收口 _gitcmd（quotePath 统一，中文路径不再误拦）
    rc, out, err = _gitcmd.run_git(["diff", "--name-only", "--cached"], project_root)
    if rc == 128 and "not a git repository" in (err + out).lower():
        # 不是 git 仓库 → 没法检查,偏向 WARN 不卡
        return True, f"非 git 仓库({project_root}),跳过范围检查"
    if rc != 0 and rc != 128:
        # 其他错误 → 不卡
        return True, f"git diff 失败(rc={rc}, {err[:80]}),跳过范围检查"

    # rc=128 也可能是 HEAD 不存在(全新仓库)→ 用 status
    if rc == 128:
        rc2, out2, err2 = _gitcmd.run_git(
            ["status", "--porcelain", "--untracked-files=no"], project_root
        )
        if rc2 != 0:
            return True, f"git status 失败,跳过范围检查"
        files = [line[3:].strip() for line in out2.splitlines() if line.strip()]
    else:
        files = [line.strip() for line in out.splitlines() if line.strip()]

    if not files:
        return True, "无改动文件"

    # 检查每个文件是否落在 scope 内
    out_of_scope = []
    for f in files:
        if _file_in_scope(f, scope):
            continue
        out_of_scope.append(f)

    if out_of_scope:
        return False, (
            f"{len(out_of_scope)} 个文件超出 task_scope={scope}: "
            + ", ".join(out_of_scope[:5])
        )
    return True, f"{len(files)} 个改动文件均在 task_scope 内"


def _file_in_scope(filepath: str, scope: list) -> bool:
    """文件路径是否在 scope(目录前缀或 glob)内。"""
    for pat in scope:
        pat = pat.strip()
        if not pat:
            continue
        # 目录前缀:foo/bar/ 或 foo/bar
        if filepath.startswith(pat.rstrip("/") + "/") or filepath == pat:
            return True
        # glob:foo/*.py 或 **/test/**
        if fnmatch.fnmatch(filepath, pat):
            return True
        if "**/" + pat in filepath or filepath.endswith("/" + pat):
            return True
    return False
