---
name: python-api-optimization
description: Use when the user asks to optimize Python API endpoints, review FastAPI/Flask/Django performance, improve API response time, or restructure API architecture.
---

# Python API 优化

## Overview

审计和优化 Python Web API（FastAPI / Flask / Django / Sanic 等），提升响应速度、吞吐量和可维护性。

## Audit Checklist

### 1. 端点设计
- RESTful 规范：资源命名（名词复数）、HTTP 方法语义正确
- 路径参数 vs 查询参数的使用
- 版本化策略：URL 前缀 / Header
- 分页：offset/limit 或 cursor-based
- 批量端点：单条操作 → 批量操作

### 2. 查询优化
- N+1 查询：使用 `selectinload` / `joinedload`（SQLAlchemy）或 `prefetch_related` / `select_related`（Django）
- 索引：查询条件的数据库索引覆盖
- 查询字段裁剪：`SELECT * ` → 只选需要的字段
- 连接池配置：`pool_size` / `max_overflow` 合理设置

### 3. 响应优化
- 响应体大小：字段过滤、gzip 压缩
- 缓存策略：`Cache-Control` / `ETag` / `Last-Modified` 头
- 服务端缓存：Redis 缓存热点数据、`functools.lru_cache`
- 异步视图：IO 密集端点使用 `async def`

### 4. 中间件与依赖
- 认证中间件的执行顺序和开销
- CORS 配置是否过宽
- 请求体大小限制
- Rate limiting

### 5. 错误处理
- 统一异常处理：`@app.exception_handler` / middleware
- 错误响应格式一致
- 不暴露内部堆栈信息给客户端

## Output Format

```markdown
## API 概览
| 端点 | 方法 | 平均耗时 | 查询数 |

## 瓶颈清单
| 问题 | 端点 | 严重程度 | 预期改善 |

## 优化方案
[Before/After 代码对比]

## 缓存策略建议
[哪些数据可缓存 + TTL]
```

## Constraints

- 优先优化高频调用端点
- 标注优化是否需要数据库迁移
- 响应格式变更标注为 breaking change
