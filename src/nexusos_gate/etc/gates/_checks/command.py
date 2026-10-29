"""检查类型: command — 跑外部命令,检查退出码。
通用插件,后续场景(I3 脚本完整性/C5 测试通过)复用。
"""
import subprocess


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params:
      cmd: 命令字符串(shell=True)
      expect_rc: 期望退出码(默认 0)
      timeout: 超时秒(默认 30)
      cwd: 工作目录(可选)
    返回: (passed, detail)
    """
    cmd = params.get("cmd", "")
    expect_rc = params.get("expect_rc", 0)
    timeout = params.get("timeout", 30)
    cwd = params.get("cwd")
    if not cmd:
        return False, "未提供 cmd 参数"
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd,
        )
        passed = r.returncode == expect_rc
        # 截取 stderr 前 200 字符(诊断用)
        err_snippet = (r.stderr or "").strip()[:200]
        if passed:
            return True, f"rc={r.returncode}(期望 {expect_rc})"
        else:
            detail = f"rc={r.returncode}(期望 {expect_rc})"
            if err_snippet:
                detail += f" stderr: {err_snippet}"
            return False, detail
    except subprocess.TimeoutExpired:
        return False, f"超时({timeout}s): {cmd}"
    except Exception as e:
        return False, f"执行异常: {type(e).__name__}: {e}"
