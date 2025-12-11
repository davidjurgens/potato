# User-Centric System Prompt Analysis Report

## 概述

本报告对 200+ 个 benign system prompts 进行了"以用户为中心" (User-Centric) 的分析，旨在揭示这些 Prompt 主要是围绕什么用户目标、场景和角色展开的。

我们通过关键词聚类和角色定义提取，将这些 System Prompts 分为四大类：

1.  **Coding Assistants (代码助手)**
2.  **Information & Search Agents (信息搜索代理)**
3.  **Creative & Conversational Companions (创意与对话伴侣)**
4.  **Task Automation Agents (任务自动化代理)**

## 1. Coding Assistants (代码助手) - 占比最高

这是目前 System Prompt 中最庞大的类别，主要围绕**软件开发生命周期**展开。

*   **核心关注点**: 代码生成、Debug、文件操作 (读/写/删)、终端命令执行、项目上下文理解。
*   **用户角色**: 开发者 (Developer)、工程师。
*   **典型代表**: `Cursor`, `VSCode Agent`, `Devin`, `Replit`, `Windsurf`.
*   **Prompt 特征**:
    *   强调 "Pair Programming" (结对编程) 关系。
    *   严格限制代码输出格式 (Markdown, Code blocks)。
    *   包含大量关于工具使用的说明 (`read_file`, `run_terminal_cmd`).
    *   **User-Centric 指令**: "Bias towards not asking the user for help if you can find the answer yourself" (尽量自己解决，少打扰用户)。

> **示例 (Cursor)**: "You are pair programming with a USER to solve their coding task... Your main goal is to follow the USER's instructions at each message."

## 2. Information & Search Agents (信息搜索代理)

这类 Prompt 围绕**获取、验证和整合信息**展开，通常配备联网能力。

*   **核心关注点**: 实时性 (Freshness)、准确性 (Accuracy)、引用来源 (Citations)、浏览网页。
*   **用户角色**: 信息寻求者 (Information Seeker)。
*   **典型代表**: `MultiOn`, `Grok`, `Perplexity`, `Mistral`, `ChatGPT` (Search mode).
*   **Prompt 特征**:
    *   强调 "Up-to-date information" (最新信息)。
    *   包含复杂的浏览器控制指令 (`click`, `scroll`, `search`).
    *   **User-Centric 指令**: "If the cost of a small mistake... is high, then use the web tool" (如果犯错成本高，务必联网)。

> **示例 (MultiOn)**: "You are an expert agent named MULTI·ON... controlling a browser (you are not just a language model anymore)."

## 3. Creative & Conversational Companions (创意与对话伴侣)

这类 Prompt 围绕**情感连接、个性化表达和创意生成**展开。

*   **核心关注点**: 语气 (Tone)、同理心 (Empathy)、角色扮演 (Roleplay)、故事创作。
*   **用户角色**: 朋友 (Friend)、倾诉对象、读者。
*   **典型代表**: `Hume` (Voice/Emotion), `Meta AI` (Persona), `Moonshot Kimi`, `Character.AI` 风格.
*   **Prompt 特征**:
    *   极少出现代码或工具限制。
    *   大量关于性格的描述 ("empathic", "witty", "sarcastic").
    *   **User-Centric 指令**: "Match the user’s vibe" (匹配用户的氛围), "Listen, let the user talk" (倾听，让用户多说).

> **示例 (Hume)**: "Assistant is an empathic voice interface... Sound like a caring, funny, empathetic friend, not a generic chatbot."

## 4. Task Automation Agents (任务自动化代理)

这类 Prompt 围绕**特定工作流的执行**展开，通常是垂直领域的 Agent。

*   **核心关注点**: 流程执行 (Execution)、状态管理 (State)、特定领域任务 (如客服管理、设计)。
*   **用户角色**: 管理者 (Manager)、客户 (Customer)。
*   **典型代表**: `Poke`, `Parahelp`, `Orchids`.
*   **Prompt 特征**:
    *   定义了明确的步骤 (Step-by-step workflows)。
    *   包含特定领域的规则 (如客服话术、设计规范)。

## 数据分析摘要

基于关键词频率分析 (Keyword Frequency Analysis)：

| 类别 | 占比 (估算) | 主要关键词 |
| :--- | :--- | :--- |
| **Coding** | ~45% | code, debug, file, terminal, repository |
| **Web Search** | ~25% | search, browser, internet, news |
| **Creative/Chat**| ~15% | story, emotion, empathy, tone |
| **Automation** | ~15% | schedule, execute, manager, workflow |

## 结论：System Prompt 的演变趋势

从 User-Centric 的角度来看，System Prompt 正在从**通用的对话者 (General Chatbot)** 向 **专业的合作伙伴 (Specialized Partner)** 演变。

*   **通用 -> 垂直**: 越来越多的 Prompt 是专门为 Coding 或 Search 设计的，而不是试图做一个全能助手。
*   **被动 -> 主动**: Coding Agents (如 Devin, Cursor) 被赋予了更多的主动权 (Agentic behavior)，可以主动读取文件、修复错误，而不仅仅是回答问题。
*   **工具化**: "用户"在 Prompt 中的定义，从一个"聊天对象"，变成了一个"下达指令并期待结果"的管理者。
