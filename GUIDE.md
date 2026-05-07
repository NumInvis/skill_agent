# Skill Agent 开发指南

## 项目概述

Skill Agent 是一个 Dify 工具插件，基于"渐进式披露（Progressive Disclosure）"模式设计，让大模型按需读取技能说明书（SKILL.md），执行命令并交付文件。

## 技术栈

- **Python 3.12**
- **Dify Plugin SDK** (`dify_plugin>=0.6.2`)
- 依赖：见 `requirements.txt`

## 本地开发

### 1. 环境准备

```bash
# 安装依赖
pip install -r requirements.txt

# 复制环境配置
cp .env.example .env
# 编辑 .env 填入你的远程调试配置
```

### 2. 远程调试

在 Dify 后台 → 插件管理 → 点击 bug 图标，复制 API Key 和 Host 到 `.env`：

```bash
INSTALL_METHOD=remote
REMOTE_INSTALL_HOST=your-dify-host
REMOTE_INSTALL_PORT=5003
REMOTE_INSTALL_KEY=your-debug-key
```

启动插件：
```bash
python -m main
```

### 3. 项目结构说明

```
provider/           # Provider 定义与凭证校验
tools/              # 工具实现
  skill_agent.py    # 主 Agent 逻辑
  TM.py             # 技能管理工具
utils/              # 工具模块
  skill_agent_runtime.py    # Skill 运行时
  skill_agent_storage.py    # Storage 封装
  skill_agent_schemas.py    # Tool Schema 定义
  skill_agent_debug.py      # 日志与调试
  tools.py                  # 通用工具函数
```

### 4. 打包发布

```bash
# 使用官方 CLI
dify plugin package . -o skill_agent.difypkg

# 或使用 Python fallback
python scripts/package_plugin.py . -o skill_agent.difypkg
```

### 5. 发布到 Marketplace

创建 GitHub Release 后，`.github/workflows/plugin-publish.yml` 会自动：
1. 打包插件
2. 向 `langgenius/dify-plugins` 提交 PR

## 核心设计原则

1. **渐进式披露**：先读索引 → 再读 SKILL.md → 再读文件 → 再执行命令
2. **安全第一**：命令白名单、路径遍历防护、文件名过滤
3. **状态持久化**：利用 Dify Storage 支持多轮对话和断点续跑

## 常见问题

1. **模型不输出 / 不调用工具**：检查模型是否支持 Function Call；fallback JSON Protocol 需要模型遵循 prompt 中的格式要求
2. **文件上传失败**：检查 Dify `.env` 中 `FILES_URL` 是否配置正确
3. **命令执行失败**：确认 plugin_daemon 容器中已安装所需运行时（Node.js 等）
