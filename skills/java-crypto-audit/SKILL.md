---
name: java-crypto-audit
description: Use when the user asks to audit Java encryption/decryption code, cryptographic utilities, or security algorithms. Triggers on requests like "加密代码审计", "密钥有没有硬编码", "加密算法安全吗", "AES用得规范吗", "SM4国密算法", "密码存储安全吗", "crypto code review". Also use for analyzing AES/RSA/MD5/SHA256/SM4 usage, key management, encoding issues, and cryptographic best practices.
---

# Java 加解密工具类深度审计

## Overview

分析各类 Java 工具类、数据加解密代码，涵盖 AES、RSA、MD5、SHA256、SM4 国密算法。拆解加密、解密、加盐、编码转换全流程。排查密钥硬编码、弱加密算法、密钥泄露、编码错乱等安全漏洞。

## Analysis Checklist

### 1. 算法选型审计
- 对称加密：AES（推荐）> 3DES（已过时）> DES（不安全）
- 非对称加密：RSA 2048+（推荐）> RSA 1024（不安全）
- 哈希算法：SHA-256/SHA-512（推荐）> SHA-1（不安全）> MD5（不安全，仅用于非安全场景）
- 国密算法：SM2（非对称）> SM3（哈希）> SM4（对称）
- 密码存储：bcrypt/scrypt/Argon2（推荐）> PBKDF2 > 直接哈希（不安全）

### 2. 密钥管理审计
- 密钥硬编码检测：代码中直接出现密钥字符串、字节数组、Base64 编码密钥
- 配置文件中的密钥是否正确加密存储
- 密钥的来源和生成方式（SecureRandom vs Random）
- 密钥存储位置：环境变量 > 密钥管理服务（KMS/Vault）> 加密配置文件 > 明文配置
- 密钥轮换策略是否存在

### 3. 加密实现审计
- AES 工作模式：GCM（推荐，自带认证）> CBC（需要 HMAC）> ECB（不安全）
- IV/Nonce 的生成和使用：
  - 每次加密必须使用新的随机 IV
  - IV 是否使用 SecureRandom 生成
  - GCM 模式 nonce 长度（96 位推荐）
- 填充模式：PKCS5Padding/PKCS7Padding
- 加密后的数据完整性校验（GCM 自动认证 / HMAC 校验）

### 4. 编码转换分析
- 密钥、明文、密文的编码一致性：
  - 密钥生成：字节 → Base64 存储
  - 加密前：明文字符串 → 字节（指定编码 UTF-8）
  - 加密后：密文字节 → Base64/Hex 传输
- 常见的编码错乱：
  - 未指定字符编码导致平台差异
  - Base64 URL Safe vs 标准 Base64 混用
  - 加解密两端字符编码不一致

### 5. 随机数安全
- 使用 SecureRandom（推荐 /dev/urandom 或 SHA1PRNG）而非 Random
- 种子设置是否安全（不要使用固定种子或时间戳）
- SecureRandom.getInstanceStrong() 的阻塞风险

### 6. 协议与证书
- HTTPS/TLS 版本检测（TLS 1.2+）
- 证书校验是否被绕过（TrustAll/HostnameVerifier 全接受）
- 自定义 TrustManager/SSLSocketFactory 的安全性
- JCA/JCE 的 Provider 选择

## Output Format

```markdown
## 加解密概览
| 位置 | 算法 | 模式 | 密钥来源 | 风险等级 |

## 密钥硬编码
| 位置 | 密钥类型 | 编码方式 | 严重程度 | 修复方案 |

## 算法问题
| 问题 | 位置 | 当前写法 | 风险说明 | 修复代码 |

## 编码一致性检查
| 加解密位置 | 编码方式 | 是否一致 | 问题 |
```

## Common Pitfalls

- ECB 模式在图像加密时会暴露图案轮廓（这是经典的反面教材）
- GCM 模式的 nonce 重复使用会导致认证密钥泄露
- MD5 和 SHA-1 用于密码哈希是不安全的，但用于文件校验（checksum）可以接受
- 不要自己设计加密算法或协议，使用标准库
- Cipher 实例不是线程安全的，每次加解密应创建新实例
