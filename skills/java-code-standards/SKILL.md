---
name: java-code-standards
description: Use when the user asks to check Java code quality, coding standards, naming conventions, or style issues. Triggers on requests like "检查代码规范", "代码格式有问题吗", "按阿里巴巴手册检查", "scan for code violations", "命名是否规范". Also use when the user wants a comprehensive code standards audit including compilation errors, syntax issues, missing comments, and format problems.
---

# Java 编码规范与语法检测

## Overview

专门检测 Java 代码的编译报错、语法异常、变量方法命名不规范、缺少必要注释、代码格式混乱等问题。严格参照阿里巴巴 Java 开发手册规约扫描违规写法，按错误/警告/规范建议三级分类输出。

## Analysis Checklist

### 1. 编译级错误检测（Error 级别）
- 缺少必需的 import 语句
- 引用了不存在的类、方法或变量
- 类型不匹配：参数类型、返回类型、泛型类型
- 访问权限冲突：尝试访问 private/protected 成员
- 未处理的受检异常（checked exception）
- 抽象方法未实现
- 接口方法签名不一致
- 无效的注解使用（如 @Override 应用于非重写方法）

### 2. 语法异常检测（Warning 级别）
- 无条件使用泛型（raw type）
- 未使用的变量、方法、导入
- 资源未关闭（未使用 try-with-resources）
- equals() 与 hashCode() 不一致
- 序列化类未声明 serialVersionUID
- 可能的空指针解引用
- switch 语句缺少 default 分支

### 3. 命名规范检测
按阿里巴巴 Java 开发手册（一）命名风格章节逐项检查：
- 类名使用 UpperCamelCase
- 方法名、参数名、变量名使用 lowerCamelCase
- 常量名全部大写，下划线分隔
- 抽象类以 Abstract 或 Base 开头
- 异常类以 Exception 结尾
- 测试类以 Test 结尾
- 数组定义时中括号紧跟类型（String[] args 而非 String args[]）
- POJO 类中布尔变量不加 is 前缀
- 包名全部小写，连续单词无双下划线
- 接口命名不加 I 前缀或 Impl 后缀（除特殊场景）

### 4. 注释规范检测
- 所有类必须有 Javadoc 注释（@author, @since 等）
- 所有 public 方法必须有 Javadoc 注释
- 复杂业务逻辑必须有行内注释
- 被注释掉的代码必须删除而非保留
- 特殊注释标记（TODO/FIXME/XXX）必须注明责任人和时间

### 5. 代码格式检测
- 缩进：4 个空格，禁止 Tab
- 单行字符数不超过 120
- 大括号使用约定：左大括号不换行，右大括号换行
- if/for/while 等语句必须使用大括号（即使只有一行）
- 不同逻辑块之间使用空行分隔
- 运算符两侧加空格
- 逗号后加空格
- 文件末尾有且仅有一个换行符

### 6. 阿里巴巴规约专项扫描
参照阿里巴巴 Java 开发手册各章节进行扫描：
- 集合处理：ArrayList 初始化指定容量、keySet/values 不可修改、subList 不可序列化
- 并发处理：线程池不允许使用 Executors 创建、SimpleDateFormat 线程不安全
- 控制语句：switch 使用 String 需判空、不要在条件判断中执行复杂语句
- OOP 规约：避免通过对象引用访问静态变量、所有重写方法必须加 @Override
- 异常处理：finally 中不要使用 return、异常不应用来做流程控制
-  MySQL 规约：表名/字段名必须小写、索引命名规范、varchar 长度指定

## Output Format

按三级分类输出，每项含行号和修改方案：

```markdown
## 🔴 错误（必须修复）
| 行号 | 问题描述 | 违规代码 | 修改方案 | 规约引用 |

## 🟡 警告（建议修复）
| 行号 | 问题描述 | 违规代码 | 修改方案 | 规约引用 |

## 🔵 规范建议（可选优化）
| 行号 | 问题描述 | 违规代码 | 修改方案 | 规约引用 |
```

## Common Pitfalls

- Lombok 注解（@Data/@Getter/@Setter）自动生成的方法不要标记为 "缺少 Javadoc"
- MapStruct/Protobuf 等自动生成的类可以豁免部分命名和注释规则
- 测试类的方法命名可使用下划线分隔（given_when_then 风格）
- Spring Bean 的注入字段可为 null 用 @Autowired(required = false) 标注
- 自动生成的 equals/hashCode/toString 不算缺失代码
