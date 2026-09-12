# galgame通用翻译skill

一个面向 Codex 的 Galgame／视觉小说翻译与校订 skill。它把正文翻译、术语统一、多路线连续性、分批自审、整线纠错和格式检查组织成可恢复、可核验的工作流。

## 主要能力

- 在不改变事实、人物关系、信息揭示时机和原作强度的前提下，生成自然且有角色辨识度的中文。
- 维护角色名、称呼、专有名词、UI 文案等术语，并避免跨路线或跨阶段泄露信息。
- 按场景或合理批次翻译并自审，整线完成后执行一次独立纠错。
- 检查 ID、变量、标签、占位符、控制符和受保护文本是否被误改。
- 用最小状态文件记录路线进度、审核批次和术语决策，便于长项目恢复上下文。
- 仅在用户明确授权时使用子代理，并限制同一线路同时占用的代理名额。

## 仓库结构

```text
.
├── README.md
└── galgame-general-translation/
    ├── SKILL.md
    ├── agents/
    │   └── openai.yaml
    ├── assets/
    ├── references/
    └── scripts/
```

真正的 skill 根目录是 `galgame-general-translation/`；仓库根目录的 README 不属于 skill 本体。

## 安装

1. 克隆或下载本仓库。
2. 将完整的 `galgame-general-translation` 文件夹复制到个人 skill 目录：

   - Windows：`%USERPROFILE%\.agents\skills\galgame-general-translation`
   - macOS／Linux：`$HOME/.agents/skills/galgame-general-translation`

3. Codex 通常会自动发现新 skill；如果没有出现，请重启 Codex。

Codex 的 skill 目录与加载规则以 [OpenAI 官方说明](https://developers.openai.com/codex/skills) 为准。

## 使用

显式调用：

```text
$galgame-general-translation 翻译并校订这个 Galgame 项目，保留脚本结构并建立统一术语表。
```

也可以直接描述 Galgame／视觉小说翻译任务；当前配置允许 Codex 在任务与描述匹配时自动启用该 skill。

开始前建议提供：

- 原文文件或项目目录；
- 目标语言、文本格式和需要处理的路线范围；
- 已有译文、术语表或角色设定；
- 是否允许使用子代理并行处理不同线路。

## 工作流概览

1. 识别脚本格式、可译单元、路线与共享文本。
2. 预扫人物、术语、变量、标签和其他受保护内容。
3. 按场景或合理批次翻译，每批完成后对照原文自审。
4. 整线完成后进行一次独立纠错，原译者修正并局部复检。
5. 汇总译文、术语表和检查报告，明确说明未决问题与未验证项。

详细规则见 [`galgame-general-translation/SKILL.md`](galgame-general-translation/SKILL.md)。

## 辅助脚本

- `scripts/check_units.py`：检查源文与译文单元、受保护内容等结构差异。
- `scripts/term_audit.py`：审计术语使用情况。

具体参数请运行脚本的 `--help` 查看。建议先在副本上测试，不要直接覆盖原始游戏脚本。

## 说明

- 原始文件应保持只读，译文另存。
- 自动检查只能发现结构和术语类问题，不能替代人工语义审核。
- 本仓库目前未附带开源许可证。
