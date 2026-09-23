# Evidence — confluence backend (spec 2026-09-22)

- **Date:** 2026-09-23
- **Branch:** `worktree-confluence-backend` @ `7708516`（base `4d4f32d` = main post-#17；2 个实现提交：docs `ef8024e` + impl amend 后 `7708516`）
- **Entry point:** `bash tools/gauntlet.sh`（本 close-out 以**逐层 foreground 序列**执行——两次 background 整跑在 install-surgery 窗口被杀且出现文档记载的跨层瞬时失败，改按用户裁决分层取证；层序与 gauntlet.sh 完全一致）
- **Result:** **GAUNTLET PASS（逐层等价取证）**
  - artifact-smoke：**21/21 surface probes passed**（含 `kgent formats` 3 条新探针；首跑 3 FAIL 揭示 ambient 安装过期——重跑 `tools/install-skills.sh` 后全绿；gate 正确拦截 stale install，2026-09-06 uv-cache 事故的回归防线有效）
  - pytest：**856 passed / 4 skipped / 0 failed**（245.34s；4 skips = POSIX-mode 平台 skip，历有；10 deselected = `real` opt-in）
  - diff-cover：**Coverage: 100%**（`--fail-under 100` 等价断言：Missing 0 / branch diff 538 行；TOTAL coverage 88%）
  - mypy strict：**Success — no issues in 55 source files**
  - lint：report-only（既有 baseline 债务不动；**本 PR 新增 9 文件 ruff 0 错 + format 稳定**——8 项自动修复 + 4 项手修，含 1 处死代码删除）
  - mutation：mutmut 原生 Windows 不可用（boxed/mutmut#397）→ `tools/mutants.py` fallback：「No manual mutants registered」（报告如实；新逻辑由 diff-cover 100% + 专项测试覆盖）
  - properties：**20 passed**（含格式桥 round-trip hypothesis property）
  - adversarial：**53 passed**（含格式桥对抗语料 17 支：script 剥离、CQL/markdown 注入、畸形嵌套）
  - secret scan：clean（grep 无命中，exit 1 = 无 token）
  - local-fs flow leg：**both modes passed**（既有语义零回归）

## Behavior → test mapping（spec A1–A7）

| Spec criterion | Test / leg | Result |
|---|---|---|
| A1 acli 探针（gated，real） | `tools/confluence-probe.sh`（凭据缺失 → 显式 SKIP，不 fail；**未运行——凭据未备，e2e 宣称保持 gated**，见 Skipped） | ⏸ SKIP by design |
| A2 schema：confluence 条目默认 `spaces: []`/`site: None`、allowlist/site 正负向、mode/remote 无害并存、type 枚举零扩动 | `tests/test_config_schema.py`（+5 tests）、`tests/test_confluence_urls.py::TestSiteConfigKey`（3） | ✅ |
| A3 adapter：搜索映射/argv 形状/allowlist 进 CQL、read 走格式桥、wiki 块、`_native_id` 数字+跨后端拒绝、写车道全 NotImplementedError、payload 兜底与错误路径、CQL 转义 hypothesis | `tests/test_confluence_adapter.py`（32 tests） | ✅ |
| A4 格式桥：子集 round-trip（unit + hypothesis）、桥外读占位/写拒绝、对抗语料（script/事件属性/深嵌套/错配标签/空输入）、CLI 进 surface-manifest 且 artifact-smoke 过 | `tests/test_formats.py`（40）、`tests/properties/test_formats_roundtrip.py`（1 property）、`tests/adversarial/test_formats_adversarial.py`（17）、`tools/surface-manifest.txt` +3 | ✅ |
| A5 台账/undo：`version-revert` 机制、`integration_skill: confluence-integration`、FM2 新鲜度拒绝、history_hint | `tests/test_undo_ledger.py`（+2） | ✅ |
| A6 skill 纪律 docs-pin：Gate 阶梯三腿、凭据、journal 配对+CAS(409/version+1)、CQL 转义、格式桥有损披露、allowlist 收窄语义、native URL、undo 语义、已知限制 | `tests/test_confluence_docs_pins.py`（10）、`tests/test_docs_conformance.py`（confluence-integration 注册；kgent 示例对安装后工件全过；acli 示例 A1-gated 显式跳过） | ✅ |
| A6 传输阶梯 discover/doctor：acli→MCP→unavailable 三态、skill 前缀发现、doctor enabled/unavailable/mcp/acli-silent | `tests/test_confluence_setup_doctor.py`（8） | ✅ |
| A7 real e2e（opt-in，sandbox 空间） | 未运行（A1 探针同门——凭据未备） | ⏸ SKIP by design |

## 本 PR 的源代码面（计划外但必要的扩展）

- `tests/test_docs_conformance.py`：命令 regex 与 dispatch 增 `acli`——acli 在场时与其他 CLI 同规格校验，缺席时**显式跳过**（A1 gate，ADR 0015）；`DOC_FILES` 注册 confluence-integration。
- config schema 增 `site` 键（str|None，同 `remote` 校验形状）——native URL 引用（N20）需要站点 host，实现期补遗已记入 spec。

## Skipped / environmental layers（如实）

- **A1 探针与 A7 real e2e 未运行**：本机无 acli、未提供 Confluence 凭据（用户裁决：spec 先行，探针 gated）。**在探针通过前，confluence 的 e2e 可用性不作宣称**（ADR 0015 后果条款）；这是 impl PR 关闭前的显式豁免记录。
- 两次 background 整跑（bv6aknjkg / b8alzktmm）在运行中被杀，pytest 层出现 119/112 failed 的同型跨层失败——与 EVIDENCE 既有记载的「并发会话 install-surgery 窗口」现象一致；改分层 foreground 取证后全绿，且 artifact-smoke 揭示 ambient 安装已被换为过期版本（重装后 21/21）——最终有效证据以本 close-out 的分层序列为准。
- agent evals（发布门）：`evals/skills/platform-via-integration-evals.json` 增 confluence 腿尚未落——需 A1 探针通过 + 凭据可得环境，属 release-gate follow-up（spec Setup plan 如实声明），不在本 spec 门。

## 已知残余（fail-closed 方向或已声明）

- acli 命令形状与 payload 键位是契约草案（`_cmd_*`/`_extract_*` 锚点集中）——A1 探针对账后如漂移只改锚点 + 同步 skill。
- MCP 腿不可密闭测试（无 subprocess）——纪律在 docs-pin + agent evals（ADR 0015 如实记录）。
- ambient 安装易被并发会话回退——gate 已两度拦截（artifact-smoke FAIL → 重装），无需代码动作。

## Reproduce

```
bash tools/install-skills.sh   # 工件新鲜度前置（artifact-smoke 的 gate 对象）
bash tools/gauntlet.sh
CONFLUENCE_SANDBOX_SPACE=<key> bash tools/confluence-probe.sh   # A1，凭据可得时
```
