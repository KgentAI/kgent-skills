# EVIDENCE: Phase 1（lark）integration skill 中心制

- **Spec:** `specs/2026-09-05-write-path-skill-delegation-design.md`（approved v3，2026-09-05 维护者批准——spec approval: obtained）
- **Tier:** 3（数据丢失域；失败模型见 spec「失败模型」节，FM1–FM10）
- **Source state:** commit `40d5a94`（分支 `feat/lark-integration-shared-doc`，PR #7）
- **Fresh run:** 2026-09-06，`bash tools/gauntlet.sh` → **GAUNTLET PASS（EXIT=0）**，本文件全部数字来自该次运行（最后一次代码编辑之后）
- **Environment:** Windows 11 + Git Bash；`.venv` Python 3.12；工具链为 `[dev]` extras（pytest 8 / pytest-randomly / mypy / ruff / coverage+diff-cover / hypothesis；mutmut 已配置未使用，见 skip 理由）
- **Reproduce:** 仓库根执行 `bash tools/gauntlet.sh`（一条命令重跑全部层）

## Baseline 演进（诚实记录）

| 时点 | 结果 |
|---|---|
| 动工前 baseline | `1 failed (test_install_skills.py::test_s5b_backend_none_fails_loudly), 460 passed, 2 skipped` |
| 最终 fresh run | `556 passed, 0 failed, 3 skipped`（+3 skip 均为 POSIX mode-bit 平台 skip，含本 PR 新增 test_ledger.py:99） |

S5b 的既有失败经控制方裁决修复（test-only：测试内摘除被污染的 PATH——本机 PATH 上的旧 `kgent` 把 S7 健康检查 FAIL 伪装成 install OK；断言本身未弱化，产品代码零改动）。

## Gauntlet 各层（命令 + 实际数字）

| 层 | 命令（tools/gauntlet.sh 内） | 结果 |
|---|---|---|
| 全套测试（随机序） | `coverage run -m pytest tests` | **556 passed, 3 skipped, 0 failed**（104.32s） |
| 变更行覆盖 | `diff-cover coverage.xml` | **Total 326 lines / Missing 0（100%）** |
| 静态类型 | `mypy src`（strict） | **Success: no issues found in 52 source files** |
| 属性测试 | tests/properties/（hypothesis，随全套） | 16 passed（含内容通道 unicode 往返） |
| 对抗通过 | tests/adversarial/（随全套） | 39 passed（prompt/string injection、模板/SQL/XSS 载荷） |
| 真机执行 | `tests/e2e/test_lark_undo_real.py`（随全套，真 lark-cli） | **B3/B4 PASS**：探针 rev 3→overwrite→5 → `kgent undo` 计划 ok（mechanism=history-revert）→ `+history-revert`(history_version_id 2048) → 读回 AAA-CONTENT（rev 6）；teardown 删探针，0 遗留 |
| 手工 mutant | 见下表 | 2 轮共 10 投入，9 杀 + 1 平台限制存活（分类见下） |
| Secret scan | gauntlet 内建 | pass |
| 网络捕获（N14） | fixture 强制 | pass（"network capture enforced via test fixture"） |
| Lint + format | `ruff check src tests` + `ruff format --check` | **report-only（显式降级裁决）**：baseline 39 errors / 11 files would be reformatted，全部非本 PR 触碰；本 PR 新代码 0 lint/format 债。恢复方法在 tools/gauntlet.sh 头注释 |

### 手工 mutant 表

**T4 轮（compensation_plan/undo 分流）：**

| Mutant（真实 bug） | 被杀于 |
|---|---|
| 新鲜度比较 `!=` 翻转 | 8 tests（test_undo_ledger.py rejected 用例簇） |
| 机制映射错位（lark→version-revert） | 4 tests |
| `_cmd_undo` 分流条件取反 | 3 tests |
| `end()` 丢 kind=="begin" 门 | 1 test（T2 遗留收紧的专属用例） |
| history_hint 错位 | 1 test |

**T11 轮（台账/快照/op_id）：**

| Mutant（真实 bug） | 结果 |
|---|---|
| 新鲜度比较翻转 | killed |
| 机制映射错位 | killed |
| op_id 丢 uuid 后缀（回归撞号） | killed |
| 分流取反 | killed |
| 快照 0600→0644 | **Windows 存活（4/5）**——mode 断言按 spec FM5 为 POSIX-only（skipif）；断言存在，POSIX 环境必杀。分类：平台限制，非 equivalent mutant，POSIX CI 即闭合 |

每个 mutant 以 `git diff` 验证还原后再投下一个。

## 验收标准 → 测试映射（B1–B12）

| 行为 | 验证测试（位置） |
|---|---|
| B1 op_id 同秒唯一 + 格式 | tests/test_op_id.py（2 用例，RED=旧格式断言） |
| B2 台账生命周期 / FM1 异常落账 / FM5 权限 / FM8 strict | tests/test_ledger.py（11+ 用例）+ tests/test_cli.py（journal begin/end 3 用例） |
| B3 undo·lark 计划 + FM2 拒绝 | tests/test_undo_ledger.py（计划簇）+ tests/e2e/test_lark_undo_real.py（真机全链） |
| B4 create 补偿 + 已删幂等 | tests/test_undo_ledger.py（create/幂等分支）+ 真机 e2e |
| B5 wecom 快照写回计划 | tests/test_undo_ledger.py（snapshot 机制 + 无快照拒绝盲回滚） |
| B6 dingtalk 机制映射 | tests/test_undo_ledger.py（mechanism 矩阵用例；真机待凭据，Phase 2） |
| B7 route 裁决 | tests/test_route_command.py（14+ 用例，含 spec `--dry-run` 旗标与 zone 注入拒绝路径） |
| B8 内容完整性 | tests/properties/test_content_channel.py + 真机 e2e（多行中文+emoji 写入读回） |
| B9 平台操作经 integration skill | tests/test_skill_docs_integration_routing.py（RED 曾命中 18 行直调）+ evals 三断言 |
| B10 checker 负控 | tests/test_ledger.py strict 坏行 raise；lint 层 fail-open 被发现并降级裁决（见已知限制） |
| B11 search 保真迁移 | skills/lark-integration/SKILL.md Search 章节（规则同 2026-09-02 spec）；tests/test_lark_node_type.py 16 用例原样回归 |
| B12 基线不变量 | 既有测试零断言改动（4 处 trust_zone 断言为 spec 授权行为变更，逐处核实仅改值）；test_archive_delete_undo.py 原样通过 |

## Checker 负控（fail-open 排查）

- 台账读 strict：喂 `{broken json` → `Journal(strict_load=True)` 构造即 raise（测试在案）
- lint 层曾为 fail-open（`&&` 列表非末位命令在 set -e 下不退出，39 个 baseline 错后照走）——被发现后按裁决降级为显式 report-only，层尾如实打印
- **已知 caveat：diff-cover 9.x 在 <100% 时也退 0**——GAUNTLET EXIT 0 不单独构成 100% 证据，本轮数字为人工核对 log（326/0）；建议后续给 gauntlet 加 `--fail-under 100`

## 跳过/受限层（带理由）

- **mutmut 工具化**：未注册进 tools/mutants.py，按 brief 用手工 mutant 程序替代（3–5 个真实 bug 要求已满足，两轮共 10 个）
- **lint 硬 gate**：baseline 债 39 错/11 文件清偿属范围外，显式降级 report-only（裁决+恢复方法见 tools/gauntlet.sh）
- **B6 dingtalk / B5 wecom 真机**：凭据未就绪（dws 需组织管理员开启 CLI Access Management；wecom 需扫码 auth init）——Phase 2/3 各自动实施计划；fake 层计划生成已覆盖
- **CI 跑真机 e2e**：无凭据环境用 `-m "not real"` 屏蔽（真机探针需 lark 凭据，且 Lark 建点异步实测可 >60s）

## 已知限制（spec 声明 + 实施中确认）

1. 台账快照为本地明文（0600/0700 收紧、目录不入库）——FM5 声明在案
2. 本机 `~/.kgent/config.yaml` 的 lark `trust_zone` 仍为 external（存量配置不随 setup 默认值迁移）——route 会按 external fail-closed；维护者手工改或重跑 `kgent setup`
3. policy.py 写路径 zone 已与 route 同源（config 读取，fail-closed）——终审 I4 修复
4. lint report-only 的残余风险：后续 PR 新增 lint 错不会拦合并——显式裁决，恢复方法在案

## 事故与解决史（本 PR 过程中，诚实记录）

1. 首次 `kgent update`（本次工程的前因）清空文档 v50 → `kgent undo` 假 ok → 用 `docs +history-revert` 完整恢复 → 三层对照实验定位根因（见 spec「事故与实证」）
2. 实施中两次 review-driven 修复：T2 快照目录 0700（docstring 承诺落地）；T5 真实 config AttributeError（FakeBackend 掩蔽，真机 LarkAdapter RED 复现后修）
3. 终审 C1（create 腿 undo 指向占位 URI、谎报 ok——与原事故同类）经 `journal end --doc-uri` 回填 + 计划 target 优先级修复，真机 e2e 覆盖回填路径
