---
title: PostgreSQL与pgvector课程笔记
notebook: 技术学习
tags: [PostgreSQL, pgvector, 数据库]
type: study-note
date: 2026-09-26
---

# PostgreSQL 与 pgvector：复习卡片

## 关系数据和向量数据

PostgreSQL 可以在同一数据库中保存普通业务字段与向量列。个人知识库可以在笔记表中保存标题、正文版本和账号归属，再把切分后的文本及向量放到片段表。

示意结构：

```sql
CREATE TABLE note_chunks (
  note_id uuid NOT NULL,
  note_version integer NOT NULL,
  ordinal integer NOT NULL,
  content text NOT NULL,
  embedding vector(1024)
);
```

此片段仅是教学用 SQL，实际表结构还要按应用迁移定义核对。

## 检索时容易遗漏的条件

- 片段属于当前账号。
- 笔记没有被软删除。
- 片段版本等于笔记当前内容版本。
- 计算向量距离前先限制候选范围，避免混入过期片段。

## 自测

**问：** 为什么软删除的笔记可能还留在数据库？  
**答：** 软删除通常写入 `deleted_at`，便于保留恢复或审计所需的信息；读取接口需要显式排除已删除记录。

**问：** 标签变化需要重新生成正文向量吗？  
**答：** 一般不需要，因为标签变化没有改变标题或正文；这套项目素材用来验证系统的这一设计边界。
