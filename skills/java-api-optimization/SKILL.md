---
name: java-api-optimization
description: Use when the user asks to optimize Java REST API design, review controller interfaces, improve request/response structures, or standardize API conventions. Triggers on requests like "接口优化", "API设计规范", "Controller代码审查", "出参格式统一", "全局异常处理", "参数校验完善". Also use for analyzing API request validation, response format consistency, error handling, and interface responsibility separation.
---

# Java 接口规范优化分析

## Overview

分析后端 Java 接口结构、入参实体、出参封装、全局异常处理逻辑。排查参数缺少校验、返回格式不统一、冗余返回字段、接口职责混杂等问题，按照企业级开发规范优化接口整体设计。

## Analysis Checklist

### 1. 接口结构分析
- RESTful 风格检查：使用名词而非动词作为 URL 路径
- HTTP 方法正确性：GET（查询）/ POST（创建）/ PUT（全量更新）/ PATCH（部分更新）/ DELETE（删除）
- URL 版本管理：/api/v1/xxx
- 接口粒度：是否一个接口做了多件事（违反单一职责）
- 幂等性：GET/PUT/DELETE 应该是幂等的，POST 非幂等

### 2. 入参校验
- 必填参数是否标注 @NotNull/@NotEmpty/@NotBlank
- 数值范围是否标注 @Min/@Max/@Positive/@Negative
- 字符串长度是否标注 @Size/@Length
- 日期格式是否标注 @DateTimeFormat/@JsonFormat
- 自定义业务校验是否用 @AssertTrue 或自定义 Validator
- 分组校验（groups）的使用场景
- 嵌套对象的校验（@Valid 级联校验）
- 是否所有 public API 接口入参都有校验

### 3. 出参封装
- 统一返回结构（如 Result<T> 包含 code/message/data）
- 是否暴露了过多的内部字段（Entity 直接返回给前端）
- 敏感字段是否脱敏或排除（密码/身份证/手机号/银行卡）
- 日期类型格式是否统一（时间戳 vs ISO 8601 字符串）
- null 值的处理策略（@JsonInclude NON_NULL vs 返回空值）
- 分页结果是否有统一的结构（total/pageNum/pageSize/records）

### 4. 全局异常处理
- @ControllerAdvice + @ExceptionHandler 的覆盖范围
- 异常分类是否合理（业务异常/参数异常/系统异常）
- 异常信息是否暴露内部细节到前端
- HTTP 状态码使用是否正确：
  - 200 成功
  - 400 参数错误
  - 401 未认证
  - 403 无权限
  - 404 资源不存在
  - 500 服务器内部错误
- 第三方异常（RPC/数据库）是否正确包装

### 5. 接口文档与契约
- 是否有 Swagger/OpenAPI 注解（@Api/@ApiOperation/@ApiModel）
- 接口描述是否清晰
- 请求/响应示例是否提供
- 废弃接口是否标注 @Deprecated

### 6. 其他最佳实践
- 接口防重放攻击（时间戳+nonce+签名）
- 接口限流保护（RateLimiter/Guava/Sentinel）
- 大文件上传/下载接口的特殊设计
- 异步接口的设计（返回任务 ID，轮询或回调获取结果）
- 接口耗时监控和慢查询告警

## Output Format

```markdown
## 接口概览
| HTTP方法 | URL | 方法 | 职责 | 评估 |

## 入参校验审计
| 接口 | 参数 | 当前校验 | 缺失校验 | 修复建议 |

## 出参审计
| 接口 | 返回类型 | 问题 | 修复建议 |

## 异常处理审计
| 异常类型 | 处理方式 | 返回信息 | 问题 | 修复建议 |

## 统一返回结构建议
[推荐的结构和工具类]
```

## Common Pitfalls

- 不要把所有字段都标记为 @NotNull，区分必填和可选
- @Valid 只校验当前层，嵌套对象需另外加 @Valid 注解
- @Validated 是 Spring 的，@Valid 是 JSR-380 的，功能有细微差异
- 全局异常处理不要吞掉异常日志
- RESTful 不是银弹，一些复杂操作（如批量操作）可能不适合 RESTful 风格
