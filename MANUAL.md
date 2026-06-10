# OfflineAgent v5 — 完整使用手册

> 版本: 5.0 | 更新: 2026-06-10 | 适用: Windows (域用户) / Linux / macOS

---

## 目录

1. [概述](#1-概述)
2. [快速开始](#2-快速开始)
3. [配置说明](#3-配置说明)
4. [Skills 管理体系](#4-skills-管理体系)
5. [工具系统](#5-工具系统)
6. [内置命令](#6-内置命令)
7. [Token 节省策略](#7-token-节省策略)
8. [错误自愈机制](#8-错误自愈机制)
9. [话题偏移检测](#9-话题偏移检测)
10. [自成长机制](#10-自成长机制)
11. [Web 前端](#11-web-前端)
12. [域用户部署指南](#12-域用户部署指南)
13. [Playwright 离线安装](#13-playwright-离线安装)
14. [FAQ](#14-faq)

---

## 1. 概述

OfflineAgent 是一个**便携、零系统依赖**的全功能 AI Agent，专为内网环境设计。它可以在没有互联网连接、没有管理员权限的 Windows 域用户电脑上直接运行。

### 1.1 核心特性

| 特性 | 说明 |
|------|------|
| **零安装** | 拷贝即用，不写注册表，不写 C 盘 |
| **便携 Python** | 可选自带 Python，不依赖系统安装 |
| **兼容 Skills** | 兼容 Codex SKILL.md 和 OpenClaw Skill 格式 |
| **自成长** | 从错误中学习、自动摘要、生成 Skill 草稿 |
| **Token 节省** | 两级 Skill 加载、对话压缩、Prompt 缓存 |
| **错误自愈** | 自动识别不兼容内容并剥离重试 |
| **话题防护** | 检测话题偏移，提示是否开启新对话 |
| **工具手脚** | 文件读写、Shell 执行、代码搜索、HTTP 请求、模板填充 |
| **Web 前端** | 纯 HTML/CSS/JS，SSE 流式输出，零 npm |

### 1.2 项目结构

```
Offlineagent/
├── agent.py              # CLI 入口
├── server.py             # Web 服务器入口
├── config.yaml           # 统一配置文件
├── setup.bat             # Windows 一键启动
├── MANUAL.md             # 本手册
│
├── frontend/             # Web UI (零 npm)
│   ├── index.html
│   ├── style.css
│   └── app.js
│
├── vendor/               # 内置依赖 (urllib 封装)
│   └── requests.py
│
├── prompt_layer/         # 第1层: Prompt
├── orchestrator/         # 第2层: 编排
├── tool_layer/           # 第3层: 工具
├── evaluation/           # 第4层: 评估
├── metrics/              # 第5层: 指标
├── memory_layer/         # 成长层
│
├── memory/               # 运行时数据 (自动创建)
├── skills/               # 本地 Skills 目录
├── templates/            # 文档模板
├── output/               # 生成文档输出
│
├── python/               # [可选] 便携 Python
└── browsers/             # [可选] Playwright 浏览器
```

---

## 2. 快速开始

### 2.1 最小部署 (3 步)

```bash
# 步骤 1: 拷贝整个 Offlineagent/ 文件夹到可写磁盘
# 例如: D:\AiCoding\Ai-Fields\Offlineagent\

# 步骤 2: 修改配置文件中的 LLM 地址
# 编辑 config.yaml，修改 llm.url 和 llm.model

# 步骤 3: 双击 setup.bat 启动
```

### 2.2 启动模式

| 模式 | 命令 | 说明 |
|------|------|------|
| CLI 交互 | `python agent.py` | 命令行对话 |
| Web 服务 | `python server.py` | HTTP 服务 + 前端 |
| 菜单启动 | 双击 `setup.bat` | 自动检测 Python 并选择模式 |

### 2.3 验证

启动后，输入 `/status` 查看当前状态，输入 `/help` 查看所有命令。

---

## 3. 配置说明

编辑 `config.yaml`，以下是关键配置项：

### 3.1 LLM 配置

```yaml
llm:
  url: "http://your-internal-api/v1/chat/completions"   # 内网 API 地址
  model: "Qwen3"                                         # 模型名称
  timeout: 60                                            # 请求超时 (秒)
  extra_headers: {}                                       # 额外 HTTP 头
```

API 兼容格式: `{"model": "xxx", "messages": [{"role": "user", "content": "..."}]}`

### 3.2 Agent 配置

```yaml
agent:
  max_history: 20              # 最大对话轮次
  max_tokens_estimate: 8000    # Token 预算上限

  compression:                 # 对话压缩
    enabled: true              # 开启自动压缩
    trigger_ratio: 0.7         # 触发比例 (70% token 用量)
    keep_recent: 2             # 保留最近 N 轮原文

  error_recovery:              # 错误自愈
    enabled: true
    max_retries: 2             # 最大重试次数
    retry_delay: 2             # 重试间隔 (秒)

  topic_guard:                 # 话题偏移检测
    enabled: true
    check_interval: 1          # 每 N 轮检测一次

  memory:                      # 会话记忆
    enabled: true
    max_recent: 3              # 注入上下文的记忆数
    auto_summarize_on_exit: true

  feedback:                    # 用户反馈
    enabled: true
```

### 3.3 工具配置

```yaml
tools:
  enabled:                     # 启用的工具列表
    - read_file
    - write_file
    - list_dir
    - search_code
    - shell
    - read_template
    - write_output
    - web_fetch

  shell:
    allowed:                   # Shell 白名单
      - mvn
      - javac
      - java
      - git
      - python
      - pip
      - npm
      - docker
    require_confirm: true      # 执行前需确认

  file_write:
    require_confirm: true      # 写文件前需确认

  browser:
    enabled: false             # 浏览器自动化 (需 Playwright)
    engine: playwright
```

### 3.4 Skills 路径

```yaml
skills:
  paths:
    - "./skills"               # 本地 skills/
    - "~/.codex/skills"        # Codex skills (兼容)
    - "~/.openclaw/skills"     # OpenClaw skills (兼容)
```

### 3.5 服务器配置

```yaml
server:
  host: "0.0.0.0"    # 监听地址 (0.0.0.0 = 所有网卡)
  port: 8999          # 监听端口
```

---

## 4. Skills 管理体系

### 4.1 两级加载机制

| 层级 | 内容 | 何时加载 | Token 消耗 |
|------|------|----------|------------|
| L1 索引 | Skill 名称 + 60 字描述 | 启动时自动注入 | ~30 tokens/skill |
| L2 正文 | 完整 SKILL.md 内容 | 用户执行 `/skill <name>` | 用完即弃 |

### 4.2 Skill 文件格式

```markdown
---
name: My Skill Name
description: A concise description of what this skill does.
platforms: [windows, linux]    # 可选，限制运行平台
---

# My Skill Body

Full instructions for the LLM...
```

### 4.3 平台过滤

- `platforms: [macos]` — 仅 macOS 可用
- `platforms: [windows, linux]` — Windows 和 Linux 可用
- 不写 `platforms` — 全平台可用

**Windows 上自动跳过 `platforms: [macos]` 的 Skill。**

### 4.4 目录排除

自动跳过以下目录中的文件: `.git`, `node_modules`, `__pycache__`, `.venv`, `venv`, `site-packages`, `.tox`, `.mypy_cache`

---

## 5. 工具系统

### 5.1 工具调用协议

LLM 通过 XML 标签调用工具:

```xml
<tool_call>
<name>read_file</name>
<path>src/Main.java</path>
</tool_call>
```

### 5.2 工具清单

| 工具 | 功能 | 参数 | 需确认 |
|------|------|------|--------|
| `read_file` | 读取文件内容 (上限 8000 字符) | `path` | 否 |
| `write_file` | 创建/覆盖文件 | `path`, `content` | 是 |
| `list_dir` | 列出目录内容 | `path` | 否 |
| `search_code` | 代码搜索 (rg/grep 兜底) | `pattern`, `path` | 否 |
| `shell` | 执行命令 (白名单+确认) | `command` | 是 |
| `read_template` | 读取模板文件 | `path` | 否 |
| `write_output` | 输出到 output/ | `path`, `content` | 否 |
| `web_fetch` | HTTP GET/POST 请求 | `url`, `method` | 否 |

### 5.3 Shell 安全模型

- **白名单验证**: 命令首词必须在 `tools.shell.allowed` 列表中
- **确认机制**: 每次执行前提示用户确认
- **超时保护**: 60 秒超时自动终止
- **输出截断**: 超过 4000 字符自动截断

### 5.4 自动编排

一次用户输入 → Agent 自动决定调用哪些工具 → 工具结果注入上下文 → 继续思考 → 最终回复。整个过程自动循环，无需用户干预。

---

## 6. 内置命令

| 命令 | 功能 |
|------|------|
| `/help` | 显示所有命令帮助 |
| `/skills` | 列出已加载的 Skills (含来源和使用次数) |
| `/skill <name>` | 加载 Skill 完整正文到上下文 |
| `/tools` | 列出可用工具及状态 |
| `/status` | Token 用量仪表板 |
| `/memory` | 显示记忆列表 |
| `/memory <id>` | 查看某条记忆全文 |
| `/clear` | 清空当前对话历史 |
| `/config` | 显示当前配置摘要 |
| `/exit` | 退出 (自动摘要 + 评分 + Skill 草稿提示) |

---

## 7. Token 节省策略

### 7.1 两级 Skill 加载

- L1 索引始终在 system prompt 中 (~30 tokens/skill)
- L2 正文仅在用户执行 `/skill <name>` 后注入
- 切换话题后旧 Skill 正文自动失效

### 7.2 Prompt 缓存

- system prompt 的 stable 层在 Skill 文件未修改时复用磁盘缓存
- 启动零扫描，直接命中

### 7.3 对话压缩

- 达到 70% token 预算时自动触发
- 保留最近 2 轮原文
- 旧轮次使用 LLM 压缩为简短摘要 (~2000 → ~200 tokens)

### 7.4 用量仪表板

输入 `/status` 实时查看:

```
Session Status
  Estimated tokens:  3200 / 8000 (40.0%)
  Conversation turns: 5 / 20
  Skills loaded:      3
```

---

## 8. 错误自愈机制

### 8.1 工作流程

```
用户发送消息 (含图片)
    ↓
┌─────────────────────────────┐
│ check_before_send():        │
│ 查询 model_capabilities.json│
│ → 该模型不支持 image       │
│ → 预剥离图片内容            │
└─────────────────────────────┘
    ↓
发送纯净消息 → LLM 正常响应 ✓
```

### 8.2 如果未预剥离 (第一次遇到)

```
发送消息 (含图片)
    ↓
LLM 返回错误: "model does not support image input"
    ↓
┌─────────────────────────────┐
│ observe_error():            │
│ 1. 记录模型名: "deepseek"  │
│ 2. 记录错误关键词: "image" │
│ 3. 推断不支持类型: "image" │
│ 4. 写入 model_capabilities │
│                             │
│ repair_after_error():       │
│ 5. 剥离图片 → 纯文本      │
│ 6. 重试 → 成功             │
└─────────────────────────────┘
```

### 8.3 `model_capabilities.json` 结构

```json
{
  "deepseek-chat": {
    "unsupported": ["image"],
    "last_seen": "2026-06-10T10:30:00",
    "error_count": 2,
    "error_snippet": "model does not support image input"
  }
}
```

---

## 9. 话题偏移检测

### 9.1 触发机制

- 每 N 轮 (可配 `topic_guard.check_interval`) 调一次 LLM 做极简判断
- 消耗 ~150 tokens/次

### 9.2 用户交互

```
检测到话题偏移:
  原话题: Java 单元测试覆盖率
  新话题: 晚上吃什么

  [Y] 开启新对话 (清空历史)
  [N] 继续当前对话
  [S] 不再提示 (关闭检测)
```

---

## 10. 自成长机制

### 10.1 错误学习

见 [第 8 节：错误自愈机制](#8-错误自愈机制)。

### 10.2 会话记忆

- 退出时 LLM 自动生成会话摘要
- 保存到 `memory/` 目录 (JSON 索引 + Markdown 文件)
- 下次启动注入最近 3 条记忆到 system prompt

### 10.3 Skill 草稿生成

- 深入讨论某个话题后 (如"Java 微服务架构")
- 退出时提示: "是否为这个话题生成 SKILL.md 草稿?"
- 确认后自动生成并保存到 `skills/`

### 10.4 用户反馈

- 退出时 1-5 星评分
- 保存到 `memory/feedback.jsonl`
- 下次启动注入最近 3 条反馈

---

## 11. Web 前端

### 11.1 启动

```bash
python server.py
# 或
setup.bat → 选择 [2] Web mode
```

### 11.2 访问

浏览器打开 `http://localhost:8999`

### 11.3 特性

- **SSE 流式输出**: 无需 WebSocket，内网老浏览器兼容
- **工具状态指示**: 执行工具时显示旋转指示器
- **深色主题**: 护眼、专业
- **零 npm**: 纯原生 HTML/CSS/JS
- **响应式**: 桌面和移动端适配

---

## 12. 域用户部署指南

### 12.1 场景说明

- Windows 域用户登录
- 没有管理员权限
- 没有 C 盘 Program Files 写入权限
- 可能无法修改系统 PATH
- PowerShell 执行策略受限

### 12.2 部署步骤

| 步骤 | 操作 | 说明 |
|------|------|------|
| 1 | 将 `Offlineagent/` 文件夹拷贝到可写位置 | 如 `D:\AiCoding\` |
| 2 | 从 python.org 下载 Windows embeddable package | 选择 3.8+ 版本 |
| 3 | 解压到 `Offlineagent\python\` | `python.exe` 直接可用 |
| 4 | 修改 `config.yaml` | 填入内网 LLM API 地址 |
| 5 | 放入 Skill 文件到 `skills/` | SKILL.md 格式 |
| 6 | 双击 `setup.bat` | 自动检测 Python 并启动 |

### 12.3 Python Embeddable 注意事项

```bash
# 1. 下载 embeddable zip (不是 installer)
#    https://www.python.org/downloads/windows/
#    搜索 "Windows embeddable package (64-bit)"

# 2. 解压到 .\python\
#    确认 python.exe 在 .\python\python.exe

# 3. 编辑 python310._pth (去掉 import site 的注释)
#    确保 Lib 目录被识别
```

### 12.4 验证部署

```bash
# 在 Offlineagent 目录下:
.\python\python.exe -c "print('OK')"
# 输出: OK

.\python\python.exe agent.py
# 启动 CLI 模式
```

### 12.5 环境兼容性

| 约束 | 解决方案 |
|------|----------|
| 无管理员权限 | 不写 C:\Program Files, 不碰注册表 |
| 无法修改 PATH | setup.bat 使用相对路径调用 Python |
| PowerShell 限制 | 使用 .bat 而非 .ps1 |
| C 盘写入限制 | 所有数据在项目目录内 |
| 无外网 | 所有依赖已内置 (vendor/) 或预下载 |

---

## 13. Playwright 离线安装

### 13.1 外网准备 (一次性)

```bash
# 在外网机器上:
pip install playwright
python -m playwright install chromium

# 找到浏览器安装位置:
python -c "import playwright; print(playwright.__file__)"
# 通常在: %USERPROFILE%\AppData\Local\ms-playwright\

# 打包:
# 将 ms-playwright\ 目录打包为 browsers.zip
```

### 13.2 内网部署

```bash
# 1. 将 browsers.zip 通过 U 盘或其他方式传入内网
# 2. 解压到 Offlineagent\browsers\
#    Offlineagent\browsers\chromium-1124\
#    Offlineagent\browsers\ffmpeg-xxx\

# 3. 修改 config.yaml:
#    tools.browser.enabled: true

# 4. setup.bat 会自动设置 PLAYWRIGHT_BROWSERS_PATH
```

### 13.3 验证

```bash
python -c "import os; os.environ['PLAYWRIGHT_BROWSERS_PATH']='.\\browsers'; from playwright.sync_api import sync_playwright; print('OK')"
```

---

## 14. FAQ

### Q: LLM 地址格式不对怎么办？
确认 API 兼容 OpenAI Chat Completions 格式:
- URL: `http://your-api/v1/chat/completions`
- 请求体: `{"model": "...", "messages": [...]}`
- 响应体: `{"choices": [{"message": {"content": "..."}}]}`

### Q: Skills 加载不到怎么办？
1. 确认 `config.yaml` 中 `skills.paths` 路径正确
2. 确认 SKILL.md 文件名大小写正确 (大写)
3. 输入 `/skills` 检查已加载列表

### Q: 工具调用不工作？
1. 确认 `config.yaml` 中 `tools.enabled` 包含对应工具名
2. 检查 LLM 是否理解 XML 工具调用格式
3. 查看错误信息: 工具调用失败会在对话中显示 `[Error]` 前缀

### Q: Token 消耗太快？
1. 减少 `agent.max_history` 值
2. 降低 `agent.compression.trigger_ratio` (如 0.5)
3. 减少 Skills 数量或精简 Skill 描述
4. 输入 `/clear` 定期清理对话历史

### Q: 如何添加新工具？
编辑对应的 `tool_layer/*.py` 文件：
1. 添加工具函数
2. 在 `agent.py` 的 `register_tools()` 中注册
3. 在 `config.yaml` 的 `tools.enabled` 中启用

### Q: Web 前端连不上？
1. 确认 `python server.py` 正常启动
2. 检查防火墙是否拦截 8999 端口
3. 确认浏览器访问 `http://localhost:8999` (不是 https)
4. 如果使用其他端口: `python server.py -p 8080`

### Q: 域用户 Python 找不到模块？
确保 portable Python 的 `python._pth` 文件中 `import site` 未被注释:
```
python310.zip
.
# 去掉下一行的 #
import site
```

### Q: 如何备份记忆和配置？
直接复制 `memory/` 目录和 `config.yaml`:
```bash
xcopy memory\* D:\backup\offlineagent\memory\ /E /I
copy config.yaml D:\backup\offlineagent\
```

---

## 附录 A: 依赖清单

| 用途 | 文件 | 来源 | 是否必需 |
|------|------|------|----------|
| HTTP 请求 | vendor/requests.py | 内置 (urllib 封装) | 是 |
| 配置文件 | config.yaml | 用户编辑 | 是 |
| Python 运行时 | python/python.exe | 便携/系统 | 是 |
| Playwright 浏览器 | browsers/ | 外网预下载 | 否 |

---

## 附录 B: 兼容性矩阵

| 组件 | 最低要求 | 推荐 |
|------|----------|------|
| Python | 3.8 | 3.11+ |
| Windows | Windows 10 | Windows 10/11 |
| LLM API | OpenAI Chat Completions 格式 | 兼容格式均可 |
| 浏览器 (前端) | 支持 SSE 的浏览器 | Chrome/Edge/Firefox 最新 |
| Playwright | 1.40+ (可选) | 最新稳定版 |
