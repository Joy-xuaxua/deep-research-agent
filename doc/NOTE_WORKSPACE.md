# Note Workspace 结构说明

## 目录结构

```
./notes/                          # 工作区（默认位置）
├── {task_note_id}.md             # 任务状态笔记（note_type: task_state）
├── {report_note_id}.md           # 最终报告笔记（note_type: conclusion）
└── ...

./archives/                       # 归档区（调研完成后移动到这里）
└── {timestamp}_{topic_safe}/     # 按时间戳和主题分组的归档目录
    ├── {report_note_id}_report.md    # 最终报告（保留note_id）
    ├── {task_note_id}_任务标题.md    # 任务笔记（保留note_id）
    └── ...

# 示例
./archives/
└── 20260128_163238_talking face generation在商业中的最新应用和效果/
    ├── note_20260128_163450_5_report.md
    ├── note_20260128_163238_0_技术发展概览.md
    ├── note_20260128_163238_1_商业应用案例.md
    └── ...
```

## Note类型与字段

### 1. 任务状态笔记 (task_state)
```markdown
---
note_id: xxx
task_id: 1
title: 任务 1: xxx
note_type: task_state
tags: ["deep_research", "task_1"]
created_at: xxx
updated_at: xxx
---

# 任务 1: xxx

## 任务概览
任务描述...

## 来源概览
- 来源1 : url
- 来源2 : url

## 总结
任务的详细总结...
```

### 2. 最终报告笔记 (conclusion)
```markdown
---
note_id: xxx
note_type: conclusion
tags: ["deep_research", "report"]
created_at: xxx
updated_at: xxx
---

# 研究报告：xxx

完整的报告内容...
```

## 归档流程

1. **触发时机**：调研完成时（无论成功或失败）

2. **归档操作**：
   - 为最终报告生成有意义的标题（基于研究主题）
   - 为每个任务笔记生成有意义的文件名
   - 将所有相关notes从workspace移动到归档目录
   - 发送`archived`事件到前端，显示归档路径

3. **归档目录命名**：
   - 格式：`{timestamp}_{safe_topic}{_failed可选}`
   - timestamp从note_id中提取（YYYYMMDD_HHMMSS格式）
   - 使用研究主题的安全文件名（移除特殊字符）
   - 例如：`note_20260128_163238_0` + `talking face generation在商业中的最新应用和效果`
     -> `20260128_163238_talking face generation在商业中的最新应用和效果`
   - 失败的研究添加`_failed`后缀

4. **文件重命名规则**：
   - 报告：`{note_id}.md` -> `{note_id}_report.md`
   - 任务：`{note_id}.md` -> `{note_id}_{sanitize(title)}.md`
   - 保留原始note_id，后跟描述性名称
   - 例如：`note_20260128_163238_0.md` + `技术发展概览`
     -> `note_20260128_163238_0_技术发展概览.md`

5. **孤儿笔记处理**：
   - 归档时会检查workspace中所有.md文件
   - 未被tracking的note会被归档为`{note_id}_orphaned.md`
   - 确保workspace中没有遗留的note文件

## 配置选项

| 环境变量 | 默认值 | 说明 |
|---------|-------|------|
| `ENABLE_NOTES` | `True` | 是否启用NoteTool记录任务进度 |
| `NOTES_WORKSPACE` | `./notes` | 活跃笔记的存储目录 |
| `ENABLE_ARCHIVING` | `True` | 是否在完成后自动归档 |
| `ARCHIVES_DIR` | `./archives` | 归档根目录 |

## API事件

归档完成后会发送以下SSE事件：

```typescript
// 归档成功
{
  type: "archived",
  archive_dir: "./archives/20260128_163238_多模态模型在2025年的突破",
  report_path: "./archives/.../note_20260128_163450_5_report.md",
  task_count: 3
}

// 归档失败
{
  type: "archive_failed",
  error: "错误信息"
}
```

**注意**：归档会自动检测并移动workspace中所有.md文件，包括未被明确tracking的孤儿笔记。
