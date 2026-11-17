"""检查类型: grep_in_diff — 在 git diff 内容里 grep 模式。
C2(time.sleep 排除 test)/ C3(except: pass)用。
默认行为:命中 = 不通过(发现反模式)。require_pattern 模式:需 pattern 与
require_pattern 同 hunk 命中才算不通过(用于 except ... : pass)。
"""
import fnmatch
import re

try:
    import _gitcmd
except ImportError:
    from . import _gitcmd


def _git_diff(cwd: str) -> tuple:
    """取 diff 内容。返回 (rc, stdout, stderr)。
    Task1552 S2: 收口 _gitcmd（quotePath 统一）。"""
    return _gitcmd.run_git(["diff", "--cached"], cwd)


def _split_hunks(diff_text: str):
    """把 diff 切成 [(file, [added_lines])]。

    只取 + 开头(新增行),去掉 +++ 文件头。
    返回 {file: [新增行内容(不含 +)]}。
    """
    out = {}
    cur_file = None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            # b/path 或 b/"path with space"（Task1552 S1: 解析收口 _gitcmd.diff_b_path）
            cur_file = _gitcmd.diff_b_path(line[4:])
            out.setdefault(cur_file, [])
        elif line.startswith("+++" ):
            cur_file = None
        elif line.startswith("+") and not line.startswith("+++"):
            if cur_file is not None:
                out[cur_file].append(line[1:])
    return out


def _is_excluded(filepath: str, exclude_files: list) -> bool:
    """文件路径是否匹配任一 exclude glob。"""
    if not exclude_files:
        return False
    base = filepath.rsplit("/", 1)[-1]
    for pat in exclude_files:
        pat = pat.strip()
        if not pat:
            continue
        if fnmatch.fnmatch(filepath, pat) or fnmatch.fnmatch(base, pat):
            return True
        if pat.endswith("/") and (filepath.startswith(pat) or ("/" + pat) in filepath):
            return True
    return False


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params:
      pattern: 要 grep 的正则(命中=反模式)
      exclude_files: 排除文件 glob 列表(如 ["*test*", "tests/*"])
      require_pattern: 可选,需 pattern 与 require_pattern 同 hunk 同行附近命中
                       才算反模式(用于 except: pass 模式)
      allow_pattern: 可选,行内注解豁免(Task1566)。命中行同时匹配
                       allow_pattern 且捕获组1(理由)非空时该行豁免;
                       理由为空(如 `# c2-allow:`)仍判反模式。
      project_root: git 仓库根
    返回: (passed, detail)  — passed=True 表示未发现反模式
    """
    project_root = params.get("project_root") or context.get("project_root") or "."
    if isinstance(project_root, str) and "{" in project_root:
        project_root = context.get("project_root", ".")

    pattern = params.get("pattern", "")
    require_pattern = params.get("require_pattern")
    exclude_files = params.get("exclude_files") or []

    if not pattern:
        return True, "未声明 pattern,跳过"

    rc, diff, err = _git_diff(project_root)
    if rc == 128 and "not a git repository" in (err or "").lower():
        return True, "非 git 仓库,跳过"
    if rc not in (0, 128):
        # 拿不到 diff,偏向 WARN
        return True, f"git diff 失败(rc={rc}),跳过"
    if not diff.strip():
        return True, "无 diff 内容"

    try:
        pat_re = re.compile(pattern)
    except re.error as e:
        return False, f"pattern 编译失败: {pattern} ({e})"

    require_re = None
    if require_pattern:
        try:
            require_re = re.compile(require_pattern)
        except re.error as e:
            return False, f"require_pattern 编译失败: {e}"

    allow_re = None
    allow_pattern = params.get("allow_pattern")
    if allow_pattern:
        try:
            allow_re = re.compile(allow_pattern)
        except re.error as e:
            return False, f"allow_pattern 编译失败: {e}"

    hunks = _split_hunks(diff)

    hits = []
    exempted = 0
    for fname, added in hunks.items():
        if _is_excluded(fname, exclude_files):
            continue
        for line in added:
            if pat_re.search(line):
                if allow_re is not None:
                    # 行内注解豁免(Task1566): 注解命中且理由(捕获组1)非空才豁免
                    m = allow_re.search(line)
                    if m:
                        reason = ""
                        if m.groups():
                            reason = (m.group(1) or "").strip()
                        else:
                            reason = "1"  # 无捕获组时注解命中即豁免
                        if reason:
                            exempted += 1
                            continue
                if require_re is not None:
                    # require 模式:此 hunk 内需有 require_pattern 命中
                    if not any(require_re.search(l) for l in added):
                        continue
                hits.append((fname, line.strip()))

    suffix = f"(另有 {exempted} 处行内注解豁免)" if exempted else ""
    if hits:
        sample = "; ".join(f"{f}: {l[:60]}" for f, l in hits[:3])
        return False, f"发现 {len(hits)} 处反模式 /{pattern}/: {sample}{suffix}"
    return True, f"未发现 /{pattern}/ 反模式(扫描 {len(hunks)} 个文件){suffix}"
