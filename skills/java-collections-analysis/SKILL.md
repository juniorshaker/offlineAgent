---
name: java-collections-analysis
description: Use when the user asks to analyze Java collection usage, ArrayList/LinkedList/HashMap/ConcurrentHashMap/HashSet patterns, or collection-related bugs. Triggers on requests like "集合用得对吗", "HashMap还是ArrayList", "ConcurrentModificationException", "集合遍历删除", "集合扩容问题", "collection best practice". Also use for collection type selection analysis and traversal/deletion correctness.
---

# Java 集合专项源码分析

## Overview

深度剖析 ArrayList、LinkedList、HashMap、ConcurrentHashMap、HashSet 等主流集合的使用逻辑。识别集合选型错误、遍历删除异常、扩容隐患、空值存储风险、并发修改异常等问题，规范集合最佳实践。

## Analysis Checklist

### 1. 集合选型评估
- 访问模式：随机访问 → ArrayList，顺序访问/频繁插入删除 → LinkedList
- 去重需求：HashSet（无序）/LinkedHashSet（有序）/TreeSet（排序）
- 键值对：HashMap（无序）/LinkedHashMap（有序）/TreeMap（排序键）
- 线程安全：ConcurrentHashMap > Hashtable > Collections.synchronizedMap()
- 读多写少 → CopyOnWriteArrayList
- 优先级 → PriorityQueue vs TreeSet
- 只读 → Collections.unmodifiableXxx() 或 List.of()/Set.of()（Java 9+）

### 2. 初始化与容量
- ArrayList 未指定初始容量 → 频繁扩容（默认 10 → 1.5 倍增长）
- HashMap 未指定初始容量 → 频繁 rehash（默认 16 → 2 倍增长，阈值 0.75）
- 已知大小的集合是否指定了初始容量
- LinkedHashMap 的 accessOrder 参数（LRU 缓存实现）
- HashSet 底层是 HashMap，容量逻辑一致

### 3. 遍历与删除
- 不能在 for-each 循环中直接调用 list.remove()（ConcurrentModificationException）
- 正确方式：Iterator.remove() 或 removeIf()（Java 8+）
- 倒序遍历用普通 for 循环删除（ArrayList 场景）
- Map 遍历时删除：entrySet().removeIf() 或 iterator.remove()
- stream().filter().collect() 替代遍历删除
- List 的正向索引删除导致跳过元素

### 4. 空值与键设计
- HashMap 允许 null key 和 null value，Hashtable/ConcurrentHashMap 不允许
- TreeMap 不允许 null key（需要 Comparator）
- ArrayList 允许 null 元素，但要注意后续操作（sort/stream）
- equals/hashCode 一致性：作为 HashMap key 的对象必须正确实现两者
- 可变对象作为 key 的风险

### 5. 排序与比较
- Collections.sort() 使用 TimSort（稳定排序）
- Comparable（自然顺序）vs Comparator（自定义顺序）
- Comparator 必须满足自反性、对称性、传递性
- TreeSet/TreeMap 的 Comparator 与 equals 一致性问题
- 排序前是否需要去重

### 6. 并发集合
- ConcurrentHashMap 的分段锁（JDK7）→ CAS + synchronized（JDK8+）
- ConcurrentHashMap 的 computeIfAbsent 原子性
- CopyOnWriteArrayList 的写时复制开销（适合读多写少）
- ConcurrentLinkedQueue 的 CAS 无锁算法
- BlockingQueue 的 put/take 阻塞语义

## Output Format

```markdown
## 集合使用概览
| 变量 | 集合类型 | 使用场景 | 选型评估 | 建议 |

## 问题清单
| 优先级 | 问题 | 位置 | 当前写法 | 风险 | 修复建议 |

## 遍历删除审计
| 位置 | 遍历方式 | 删除方式 | 安全性 | 说明 |

## 容量审计
| 集合 | 当前容量 | 预计大小 | 扩容次数 | 建议初始容量 |
```

## Common Pitfalls

- Arrays.asList() 返回的是固定大小的 List，不支持 add/remove
- subList() 返回的是原 List 的视图，修改互相关联，且 subList 不可序列化
- Collections.emptyList() 返回不可变空列表
- toArray() 无参方法返回 Object[]，应用 toArray(new String[0])
- Map.values() 和 keySet() 返回的集合不支持 add/addAll 操作
- Stream.collect() 优于 for-each 中 add 到集合
