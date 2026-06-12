---
name: diagrams
description: Use when the user asks to draw flowcharts, architecture diagrams (logical/physical), sequence diagrams, class diagrams, ER diagrams, state diagrams, deployment diagrams, or any visual diagram representing system structure, process flow, or data flow. Triggers on requests like "画个流程图", "架构图", "部署图", "时序图", "ER图", "类图", "draw a diagram", "visualize the architecture", or any task requiring diagram output.
---

# 图表绘制：流程图 / 架构图 / 部署图

## Overview

根据用户需求，使用 Mermaid 语法输出以下类型的专业图表。所有图表标注使用中文，节点命名保持简洁。

## 图表类型速查

| 类型 | Mermaid 语法 | 适用场景 |
|------|-------------|----------|
| 流程图 | `flowchart TD/LR` | 业务流程、代码执行流、审批流、算法步骤 |
| 逻辑架构图 | `graph TB` | 模块分层、微服务依赖、组件关系、分层架构 |
| 物理架构图 | `graph TB` + 节点标注 | 服务器部署、网络分区、数据库集群、负载均衡 |
| 时序图 | `sequenceDiagram` | API 调用链、微服务交互、认证流程、消息传递 |
| 类图 | `classDiagram` | 面向对象设计、继承关系、接口实现 |
| ER 图 | `erDiagram` | 数据库表关系、字段设计、外键约束 |
| 状态图 | `stateDiagram-v2` | 订单状态流转、用户生命周期、设备状态机 |
| 甘特图 | `gantt` | 项目排期、迭代计划、里程碑 |
| C4 模型 | `graph TB` + 分组 | 系统上下文、容器图、组件图 |

## 绘制规范

### 通用规范
- 节点 ID 使用英文小写 + 下划线（如 `user_service`），显示文本用中文（如 `用户服务`）
- 复杂图使用 `subgraph` 分组，每组标注层/域/系统边界
- 关键路径用颜色标注：正常流 `#a0d2af`，异常流 `#f5a0a0`，外部系统 `#a0c8f5`
- 图标题放在 Mermaid 代码块上面，用 `### 标题` 格式
- 每个节点不超过 10 个中文字，过长的加 `\n` 换行

### 流程图规范
- 起止节点用 `([ ])` 或 `(( ))`
- 判断节点用 `{ }`
- 处理节点用 `[ ]`

### 架构图规范
- **逻辑架构**：按层次分组（表示层 / 业务层 / 数据层 / 基础设施层）
- **物理架构**：标注服务器名、IP 段、端口、数据库实例名
- C4 风格：区分人（Person）、系统（System）、容器（Container）、组件（Component）

## 示例

### 1. 流程图 — 用户登录

\`\`\`mermaid
flowchart TD
    A([用户输入账号密码]) --> B{账号是否存在}
    B -->|是| C{密码是否正确}
    B -->|否| D[提示账号不存在]
    C -->|是| E{是否启用 MFA}
    C -->|否| F[提示密码错误]
    F --> G{错误次数 > 3?}
    G -->|是| H[锁定账号 30min]
    G -->|否| A
    E -->|是| I[发送验证码]
    E -->|否| J[签发 Token]
    I --> K{验证码正确?}
    K -->|是| J
    K -->|否| L[提示验证码错误]
    J --> M([登录成功])

    style D fill:#f5a0a0
    style F fill:#f5a0a0
    style H fill:#f5a0a0
    style L fill:#f5a0a0
    style M fill:#a0d2af
\`\`\`

### 2. 逻辑架构图 — 微服务分层

\`\`\`mermaid
graph TB
    subgraph 接入层
        LB[负载均衡\nNginx]
        GW[API 网关\nSpring Gateway]
    end

    subgraph 业务服务层
        US[用户服务\nUser Service]
        OS[订单服务\nOrder Service]
        PS[商品服务\nProduct Service]
    end

    subgraph 中间件层
        MQ[消息队列\nRabbitMQ]
        REDIS[(缓存\nRedis)]
    end

    subgraph 数据层
        MASTER[(主库\nMySQL)]
        SLAVE[(从库\nMySQL Read)]
        ES[(搜索引擎\nElasticsearch)]
    end

    LB --> GW
    GW --> US
    GW --> OS
    GW --> PS
    OS --> MQ
    MQ --> US
    US --> REDIS
    OS --> REDIS
    OS --> MASTER
    MASTER -->|主从复制| SLAVE
    PS --> ES

    style LB fill:#a0c8f5
    style GW fill:#a0c8f5
    style US fill:#a0d2af
    style OS fill:#a0d2af
    style PS fill:#a0d2af
    style MQ fill:#f5d5a0
    style REDIS fill:#f5d5a0
    style MASTER fill:#d5a0f5
    style SLAVE fill:#d5a0f5
    style ES fill:#d5a0f5
\`\`\`

### 3. 物理部署架构图

\`\`\`mermaid
graph TB
    subgraph 外网
        USER[用户\nPC/手机]
        CDN[CDN\n静态资源]
    end

    subgraph DMZ区\n192.168.1.0/24
        PROXY[Nginx 反向代理\n192.168.1.10:443]
        WAF[WAF 防火墙]
    end

    subgraph 应用区\n10.0.1.0/24
        APP1[App Server 1\n10.0.1.11:8080]
        APP2[App Server 2\n10.0.1.12:8080]
        APP3[App Server 3\n10.0.1.13:8080]
    end

    subgraph 数据区\n10.0.2.0/24
        DB_MASTER[(MySQL Master\n10.0.2.21:3306)]
        DB_SLAVE1[(MySQL Slave1\n10.0.2.22:3306)]
        DB_SLAVE2[(MySQL Slave2\n10.0.2.23:3306)]
        REDIS_CLUSTER[(Redis Cluster\n10.0.2.31-33:6379)]
    end

    USER --> CDN
    CDN --> PROXY
    PROXY --> WAF
    WAF --> APP1
    WAF --> APP2
    WAF --> APP3
    APP1 --> DB_MASTER
    APP2 --> DB_MASTER
    APP3 --> DB_MASTER
    DB_MASTER --> DB_SLAVE1
    DB_MASTER --> DB_SLAVE2
    APP1 --> REDIS_CLUSTER
    APP2 --> REDIS_CLUSTER
    APP3 --> REDIS_CLUSTER
\`\`\`

### 4. 时序图

\`\`\`mermaid
sequenceDiagram
    actor U as 用户
    participant GW as API网关
    participant Auth as 认证服务
    participant OS as 订单服务
    participant DB as 数据库

    U->>GW: POST /login
    GW->>Auth: 验证凭据
    Auth->>DB: 查询用户
    DB-->>Auth: 用户记录
    Auth-->>GW: JWT Token
    GW-->>U: Token + 用户信息

    U->>GW: POST /orders (Bearer Token)
    GW->>Auth: 校验Token
    Auth-->>GW: 合法用户
    GW->>OS: 创建订单
    OS->>DB: INSERT 订单记录
    DB-->>OS: 订单ID
    OS-->>GW: 订单详情
    GW-->>U: 订单创建成功
\`\`\`

### 5. ER 图

\`\`\`mermaid
erDiagram
    USER ||--o{ ORDER : "下单"
    ORDER ||--|{ ORDER_ITEM : "包含"
    ORDER_ITEM }o--|| PRODUCT : "对应"

    USER {
        bigint id PK "用户ID"
        varchar username "用户名"
        varchar email "邮箱"
    }

    ORDER {
        bigint id PK "订单ID"
        bigint user_id FK "用户ID"
        decimal amount "订单金额"
        tinyint status "状态"
    }

    ORDER_ITEM {
        bigint id PK "明细ID"
        bigint order_id FK "订单ID"
        bigint product_id FK "商品ID"
        int quantity "数量"
    }

    PRODUCT {
        bigint id PK "商品ID"
        varchar name "商品名"
        decimal price "单价"
    }
\`\`\`

### 6. 状态图 — 订单生命周期

\`\`\`mermaid
stateDiagram-v2
    [*] --> 待支付
    待支付 --> 已支付: 支付成功
    待支付 --> 已取消: 超时/用户取消
    已支付 --> 处理中: 系统接单
    处理中 --> 已发货: 出库完成
    已发货 --> 配送中: 快递揽收
    配送中 --> 已签收: 用户签收
    已签收 --> 已完成: 7天自动确认
    已支付 --> 退款中: 用户申请退款
    退款中 --> 已退款: 审核通过
    退款中 --> 已支付: 审核拒绝
    已取消 --> [*]
    已完成 --> [*]
    已退款 --> [*]
\`\`\`

## C4 模型指南

当用户要求"画架构图"但不明确是哪一层时，按以下优先级判断：

1. **系统上下文图（Context）**：用户问"系统有哪些外部依赖"、"整体架构"时
   - 中心是系统本身，周围是外部系统、用户角色
2. **容器图（Container）**：用户问"有哪些服务/应用"、"技术栈是什么"时
   - 展示每个可独立部署的单元（Web应用、微服务、数据库、消息队列）
3. **组件图（Component）**：用户问"服务内部怎么分层"时
   - 展示 Controller → Service → Repository 等内部结构

## 渲染选项

### 选项一：直接输出 Mermaid 文本（默认）
- 放入 Markdown 文档即可渲染（VS Code + Mermaid 插件、GitHub、语雀、Notion）
- 零依赖，所有环境通用

### 选项二：渲染为 PNG/SVG
如果环境中安装了 `playwright` 浏览器，可通过浏览器渲染 Mermaid 为图片：
1. 构造一个包含 Mermaid 代码的 HTML 页面
2. 用 `browser_screenshot` 截图
3. 输出 PNG 到指定路径

### 选项三：使用 Python 渲染库
如果 `vendor/` 下有 `mermaid` Python 包，可渲染为 PNG。否则提示用户需要先安装。

## 输出格式

```markdown
## 图表说明
[简要描述图的用途和阅读方式]

### 图：[标题]

\`\`\`mermaid
[完整的 Mermaid 代码]
\`\`\`

## 关键说明
- [节点/关系的业务含义]
- [颜色/分组的含义]
- [值得注意的边界条件或假设]
```

## Constraints

- 节点显示文本必须使用中文（技术术语例外如 Nginx、MySQL）
- 每个 `subgraph` 必须标注边界名称
- 架构图必须区分内外部系统（外网/DMZ/内网）
- 时序图必须标注 `actor`（用户角色）和 `participant`（系统组件）
- 不使用中文标点作为节点 ID
- 颜色标注必须图例说明

## Common Pitfalls

- 流程图只有主流程没有异常分支 → 必须补充异常路径
- 架构图把不同层级混在一个 subgraph → 按职责分层
- 物理架构图只有应用没有基础设施（LB/网关/监控/日志）→ 补齐
- Mermaid 语法大小写敏感，`flowchart` 不能写成 `FlowChart`
- `subgraph` 名称含特殊字符时需加引号
- 箭头方向混乱（乱用 `-->` `---`）→ 按语义选择
