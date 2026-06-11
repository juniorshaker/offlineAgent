---
name: java-security-audit
description: Use when the user asks to audit Java code for security vulnerabilities, SQL injection, XSS, authorization issues, or sensitive data exposure. Triggers on requests like "安全审计", "有没有SQL注入", "XSS漏洞检查", "权限越权", "敏感信息泄露", "security vulnerability scan", "硬编码密码". Also use for comprehensive security scanning including insecure random numbers, illegal file access, and OWASP Top 10 violations.
---

# Java 代码安全漏洞审计

## Overview

全方位进行代码安全审计，扫描 SQL 注入、XSS 跨站脚本、权限越权、敏感信息明文存储、硬编码密钥、不安全随机数、非法文件读写等高危漏洞，划分风险等级并给出合规修复方案。

## Analysis Checklist

### 1. 注入攻击检测（最高优先级）
- SQL 注入：
  - JDBC Statement（非 PreparedStatement）的字符串拼接
  - MyBatis ${} 变量替换
  - JPA nativeQuery 的字符串拼接
  - 动态表名/列名/排序字段
- 命令注入：Runtime.exec() / ProcessBuilder 的参数拼接
- 表达式注入：
  - SpEL（Spring Expression Language）动态表达式
  - OGNL 表达式注入
  - EL（Expression Language）注入
- LDAP 注入：LDAP 查询中的用户输入拼接
- 日志注入：日志中未处理用户输入（
 换行伪造日志）

### 2. XSS 与输出编码
- 反射型 XSS：URL 参数直接回显在响应中
- 存储型 XSS：用户输入存储后未经编码输出
- DOM 型 XSS：前端 JS 不安全地操作 DOM
- 后端防护检查：
  - 是否对输出做 HTML 编码（HtmlUtils.htmlEscape / OWASP Encoder）
  - JSON 响应中是否对特殊字符转义
  - 富文本输入是否做了白名单过滤（jsoup / OWASP HTML Sanitizer）

### 3. 认证与授权
- 认证绕过：
  - 未受保护的敏感接口
  - 硬编码的认证逻辑
- 授权越权：
  - 水平越权：用户 A 访问用户 B 的数据（缺少数据归属校验）
  - 垂直越权：普通用户访问管理员接口（缺少角色校验）
  - 接口是否做了权限注解（@PreAuthorize/@Secured/自定义权限注解）
- Session/Token 安全：JWT 签名算法、Token 过期策略、CSRF 防护

### 4. 敏感信息泄露
- 硬编码检测：
  - 密码/密钥/Token/AccessKey 在代码中直接出现
  - 数据库连接字符串中硬编码密码
  - 第三方 API Key 硬编码
- 日志泄露：
  - 敏感信息打印到日志（密码/手机号/身份证/银行卡/Token）
  - 数据脱敏是否到位
- 错误信息泄露：
  - 异常响应中是否暴露了堆栈信息/数据库结构/内部路径
- 配置文件中的敏感信息

### 5. 文件操作安全
- 路径遍历：文件路径中使用 ../ 等跳转（../../etc/passwd）
- 文件上传：
  - 文件类型是否校验（白名单 > 黑名单）
  - 上传路径是否可控
  - 是否限制文件大小
  - 上传的文件名是否重命名
- 文件下载：
  - 下载路径是否可控（通过参数指定路径）
  - 是否做了路径规范化
- 压缩炸弹（Zip Bomb）：解压时是否限制大小

### 6. 加密与随机数（详见 java-crypto-audit）
- 不安全随机数：java.util.Random 用于安全场景
- 弱加密算法：DES/RC4/MD5（安全场景）/SHA-1（安全场景）
- 不安全的加密模式：ECB模式
- 固定 IV/盐值

## Output Format

```markdown
## 安全漏洞清单（按风险等级排序）
| 等级 | 漏洞类型 | CWE | 位置 | 描述 |

## 漏洞详解
### [Critical/High/Medium/Low] 漏洞名称
- 位置：
- 风险描述：
- 攻击场景：
- 当前代码：
- 修复代码：

## 扫描统计
- Critical: X
- High: X
- Medium: X
- Low: X
```

## Common Pitfalls

- 不要把测试代码中的硬编码密码当成线上漏洞（但应标注）
- 不要把使用了 PreparedStatement 但动态表名的情况标记为安全
- @PreAuthorize 注解的方法同样存在自调用绕过问题
- 前端校验不能替代后端安全校验
- 不要把使用 BCrypt/SCrypt 的密码哈希当成明文存储
