# Evidence — confluence MCP-only amendment (ADR 0017; spec 2026-09-22 rev 2)

- **Date:** 2026-09-25
- **Branch:** `worktree-confluence-mcp-amendment`（base：`27b3a7a` = main post-#18 + `444e86b` 真机修复合并）
- **Entry point:** `bash tools/gauntlet.sh`（分层序列，层序与 gauntlet.sh 一致）
- **Result:** **GAUNTLET PASS（分层等价取证）**
  - artifact-smoke：**21/21**（本修订零 CLI 面变化；formats 探针照常）
  - pytest：**831 passed / 1 property flake（见下，已修）/ 4 skipped**（修复后全绿）
  - diff-cover：**100%**（修订 diff 18 行 src，Missing 0）
  - mypy strict：**Success — 54 source files**（较 #18 少 1：confluence adapter 删除）
  - lint：新增/触碰文件 ruff+format 零债务（validate.py:73 的 ISC004 为既有 baseline）
  - mutation：`tools/mutants.py` fallback——无手工变异体（报告如实）
  - properties：**20 passed**（round-trip property 修复后三连跑绿）
  - adversarial：**55 passed**（含 2026-09-25 真机回归语料）
  - secret scan：clean；local-fs flow：**both modes passed**

## 真机实测（本修订的直接证据，2026-09-25）

目标：`https://kgent.atlassian.net`（cloudId `6cde1c17-2f6f-4a73-acc2-181fd92c6bb7`，
Confluence read-write）`KKB` 空间，Atlassian Remote MCP 已连接（宿主 OAuth，唯一认证）。

| 车道 | 结果 |
|---|---|
| CQL 搜索（`space=KKB`，allowlist 语义） | ✅ 5 命中，title/pageId/spaceKey/webui 全带 |
| 读（首页 `327798`、DACI 模板 `327863`） | ✅ `metadata.version.number` + 正文（ADF-flavored HTML） |
| 格式桥（真页正文 → markdown） | ✅ 表格→GFM、标题、占位符降级；**抓出 2 个真 bug 并修复**（`444e86b`：stdin cp1252 mojibake；未闭合属性导致的裸标签泄漏——`html.parser` tolerant scan 放弃时整 tag 成 data） |
| journal 守护 create | ✅ `op-20260925-bcaadb83` → 页面 `98311`（v1）→ `journal end`（回填真实 URI + revision_after=1） |
| 读回校验 | ✅ 正文逐字一致 |
| journal 守护 update（CAS） | ✅ `op-20260925-16348520`：snapshotToken v:1 → **v2**；op_id 进 Atlassian 版本历史 message |
| `kgent undo` 计划 | ✅ `mechanism: version-revert`、`integration_skill: confluence-integration`；对死 acli 车道 **fail-closed rejected**（不盲回滚）——本修订的直接动因 |
| 清扫 | ✅ 探针页 archive（MCP 无删除工具，如实申报）；active search 0 残留 |

**acli A1 探针结论（等价完成，`tools/confluence-probe.sh` 退役）**：官方 `acli` 1.3.39
Confluence 面实测 = `page view` + space 族（无 search、无 page CUD）；文档宣称领先于
发布二进制。探针的 REQUIRED 面对真实 acli 不可满足——由 MCP 真机全绿取代其「e2e 前置」
职能（ADR 0017）。

## Behavior → test mapping（修订增量）

| 修订点 | Test / leg | Result |
|---|---|---|
| transport MCP-only（atlassian server → mcp；无 → unavailable；acli 在场无关） | `tests/test_confluence_setup_doctor.py::TestTransportMcpOnly`（7） | ✅ |
| doctor：mcp=健康静默；unavailable=申报；disabled=静默 | `::TestDoctorFindings`（3） | ✅ |
| ledger hint 改指 MCP 版本族 | `tests/test_undo_ledger.py::test_plan_confluence_mechanism_version_revert` | ✅ |
| skill Gate/undo/limitations 全 MCP 语义 | `tests/test_confluence_docs_pins.py`（11，含 no-CLI-lane pin、archive-not-delete pin） | ✅ |
| adapter 车道退役（confluence 无 adapter 注册） | `src/kgent/adapters/__init__.py` 注释锚 + 注册表断言（既有 registry 测试） | ✅ |
| round-trip property 规范化生成器（内空白 run 折叠为声明规范化） | `tests/properties/test_formats_roundtrip.py`（3 连跑绿） | ✅ |

## Skipped / environmental（如实）

- MCP 工具调用不在 gauntlet 密闭层（无 subprocess）——行为纪律由 docs-pin（11 支）+
  agent evals（发布门）承载；confluence eval 腿仍为 release-gate follow-up。
- 页面删除（回收站）MCP 目录暂缺——spec rev 2 修订项 3；skill 以 archive+申报承载。
- 全量 suite 首跑出现 1 例 property flake（`'0  0'` 内空白折叠——converter 声明规范化
  首次被生成器命中），生成器改产规范形后三连跑绿；converter 零改动。
- 探针页 `98311` 留于 KKB（archived 状态；MCP 无删除工具——用户可于 UI 删除或
  `unarchiveConfluenceContent` 恢复）。

## Reproduce

```
bash tools/gauntlet.sh
```

真机复现（宿主连 Atlassian MCP 后）：`kgent route/journal/format` 序列见
`skills/confluence-integration/SKILL.md`；KKB 搜索 CQL
`type=page AND space=KKB AND text ~ "<kw>"`。
