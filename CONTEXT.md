# kgent-skills

kgent 是联邦知识管理层：把 Lark、DingTalk、WeCom 等平台的知识内容统一为可检索、可写回、可审计的一层。kgent skills 只做编排与纪律，平台接口统一由 integration skill 承载。

## Language

**平台 (platform)**:
被接入的外部知识系统。当前：Lark/Feishu、DingTalk、WeCom。
_Avoid_: 服务、渠道

**integration skill**:
打包进 kgent-skills 的平台唯一接口层；对该平台的一切 search / read / write / undo 补偿执行 / 原生 URL 构造都必须经它，由它委派原生 skill 或平台 CLI。命名 `<platform>-integration`。
_Avoid_: 平台 skill、平台适配器

**原生 skill (native skill)**:
平台 CLI 生态自带的 agent skill（非 kgent 打包），由 integration skill 委派。
_Avoid_: 官方 skill

**后端 (backend)**:
kgent config/router 层的平台抽象，带 trust_zone。与平台一一对应：lark、dingtalk、wecom。
_Avoid_: 存储

**知识库 (knowledge base)**:
跨后端联邦全体的抽象——所有后端内容的统一视图。DingTalk 官方把 wiki space 也叫 "knowledge base"，在本项目中一律称知识空间。
_Avoid_: 文档库

**知识空间 (wiki space)**:
平台侧的知识空间容器（Lark wiki space、DingTalk workspace），平台概念而非 kgent 抽象。
_Avoid_: 空间

**kgent hosted backend**:
kgent 自有的云端托管知识库后端，与 lark / dingtalk / wecom 并列的另一种后端选择（尚未实现）；kgent CLI 平台操作（store / wiki / update / create / read / search）的唯一保留对象。三大平台的操作不经它。
_Avoid_: 本地后端、内置后端、主后端

**台账 (ledger)**:
op 级写操作账本；一个逻辑操作一条 entry，只记变更不记读。对应 CLI 命令 `journal`。
_Avoid_: 日志、审计日志（audit 是台账的读视图）

**补偿计划 (compensation plan)**:
`kgent undo` 依台账产出的待执行补偿描述（目标、机制、期望 revision）；执行归 integration skill。
_Avoid_: 回滚

**路由裁决 (routing decision)**:
kgent 对内容敏感级与目标后端的只读判定，先于任何写执行。
_Avoid_: 分流、敏感级路由
