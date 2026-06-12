# 项目上下文 (Project Context)

## 项目概述

OfflineAgent — 可离线运行的 AI Agent，基于 Python，支持 CLI 和 Web 两种交互模式。对接内网 LLM API，兼容 Codex/OpenClaw SKILL.md 格式。

## 技术栈

- Python 3.8+（便携版可选）
- 前端：原生 HTML/CSS/JS（零 npm），Chart.js
- LLM 对接：HTTP POST（两种模式：JSON API + OpenAI 标准接口）
- Playwright（可选浏览器自动化）
- python-docx / openpyxl / python-pptx（可选文档处理）

## 架构要点

- Harness Engineering 五层架构：Prompt → Orchestrator → Tool → Evaluation → Metrics
- Skills 两级加载（L1 索引 + L2 正文）
- 错误自愈：观察 → 记录能力缺陷 → 剥离 → 重试
- Token 预算控制：128K 上限，超 70% 压缩，超 90% 强制终止
- 话题偏移检测：LLM 判断 + 新对话提示
- Web 前端：SSE 流式推送，五标签面板

## 约定与规范

- 所有模块使用相对导入
- 配置集中在 config.yaml
- 日志输出到 log/ 目录
- 运行时数据在 memory/ 目录
- 生成文件输出到 output/ 目录
- 文件编辑使用 apply_patch_* 工具

## 当前状态

- Token 预算已调到 128K
- 工具循环已改为 Token 预算控制
- 双后端（primary + openai）已支持
- 前端五标签面板已实现
- Java / SQL / 文档读写等 skills 已安装
