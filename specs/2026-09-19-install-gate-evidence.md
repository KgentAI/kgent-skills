# Evidence — 安装门：平台 integration skill 按 config 门控安装（2026-09-19/20）

- Spec：[`specs/2026-09-19-install-gate-design.md`](2026-09-19-install-gate-design.md) v1.1（**spec approval: obtained** — 用户 2026-09-20 批准 v1.0 树 + B3 v1.1 修订）
- 决策：ADR 0010；术语：CONTEXT.md 安装门 / skill 同步
- **Gauntlet：PASS**（绿色，见 §2；`PYTEST_ADDOPTS='-m "not real"' bash tools/gauntlet.sh`，exit 0）

## 0. Scope 与提交序列

分支 `feat/install-gate`（merge base `9f329f5`）：

| commit | 内容 |
|---|---|
| `ebdb6f0` | spec v1.1 + ADR 0010 + CONTEXT.md（grill loop 产物） |
| `ad2a533` | 安装器安装门 + `--sync/--keep/--force/--agents`（I1–I17 测试） |
| `10ff824` | doctor finding + setup 尾注 + 车道 prose + docs（D/E 测试） |
| `05f5ba6` | doctor probe 改 `os.stat`（mutation M6 逼出的真缺陷） |
| `2c63f8f` | mutation harness M6 anchor 跟进 |
| （本次） | mutation harness M8 + 本 EVIDENCE |

## 1. 行为 → 测试映射

Spec §3 场景逐条（`tests/test_install_skills.py`，hermetic sandbox `$HOME`，bash 实装 `tools/install-skills.sh`）：

| 场景 | 测试（observed RED → GREEN） |
|---|---|
| I1 无 config fail-closed + 恰一行提示 | `test_i1_no_config_fails_closed_with_notice` |
| I2 单平台门开（verify 过门控集） | `test_i2_lark_enabled_installs_lark_integration_only` |
| I2b leg-1（show-effective）权威、缺 backend ⇒ closed | `test_i2b_showeffective_leg_wins_over_config_file` |
| I2c leg-1 不可解析 ⇒ 退化 grep 腿 | `test_i2c_unparseable_showeffective_falls_back_to_grep` |
| I3 门全关无提示 | `test_i3_all_disabled_no_notice` |
| I4 缺 enabled 键 ⇒ 关 | `test_i4_missing_enabled_key_is_closed` |
| I5 普通安装不 prune（回归盔甲） | `test_i5_plain_install_never_prunes` |
| I6 sync 移除门关 skill + hop、无 dangling | `test_i6_sync_prunes_closed_skill_and_hops` |
| I7 `--keep` 豁免移除 | `test_i7_keep_suppresses_prune` |
| I8 门开 sync 幂等 | `test_i8_sync_with_gate_open_is_idempotent` |
| I9 `--force` 全装 + 恰一行警告 | `test_i9_force_installs_all_platform_skills_with_warning` |
| I9b force+sync 跳过 prune | `test_i9b_force_with_sync_skips_prune` |
| I10 `--agents` 选 hop + 持久化 + 打印 targets | `test_i10_agents_scopes_hops_and_persists` |
| I11 裸 sync 沿用持久化 targets | `test_i11_sync_reuses_persisted_targets` |
| I12 `--agents all` 重置 | `test_i12_agents_all_resets` |
| I13/I13b 非法值（未知名 / hub-native 名）exit 2 | `test_i13_*` 两测 |
| I14a grep 腿注释/行内噪声契约 | `test_i14a_grep_leg_ignores_comments_and_inline_noise` |
| I14b 不可解析块 ⇒ 警告一行（stderr）+ 关 | `test_i14b_unparseable_block_warns_and_reads_closed` |
| I15 prune 白名单恰为三平台（车道/local-fs 不动） | `test_i15_prune_whitelist_spares_lanes_and_local` |
| I17 config 字节不变（只读承诺，盔甲） | `test_i17_config_file_never_touched` |
| I16 `--uninstall` 不变 | 既有 S4/S4b/S8d 原样绿（未削弱） |
| I17 无 codebuddy 回归 | 既有 S8b 原样绿 |

Doctor/发现回路（`tests/test_discovery_doctor.py`）：

| 场景 | 测试 |
|---|---|
| D1 已装 ⇒ 无 finding、exit 0 | `test_d1_installed_integration_skill_is_healthy` |
| D2 缺装 ⇒ finding 含 backend + `--sync`、exit 1 | `test_d2_missing_integration_skill_is_a_finding` |
| D3 any-dir 规则（仅 codebuddy 也算装） | `test_d3_any_known_skill_dir_counts` |
| D4 local-fs 豁免 | `test_d4_local_fs_is_exempt` |
| D5 探测位置不可读 ⇒ fail-closed 报 finding | `test_d5_unreadable_probe_location_fails_closed` |
| D6 wecom 报而 lark 不误报 | `test_d6_wecom_flagged_not_lark` |
| D7 disabled 平台不探测（覆盖率补腿） | `test_d7_disabled_platform_backend_is_not_probed` |
| E1 setup 尾注含 `--sync` | `test_e1_setup_prints_sync_epilogue` |
| E2 三车道 prose 含 doctor + sync | `test_e2_lane_skills_carry_the_doctor_hint` |

I5/I17 为**声明式回归盔甲**（写入当日即绿）：其非空转性由 M2/M8 变证（见 §3）。

## 2. Gauntlet 分层读数（最终 fresh run，2026-09-20，代码末次编辑后）

入口：`PYTEST_ADDOPTS='-m "not real"' bash tools/gauntlet.sh` → **exit 0 / GAUNTLET PASS**

| 层 | 结果 |
|---|---|
| A artifact-smoke | **18/18 surface probes passed** |
| tests + coverage | **697 passed / 0 failed / 4 skipped / 10 deselected**（302.72s；deselected = `real` 标记的真机用例，AGENTS.md 2026-09-11 ruling；4 skip = POSIX mode bits on Windows 既例） |
| coverage TOTAL | 4767 stmts / 631 miss / 87%（全局仅参考） |
| diff-cover（merge-base diff 变更行） | **`detect.py`/`cli.py`/`validate.py` 全 100%** — Total 31 lines, Missing 0, Coverage 100% |
| types (mypy) | **Success: no issues found in 53 source files** |
| lint (ruff) | report-only（maintainer ruling 2026-09-06）：baseline debt 40 errors / 13 files，本次触碰文件零新增 |
| mutation (gauntlet 内建) | mutmut native-Windows 不可用（boxed/mutmut#397）→ `tools/mutants.py` fallback（report-only，无注册项）；**本次新增持久化 harness 覆此层，见 §3** |
| properties | **16 passed**（hypothesis） |
| adversarial | **39 passed** |
| secret scan | PASS（硬门） |
| network capture (N14) | enforced |
| local-fs flow 双模式 | git-backed 32 ok / snapshot 22 ok — **both modes passed** |

## 3. 手动 mutation（`tools/mutate-install-gate.sh`，持久化可复现）——**8/8 killed**

| 变体 | 注入的 bug | 杀手测试 |
|---|---|---|
| M1 | grep 腿比较反转（开/关互换） | I2 + I3 |
| M2 | prune 白名单删除（sync 会波及一切 skill） | I15 |
| M3 | `gate_of` 查找反转（全部门读关） | I2 |
| M4 | `--force` 反转（force 反而啥都不装） | I9 |
| M5 | leg-1 缺 backend 读 open（破坏 fail-closed 权威性） | I2b |
| M6 | doctor 探测 fail-open（缺装报健康） | D5 |
| M7 | hub-native 拒绝分支禁用 | I13b |
| M8 | 安装器写 config（只读不变量注入） | I17 |

**M6 是 mutation 层的真捕获**：初版探测用 `Path.is_file()`——它内部吞掉 ENOENT/ENOTDIR，`except OSError` 分支实际不可达，fail-open 变体存活。改为显式 `os.stat`（`stat.S_ISREG` 判定）后缺装与不可读都流经 fail-closed 处理，变体被 D5 杀死。i17 的非空转性由 M8 兑现（写注入 ⇒ 字节等值断言开火）。

Harness 自身的 fail-closed 负控制也已实证：anchor 不唯一/不匹配、恢复后 worktree 脏、任何 SURVIVED 都 exit 1（开发过程中真实触发过三类，全部响亮失败——见 §4）。

## 4. 过程中的失败与处置（如实）

1. **RED 首轮 18 失败**（预期）：门未实现。2 测（I5/I17）按声明作为盔甲空转通过。
2. **i2b**：leg-1 把「effective 视图缺 backend」误当解析失败退化 grep——改为缺 backend 即读 closed（leg-1 权威）。**测试未动，实现收敛。**
3. **i14b**：解析警告先被写到 stdout（污染 `$()` 捕获、破坏门状态解析）→ 定案：`gate_state` stdout 只输出状态、诊断走 stderr、**每 backend 每次运行只评估一次**（预计算 `GATE_STATES`）——`$()` 子shell隔离使变量去重方案天然不可行。测试随后把流从 stdout 改为 stdout+stderr（spec 未钉流，语义不变：恰一行）。
4. **环境隐患（已存记忆 + 此处存档）**：本机 ambient python 的 kgent 是 **editable 指向陈旧 worktree** `.claude/worktrees/decision-navigator-spec`——裸 `python -m pytest` 测的是旧代码（D2/E1 假失败定位于此）。仓库 `.venv` 的 `.pth` 正确指向本 checkout `src/`，**gauntlet 不受影响**；会话内裸跑一律 `PYTHONPATH=src`。
5. **harness 自己的两类失败**：初版把测试文件当 mutation 目标（fail-closed 响亮报错）；CRLF worktree 使 LF anchor count=0（mutator 归一化 `\r\n` 修复）。M6 apply-failure 的 `git checkout` 还原曾吃掉未提交的 detect.py 修复——按 harness 头部告警**先 commit 再跑 harness**，已照办。

## 5. Baseline 与已知限制（如实声明，不属本 diff）

- **5 个 wecom 真机 e2e 失败**（`tests/e2e/test_wecom_snapshot_real.py::test_b5_undo_plan_and_snapshot_restore` / `::test_b5_create_leg_quarantine_compensation` / `::test_b8_content_integrity` / `::test_b5_fm2_rejects_after_concurrent_edit` / `::test_b5_fm3_rejects_without_post_snapshot`）：裸全量跑（PYTHONPATH=src、无 marker 过滤）观测于 698 passed / 5 failed。定谳**与本分支零交集**：该文件只 import stdlib+pytest、经 subprocess 直驱 `wecom-cli`，与本 diff 无任何导入边；失败符合既知 640459 日配额窗（见根 EVIDENCE 与 memory）。按 baseline 规则**不代修**；gauntlet 按 ruling 以 `-m "not real"` 排除之。
- **agent evals**：独立 release gate（`tools/run-agent-evals.py`），本次不跑——本次变更不触碰平台 integration 内容与 orchestrator 行为语义（eval grader 的 `<platform>-integration` 针仍按既有语义工作；安装门只改变「装没装」，eval 机器按 §B9 文档先 `--sync` 即可）。
- 已知代价（ADR 0010 明文）：config 开某平台而某 agent 目录无原生 skill 时，该 agent 仍收 integration skill——`--agents` 兜底，门不感知 per-agent 能力。

## 6. 复现

```bash
cd kgent-skills && git checkout feat/install-gate
PYTEST_ADDOPTS='-m "not real"' bash tools/gauntlet.sh   # 全层，期望 GAUNTLET PASS
bash tools/mutate-install-gate.sh                       # 期望 MUTATION RESULT: 8/8 killed
```
