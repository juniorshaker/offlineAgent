---
name: java-annotation-aop
description: Use when the user asks about Java annotations, Spring AOP aspects, reflection, or dynamic proxies. Triggers on requests like "这个注解怎么工作的", "AOP切面为什么没拦截到", "反射调用报错", "自定义注解分析", "@Around没生效", "检查切面配置", "proxy mechanism". Also use for debugging annotation失效, aspect misconfigurations, and reflection errors.
---

# Java 注解与 AOP 反射专项分析

## Overview

专注解析 Java 原生注解、项目自定义注解运行逻辑。分析 Spring AOP 切面拦截规则、生效范围、执行顺序。拆解反射、动态代理底层执行流程，定位注解失效、切面无法拦截、反射报错等常见疑难问题。

## Analysis Checklist

### 1. 注解定义分析
- 元注解检查：@Target（作用目标）、@Retention（生命周期 SOURCE/CLASS/RUNTIME）、@Documented、@Inherited、@Repeatable
- 注解属性：类型、默认值、是否必需
- 注解处理器/切面的绑定关系
- 自定义注解的完整工作链路

### 2. 注解生效条件检查
- @Retention 是否为 RUNTIME（否则反射/运行时无法读取）
- @Target 是否包含目标元素类型
- @Inherited 是否正确传递到子类
- @Repeatable 的容器注解是否正确配置
- 注解是否被代理对象丢失（JDK 动态代理只保留接口上的注解）

### 3. Spring AOP 切面分析
- 切点表达式（Pointcut）解析：execution/@annotation/@within/@args/@target
- 验证切点表达式是否匹配目标方法
- 通知类型与执行顺序：@Around → @Before → @AfterReturning/@AfterThrowing → @After
- 多个切面的执行顺序：@Order 注解或 Ordered 接口
- 自调用问题：同类内部方法调用不触发 AOP（this.method() vs AopContext.currentProxy()）

### 4. AOP 失效诊断清单
- 切点表达式写错：包名/类名/方法名不匹配
- 目标对象未被 Spring 管理（非 Bean）
- 代理机制限制：JDK 动态代理（基于接口）vs CGLIB 代理（基于继承）
- final 方法/类无法被 CGLIB 代理
- private 方法无法被代理
- 同类内部调用绕过代理
- @Transactional 和自定义切面的执行顺序冲突
- aspectj 编译期织入 vs Spring AOP 运行期代理的区别

### 5. 反射机制分析
- Class.forName / ClassLoader.loadClass 的区别
- getDeclaredMethods vs getMethods
- setAccessible(true) 的安全影响
- 反射调用 Method.invoke 的性能开销
- 泛型擦除对反射的影响（ParameterizedType/TypeVariable）
- 桥接方法（bridge method）的识别

### 6. 动态代理分析
- JDK 动态代理：Proxy.newProxyInstance + InvocationHandler
- CGLIB 代理：Enhancer + MethodInterceptor
- 代理对象的类型检查（instanceof 行为变化）
- 多层代理的嵌套关系
- 代理对象序列化问题

## Output Format

```markdown
## 注解定义
| 注解 | @Target | @Retention | 处理器/切面 | 属性 |

## AOP 切面分析
| 切面类 | Pointcut | 通知类型 | @Order | 拦截范围 |

## 问题清单
| 问题 | 类型(注解失效/切面无效/反射错误) | 根因 | 修复方案 |

## 代理链路
[Mermaid 展示代理对象的生成和调用链路]
```

## Common Pitfalls

- @Transactional 自调用失效是最常见的 Spring AOP 陷阱
- JDK 动态代理会丢失类上的注解（只保留接口注解），需用 CGLIB 或从目标类获取
- Spring Boot 2.x 默认使用 CGLIB 代理（spring.aop.proxy-target-class=true）
- 切面的 @Order 越小优先级越高（与 @Order 在集合注入中的语义可能不一致）
- Lambda 表达式无法被 AOP 拦截
- @Async 配合 @Transactional 时注意线程上下文传递
