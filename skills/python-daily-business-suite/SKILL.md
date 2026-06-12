---
name: python-daily-business-suite
description: Use when the user asks for comprehensive Python daily development tasks: code review, formatting, linting, dependency management, packaging, or general Python workflow optimization.
---

# Python 日常开发套件

## Overview

覆盖 Python 日常开发的完整工作流：代码审查、格式化、linting、依赖管理、打包发布、虚拟环境管理。

## Daily Workflow

### 1. 代码质量工具链
- 格式化：`black`（代码风格）、`isort`（import 排序）、`autopep8`
- Linting：`ruff`（快速）、`pylint`（全面）、`flake8`（经典）
- 类型检查：`mypy` / `pyright`
- 安全检查：`bandit`、`safety`

### 2. 依赖管理
- `pip` + `requirements.txt`（简单项目）
- `pip-tools` + `requirements.in`（锁定依赖）
- `poetry`（现代项目）
- `pipenv`（应用项目）
- `uv`（极速安装）
- 建议：锁文件（`requirements.lock` / `poetry.lock`）必须提交

### 3. 虚拟环境
- `venv` / `virtualenv`（标准）
- `conda`（数据科学）
- `poetry env`（Poetry 项目）
- 建议：`.venv/` 加入 `.gitignore`

### 4. 项目结构最佳实践
```
project/
├── src/package_name/    # 源代码（src layout）
├── tests/               # 测试
├── docs/                # 文档
├── scripts/             # 工具脚本
├── pyproject.toml       # 项目配置
├── README.md
└── .gitignore
```

### 5. 发布流程
- 版本管理：语义化版本（`major.minor.patch`）
- `pyproject.toml`：`[project]` 和 `[build-system]`
- `setuptools` / `hatchling` / `flit` 构建后端
- PyPI 发布：`twine upload dist/*`

## Output Format

```markdown
## 项目健康检查
| 检查项 | 状态 | 建议 |

## 工具链建议
[推荐的工具组合 + 配置文件]

## 快速修复
[可直接执行的改进]
```

## Constraints

- 先了解项目现有工具链，不强行替换
- 建议工具链时给出配置示例
- 不推荐未经验证的新工具
