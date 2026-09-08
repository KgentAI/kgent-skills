# FIXTURES-NOTE — tests/fixtures/dws/（Phase 2 Task 3）

**Provenance: documented shape from dws native-skill references; NOT live-captured
（credentials unavailable, 2026-09-08）.**

- 维护者裁决（2026-09-08，progress.md）：无有效钉钉账号，真机捕获永久阻塞。
  本目录两份 payload fixture 按文档形状构造，**不是真机输出**；B6/B11 的真值
  实证状态以仓库 EVIDENCE 为准，fixture 绿 ≠ 真机验收。
- 形状来源（按优先级，冲突以能与 `PROBE-NOTES.md` §1 命令真值对上者为准）：
  1. `PROBE-NOTES.md` §1 命令真值表 [help 实测]——`doc +search`、
     `doc +fetch --node`、`-f json`、`--limit`（默认 10 最大 30）；
  2. 原生 skill `~/.agents/skills/dingtalk-doc/`（dws 团队对着真 API 写）：
     `SKILL.md`（搜索外层 `complete/count/failures`）、`references/contracts.md`
     （doc.operation.v1 外层 `ok/status/complete/data/...`、分页
     `hasMore/truncated/stopReason`、目标至少保留 `nodeId`/资源类型/canonical
     URL）、`references/doc/doc-create.md`（`data.nodeId/verified` 实例）、
     `references/doc/doc-read.md`（fetch 默认 `--detail simple --scope full`
     返回 Markdown；revision 是编辑版本号）；
  3. 原生 skill `~/.agents/skills/dingtalk-shared/references/url-patterns.md`
     （URL 形状事实：`/i/nodes/` 不编码类型、`/document/{edit|preview}`、
     `/spreadsheetv2/`、`/i/p/` 分享短链；路由依据是 `extension`）；
  4. 原生 skill `~/.agents/skills/dingtalk-wiki/references/wiki-node-ops.md`
     （节点结果的 `extension/type/.../parentFolderId`、workspace 容器事实）。
- 文件清单：
  - `doc-search.json` — `dws doc +search --query "kgent-phase2-probe" -f json`
    的期望形状。三条 hit 覆盖类型判定三步：扁平文档（`/i/nodes/` + `type=adoc`）、
    知识库文档（同 URL 形状 + `workspaceId` 容器事实）、非文字文档产品
    （`/spreadsheetv2/` + `type=axls`）。
  - `doc-fetch.json` — `dws doc +fetch --node mXk4Qw7bZnVc2yPq8RtJeH -f json`
    的期望形状（`--detail simple` 默认档）。
  - `version-list.json` **未建**——Task 3 读车道不消费该命令（revision 从
    `+fetch` 取），不为未消费的命令发明形状；undo/version-revert 腿（integration
    skill）真机补捕时再按实测落盘（PROBE-NOTES §5 补捕命令含它）。
- 值的可信度分级：**外层/容器键**（`ok/status/complete/count/hasMore/failures/`
  `items`/`data`）有文档实证；**叶子键名**（`nodeId/title/url/type/snippet/rank/`
  `extension/revision/content/workspaceId`）是「文档语义名 + dws 惯用 camelCase」
  的构造值——dws `schema --compact` 不含返回 payload 字段契约（PROBE-NOTES §1.4
  [help 实测]），叶子键名必须等真机补捕定谳。**解析代码不散落读这些键**：
  全部集中在 `src/kgent/adapters/dingtalk.py` 模块级 `_extract_*` 帮助函数
  （键位对账锚点），补捕后只改锚点 + 回填本目录 fixture。

## 文档间冲突点（按 PROBE-NOTES 对上者裁决）

1. **fetch 的 revision 出现档**：`dingtalk-doc/references/doc/doc-read.md` 说
   revision「JSONML 读取响应返回」，而 adapter 读车道走默认 markdown 档
   （`--detail simple`）。markdown 档响应是否带 `revision` 文档未写死——fixture
   按「读响应携带 revision」构造（B6 需要），补捕时验证；若 markdown 档不带，
   锚点 `_extract_revision` 需改为 `--detail with-ids` 或 `--doc-format jsonml`
   的取数路径。
2. **搜索命中容器键**：`SKILL.md` 证明外层有 `complete/count/failures`，但命中
   数组键名（`items` vs `data.items` vs `results`）文档未点名；PROBE-NOTES §2
   把「是否在 `items[]` 下」列为 PENDING。fixture 取 `items[]`（contracts.md 的
   partial 分支已用 `details.items` 命名，`items` 是同族容器键）。
3. **类型字段名**：`dingtalk-shared` 说路由依据是 `extension`；
   `dingtalk-wiki/wiki-node-ops.md` 说节点结果的 `extension/type` 互为规范化
   别名；PROBE-NOTES §2 记的字段名是 `type`。fixture 主用 `type`（search hit）/
   `extension`（fetch data），解析锚点对两者都认（`_extract_hit_type`）。
4. **知识库 hit 的判型事实**：知识库（wiki/workspace）节点 URL 形状
   [PENDING-凭据]（PROBE-NOTES §3），URL 路径段对知识库/扁平文档**不可判型**
   （`/i/nodes/` 共享）。fixture 用 `workspaceId` 容器事实判 `wiki_node`——
   该叶子键名同样待真机定谳；`_node_type_from_hit` 的判型顺序不因补捕改变，
   只改 `_extract_*` 锚点。
