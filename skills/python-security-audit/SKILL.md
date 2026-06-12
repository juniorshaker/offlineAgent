---
name: python-security-audit
description: Use when the user asks to audit Python code security, check for vulnerabilities, review authentication/authorization logic, or scan for OWASP Top 10 issues in Python.
---

# Python 安全审计

## Overview

按 OWASP Top 10 + Python 特有安全风险审计 Python 代码，识别安全漏洞并给出修复方案。

## Audit Checklist

### 1. 注入攻击
- SQL 注入：字符串拼接 SQL → 参数化查询（`cursor.execute(sql, params)`）
- 命令注入：`os.system()` / `subprocess.call(shell=True)` → `subprocess.run([...], shell=False)`
- 模板注入：`render_template_string(user_input)` → 避免用户输入进模板
- 反序列化：`pickle.loads(user_input)` → 禁用，用 `json` 替代
- `eval()` / `exec()` / `compile()`：检查是否包含用户输入

### 2. 认证与授权
- 密码存储：明文 → `bcrypt` / `argon2`
- JWT：验证 `alg=none` 攻击、过期时间、签名验证
- 会话管理：secure/httpOnly/SameSite Cookie 属性
- 路径遍历：`os.path.join(user_input, ...)` → 验证/规范化路径

### 3. 敏感数据暴露
- 日志中是否包含密码/token/密钥
- 异常信息是否暴露内部细节给客户端
- 配置文件中的硬编码密钥/密码
- DEBUG 模式在生产环境是否关闭

### 4. 依赖安全
- `requirements.txt` / `pyproject.toml` 中是否有已知 CVE 的包
- 是否使用不再维护的包
- 依赖版本是否锁定

### 5. Python 特有风险
- `assert` 在生产环境被 `-O` 跳过
- `__init__.py` 中的自动导入副作用
- 动态属性访问 `getattr(obj, user_key)` 的安全风险
- `yaml.load()` 使用 `SafeLoader`

## Output Format

```markdown
## 漏洞清单
| 行号 | 漏洞类型 | OWASP 类别 | 严重程度 | 说明 |

## 修复方案
[Before/After 代码对比]

## 依赖风险
| 包名 | 版本 | 风险 | 建议 |

## 安全检查清单
- [已完成项]
```

## Constraints

- 不做渗透测试，只做静态代码审查
- 标注误报可能（如框架自动转义）
- 优先标注高危和极易利用的漏洞
