# Plan: Optimize Context Data Structure in `task_executor.py`

## Context

在 `task_executor.py` 的 `execute_task()` 方法中，搜索结果经过 `prepare_research_context()` 处理后，生成两个关键数据：`sources_summary`（轻量的来源列表）和 `context`（包含完整页面内容的格式化字符串）。这些数据被传递到多个地方，但存在冗余传递和未使用的累积问题，造成内存浪费和不必要的复杂度。

---

## 当前 Context 传递全景

`prepare_research_context()` 返回 `(sources_summary, context)`:
- **`sources_summary`**: 轻量 bullet list，如 `* Title : URL`
- **`context`**: 完整格式化字符串，包含每个源的 title、URL、content snippet，如果 `fetch_full_page=True` 还包含 `raw_content`（截断到 40000 chars）

传递去向（`task_executor.py`）:

| # | 传递目标 | 传递的数据 | 是否必要 |
|---|---------|-----------|---------|
| 1 | `state.web_research_results.append(context)` | 完整 context 字符串 | ❌ **无人消费** |
| 2 | `state.sources_gathered.append(sources_summary)` | 轻量来源列表 | ❌ **无人消费** |
| 3 | SSE `sources` event → `raw_context` 字段 | 完整 context 字符串 | ⚠️ **前端可能不需要完整内容** |
| 4 | SSE `sources` event → `latest_sources` 字段 | 轻量来源列表 | ✅ 前端展示 |
| 5 | `summarizer.stream_task_summary(state, task, context)` | 完整 context 字符串 | ✅ 核心用途 |
| 6 | `summarizer.summarize_task(state, task, context)` | 完整 context 字符串 | ✅ 核心用途 |

---

## 发现的问题

### 1. `state.web_research_results` — 累积但从未被消费 🔴

- 每个任务的完整 `context`（可能包含 5 个源 × 40K chars 的 raw_content）都被 append 到这个 list
- **没有人读取这个字段**：
  - Summarizer 接收的是 per-task 的 `context` 参数，不是从这个 list 读取
  - Reporter 用的是 `task.summary` + `task.sources_summary`，不是这个 list
  - `agent.py` 从不读取 `state.web_research_results`
- **内存浪费**：5 个任务的研究 = 5 份完整 context 常驻内存

### 2. `state.sources_gathered` — 累积但从未被消费 🔴

- 同理，每个任务的 `sources_summary` 被 append
- Reporter 直接用 `task.sources_summary`，不需要累积版本
- 无人读取

### 3. SSE event `raw_context` — 大 payload 传给前端 🟡

- `"sources"` event 包含 `raw_context` 字段，携带完整 context 字符串
- 前端已收到 `latest_sources`（轻量列表），`raw_context` 可能冗余
- 需确认前端是否使用此字段

### 4. `SummaryState` 废弃字段 🟡

- `search_query`: 注释标记为 "Deprecated placeholder"，无人读写
- `running_summary`: 仅在最后赋值为 report，但输出通过 `SummaryStateOutput.running_summary` 返回，state 上的字段无人读取

---

## 优化方案

### Step 1: 移除 `state.web_research_results` 的累积

**文件**: `task_executor.py` (line 209-212)

移除 `state.web_research_results.append(context)` 这行。保留 `state.research_loop_count += 1`。

```python
# Before
with self.state_lock:
    state.web_research_results.append(context)
    state.sources_gathered.append(sources_summary)
    state.research_loop_count += 1

# After
with self.state_lock:
    state.research_loop_count += 1
```

### Step 2: 移除 `state.sources_gathered` 的累积

同 Step 1，移除 `state.sources_gathered.append(sources_summary)`。

### Step 3: 清理 `SummaryState` 中废弃的累积字段

**文件**: `models.py`

- 移除 `web_research_results` 字段
- 移除 `sources_gathered` 字段
- 移除 `search_query` 字段（已标记 deprecated）
- 保留 `running_summary`（暂保留，因为 `SummaryStateOutput` 用同名映射，可能有外部引用）

> 注意：需要全局搜索确认 `web_research_results` 和 `sources_gathered` 没有其他消费者。

### Step 4: 精简 SSE `"sources"` event 中的 `raw_context`

**文件**: `task_executor.py` (line 224-232)

先确认前端是否使用 `raw_context`。如果不用，则移除。如果需要，则只传轻量版本。

```python
# Before
yield {
    "type": "sources",
    "task_id": task.id,
    "latest_sources": sources_summary,
    "raw_context": context,  # 可能很大
    ...
}

# After (如果前端不用 raw_context)
yield {
    "type": "sources",
    "task_id": task.id,
    "latest_sources": sources_summary,
    ...
}
```

### Step 5: (可选) 优化 context 字符串结构

当前 `context` 是纯文本拼接。可考虑：
- 如果 `fetch_full_page=True` 但 `raw_content` 为空，跳过 "详细信息内容" 段
- 添加源索引编号（如 `[1]`, `[2]`），与 summarizer 的 `[N]` 引用格式对应

这是增强而非必须，可后续迭代。

---

## 已确认的调查结果

### 前端对 `raw_context` 的使用（已确认 ✅）

`App.vue:826-833` 中，`raw_context` 是 `textCandidates` 数组的**第 3 个候选（fallback）**：
```typescript
const textCandidates = [
  payload.latest_sources,   // 第1优先
  payload.sources_summary,  // 第2优先
  payload.raw_context       // 第3优先 (fallback)
];
```
由于 `latest_sources` 在有有效源时总是非空，`raw_context` 实际上**永远不会被使用**。可以安全移除。

### `web_research_results` / `sources_gathered` 引用（已确认 ✅）

仅出现在 3 处：
1. `models.py` — 字段定义
2. `task_executor.py` — append 操作
3. `test_models.py` — 测试默认值和 add 操作

**没有任何消费者读取这些字段。**

### `running_summary`（已确认 ✅）

- `SummaryState.running_summary`：在 `agent.py` 中赋值，**无人从 state 上读取**
- `SummaryStateOutput.running_summary`：这是输出 dataclass 的字段，被 `main.py` 和测试使用，**必须保留**
- 两者名字相同但是不同对象，`SummaryState` 上的可以移除

### `search_query`（已确认 ✅）

仅在 `models.py` 定义，注释为 "Deprecated placeholder"，**无任何读写**，可安全移除

---

## 涉及的文件

| 文件 | 修改内容 |
|------|---------|
| `backend/src/services/task_executor.py` | 移除 `web_research_results`/`sources_gathered` 的 append；移除 SSE `raw_context` |
| `backend/src/models.py` | 移除 `web_research_results`、`sources_gathered`、`search_query`、`running_summary` 字段 |
| `backend/tests/test_models.py` | 更新测试：移除对废弃字段的断言 |
| `frontend/src/App.vue` | 移除 `textCandidates` 中的 `raw_context` fallback |

## 验证方法

1. 全局 grep `web_research_results`、`sources_gathered`、`raw_context`、`search_query`（state上的），确认零残留
2. `cd backend && uv run ruff check src/` — 无 lint 错误
3. `cd backend && uv run python -m pytest tests/` — 所有测试通过（更新 test_models.py 后）
4. 启动 `uv run python src/main.py` + 前端 `npm run dev`，执行一次研究任务，确认端到端功能正常
