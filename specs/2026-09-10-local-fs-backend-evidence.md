# Evidence — local-fs backend (spec 2026-09-10, rev 6)

- **Date:** 2026-09-12（quota-window evidence run，WeCom 640459 当日配额内）
- **Branch:** `local-fs-backend-impl` @ `4cabcef`（base `0e7d316` = main post-#13；13 个实现提交 + 本 close-out）
- **Entry point:** `bash tools/gauntlet.sh`（一次性 fresh final run，log `/tmp/local-fs-gauntlet.log`）
- **Result:** **GAUNTLET PASS**
  - pytest：**674 passed / 7 skipped / 0 failed**（417.96s；7 skips = 3 个 dingtalk consent-gated 真租户探针 + 4 个 POSIX-mode 平台 skip）
  - diff-cover：**Coverage: 100%**（`--fail-under 100`，exit 0）
  - mypy strict：**Success — no issues in 53 source files**
  - artifact-smoke：**18/18 surface probes passed**
  - properties 16 passed / adversarial 39 passed / secret scan clean
  - mutation：mutmut 原生 Windows 不可用（boxed/mutmut#397）→ `tools/mutants.py` fallback：「No manual mutants registered」（无手工变异体登记，报告如实际）
  - lint：report-only（baseline 40 errors / 13 files，本 PR 触碰文件零新增——Task 2/4 修复轮已把本 PR 引入的 F401/PLR0402 清零）
  - local-fs flow leg：**both modes passed**（git-backed 32 + snapshot 22 = 54 assertions）

## Behavior → test mapping (spec A1–A6 + A5b)

| Spec criterion | Test / leg | Result |
|---|---|---|
| A1 mode/remote schema、枚举、默认 git-backed、负向（`auto`/`git-synced` → ConfigError） | `tests/test_config_schema.py`（9 tests） | ✅ |
| A2 setup 条目、store prep（enabled-only）、mode 变体、merge-on-rerun、fail-closed git 缺失 | `tests/test_localfs_setup.py`（9 tests） | ✅ |
| A3 doctor findings（root/git-backed-unavailable fail-closed×2/脏树 informational/remote 三态）、只读、silent-when-disabled-or-absent、healthy-snapshot | `tests/test_localfs_doctor.py`（10 tests） | ✅ |
| A4 skill 流（route→journal→CAS→原子写→commit/.trash→落账→读回；stale CAS 拒绝；archive/unarchive；delete+undo 恢复 version；undo 双 refusal；journal 配对 uuid） | `tools/local-fs-flow.sh` 两模式（54 assertions） | ✅ |
| A5 负向：外来 .md 检索后过滤/不入 index/不入 commit、`.git` 不入检索、默认无 remote、URI 拒绝（docs-pin） | flow (A5) block + `tests/test_localfs_docs_pins.py`（2 tests） | ✅ |
| A5b remote push：到位 / 非快进拒绝且不自动合并（bare-repo fixture） | flow (A5b) block（git-backed leg） | ✅ |
| A6 表面：skill 随安装器分发 + 文档示例可解析 | `tests/test_docs_conformance.py`（local-fs-integration 注册，7/7 vs 真实工件）、`tests/test_install_skills.py`（17/17 与 routing 合跑） | ✅ |

注：A5 的 URI 拒绝与 CAS 拒绝、tmp+mv 原子性属 agent 执行纪律——本轮的可执行证据是 docs-pin（SKILL.md 规则文本），行为保证归 agent-evals 发布门（ADR 0006，controller ruling，见 progress ledger）。

## 本 PR 的源代码面（计划外但经裁决的扩展）

- `cli.py _coerce_revision`：journal begin/end 的 revision 原为 `int()` 强转，git-SHA（local-fs 记录形态）直接崩溃——修复为数值可转则转、否则原样透传；数值契约由既有严格 int 断言钉住（`test_cli.py:412,416`），undo 新鲜度比较本就 `str(a)==str(b)`。
- `cli.py _cmd_route`：configured-but-adapter-less 后端从 config trust_zone 裁决（spec 明文承诺）；未知名字仍 exit 1；route 保持只读、`_build_router` 未动。

## Skipped / environmental layers（如实）

- 5 个 WeCom 真租户 e2e：本次窗口内 ✅ 通过（配额重置后的一次性运行）。
- 3 个 dingtalk 真租户 e2e：consent-gated skip（`DWS_PROBE_CONFIRM=yes` 时才实跑——破坏性真租户操作须操作者同意；controller ruling）。
- 4 个 POSIX-mode 平台 skip（历有）。
- mutation 层：无手工变异体登记（报告如实；本 PR 的新逻辑由 diff-cover 100% + 专项测试覆盖）。

## 已知残余（全部 fail-closed 方向或 cosmetic，逐条见 progress ledger）

hand-edit 写路径不可见（undo hash 兜底）；`os.access(W_OK)` Windows 弱化；env root 不 expanduser；linked-worktree `.git` file 边缘（backlog）；route 默认路径（无 `--backends`）仅遍历 adapter 后端（spec-owner open question）。

## 遗留人工事项

- 真租户 stray probe docs 清理（子代理权限被拒，需人工）：dingtalk `X6GRezwJlAbb14zph0yApL4v8dqbropQ`、`OG9lyrgJPzoo1lPxCl2xg52pWzN67Mw4`（sweep：`dws drive +find-file --query kgent-phase2-probe -f json`）；wecom `dchY1gU8sgi7-CunWBF81s_KzBFAm0W4r2t0bYvq1GaFLFetsUvvk17xii-SVpBBBmGVbiH7X573bCDnPIk06Kng`。

## Reproduce

```
bash tools/gauntlet.sh
```
