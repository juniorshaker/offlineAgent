---
name: python-development
description: Use for general Python development tasks when no more specific Python skill matches. Covers Python setup, debugging, code writing, framework guidance, and best practices.
---

# Python 开发

## Overview

通用 Python 开发指南，当没有更具体的 Python skill 匹配时使用。覆盖 Python 开发的核心工作流。

## Default Workflow

当用户提出 Python 相关任务时：

### 1. 理解需求
- 确定项目类型：脚本 / Web 应用 / CLI 工具 / 数据处理 / 机器学习
- 确定 Python 版本（优先 3.10+）
- 确定依赖框架（FastAPI / Flask / Django / 无框架）

### 2. 代码探索
- 使用 `read_file` 读取相关代码文件
- 使用 `search_code` 搜索关键函数/类/模式
- 使用 `list_dir` 了解项目结构

### 3. 实现
- 遵循 PEP 8 风格
- 包含适当的类型注解
- 添加 docstring
- 处理异常
- 使用 `write_file` 创建/修改代码

### 4. 验证
- 使用 `shell` 运行 `python -m pytest` 或 `python <script>.py`
- 检查 import 是否正确
- 验证类型注解（如果项目配置了 mypy）

## Python 工具链

| 用途 | 工具 |
|------|------|
| 包管理 | pip / poetry / uv |
| 格式化 | black / ruff format |
| Lint | ruff / flake8 / pylint |
| 类型检查 | mypy / pyright |
| 测试 | pytest |
| 安全 | bandit / safety |

## Constraints

- Python 3.8+ 语法优先
- 优先使用标准库
- 依赖明确列在 requirements.txt 或 pyproject.toml
- 虚拟环境隔离
