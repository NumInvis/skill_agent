<div align="center">

# 🤖 Skill Agent

**基于 Skills 渐进式披露的通用 Agent 插件 for Dify**

[![Version](https://img.shields.io/badge/version-0.0.4-blue?style=flat-square)](https://github.com/NumInvis/skill_agent)
[![Python](https://img.shields.io/badge/python-3.12-blue?style=flat-square&logo=python)](https://www.python.org/)
[![Dify](https://img.shields.io/badge/Dify-Plugin-green?style=flat-square)](https://dify.ai/)
[![License](https://img.shields.io/badge/license-MIT-orange?style=flat-square)](./LICENSE)

[📖 功能介绍](#功能介绍) · [🛠️ 工具系统](#工具系统) · [📁 Skill 系统](#skill-系统) · [🚀 快速开始](#快速开始) · [📦 安装](#安装) · [📝 更新日志](#更新日志)

</div>

---

## 📖 功能介绍

Skill Agent 是一个 **Dify 插件**，它将 `skills/` 文件夹作为 Agent 的**工具箱**。LLM 按需加载 Skill 指令，自主执行多步任务——读取文件、执行命令、写入结果、标记交付，**全程无需人工干预**。

### 核心能力

| 能力 | 说明 |
|------|------|
| 🧩 **Skill 渐进式加载** | Skills 不会一次性塞进上下文，LLM 按需调用 `skill` 工具加载 |
| 🔧 **6 大内置工具** | skill、read_file、write_file、bash、export_file、invalid |
| 🔄 **多步自主执行** | 最多 15 步循环，tool → result → next tool |
| ⚡ **实时流式反馈** | 每步操作实时显示："正在加载技能..."、"正在执行命令..." |
| 🛡️ **安全沙箱** | UUID 会话隔离，路径双重验证，命令执行限定目录 |
| 🔀 **工具调用容错** | 大小写不敏感匹配修复拼写错误，无效工具友好回退 |

### 它能做什么

- **知识库检索与回答** — 加载 `dify-knowledge-retrieve` Skill，自动调用 API 检索知识库，整理成文档交付
- **文件读写与代码生成** — 读取参考文件，生成新文件，标记为交付物
- **命令执行与数据处理** — 执行 curl、python 等命令获取数据，处理后再输出
- **一句指令完成全流程** — 说"帮我查一下糖尿病患者合并房颤的风险"，Agent 自动加载 Skill → 检索 → 整理 → 写文件 → 标记交付

---

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                         用户输入                              │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                      Skill Agent                             │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────────┐  │
│  │  System     │───▶│  LLM         │───▶│  Tool Executor │  │
│  │  Prompt     │    │  (function   │    │  (6 tools)     │  │
│  │  + Skills   │◀───│  calling /   │◀───│  + Sandbox     │  │
│  │  list       │    │  JSON text)  │    │  + Session     │  │
│  └─────────────┘    └──────────────┘    └────────────────┘  │
│         │                                              │      │
│         │         循环: LLM → Tool → Result → LLM      │      │
│         │              (最多 15 步)                      │      │
│         │                                              │      │
│         └──────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                      输出给用户                               │
│         最终文本 + 标记的交付文件 (export_file)               │
└─────────────────────────────────────────────────────────────┘
```

### 执行循环

```
Step 1: LLM → skill(name="dify-knowledge-retrieve")
Step 2: 执行 → 返回 SKILL.md 内容
Step 3: LLM → bash(command="curl ...")
Step 4: 执行 → 返回知识库检索结果
Step 5: LLM → write_file(path="answer.md", content="...")
Step 6: 执行 → 文件写入成功
Step 7: LLM → export_file(path="answer.md")
Step 8: 执行 → 标记交付成功 → 结束
```

---

## 🛠️ 工具系统

Agent 内置 **6 个核心工具**，覆盖从"获取指令"到"交付成果"的完整链路：

### 1. `skill` — 加载技能

加载指定 Skill，返回 SKILL.md 完整内容 + 相关文件列表（XML 格式）。

```xml
<skill_content name="dify-knowledge-retrieve">
# Skill: dify-knowledge-retrieve

...SKILL.md 完整内容...

Base directory for this skill: /path/to/skills/dify-knowledge-retrieve
Relative paths in this skill are relative to this base directory.
Note: file list is sampled.

<skill_files>
  <file>/path/to/skills/dify-knowledge-retrieve/README.md</file>
  <file>/path/to/skills/dify-knowledge-retrieve/config.json</file>
</skill_files>
</skill_content>
```

### 2. `read_file` — 读取文件

支持两种模式：
- **从 Skill 目录读取**：`read_file(path="config.json", skill_name="dify-knowledge-retrieve")`
- **从 Session 目录读取**：`read_file(path="answer.md")`

### 3. `write_file` — 写入文件

在 Session 目录中写入文本文件：
```json
{"name": "write_file", "arguments": {"path": "answer.md", "content": "# 标题\n\n内容..."}}
```

### 4. `bash` — 执行命令

支持字符串和数组格式，支持 `cwd` 限定工作目录：
```json
// 字符串形式
{"name": "bash", "arguments": {"command": "curl -s http://api.example.com/data"}}

// 限定 Skill 目录
{"name": "bash", "arguments": {"command": "python script.py", "cwd": "skill:dify-knowledge-retrieve"}}
```

### 5. `export_file` — 标记交付

将 Session 目录中的文件标记为最终交付物：
```json
{"name": "export_file", "arguments": {"path": "answer.md"}}
```

### 6. `invalid` — 无效调用回退

当 LLM 调用未知工具或参数错误时，Agent 自动触发 `invalid` 工具返回友好错误信息，帮助 LLM 自我修正。

---

## 📁 Skill 系统

### 目录结构

```
skills/
└── dify-knowledge-retrieve/
    ├── SKILL.md          # 技能指令（必须）
    ├── README.md         # 补充说明（可选）
    ├── config.json       # 配置文件（可选）
    └── script.py         # 辅助脚本（可选）
```

### SKILL.md 格式

```markdown
---
name: dify-knowledge-retrieve
description: 检索 Dify 知识库内容，返回结构化的检索结果
---

# 检索 Dify 知识库

## 用途
当用户询问与医学、疾病相关的问题时，使用本 Skill 检索知识库获取权威信息。

## 操作步骤
1. 使用 bash 工具调用 Dify 知识库 API
2. API 地址: http://host:port/v1/datasets/xxx/retrieve
3. 解析返回的 JSON，提取 content 字段
4. 整理成 Markdown 格式写入文件
```

### 渐进式披露

Skills **不会一次性全部加载到 LLM 上下文**。Agent 只在 System Prompt 中列出 Skills 的名称和描述：

```xml
<available_skills>
  <skill>
    <name>dify-knowledge-retrieve</name>
    <description>检索 Dify 知识库内容</description>
  </skill>
</available_skills>
```

LLM 识别到任务匹配某个 Skill 描述时，才会调用 `skill` 工具加载完整内容。

**好处**：减少 Token 消耗、避免无关 Skill 干扰、Skills 可无限扩展。

---

## 🚀 快速开始

### 安装插件

**方式一：上传 difypkg**
```
Dify 控制台 → 插件 → 安装插件 → 上传 .difypkg
```

**方式二：从 GitHub 安装**
```
Dify 控制台 → 插件 → 安装插件 → GitHub
输入: NumInvis/skill_agent
```

### 配置 Skills

在 `skills/` 目录下创建 Skill 文件夹：

```bash
mkdir -p skills/dify-knowledge-retrieve
cat > skills/dify-knowledge-retrieve/SKILL.md << 'EOF'
---
name: dify-knowledge-retrieve
description: 检索 Dify 知识库内容
---

# 检索 Dify 知识库

## 操作步骤
1. 使用 bash 工具调用 API
2. 解析结果
3. 写入文件
EOF
```

### 使用 Agent

在 Dify 应用中添加 **Skill Agent** 工具节点，输入自然语言：

> "查一下糖尿病患者合并房颤，发生脑梗死的风险高吗？"

Agent 自动执行：加载 Skill → 检索知识库 → 整理答案 → 写入文件 → 标记交付。

### 远程调试（开发环境）

```bash
# .env 配置
INSTALL_METHOD=remote
REMOTE_INSTALL_HOST=172.16.7.122
REMOTE_INSTALL_PORT=5003
REMOTE_INSTALL_KEY=your-key-here

# 启动（或使用 start_remote_debug.ps1）
python -m main
```

---

## 📝 实际案例

### 用户输入

> "查一下糖尿病患者合并房颤，发生脑梗死的风险高吗？"

### Agent 执行流程

| 步骤 | 工具 | 操作 | 反馈 |
|------|------|------|------|
| 1 | `skill` | 加载 `dify-knowledge-retrieve` | ✅ 正在加载技能... |
| 2 | `bash` | curl 检索知识库（过滤版） | ✅ 正在执行命令... |
| 3 | `bash` | curl 检索知识库（完整版） | ✅ 正在执行命令... |
| 4 | `write_file` | 写入 `answer.md` | ✅ 正在写入文件... |
| 5 | `export_file` | 标记 `answer.md` 为交付物 | ✅ 正在标记交付文件... |

### 生成的 answer.md

```markdown
# 糖尿病患者合并房颤，发生脑梗死的风险高吗？

## 检索结果分析

根据知识库检索结果，**糖尿病患者合并房颤时，发生脑梗死的风险确实显著增高**。

### 关键信息

1. **房颤与脑梗死的关系**
   - 房颤是最常见的心律失常之一
   - 房颤时心房丧失有序电活动，易引发血栓、卒中

2. **脑栓塞的机制**
   - 各种栓子（如房颤血栓）随血流进入脑动脉
   - 阻塞血管致脑组织缺血坏死

3. **糖尿病与房颤的叠加风险**
   - 糖尿病本身是脑血管疾病的独立危险因素
   - 两者合并存在时，风险远高于普通人群

## 结论

糖尿病患者合并房颤时，发生脑梗死的概率**显著增高**。这类患者通常需要严格的抗凝治疗以预防卒中。
```

---

## ✨ 体验优化

### 隐藏 JSON 工具调用文本

LLM 输出 `{"name":"bash","arguments":{...}}` 时，Agent 自动检测并隐藏，用户只看到执行反馈和最终结果。

### 减少重复工具调用

System Prompt 明确告诉 LLM："执行命令时尽量一次获取完整输出，不要先过滤再补充。"

### 结构化 Tool Result

bash 命令结果以 XML 格式返回：
```xml
<tool_result id="call_xxx" name="bash" status="success" returncode="0">
<stdout_length>1234 chars</stdout_length>
<stdout>
...命令输出...
</stdout>
</tool_result>
```

### 工具调用容错修复

- LLM 拼写 `Bash` → Agent 自动修复为 `bash`
- LLM 调用未知工具 → 返回友好错误信息和可用工具列表

### 安全沙箱

- 每次调用独立 UUID 会话目录
- 路径经过 `resolve + is_within_dir` 双重验证
- 命令执行限定在 `session_dir` 或 `skill` 目录

---

## 📦 安装

### 环境要求

- Python 3.12+
- Dify 平台（支持插件安装）

### 从源码安装

```bash
git clone https://github.com/NumInvis/skill_agent.git
cd skill_agent

# 安装依赖
pip install -r requirements.txt

# 本地打包
dify-plugin plugin package
```

### 远程调试

```bash
# 配置 .env
cp .env.example .env
# 编辑 .env 填入远程调试参数

# 启动
python -m main
```

---

## 📝 更新日志

### v0.0.4 (当前版本)

- **feat:** 隐藏 JSON 工具调用文本，`should_emit_user_text` 检测 `name+arguments` 格式
- **feat:** 减少重复工具调用，System Prompt 增加最佳实践规则
- **feat:** Skill 返回格式改为结构化 XML（`<skill_content>`）
- **feat:** 工具调用容错修复，大小写不敏感匹配 + `invalid` 工具回退
- **feat:** 改进 tool result XML 格式，bash 命令结构化输出 stdout/stderr/returncode
- **feat:** 添加诊断日志，帮助定位原生 function call 问题
- **feat:** 新增 `start_remote_debug.ps1` 远程调试启动脚本
- **fix:** 修复远程调试 asset chunk 阻塞问题
- **fix:** 改进工具参数验证和错误处理
- **fix:** 加强路径遍历保护和命令白名单

### v0.0.3

- 支持 Agent 流式输出
- 支持交互式多轮对话
- 支持文件记忆（无需重复上传）
- 支持运行 Node.js 脚本作为 Skills
- 改进 skill_agent 运行时稳定性

### v0.0.2

- 支持 Agent 文件上传和解析
- 支持自动依赖安装

### v0.0.1

- 实现 Skill 管理和基于渐进式披露的通用 Agent

---

## ❓ FAQ

### 安装失败怎么办？

如果安装失败且有网络访问，尝试切换 Dify 的 pip 镜像。内网环境可使用离线包安装。

### 文件上传/下载失败？

检查 Dify 的 `.env` 中 `Files_url` 是否设置正确，是否匹配你的 Dify 地址。

### skill_agent 没有输出？

通常是模型问题。确保你的模型和 Provider 插件支持 function calling。推荐 DeepSeek-V3.1。

### Skill 调用不顺畅？

Skill 越完整，Agent 调用越顺畅。确保 Skill 材料和脚本不缺失。Node.js 脚本技能需先在 `plugin_daemon` 容器中安装 Node.js 运行时。

---

## 👤 作者与联系

- **GitHub:** [NumInvis/skill_agent](https://github.com/NumInvis/skill_agent)
- **Bilibili:** 元视界\_O凌枫o
- **Email:** 550916599@qq.com

---

<div align="center">

**如果这个项目对你有帮助，请 ⭐ Star 支持一下！**

[⭐ Star on GitHub](https://github.com/NumInvis/skill_agent)

</div>
