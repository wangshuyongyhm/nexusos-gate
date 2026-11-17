# verify: doc_consistency.py C9 INLINE_RE 修复（2026-08-18, task/569, 未决#27）

## 改动
`gates/_checks/doc_consistency.py:64` 行内代码剥离正则从 `` `[^`\n]*` `` 改为
CommonMark 等长闭合 `` (`+)[^`]*\1 ``（与 common.sh:131 I2 修法一致，commit 27dcdfa）。
修复双反引号包裹的 ``x`` 被拆成两对空行内代码、wikilink 暴露误报断链的盲区。

## 验证场景（Level 2 函数级 + Level 3 真实场景，新进程 importlib 加载）
1. **单元边界**（4 用例，输出存 task/569-c9-b12-hotfix-review/output/files/c9-verify-output.txt）：
   - 双反引号包裹 ``经验-XXX`` 整段剥除为空格占位 ✅（旧版拆对暴露）
   - 单反引号 `` `x=1` `` 行为不变 ✅
   - 未闭合反引号（`` `inline link-x 无闭合 ``）不匹配（与旧版一致，无回归）✅
   - 三反引号行内（```[[y]]```）剥除 ✅
2. **真实场景**（曾误报的 2 文件，check(params, context, agent) 签名实测调用）：
   - `01-Projects/demo-project-a/task/220-kb-freshness/input/task.md` → passed=True，`经验-XXX` 断链 WARN 消失 ✅
   - `02-Skills/productivity/memory-cleanup-routine.md` → passed=True，`旧名字`/`新名字` 断链 WARN 消失 ✅
3. **py_compile 通过**；git diff 本文件 4 行（≤6 边界内），未动其他函数。

## 复现命令
```bash
python3 - << 'EOF'
import importlib.util
spec = importlib.util.spec_from_file_location('dc', '05-System/自动化脚本/nexusos_xdr/etc/gates/_checks/doc_consistency.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m._strip_code_blocks("前文 ``[[经验-XXX]]`` 后文"))
# 期望: '前文                后文'（整段空格占位，wikilink 不暴露）
EOF
```
