---
name: java-springboot-analysis
description: Use when the user asks to analyze Spring/SpringBoot code, Bean lifecycle, dependency injection, transaction management, or AOP configuration.
triggers: "spring, @transactional, bean, ioc, autowired, 事务传播, controller, service, boot"
applicable: "Spring/SpringBoot specific questions: Bean config, DI, transaction propagation, AOP, Spring Boot auto-config, layered architecture"
not_applicable: "General Java code reading without Spring context, SQL queries, MyBatis XML mapping, generic code style checks"
---

# SpringBoot 源码业务分析

## Overview

精通 Spring/SpringBoot 全机制，分析 Bean 生命周期、三级缓存、依赖注入、事务传播机制。精准识别 @Transactional 事务失效、Bean 循环依赖、切面执行异常、全局配置不生效等经典问题，适配 Controller/Service/Mapper 分层业务代码。

## Analysis Checklist

### 1. Bean 生命周期分析
- Bean 定义 → 实例化 → 属性填充 → 初始化前（BeanPostProcessor.postProcessBeforeInitialization）→ 初始化（InitializingBean/@PostConstruct）→ 初始化后（BeanPostProcessor.postProcessAfterInitialization）→ 就绪 → 销毁（DisposableBean/@PreDestroy）
- 标注每个阶段的关键扩展点
- Bean 的作用域：singleton/prototype/request/session
- @Lazy 延迟加载的分析

### 2. 依赖注入分析
- 注入方式：构造器注入（推荐）> setter 注入 > 字段注入（@Autowired 在字段上）
- 多个同类型 Bean 的歧义：@Primary vs @Qualifier
- @Resource vs @Autowired 的区别（byName vs byType）
- 可选依赖：@Autowired(required = false)
- 构造器注入的循环依赖问题（Spring 无法解决构造器注入的循环依赖）

### 3. 循环依赖诊断
- Spring 三级缓存机制：singletonObjects → earlySingletonObjects → singletonFactories
- 哪些循环依赖可以解决：setter 注入/字段注入（通过三级缓存暴露早期引用）
- 哪些不能解决：构造器注入的循环依赖
- @Lazy 解决构造器循环依赖的原理
- 循环依赖 + AOP 代理的叠加问题

### 4. @Transactional 事务分析
- 事务失效清单（完整排查）：
  1. 非 public 方法
  2. 同类内部调用（this.method() 绕过代理）
  3. 异常被 catch 吞掉
  4. rollbackFor 未包含当前异常类型
  5. 数据库引擎不支持事务（MyISAM）
  6. 多线程环境（事务与线程绑定）
- 事务传播行为（7 种）：REQUIRED/SUPPORTS/MANDATORY/REQUIRES_NEW/NOT_SUPPORTED/NEVER/NESTED
- 事务隔离级别（5 种）：DEFAULT/READ_UNCOMMITTED/READ_COMMITTED/REPEATABLE_READ/SERIALIZABLE
- @Transactional 的超时和只读优化

### 5. 全局配置与自动装配
- @ConfigurationProperties vs @Value
- @ConditionalOnXxx 注解的条件装配
- spring.factories / spring-autoconfigure-metadata.properties 的作用
- 自定义 starter 的自动装配
- 配置优先级：命令行参数 > 环境变量 > application-{profile}.yml > application.yml

### 6. 分层架构分析
- Controller：参数校验（@Valid/@Validated）、异常处理（@ExceptionHandler/@ControllerAdvice）
- Service：事务边界、业务逻辑、幂等性
- Mapper/Repository：SQL 逻辑、分页、缓存
- 跨层调用是否规范（禁止 Controller 直接调 Mapper）
- DTO/VO/PO 的转换位置

## Output Format

```markdown
## Bean 依赖图
[Mermaid classDiagram 展示 Bean 注入关系]

## @Transactional 审计
| 方法 | 传播行为 | rollbackFor | 自调用风险 | 评估 |

## 问题清单
| 优先级 | 问题 | 位置 | 根因 | 修复方案 |

## 分层结构
[Mermaid 或表格展示 Controller→Service→Mapper 关系]
```

## Common Pitfalls

- Spring Boot 的 @SpringBootApplication 默认扫描同包及子包
- @Async 方法也依赖代理，同类内部调用同理失效
- @Cacheable 注解同样存在自调用失效问题
- @EventListener 的异步事件需要使用 @Async 配合
- 不要在 @PostConstruct 中做耗时操作（阻塞启动）
