# 0016 — confluence 内容格式桥：markdown ↔ 最小 storage XHTML，有损显式声明

Confluence Cloud v2 REST 的页面正文没有 markdown 表示（storage XHTML 或 ADF JSON），而 markdown 是 kgent 的内容通用语。决定建**格式桥**：读 = storage XHTML → markdown，写 = markdown → 最小公共子集 storage XHTML（`p`、`h1–h6`、`ul/ol/li`、`code/pre`、`table`、`blockquote`、粗斜体、链接）；桥外结构（宏 `ac:structured-macro`、附件/媒体、锚点、表情、内嵌数据库等）读取时降级为占位 + 保真声明，写入时不支持即拒绝构造，绝不静默丢弃内容。双向转换以 stdlib 实现（`html.parser` + 转义），零新依赖，落点 `kgent formats` CLI（skill 与 adapter 共用同一实现，不允许两套转换器漂移）。

## Considered Options

- **ADF (atlas_doc_format) 为 kgent 侧格式**：被否——JSON 树冗长且对 agent 不可读不可写，违背「markdown 通用语」立场；社区与脚本生态亦以 storage XHTML 为主。
- **社区 markdown↔wiki 转换器依赖**：被否——repo 零运行时依赖是硬约束（pyproject `dependencies = []`），且外部转换器不保证与 Confluence storage 方言同步。
- **skill 层 prose 描述转换规则、无共享实现**：被否——两套转换器（skill 手写 vs adapter 代码）必然漂移；conversion 是正确性敏感代码，必须在 pytest/property 覆盖内。

## Consequences

- `kgent formats` 进 CLI 面（surface manifest 两探针），docs-conformance 校验 skill 中的调用示例。
- 保真声明进 `adapters/fidelity.py` 与 skill 已知限制：复杂宏/媒体读为占位、写不支持；首次转换即声明，不是出了问题才声明。
- 恶意/畸形 XHTML 是对抗面（脚本注入、畸形嵌套）：转换器按对抗语料测试，输出 markdown 时脚本内容剥离并转义。
- round-trip 仅对最小子集闭合；桥外结构读后写不保形——skill 文档必须明示「桥外内容编辑会丢失该结构」，写前快照（journal `--snapshot-content`）是唯一的完整恢复途径。
