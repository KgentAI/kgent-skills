# FIXTURES-NOTE — tests/fixtures/dws/

**Provenance: live-captured 2026-09-09（dws v1.0.61 真机，MergeGameStudio 租户；
B6/B8 兑现轮修复半场）.**

- 前史：2026-09-08 维护者无账号裁决下，`doc-search.json`/`doc-fetch.json` 曾以
  **documented-not-captured** 形态落盘（叶子键名是构造值）。2026-09-09 B6/B8
  真机兑现轮首跑 3/3 failed（命令形状类——documented 锚点与真 payload 漂移，
  见 `.superpowers/sdd/2026-09-08-phase3-wecom-integration/dingtalk-closure-report.md`
  §3/§4），修复轮按真值回填：**全部 payload 原样真机捕获，键位定谳**。
- 纪法（PROBE-NOTES §6）：结构原样保存；**身份信息剥除**（`version-list.json`
  的 `userId` → `[user-id-stripped]`）；标题保留 verbatim——它们是 e2e 的
  `PROBE_TITLE` 探针协议名，非个人身份；URL/utm 跟随参数/logId 保留（fixtures
  是 B11/adapter 的真值来源）。
- 真机命令（捕获原样）：
  - `dws doc +search --query "kgent-phase2-probe" -f json` → `doc-search.json`
  - `dws doc +fetch --node <DOC_ID> --detail with-ids -f json` → `doc-fetch.json`
  - `dws doc +fetch --node <DOC_ID> -f json`（默认 `--detail simple`）→
    `doc-fetch-simple.json`
  - `dws doc +version-list --node <DOC_ID> -f json` → `version-list.json`
  - `dws drive +info --node <DOC_ID> -f json` → `drive-info.json`
  - `dws drive +find-file --query "kgent-phase2-probe" -f json` →
    `drive-find-file.json`
  - `dws drive +delete --node <DOC_ID> -y -f json` → `drive-delete.json`
- 文件清单与锚点定谳（解析锚点全在 `src/kgent/adapters/dingtalk.py` 模块级
  `_extract_*`；测试侧在 `tests/e2e/test_dingtalk_undo_real.py` 的 `_extract_*`）：
  - `doc-search.json` — `doc.list.v1` 外层；命中容器键 **`documents`**（非
    `items`/`data.items`）；hit 键 `nodeId`/`name`/`docType`/`url`/
    `modifiedTime`，**无 `snippet`、无 `rank`、无 `title`、无 `type`**。
    真机分页语义：3 命中（< limit 10）也报 `complete:false + hasMore:true +
    stopReason:single_page`；0 命中才是 `complete:true +
    stopReason:source_complete`（`search-after-clean` 观测）。
  - `doc-fetch.json`（with-ids 档）— `doc.content.v1` 外层，目标块是**顶层
    `content`**（外层无 `data`）；`content.revision` = **字符串** `"1"`；
    正文键是 **`jsonml`**（JSONML 字符串，**非 markdown**）；键集
    `docUrl/jsonml/logId/nodeId/revision/success/title`。
  - `doc-fetch-simple.json`（默认档）— 同外层；正文键 **`markdown`**；
    **无 `revision`、无 `jsonml`**。⇒ dws **没有任何单档同时携带 markdown 与
    revision**（`--detail full` 与 with-ids 同键集，另测）——adapter
    `read_document` 两枪：with-ids 取 revision，默认档取正文。
  - `version-list.json` — 外层 `hasMore/success/versions`；条目只有
    `version`（int）+ `createTime/updateTime/type/userId`，**无 revision 字段**
    ⇒ revision→version 映射走替代通道
    `doc +fetch --version N --detail with-ids` 读 `content.revision`
    （真机实测 1:1：`--version 0 → "0"`、`--version 1 → "1"`；历史档 `content`
    另带 `historyVersion` 键）。新建文档即有两版本（0=AUTO_SAVE、1=OVERWRITE）。
  - `drive-info.json` — `data.fileId` = **32 位 DOC_ID 本体**；
    `data.dentryId` 是 **12 位内部号**；另有 `spaceId/path/extension/type`。
  - `drive-find-file.json` — `files[].dentryId` = **DOC_ID 本体**（与
    `drive +info` 的 `fileId` 一致）⇒ drive 域删除句柄 = DOC_ID，
    两域 ID 对应关系定谳。
  - `drive-delete.json` — 删除响应：`ok/outcome/data.nodeId/data.result.
    {message,success}/data.success`（回收站语义，30 天可恢复）。
    `drive +delete` 拒收 12 位 `dentryId`
    （「nodeId 须为 dentryUuid：32 位字母数字字符串」）。
- `create` 响应（未落 fixture，e2e 消费）：`doc.operation.v1` 外层
  `ok/compensation/complete/data/steps/warnings`；`data.nodeId` 真机证实；
  `data.verification.verified/readbackSha256` 自带读回校验；**全块无 revision**。
- 仍为 documented-not-captured（真机未覆盖，保留构造值测试替身）：知识库 hit
  的 `workspaceId` 容器事实（真机 search 命中全为扁平 adoc）与非文字文档 hit
  （`docType: axls`）——B11 判型三分支里这两支用内联合成 payload 测
  （`tests/test_dingtalk_adapter.py`，已标注 synthetic）。
