# 0004 — 平台操作统一经 integration skill

kgent 的 skills（knowledge-storage / question-answering / wiki-setup）只做编排；对 Lark、DingTalk、WeCom 的一切 search / read / write 及 undo 补偿执行，统一经各平台的 integration skill（lark-integration / dingtalk-integration / wecom-integration，随 kgent-skills 打包），由其委派原生 skill 或平台 CLI（lark-cli / wecom-cli / dws）。kgent CLI 自身的平台 adapter（LarkAdapter 等）对 skills 退役，标 deprecated 保留供调试；CLI 平台操作仅保留给 kgent hosted backend。

## Considered Options

- **C（执行收编进 kgent 适配器）**：由 LarkAdapter 内部改调更可靠的原语。被否：需在 Python 里重写 lark-doc 已打磨的 DocxXML / 块级 / history 知识并长期跟版本；MCP 消费面已裁决直连平台 API，"kgent 统一漏斗"的最大论据不成立。
- **B（skill 层直调原生 skill，无 integration skill 层）**：被否——三个平台各有一套接口知识却没有统一落点；journal/undo 补偿、原生 URL、错误语义需要共同的家，这就是 integration skill。

## Consequences

- 直接动机是一次数据丢失事故：kgent 经 `lark-cli.cmd` 批处理包装内联传参，多块/UTF-8 内容被 cmd.exe 截断（详见 spec 2026-09-05）。执行知识在平台层最可靠。
- undo 补偿按平台能力降级（lark `history-revert` / dws `version-revert` / wecom 仅快照写回），台账给计划、integration skill 执行（见 0005）。
- route-before-execute 与 journal begin/end 是 skill 层纪律（eval 强制），不是 kgent 结构强制；若观测到真实泄漏，fallback 是把执行漏斗收回 kgent（C 路线）。
- 平台硬约束随之进入 integration skill 的已知限制：wecom 仅 bot 身份、消息只达近期会话；dws 需组织管理员开启 CLI Access Management。
