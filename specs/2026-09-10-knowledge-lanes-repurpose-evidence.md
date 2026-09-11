# Evidence — 知识双车道改名与组合（query-knowledge ← question-answering、ingest-knowledge ← knowledge-storage）

Date: 2026-09-10 · Branch: `worktree-knowledge-lanes-repurpose` · Commit: 62f323b
Spec: `specs/2026-09-10-knowledge-lanes-repurpose-design.md` · ADRs: 0006, 0007

## 1. Fresh final run（一次全新终跑）

入口（可复现）：

```bash
# worktree 内；editable 安装指向主 checkout，worktree 源码必须经 PYTHONPATH 优先
PATH="/c/Users/yong_/projects/kgent/kgent-skills/.venv/Scripts:$PATH" \
PYTHONPATH="$PWD/src" \
PYTEST_ADDOPTS='-m "not real"' \
bash tools/gauntlet.sh
```

结果：**GAUNTLET PASS**（`gauntlet-run2.log`，2026-09-10）。

## 2. Per-layer gauntlet numbers

| Layer | Result |
|---|---|
| A artifact smoke（安装态 CLI 面） | 18/18 surface probes passed |
| tests + coverage | **616 passed, 4 skipped, 10 deselected**（`-m "not real"`，见 §4）；TOTAL 86% |
| diff-cover（changed lines） | **100%**（4 changed Python lines, 0 missing） |
| mypy `src/ --strict` | Success: no issues in 52 source files |
| lint | report-only（在案 baseline debt：40 errors / 13 files，2026-09-06 maintainer ruling；本 PR 规则画像与 main 完全一致，零新增） |
| mutation | mutmut 不可用（native Windows，boxed/mutmut#397）→ `tools/mutants.py` fallback：No manual mutants registered |
| properties | 16 passed |
| adversarial | 39 passed |
| secret scan / N14 | clean |

前置完整 suite（无过滤，同分支）：**624 passed, 4 skipped, 2 failed** —— 2 个失败即 §4 的 dingtalk 真机探针（attended-only），与 diff-cover/mypy 层无交互。

## 3. Behavior → test mapping（验收标准 A1–A11）

| 验收 | 证据 | 状态 |
|---|---|---|
| A1 读车道改名自洽 | `grep -ri "question-answering" skills/ tools/ src/ tests/ README.md docs/install/ evals/skills/ evals/README.md` 零命中；`test_docs_conformance`（DOC_FILES 已改名）6/6 | ✅ |
| A2 触发面 | `skills/query-knowledge/SKILL.md`：知识依赖判据 + 5 条任务语境触发 + 3 条跳过示例；description 覆盖 task 语义 + grounding 条款 | ✅ |
| A3 输出单一形态 | SKILL.md 无第二套输出骨架；"Called by Other Skills" 小节含匹配候选契约；冲突/缺口随行声明（步骤 4 + Edge cases） | ✅ |
| A4 写车道改名与组合 | frontmatter `name: ingest-knowledge`；步骤 2 = 委派 query-knowledge（五要素契约）；自带检索步骤文字已移除（`docs +search` 仅存于 query-knowledge）；N18/S61 + 写序列文字保留 | ✅ |
| A5 Python 改名 | `from kgent.skills.query_knowledge import query_knowledge`、`from kgent.skills.ingest_knowledge import ingest_knowledge` 导入成功；`grep question_answering\|knowledge_storage\|store_workflow src/` 零命中；mypy strict 绿 | ✅ |
| A6 测试同步 | 8 个测试文件（设计稿列 6，实际另含 `test_skill_contract.py`、`test_skill_knowledge_storage.py`→`test_skill_ingest_knowledge.py`，后者为 spec A1 grep 门捕捉的漏项）；全绿 | ✅ |
| A7 evals fixture | `query-knowledge-evals.json`（ids 1–10，含任务语境触发 #9、跳过 #10）、`ingest-knowledge-evals.json`（ids 1–11，含组合用例 #11）；discovery 按 runner 同款逻辑（stem + skill_name）离线验证全列。runner 直跑被权限层拦截（判为真写）；其 dry 路径仅是本验证的 glob+json 解析，无外部效应 | ✅（离线验证） |
| A8 安装器悬挂回收 | `tests/test_install_skills.py::test_s2d_dangling_self_entry_reclaimed_external_left_alone`（mklink /J 造悬挂自有条目 + 外部悬挂条目 → 重装后删除/保留各就位）；安装器 suite 15/15 | ✅ |
| A9 车道纪律 | query-knowledge SKILL.md 零 journal 字样；ingest 写序列（route→begin→委派写→end→读回）完整；B9 静态检查（integration 路由）3/3 绿 | ✅ |
| A10 文档一致 | README（ln -s、调用示例含任务语境条目、Python API §1/§2）、`docs/install/`（全部 6 份，不止设计稿所列 codex.md）、3 份 integration 头部枚举；layer D 6/6 | ✅ |
| A11 收尾证据 | 本文件 + 根 `EVIDENCE.md` 追加节 | ✅ |

CONTEXT.md「知识依赖」词条、ADR 0006/0007 随实现首 commit 落盘。

## 4. Skipped layers / 排除项与理由

1. **`-m "not real"`（10 deselected）**：`pytest.mark.real` 是仓库在案的筛选契约（两份真机探针模块 docstring 自述）。排除原因：
   - `test_dingtalk_undo_real.py`（无过滤跑 2 failed）：`-y` 确认门为 **attended-only**（`DWS_PROBE_CONFIRM=yes`，操作者明示同意），模块无该条件的 skipif，headless 必失败——在案行为，与本变更无关（该文件不 import 本变更改名的任何模块）。
   - `test_wecom_snapshot_real.py`（无过滤跑 5 failed）：`WecomDailyQuotaExhausted`（640459 日配额，~09:00 PDT 重置）——同日首轮完整 suite 已消耗配额，二轮触发环境级阻断；测试模块自述其为环境级阻断。
2. **Agent evals（release gate）deferred**：新触发面/组合用例（query #9/#10、ingest #11）待下次 release-gate 窗口真跑（`python tools/run-agent-evals.py --execute --parallel 3`）；跳过 #10 按例标 `manual review`。
3. **lint 层**：report-only 为 2026-09-06 maintainer ruling 在案状态；本变更规则画像与 main 逐规则一致，零新增。

## 5. 环境注意与残留（operator 手册）

- **worktree 运行前提**：venv 的 editable `.pth` 指向主 checkout `src`；worktree 内跑 pytest/gauntlet 必须 `PYTHONPATH="$PWD/src"`，否则 19 个用例 import 旧模块名失败。
- **dws 探针残留（4 个，可删）**：headless teardown 的 `drive +delete` 被 `-y` 门阻断。句柄已 live-verified（= DOC_ID 本体）：
  - 首轮：`9bN7RYPWdMzz1wy9cjZLbM3LVZd1wyK0`、`9E05BDRVQ2oo1EROtPGRy1n3J63zgkYA`
  - 二轮：`3NwLYZXWyn112PxyUGoP5xpzVkyEqBQm`、`vNG4YZ7JnP334gxzCA1a57kMW2LD0oRE`
  - 清理命令：`dws drive +delete --node <DOC_ID> -y -f json`（进回收站，可恢复；需操作者同意 -y）
- **wecom 探针残留（5 个，CLI 无删除命令）**：`dc9IBcj5…`、`dcEVtIviaB…`、`dcPtyk41e5…`、`dcbmGt_1Pg…`、`dcr26L1Aj4…`（完整 id 见 `gauntlet-run.log` 的 `"docid"` 记录）。平台侧无文档删除命令（Phase 3 真值单）；需平台后台手动清理或保留至过期策略。
- 首轮 gauntlet 因上述 7 个真机失败在 coverage 层 set -e 中止（diff-cover/mypy/mutation 未达）——二轮（排除 `real`）全绿收口。

## 6. Conclusion

改名与组合按 spec A1–A11 全部落地；per-commit 门（gauntlet，排除在案的 `real` 筛选契约）绿；真机/attended 层与 agent evals 按仓库惯例作为独立 gate 声明 deferred，残留探针文档已列明句柄。
