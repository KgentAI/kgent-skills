# EVIDENCE: Phase 2（dingtalk-integration）— skill 契约 + dws 读车道 + 真机载体

- **Spec:** `specs/2026-09-07-phase2-phase3-handoff.md` §Phase 2（母 spec
  `specs/2026-09-05-write-path-skill-delegation-design.md` v3，approved）——
  工作项 1（SKILL.md 契约）、2（DOC_FILES）、3（evals fixture 回装）、
  4（B6/B8/B11）、5（EVIDENCE + agent evals）
- **Tier:** 3（数据丢失域；失败模型 FM1–FM10 见母 spec）
- **Source state:** commit `6431ddc`（分支 `feat/dingtalk-integration`，自
  phase2-phase3-handoff @ `2c3bcd7` 切出；Task 7 新增两个收尾 commit 见 §3）
- **Fresh run:** 2026-09-08，`bash tools/gauntlet.sh` → **GAUNTLET PASS（EXIT=0）**，
  本文件全部数字来自该次运行（最后一次代码编辑之后）
- **Environment:** Windows 11 + Git Bash；`.venv` Python 3.12；dws
  `v1.0.61 (50eb73a0, 2026-08-31T14:46:17Z)`（npm 全局 `dingtalk-workspace-cli`，
  **未登录**）；lark-cli 用户身份有效；`~/.kgent/config.yaml` 的
  `backends.dingtalk` 为 Task 1 补齐的 `type: skill / skill_name: dingtalk-integration /
  trust_zone: internal`（`kgent doctor` → healthy）
- **Reproduce:** 仓库根 `bash tools/gauntlet.sh`（一条命令重跑全部层）；
  agent evals 见 `evals/README.md`（release gate，不入 per-commit gauntlet）

## 0. 凭据阻塞声明（母 spec EVIDENCE 要求，先于一切数字）

**维护者裁决（2026-09-08，progress.md Ruling）：无可用钉钉账号——真机 DingTalk
验收为永久阻塞（非等待中）**。由此：

| 项 | 状态 |
|---|---|
| **B6 真机闭环**（写 A → 写 B → undo 计划 → `+version-revert` → 读回 A；`--expected-revision` 不符 → 拒绝） | **blocked**——e2e 载体已写就并通过 stub dry-run，凭据门 skip（§4） |
| **B8 真机闭环**（多段中文 + emoji 写入读回全量保真） | **blocked**——同上；lark 侧 B8 真机仍在（§2 真机层） |
| **B11 payload 真值** | **fixture 级验证**——`tests/fixtures/dws/` 两份 payload 按**文档形状**构造，**documented-not-captured**（`tests/fixtures/dws/FIXTURES-NOTE.md` 逐键 provenance + 四个文档冲突点）；fixture 绿 ≠ 真机验收 |
| **DingTalk 条目 agent evals**（knowledge-storage id3/id4、wiki-setup id1/id2） | **全部 skipped**（§5，维护者裁决） |
| dws 登录态实测 | `dws auth status -f json` → `{"success": true, "authenticated": false, "message": "未登录"}`；两次 OAuth 窗口无人扫码（**不是**组织「CLI Access Management」被关——那会在授权页报错，而本次是等满 5 分钟超时，见 `PROBE-NOTES.md` §0） |

凭据就绪后的解阻入口：`PROBE-NOTES.md` §5 补捕命令 + `task-6-report.md` §5
runbook（`DWS_PROBE_CONFIRM=yes` 确认门协议）。

## 1. Baseline 演进（诚实记录）

| 时点 | 结果 | 来源 |
|---|---|---|
| Phase 1 最终 fresh run（origin/main，PR #7） | `556 passed, 0 failed, 3 skipped` | Phase 1 EVIDENCE |
| Task 4 交付（runner 修复 + 锁测试） | `568 passed, 3 skipped, 0 failed` | task-4-report |
| Task 3 + Task 2 交付（adapter 读车道 + conformance 接线） | `575 passed, 3 skipped` | task-6-report 引用的写文件前基线 |
| Task 6 交付（e2e 载体 3 条，凭据门 skip） | `575 passed, 6 skipped, 0 failed` | task-6-report |
| **最终 fresh run（本轮）** | **`579 passed, 6 skipped, 0 failed`**（Task 7 补 4 条 adapter 覆盖测试） | §2 gauntlet log |

## 2. Gauntlet 各层（命令 + 实际数字）

| 层 | 命令（tools/gauntlet.sh 内） | 结果 |
|---|---|---|
| 工件冒烟 | `bash tools/artifact-smoke.sh` | **17/17 surface probes passed**（装机 CLI 面，含 `kgent undo --help`） |
| 全套测试 | `coverage run -m pytest -p no:randomly` | **579 passed, 6 skipped, 0 failed**（247.12s） |
| 随机序复核 | `.venv/Scripts/python.exe -m pytest tests -q`（不关 randomly） | **579 passed, 6 skipped, 0 failed**（254.49s，与固定序总数一致，EXIT=0） |
| skip 构成 | `-rs` 单独核实 | 3 × POSIX mode-bit（`test_local_state.py:95`、`test_local_state.py:397`、`test_ledger.py:99`）+ 3 × dingtalk e2e 凭据门（`tests/e2e/test_dingtalk_undo_real.py:652/702/751`，reason `real-machine probe: dws identity unavailable (credentials blocked, 见 EVIDENCE)`） |
| 变更行覆盖 | `diff-cover coverage.xml --diff-file <(git diff origin/main...HEAD)` | **Total 101 lines / Missing 0（100%）**——本分支唯一 src 变更文件 `src/kgent/adapters/dingtalk.py` |
| 静态类型 | `mypy src`（strict） | **Success: no issues found in 52 source files** |
| 属性测试 | `pytest tests/properties -v` | **16 passed** |
| 对抗通过 | `pytest tests/adversarial -v` | **39 passed**（prompt/string injection、模板/SQL/XSS 载荷） |
| 真机 lark e2e | `tests/e2e/test_lark_undo_real.py`（随全套，真 lark-cli） | **PASS**：探针 rev **3 → 5**（journal begin/end → `kgent undo` 计划 ok，mechanism=history-revert）→ `docs +history-revert`（history_version_id **2048**）→ 读回 AAA-CONTENT（rev **6**）→ teardown 删探针 **0 遗留**（2026-09-08 `-s` 现场读数，`[kgent-phase1-probe] revision_before=3 revision_after=5 history_version_id=2048 final=6`） |
| 真机 dingtalk e2e | `tests/e2e/test_dingtalk_undo_real.py`（随全套） | **3 skipped**（凭据门，§0）——文件是凭据就绪即可跑的执行载体 |
| 变异 | `mutmut run` / `tools/mutants.py` 兜底 | **report-only no-op**：mutmut 在原生 Windows 拒跑（boxed/mutmut#397），`tools/mutants.py` **本轮无 Phase 2 注册项**——零 mutant 投入，如实记录（非"已做变异"） |
| Secret scan | gauntlet 内建负控 | pass |
| 网络捕获（N14） | fixture 强制 | pass |
| Lint + format | `ruff check src tests` + `ruff format --check` | **report-only（显式降级裁决，Phase 1 起）**：`ruff check` 40 errors（逐文件对照 origin/main：**0 处在本 PR 触碰文件**）；`ruff format` 13 files would be reformatted（其中本 PR **新增**文件 **0** 件——`test_dingtalk_adapter.py`、`test_dingtalk_undo_real.py`、`fake_cli.py`、`adapters/dingtalk.py`、`test_agent_evals_runner.py` 五件全部 clean；PR 触碰的 `test_docs_conformance.py` / `run-agent-evals.py` 两件在 origin/main 上即已 unformatted，属既有债，对照见 §3）。恢复方法在 tools/gauntlet.sh 头注释 |

## 3. Task 7 收尾修复（gauntlet 首轮发现的假绿，两笔 test-only commit）

首轮 fresh run 得到 `GAUNTLET PASS EXIT=0` 但 **diff-cover 只有 92%
（101 行变更中 8 行未覆盖）**——EXIT 0 是 diff-cover 9.x「<100% 也退 0」的
已知假绿（Phase 1 EVIDENCE 已记该 caveat，本轮再次命中）。同时 Phase 1 的
「本 PR 新增文件 0 lint/format 债」纪律在 Task 4 的新测试文件上失守。两笔
test-only 修复（产品代码零改动）：

| Commit | 内容 |
|---|---|
| `b861461` | `tests/test_dingtalk_adapter.py` 补 4 条：退出 0 但 stdout 非 JSON / 非 JSON 对象 → AdapterError；envelope `ok:false` → AdapterError；类型字段 `axls`（无 URL）→ `doc` + 类型字段缺失落 `workspaceId` 容器事实 → `wiki_node`；非 dict 命中段跳过 + rank 非 int 落 0。另把 Task 3 写下的两处既有行折叠为 ruff format 规范形（`format --check` 归零） |
| `6431ddc` | `tests/test_agent_evals_runner.py`（Task 4 新增文件）归 ruff format 规范形（docstring 后空行 + 长参数列表折叠），断言零改动 |

**修复后重跑 fresh run（§2 全部数字来自这次）**：diff-cover 100%（101/0）、
`ruff format` 13 files（对照 origin/main 逐文件核实，13 件全部为既有债——
`tests/test_docs_conformance.py` 与 `tools/run-agent-evals.py` 在 origin/main
上即已 unformatted）。

**结构层教训（给 gauntlet 的后续债）**：lint 层因 2026-09-06 的裁决已是
显式 report-only，而 diff-cover 层名义上是硬 gate、实际被工具退出码假绿——
建议给 gauntlet 补 `diff-cover ... --fail-under 100` 的显式校验或对 stderr 做
`Missing: 0` 断言（Phase 1 已提过同款建议，未落地，本轮是第二次被它漏过）。

## 4. 验收标准 → 测试映射（B6 / B8 / B11 + 接线清单）

| 行为 | 验证测试（位置） | 真值状态 |
|---|---|---|
| **B6** dingtalk undo 机制映射（计划期新鲜度 + `version-revert` 补偿 + FM2 并发编辑拒绝） | 计划层：`tests/test_undo_ledger.py::test_plan_dingtalk_mechanism_version_revert`（mechanism=`version-revert`、history_hint=`dws doc +version-list`）、`::test_plan_rejects_version_string_vs_int_mismatch`（双轴）；新鲜度读：`tests/test_dingtalk_adapter.py::test_read_document_carries_revision_as_version`（fetch `revision` → `metadata.version`）；真机载体：`tests/e2e/test_dingtalk_undo_real.py::test_b6_undo_plan_and_version_revert` + `::test_b6_fm2_rejects_after_concurrent_edit`（TOCTOU 执行前复核、轮询读回 AAA-CONTENT、`expected revision X / current Y` 双侧拒绝理由） | **代码完成 + e2e 就绪 + 真机 blocked**（§0）。真机 revision 读数：**无**（凭据）；替代实证 = stub dry-run 全链 PASS（`task-6-report.md` §2：journal begin→end→计划断言→version 命中→TOCTOU→revert→读回）+ lark 同构闭环真机 PASS（§2 真机层） |
| **B8** 内容完整性（多段中文 + emoji + 块内换行，first-block 事故回归 FM7） | 共享：`tests/properties/test_content_channel.py`（unicode 往返，随全套 16 条）；真机载体：`tests/e2e/test_dingtalk_undo_real.py::test_b8_content_integrity`（`@file` 内容通道 + cwd 锚定 + emoji VS16 往返 + 换行保真双现场断言）；lark 侧真机 Phase 1 已验（多行中文 + emoji 写入读回） | dingtalk 腿 **blocked**（§0）；`@file` 通道与 `--doc-format` 契约为 `dws --help` 实测真值（`PROBE-NOTES.md` §4） |
| **B11** dingtalk search 类型保真（§7.2 词表 `doc`/`wiki_node`，只消费服务端事实） | `tests/test_dingtalk_adapter.py`（10 条：判型三步 `/document/`+`/spreadsheetv2/` URL 段 → 类型字段 `_NON_DOC_TYPES` → `workspaceId` 容器事实；无 ID hit 丢弃；`--limit` 封顶 30；win32 `.cmd` 解析；§3 新增四条）；S65 conformance 矩阵对 dingtalk 生效（`tests/test_adapters.py` 24 条中 8 条 `[dingtalk]` 参数化，fake `dws` wire 车道 `tests/fakes/fake_cli.py`）；fixture：`tests/fixtures/dws/doc-search.json`（三 hit：扁平 adoc / 知识库 / `/spreadsheetv2/` axls）+ `doc-fetch.json` | **fixture 级验证**——payload 形状 documented-not-captured（§0）；键位解析集中在 `adapters/dingtalk.py` 模块级 `_extract_*` 锚点，补捕后只改锚点 + 回填 fixture |
| 接线 1：`DOC_FILES` 追加 | `tests/test_docs_conformance.py` `DOC_FILES` 第 5 项 = `skills/dingtalk-integration/SKILL.md`；该 doc 抽取 **43 条候选**，其中 **39 条命令示例逐条对真实 `--help` 校验**（33 dws + 6 kgent；4 条 `kgent://` URI span 为非命令提及不校验），且 dingtalk 用例对 dws 缺席**显式 fail 不静默 skip**（`test_docs_conformance.py:98`） | **真机（--help）实证** |
| 接线 2：B9 静态检查自动生效 | `tests/test_skill_docs_integration_routing.py`（2 条）对三 skills 全量：无 `kgent <op> --backends dingtalk` 直调、必含 `<platform>-integration` 路由说明 | **随全套 PASS** |
| 接线 3：close 三件套 | 本文件 + 根 `EVIDENCE.md` addendum + `bash tools/install-skills.sh`（§7）；项目记忆更新未做（Task 7 执行清单外，见报告） | 本轮落地 |
| 接线 4：trust_zone | `~/.kgent/config.yaml` `backends.dingtalk.trust_zone: internal`（Task 1，仓库外文件不入 commit） | Task 1 落地，`kgent doctor` healthy |

## 5. agent evals（release gate，与 pytest 分离）

- **DingTalk 腿四条全部 skipped**（维护者裁决，§0）：`knowledge-storage-3`（钉钉
  目标）、`knowledge-storage-4`（Lark+DingTalk fan-out）、`wiki-setup-1`（钉钉
  partner guide 腿）、`wiki-setup-2`（双后端）——fixture 已按 Phase 2 工作项 3
  回装（dry run 全集 24 条），凭据就绪即可跑。
- **skill 层端到端冒烟（纯 lark 腿）**：`platform-via-integration-1`（evals 结果见
  下，真实写 lark 租户）。
- 启发式评分只是初筛（runner 自述）；transcript 抽读结论随结果一并记录。

**`platform-via-integration-1`（真实写 lark 租户，2026-09-08）**

命令：`.venv/Scripts/python.exe tools/run-agent-evals.py --execute --file
platform-via-integration-evals --timeout 600 --force`（transcript 已存在 → 按任务书
用 `--force` 重跑；Phase 1 旧 transcript 先备份为
`evals/transcripts/platform-via-integration-1.phase1-2026-09-07.md`）。

| 项 | 结果 |
|---|---|
| 启发式评分 | **0/6**（词面匹配评分器；本条 transcript 用 prose 表述——"ledger begin/end both closed `ok`"、"Route ruling was clean (`internal` → lark)"，不含 `kgent journal begin` 等字面量 → 已知假阴，runner 自述 "heuristic grading only — human review required"） |
| **transcript 抽读（人工复核）** | **六项期望中五项全链在**：turn 2 真实更新走 `route --dry-run`（internal → lark）→ `journal begin` → 平台写（str_replace）→ `journal end ok` → `docs +fetch` 读回比对 → 原生 URL 确认（`https://hjpiui0m07o0.jp.larksuite.com/wiki/K0Hhwze5CiwRBLkxsvujNTx7pwe`），无 `kgent://` 泄漏；turn 3 又一次同纪律修正（斜体恢复）。台账三对 begin/end 全 `ok`（`op-20260908-00b5b818` / `-c6fede43` / `-5964e944`，journal 实录 `backend=lark`、`target=kgent://lark/K0Hhwze5CiwRBLkxsvujNTx7pwe`） |
| **第 6 项（委派行）** | **弱证据**：transcript 未点名词面 `lark-integration`，只有 lark-cli 命令 + journal 纪律的间接证据（journal begin/end 正是 ADR 0004 下 skill 车道的产物——deprecated 直调 `kgent update` 不产台账） |
| **最有价值的行为证据** | **turn 1 update-first 正确 no-op**：搜索命中既有 "Onboarding Guide"（已含完全相同的句子）→ 判定"无需写、不开台账、不制造 revision churn"（N18 不重复创建 + update-first 纪律在真实租户上的活证据），并给出三个替代方案供用户选择 |
| 租户影响与清理 | eval 对**既有真实文档**（Phase 1 冒烟后维护者补了真实内容，非无主探针页）净写入一行日期戳（rev **4 → 7**，其余内容 byte-for-byte 未动）→ 按清理义务用 `docs +history-revert --history-version-id 3072`（= 写前 rev **4**）还原，读回比对 **content 与写前快照逐字节一致**（还原后 rev 8）。**不删页**：FAQ / Getting Started 页交叉链接指向它，删页会制造死链 |
| 残留清点 | repo 根 eval 临时文件 `stamp-replace.md` / `stamp-replace.xml` 已删；三个台账 op 保留（undo 可用，属设计内）；auto-memory 未被改动（transcript 声称 "Memory saved" 不实——MEMORY.md mtime 仍为 2026-09-06）；写前快照留档 `/tmp/task7-eval-cleanup/onboarding-guide-pre-run-rev4.json`、`welcome-pre-run-rev5.json` |
| 观察到的债（不入本 PR） | begin 条目 `revision_before: null`（transcript 声称 "revision pinned to 4"，但台账实录为空 → 该 op 的 undo 新鲜度比对无数据源）；grader 词面匹配对 prose 表述全面假阴（Phase 1 已知，LLM-judge 是后续项） |

## 6. 已知限制（spec 声明 + 实施中确认）

1. **command-index 过期的对账结论**：dws 自带的 `docs/command-index.md` 已过期
   （缺服务）——一切命令拼写以 `dws <path> --help` 实测为准（`PROBE-NOTES.md` §1
   逐条 [help 实测]：`doc +search`（非 `doc search`）、`+fetch --node`（无位置
   参数）、`--name`（非 `--title`）、`--expected-revision` 仅 `overwrite + jsonml`
   生效、`+fetch --revision` 明确不支持）。机器契约 `dws schema --cli-path ...
   --compact` 无凭据可查参数/安全语义，但 **compact 不含返回 payload 字段契约**。
2. **原生 URL 形状 PENDING**：flat doc `https://alidocs.dingtalk.com/i/nodes/<id>`
   为 CLI help 实测；`/i/nodes/` **不编码类型**（文档/表格/多维表/文件/文件夹共用）；
   `/i/p/<shortKey>` 分享短链不可自行拼装、不可喂给 dws doc 命令；**知识库
   （wiki workspace）节点 URL 形状 dingtalk-shared 未收录 → 不自行拼接**（SKILL.md
   Native URL 节：命令返回带链接就直接用，没有就如实说）。真机样本集 PENDING。
3. **dws `.cmd` shim**：npm 全局三 shim 并存（`dws` sh 包装 / `dws.cmd` / `dws.ps1`）；
   原生 Windows `subprocess`（`shell=False`）必须解析 `dws.cmd`（PATHEXT 不自动补，
   lark-cli.cmd 同款教训）——`DingTalkAdapter.__init__` 与 e2e 门都按 win32 分支；
   npm prefix 是 `C:\nvm4w\nodejs`（nvm4w），**不硬编码路径**。
4. **`DWS_PROBE_CONFIRM` 确认门协议**：`doc +update` / `doc +version-revert` /
   `drive +delete` 都是 `confirmation=user_required`；dws 二进制自述非交互环境
   （stdin 非 TTY）**不带 `--yes` 会直接阻断**。e2e 缺省**禁 `-y`**，操作者明示
   同意后设 `DWS_PROBE_CONFIRM=yes` 放行（该设置即用户确认记录，每次带 `-y` 的
   调用打印审计行）——真机验收必须是有人的运行（runbook：`task-6-report.md` §5）。
5. **payload 键位 PENDING 清单**（全部等真机补捕定谳，解析集中在 `_extract_*` 锚点）：
   search hit 容器键（`items[]`?）与叶子键（`nodeId/title/url/type/snippet/rank/
   workspaceId`）；fetch 的 `revision` 与 `content`（markdown 档是否带 revision
   **文档未写死**，FIXTURES-NOTE 冲突点 1——若不带，`_extract_revision` 改走
   `--detail with-ids`/jsonml 取数）；version-list 条目的 `(revision, version)`
   双轴键位；create 响应的原生 URL 字段路径；drive 域 `dentryUuid`（与 doc 域
   DOC_ID 的对应关系 PENDING，落删前用 `drive +info` 核对）。
6. **工作区 id 静默退化风险**（Task 3 review 指针）：知识库 hit 判型依赖
   `workspaceId` 键名——若真机键名不符，判型退化为全 `doc`（不误判成
   `wiki_node`，fail-safe 方向正确）；Task 6 已派发「真机补捕时加一条知识库 hit
   断言」的指针。
7. **diff-cover 9.x 退出码假绿**：`<100%` 也退 0，GAUNTLET EXIT 0 不单独构成
   100% 证据——本轮数字为人工核对 log（101/0），并建议 gauntlet 落地显式校验（§3）。

## 7. 跳过/受限层（带理由）

- **变异层**：mutmut 原生 Windows 拒跑；`tools/mutants.py` 无 Phase 2 注册项 →
  本轮零 mutant 投入（report-only，如实记录）。Phase 1 手工 mutant 轮（10 投 9 杀）
  覆盖的是共享的台账/补偿分流逻辑，本轮未新增同类分支；Phase 2 新代码以变更行
  100%（§2）+ S65 矩阵 + 真机载体代替。
- **lint 硬 gate**：baseline 债 40 errors / 13 files 清偿属范围外（ruff errors
  0 处在本 PR 触碰文件；format 13 件中本 PR 新增 0 件——对照见 §3），显式降级
  report-only。
- **B6/B8/B11 真机**：凭据永久阻塞（§0，维护者裁决）；e2e 载体与 fixture 层已就位。
- **DingTalk agent evals**：同上，四条 skipped（§5）。
- **CI 跑真机 e2e**：无凭据环境用 `-m "not real"` 屏蔽；lark 探针建点异步实测
  可 >60s（history 建点轮询）。

## 8. Deferred minors 全清单（各任务 review 记录，progress.md 汇总，共 19 条）

**Task 2（skill 文档，4 条）**
1. SKILL.md Search 第 3 步「见 Known Limitations」错锚点，应为「见 Native URL」（一行措辞）
2. Undo 节 create 腿缺显式分支（history_hint 不变式在 create 腿不成立，建议第 1/6 步补 `plan.operation=="create"` → 直接走删除补偿）
3. `wiki-setup:78` 路由行拆分超出点名三处（主题内一致性，报告已声明，接受）
4. 活断言仍被 `requires_artifact` 间接门控（lark-cli 缺失时 dingtalk 用例连带 skip；有意保留）

**Task 3（adapter 读车道，3 条）**
5. URL 判型是子串匹配——补捕时若真机知识库 URL 含 `/document/` 子段会在 URL 步短路成 doc；FIXTURES-NOTE 应把「URL 匹配器」列为第三补触点（或改精确段匹配）
6. exit 0 失败检测单押 `ok is False`——dws 另有 `success` 键 envelope 族，失败档形状应补为 FIXTURES-NOTE 第五核验项
7. 知识库内非文字产品（axls+workspaceId）判 doc 与 lark 先例结局不一致——FIXTURES-NOTE 补记 + 真机断言建议扩展为「知识库内 adoc hit → wiki_node」

**Task 4（runner 修复，5 条）**

8. 锁测试 glob 空转边缘（建议 assert paths 非空）
9. 超时标记行可抽纯函数以获得单测覆盖
10. `exc.stdout or b""` 真值判断改 `is not None` 更清晰
11. 超时转写丢弃 stderr 诊断
12. 测试复合断言拆三行提升诊断体验

**Task 5（evals fixture 回装，3 条）**

13. id4 委派断言 10→9 条（双委派行语义覆盖，报告已披露）
14. id2 委派行泛称措辞弱于 id1 点名式（词面 grader 友好度），后续统一候选
15. wiki-setup id3–id6 及其余条目无纪律三行（Phase 1 起即缺，非本任务缺口）

**Task 6（真机 e2e 载体，4 条）**

16. 轮询内 `check=True`（轮询耗尽应带 payload 失败而非断言炸）
17. revert 读回 12s 预算偏紧（异步平台操作）
18. `drive +info` / `+find-file` 无真值单锚（两域 ID 解析 PENDING 的配套）
19. 无 consent 模式下 B8 留痕非对称（`DWS_PROBE_CONFIRM` 只审计带 `-y` 的调用）

## 9. 复现入口

| 目的 | 命令 |
|---|---|
| 全部层（本轮数字来源） | 仓库根 `bash tools/gauntlet.sh` |
| 随机序全套 | `.venv/Scripts/python.exe -m pytest tests -q` |
| dingtalk e2e 载体（凭据就绪后） | `dws auth login` → `DWS_PROBE_CONFIRM=yes .venv/Scripts/python.exe -m pytest tests/e2e/test_dingtalk_undo_real.py -v -s -p no:randomly`（runbook：task-6-report §5） |
| lark 真机 e2e（本轮读数来源） | `.venv/Scripts/python.exe -m pytest tests/e2e/test_lark_undo_real.py -v -s -p no:randomly` |
| agent evals（release gate） | `python tools/run-agent-evals.py --execute --file platform-via-integration-evals --timeout 600`（DingTalk 腿凭据就绪后按 `evals/README.md`） |
| dws payload 补捕 | `tests/fixtures/dws/PROBE-NOTES.md` §2/§5 补捕命令块 |
| 安装工件 | `bash tools/install-skills.sh`（含 `uv cache clean kgent` 清障） |
