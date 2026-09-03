# Handoff Spec: search/read 将 wiki 节点误标为 `doc`，导致原生引用链接为死链

- **Date:** 2026-09-02
- **Status:** implemented (2026-09-03) — adapter 层全量落地，真机验收通过
- **Priority:** high — skills 的引用链接（N20/S74/S85）在 wiki 内容上全部打不开
- **Discovered while:** 排查「新人入职」问题时用 `drive +search` 反查 kgent 结果的原生 URL（见“实证”）

## 实施结果（2026-09-03）

按“分层修复”落地，有一处基于实测证据的关键修正：

- **实际执行路径是 CLI adapter，不是 skill 委托。** 代码里“尚无 skill 调用实现”
  （`lark.py` docstring）：`kgent` CLI 经 registry 恒以 `LarkAdapter`
  （`docs +search` / `docs +fetch`）执行 search/read，config 的
  `type: skill` 只影响 resolve 的 `adapter_name` 命名。因此本 spec 的修复
  全部落在 adapter 层；skill 委托契约写入 `lark.py` 模块 docstring 备将来。
- **类型事实比预期更便宜：`docs +search` 本身就带。** 实测每条 hit 携带
  `entity_type`（`WIKI`/`DOC`…）与 `result_meta.url`（路径段 `/wiki/` vs
  `/docx/`，含 `#块锚点`/`?sheet=` 噪声）。零额外调用即可定 `node_type`，
  无需按原方案改用 `drive +search`。

### 改动

| 位置 | 内容 |
|---|---|
| `src/kgent/adapters/lark.py` | `_node_type_from_hit`（url 路径段优先，`entity_type` 兜底，其余保持 `doc`，不从 token 推断）；read 用一次 `wiki +node-get` 探测（成功 → `wiki_node`+space 位置；`131005 not_found` → `doc`；其它失败 → 退化为 `doc`，绝不抛异常）；search 对 wiki hit 做有界探测补 `space_id`/`parent_node_token`（cap 8 次 + 4s 墙钟预算——`fanout` 超时整个后端作废 S33，探测绝不越过预算；探测失败只缺位置字段，**永不降级 node_type**） |
| `src/kgent/adapters/cli_adapter.py` | 协议 v1 通用路径：可选解析 `node_type`/`space_id`/`parent_node_token`，词表外/缺失一律 `doc`（N12：CLI 输出是未校验输入） |
| `tests/test_lark_node_type.py` | 16 个 fixture 驱动用例（真实 payload 形状，不起真 lark-cli）：两条路径的赋值/缺省、锚点与 query 噪声、非 doc 实体（BITABLE）保持 `doc`、探测失败/超时退化、cap 与预算 |

### 真机验收（2026-09-03，租户 `hjpiui0m07o0.jp.larksuite.com`）

- wiki token `Lsu5wOin…`：search 与 read 均输出 `node_type: "wiki_node"`，
  read 的 `space_id` 与服务端 `wiki +node-get` 原始返回一致（`7534610915493150753`）。
- 普通 docx `Xg8sdBt8…`：两条路径仍为 `node_type: "doc"`。
- `native_url` 渲染结果与 Lark 服务端自己的 `result_meta.url` **逐字符一致**
  （wiki → `/wiki/`，doc → `/docx/`）——即浏览器可打开的规范链接。
- 全套 446 passed / 2 skipped（Windows 既有跳过），ruff/mypy 干净。
- 已知留痕：search 中部分 wiki hit 的 `space_id` 为 `None` —— 探测身份对
  该空间无读权限（如他部门“Kgent测试版”所建节点），按设计退化，类型不失真。
- 未做（按原 spec 范围外）：metas 970005 权限模型；capabilities cache 的
  `unverified: [node_type]` 标注（仓库尚无该机制，未为其新造）。

## 问题陈述

`kgent search` / `kgent read` 输出中的 `node_type` 在 lark 后端上**恒为 `"doc"`**，
即使底层实体是知识库（wiki）节点。skills 依据该字段渲染原生链接
（`skills/urls.py` 的 `_LARK_PATH = {"doc": "docx", "wiki_node": "wiki"}`），
于是 wiki 文档被渲染成 `https://<domain>/docx/<token>` —— **死链**。
正确链接是 `https://<domain>/wiki/<token>`。

同时 `space_id` / `parent_node_token` 也恒为 `null`（§7.2 承诺 wiki 结果携带
空间与父位置信息，实际从未发生）。

## 实证（2026-09-02 会话记录）

本机 lark 后端配置为 `type: skill, skill_name: lark-approval`。对 8 个 kgent
搜索结果逐个用 `lark-cli drive +search`（用户身份）反查：

- kgent 全部返回 `node_type: "doc"`、`space_id: null`；
- Lark 服务端对同样的 8 个 token 返回 `entity_type: "WIKI"`，规范 URL 均为
  `https://hjpiui0m07o0.jp.larksuite.com/wiki/<同一 token>`；
- 按 kgent 的 node_type 渲染 `/docx/` 链接 → 打不开；
- `lark-cli wiki +node-get --node-token <token> --obj-type docx` 报
  `131005 not found` —— 这批 token 是 wiki node_token，不是 obj_token，
  也反证 kgent 索引的 lark token 实为 node token；
- `drive metas batch_query` 对全部 token 返回 `970005`（user/bot 均无权限），
  说明“元数据接口补全类型”在该权限模型下不可行，不能作为修复依赖。

## 根因（代码定位）

`node_type` 字段存在且类型正确（§7.2 设计未缺失），缺的是**赋值路径**：

| 位置 | 现状 |
|---|---|
| `src/kgent/types.py:31` (`DocumentMetadata.node_type`) | 默认 `"doc"`，无人改写 |
| `src/kgent/types.py:61` (`SearchResult.node_type`) | 默认 `"doc"`，无人改写 |
| `src/kgent/adapters/cli_adapter.py:296-313` (`search_by_keywords`) | 构造 `SearchResult(DocumentMetadata(doc_uri, title, backend))`，不设 node_type/space_id/parent_node_token |
| `src/kgent/adapters/cli_adapter.py:218-224` (`read_document`) | 同样不设 |
| skill 委托路径 `src/kgent/router/resolve.py:254-256` | `skill_name` 后端的 search/read 完全委托给平台 skill（如 lark-approval），结果回到 CLI 时 node_type 仍是默认 `"doc"` —— **两条路径都不会产生 `wiki_node`** |

对照：wiki **写入**路径是完整的（`router/policy.py:381-538` 在 create/update
wiki 节点时正确记录 `node_type: "wiki_node"` 到 journal）。坏的只是**读取/搜索**侧。

## 建议方案

核心原则：**node_type 必须来自服务端事实，不得从 token 形状推断**（§3.6/N23
精神）。分层修复：

1. **skill 委托路径（本机实际命中的路径，优先修）**
   - 定义委托结果契约：平台 skill 返回的搜索/读取结果需携带
     `node_type`/`space_id`/`parent_node_token`（缺省视为 `"doc"`，向后兼容）。
   - 在 lark 侧平台 skill 中，用一次 `lark-cli drive +search`（而非 metas，
     见实证第 4 条）获取 `entity_type` 与 `result_meta.url` 的路径段
     （`/wiki/` vs `/docx/`）作为类型事实来源。
2. **CLI adapter 路径**
   - `CliCapabilityAdapter.search_by_keywords` / `read_document` 从 CLI 的
     结构化输出解析 node_type；协议里没有该字段时保持 `"doc"` 并在
     capabilities cache 中标记 `unverified: [node_type]`（N12 风格）。
3. **兜底自检（可选，低成本高收益）**
   - `kgent read` 时若 URL 渲染 404 风险高（无法本地判断），至少在
     `kgent doctor` 增加 finding：lark 后端返回的采样结果中 wiki 实体占比
     异常（全 `doc`）时提示 node_type 可能失真。

## 验收标准

- [ ] 对一个已知 wiki 节点 token：`kgent search` 输出 `node_type: "wiki_node"`
      且带 `space_id`；`kgent read` 同。
- [ ] 对一个已知普通 docx：仍输出 `node_type: "doc"`。
- [ ] `native_url(uri, domain, node_type=...)` 对两者分别渲染 `/wiki/`、
      `/docx/`（已有逻辑，回归即可）。
- [ ] skills（question-answering / knowledge-storage / wiki-setup）端到端引用
      链接在浏览器中可打开。
- [ ] 单测覆盖两条路径的赋值与缺省行为；不依赖真实 lark-cli（fixture JSON）。

## 范围外

- metas 970005 权限问题本身（平台侧权限模型）。
- `workspace_domain` 缺失问题 —— 已由 `kgent config set-workspace-domain`
  处理（另见本次同日实现）。
