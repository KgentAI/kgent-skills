# EVIDENCE — decision-navigator 评审门（2026-09-20 · ADR 0014 · spec 2026-09-20-decision-navigator-review-gate-design）

## 1. Fresh final run

- **命令**：`PYTHONPATH=src bash tools/gauntlet.sh`
- **位置/状态**：worktree `worktree-dn-truth-grounding`（基点 origin/main tip `8ec96d6`，改动未提交工作树态），2026-09-20
- **结果**：**GAUNTLET PASS（exit 0）**，全层绿。完整日志 `/tmp/gauntlet-dn-review-gate-final2.log`（scratch，仅转录数字；复现入口是命令本身）

## 2. Per-layer gauntlet numbers

| 层 | 结果 |
|---|---|
| A artifact smoke（硬门） | **18/18** surface probes passed（installed CLI 面） |
| clean | ok |
| tests + coverage（`-m "not real"`，PYTHONPATH=src） | **731 passed / 0 failed / 4 skipped / 10 deselected**，196.28s；coverage TOTAL 4741 stmts **87%** |
| changed lines（diff-cover） | "No lines with coverage information in this diff"——**vacuous pass，如实申报**：本 diff **零 `src/kgent` 变更**（组件表可查）；新 checker 在 `tools/`，经 subprocess 黑盒执行，不在 coverage 钩子内 |
| types（mypy src） | **Success: no issues found in 53 source files** |
| lint（report-only） | 既有全仓债务照旧：ruff **1 error**（`tests/test_ledger.py:187` F841，既有）+ **17 files would be reformatted**（全既有）；**本 diff 三个新文件 ruff check 0 错、format 稳定**（专项跑过：`All checks passed!`） |
| mutation（report-only） | mutmut native Windows 不可用（boxed/mutmut#397）；`tools/mutants.py` fallback：无手工突变注册——与历次 close 相同 |
| properties | **19 passed**（17 既有 + 本 diff 新增 2） |
| adversarial | **39 passed** |
| secret scan | pass |
| N14 network capture | enforced via test fixture |
| local-fs flow conformance | **both modes passed**（git-backed + snapshot，throwaway homes，installed artifact） |

## 3. Behavior → test mapping（R1–R12）

> 2026-09-21 更新：agent-eval release gate 已真跑（9/9，见 §4）——下表「eval 待发布轮」各项转为「已跑，人工签署进行中」。

| # | 行为 | 断言层 | 状态 |
|---|---|---|---|
| R1 | 呈报前评审门标记 + 执行方式三态枚举 | `dn_review_check`（缺头/未知方式/重复头/未执行形态 6 用例）+ eval expectations（案例 1/8/9）+ transcript 人工审查；「每呈报点恰一次」属 transcript 层（checker 只管单份结论） | 绿（单元）/ eval 待发布轮 |
| R2 | 评审包固定四件 | SKILL.md 文法节（文面契约）+ eval `expected_output` + 人工审查——**无机器断言器，如实声明** | 文面落定 / 人工审查待 eval 轮 |
| R3 | 两节齐备、节序、头先于节 | checker 正控 5 例（CLEAN_DISPATCH/INLINE/NO_FINDINGS/AT_CAP/UNEXECUTED）+ 缺节/逆序/空节负例 | 绿 |
| R4 | 严重级/核对方式枚举封闭 | checker 负例（[重大]、缺核对方式、逻辑节带核对方式、残缺行）+ property 注入（非法严重级恒 exit 1） | 绿 |
| R5 | 引用逐条申报解析（n ≤ m） | checker（缺申报行 / 5>3）+ eval 案例 1 expectation | 绿 |
| R6 | 实证复核 ≤3/结论 | checker（超限 exit 1 / `--max-spot-checks 5` 放行）+ property（生成器构造性 ≤3） | 绿 |
| R7 | 评审者不修正、修正归导航者 | SKILL.md 清单条 5 + §6 修正纪律；eval 案例 8（导航者修正 + 「已修正 a 处」注记）+ 人工审查——机器不可断言部分如实声明 | 文面落定 / eval 待发布轮 |
| R8 | 未决折入既有章节、简报文法零改动 | eval 案例 1/5 expectations + `dn_brief_check` 回归（简报 30 用例 + property 全绿含于 731；`tools/dn_brief_check.py` 零改动） | 绿（回归）/ eval 待发布轮 |
| R9 | 致命 → 排序挂起（复用零证据降级） | eval 案例 5 既有挂起断言 + 新增评审门 expectation | eval 待发布轮 |
| R10 | 致命/可修修正后恰一次 delta 再查 | transcript 结构断言（同 gate 至多两份结论）+ 人工审查——checker 单文件单结论，无法跨结论计数，**如实声明** | eval 待发布轮 |
| R11 | 无派发宿主走内联并标注、永不静默跳过 | runner 无 Task 工具 → evals 天然全走内联路径；eval 案例 1 expectation（`【评审门 · 执行方式：内联复查】`） | eval 待发布轮 |
| R12 | 评审面语言跟随请求（结构记号固定中文） | eval 案例 9（英文请求，正文英文 + 中文结构记号）+ 案例 7 增补 expectation | eval 待发布轮 |

**RED 见证**：`tests/test_dn_review_check.py` + property 先于 checker 存在运行——**25 failed / 4 passed**（4 个 pass 为 fail-closed exit-2 用例：缺脚本本身 exit 2，非契约见证；全部契约用例目睹失败）。checker 落地后 **29/29 绿**（单元 27 + property 2；hypothesis 50+30 examples，derandomize）。

## 4. Skipped layers 与理由

- **real 平台腿**：本 diff 零平台集成改动（无 src/、无 integration skill 触碰）→ 按 2026-09-11 维护者裁定 opt-out；e2e 由 local-fs flow 双模式覆盖。
- **mutation**：平台限制，report-only（既有，非本次新免）。
- **agent evals（release gate）——已于 2026-09-20/21 真跑（9/9 案例，serial ~6h45m；随附一次作废腿与一次案例 5 重跑）**：
  - **作废腿（如实入档）**：首轮 launch 未验证 skill 装载面——runner 派生裸 `claude -p`，本机无任何 kgent skill 安装点，headless 会话凭 prompt 自行发挥（transcript 零 SKILL.md 读取、零评审门标记）。修复：worktree 建 `.claude/skills/`（项目级 skill 发现，8 个 kgent skill 镜像，不入库）；作废 transcript 归档 `evals/transcripts/backup-20260911-pre-review-gate/void-run-*-stale-skill.md`。教训：**runner 不接线 skill 目录是结构缺口**（follow-up 候选：runner 显式接线或安装校验）。
  - **结果**：9 案例 heuristic 全 0 hits（双语 prose 断言的文档化局限，与前例一致）；verdict 依人工 transcript 复核：**9/9 PASS**——案例 2 反触发零门正确；案例 4 申报真实 `评审未决`；案例 6 逐门恰一次 delta 且自陈 R10 上限推理；案例 8 评审门抓出预置的无出处动机（1 致命）并关闭假二选一；案例 9 英文评审正文 + canonical 门标记。**案例 5 首跑候选 R9 缺口**（完整加权排序、无排序挂起、终局评审无致命）→ 维护者裁决 `--ids 5 --force` 重跑（首跑归档 `candidate-r9-miss-leg1.md`）。**重跑裁决（2026-09-21）：转 PASS，判定为运行方差而非系统缺口**——同一 prompt 下正确走零证据降级（「本轮不排序」+ 挂起加权排序 + `低——…纯假设推演` 置信钉 + 何者会改变排序的恢复条件）；评审门 派发评审 ×2、`dn_review_check` ×3 份结论与 `dn_brief_check` 简报**首次机器执行各 0 violations**（python 入 allowlist，2ebc898），无 turn 超时。
  - **FM-R9 修正（关键发现）**：headless 会话**实际派发了子代理**（live session 6 个 subagents、多个 subagent transcript 含 评审结论；各案门标记均 执行方式=派发评审）——spec Q13/FM-R9 的「runner 无 Task 工具 → 只能走内联路径」假设**不成立**，真派发路径已被 evals 实证覆盖；原「真派发以人工审查覆盖一次」的分期约束作废（runner allowlist 的显式 Task 断言补齐仍属 follow-up）。
  - **发现清单（人工签署材料，7 项）**：① 案例 5 R9 —— **已关闭：运行方差（重跑 PASS，leg 9/9）**；② 案例 6/7/8 将工件写入 `.dn-scratch/`——B12「永不写盘」候选违规，支持 #14 遗留建议（read-only eval 腿收回 Write/Edit）；③ 门标记 4 种渲染变体（【评审门 · 执行方式：…】/ `**评审门：（派发评审）**` / `**评审门 · 执行方式：…**` / `**评审门**（派发评审）`）——SKILL.md 应钉死一种；④ 案例 7 自陈对评审者输出做 line-form normalization 后再跑 checker——checker 必须审 as-emitted 结论；⑤ runner allowlist 无 `python`——**已修复（2ebc898）：`Bash(python:*)` 入列，案例 5 重跑即首次机器执行双 checker 各 0 violations**；⑥ 即上述 FM-R9 修正；⑦ 案例 8 预算矛盾经澄清道化解而非作为评审发现条目——预期措辞与路径等价之争。另：eval 长跑运维教训——per-turn timeout 必须保留（一次 `--timeout 86400` 的案例 5 重跑停滞 9.5h 被杀，1800s 重跑 ~80min 完成）；`--parallel` 分区单位是 eval 文件（单文件串行），多 case 并行需按 `--ids` 拆多进程。

## 5. 环境注意（含失败/修复日志——6 轮 gauntlet 全记）

- **PYTHONPATH=src 必须**：本机 ambient editable install 把 `kgent` 指向陈旧 worktree（另一会话的 feat/install-gate checkout）。不带它，pytest import 错包——run1 的 `test_cli_doctor_healthy` 失败即此（报错文本 "not installed in any agent skills dir" **不在本分支源码中**，铁证）。`tools/gauntlet.sh` 自身不设 PYTHONPATH，本机唯一正确跑法 `PYTHONPATH=src bash tools/gauntlet.sh`。**后续建议**：gauntlet 自带 `PYTHONPATH=src` 或断言 `kgent.__file__` 在本仓（另行 spec）。
- run1（无 PYTHONPATH）：suite 1 failed（doctor，void——错包）。
- run2（PYTHONPATH=src）：1 failed——`test_p2_repair_idempotence` hypothesis 200ms deadline 的 Windows 抖动（首例 291.5ms → 复跑 8.6ms）。**修复**：按 hypothesis 官方处方 `deadline=None`（幂等断言零改动）；同批预防性加给本 diff 新增的两个 subprocess 性质测试。`test_dn_brief_props.py` 属同类暴露、既有且不在本 diff——列为潜在抖动点，未动。
- run3：**GAUNTLET PASS**（tail 捕获，全量日志未存）。
- run4（试录全量日志）：suite **42 failed / 32.57s** + 后台任务被 ~10 分钟上限杀掉——**瞬时机器态漂移**：并发 install-gate 会话正在做安装态手术，CLI probes（docs conformance 8 例全挂）、installer 用例（14 例）、local-fs git 用例（9 例）、real-config smoke（4 例）同时失败；`kgent config validate` 数分钟后自愈，诊断轮两遍 **731 passed 全绿**。同一 diff 在 run3/run5/run6 三次 PASS——run4 失败与本 diff 无因果。教训：并发会话动安装态期间不录证据；录制轮用前台（600s 内可完成）。
- run5：GAUNTLET PASS（全量日志）；lint 层暴露本 diff 新文件进了 would-reformat 名单 → `ruff format` 三个新文件 + 修掉 checker 的 E741（歧义名 `l`）——新文件不添债。
- **run6（最终录制）**：GAUNTLET PASS exit 0，§2 全部数字出自此轮日志。
- hypothesis 失败会在 `.hypothesis/patches/` 留 patch 建议——未采用（gitignored）。

## 6. Conclusion + Reproduce

评审门（ADR 0014）实现完成且全量绿：SKILL.md 新 §6 方案评审（简报顺延 §7）+ 评审包/独立评审清单/评审结论文法（与断言器逐字对齐）+ 评审纪律节；`tools/dn_review_check.py`（stdlib-only、fail-closed 三态、`--max-spot-checks` 可调）；29 黑盒用例 + 2 property（RED→GREEN 全程目睹）；evals 7→9 案例 + 既有案例增补；CONTEXT.md +3 词条与 ADR 0014 随 grill 落。两次全量 GAUNTLET PASS（run3/run6，同一最终代码态以 run6 为录制轮）。agent evals release gate 已于 2026-09-20/21 真跑并签署：**leg 9/9**（案例 5 经重跑裁决为运行方差，见 §4；真派发实证见 FM-R9 修正）；runner allowlist 已补 python（2ebc898，双 checker 首次机器执行 0 violations）。余：§4 发现清单的 follow-up 处置（runner skill 接线、门标记钉死、checker as-emitted、Write/Edit 收回）。

**Reproduce**：

```bash
PYTHONPATH=src bash tools/gauntlet.sh
PYTHONPATH=src python -m pytest tests/test_dn_review_check.py tests/properties/test_dn_review_props.py -p no:randomly -q
python tools/dn_review_check.py <结论.md>          # exit 0 = 评审结论合规
python tools/run-agent-evals.py --execute --file decision-navigator-evals --parallel 3 --timeout 600   # 发布前
```
