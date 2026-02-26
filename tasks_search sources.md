# 精准搜索策略功能 - 任务列表

## 概述

实现让 LLM 动态判断什么是可靠信息源，并据此增强搜索查询的功能。用户可以选择对单个 task 或全局启用精准搜索。

---

## Phase 1: Backend - 数据模型

### Task 1.1: 添加 SearchStrategy 数据类
**文件:** `backend/src/models.py`

创建 `SearchStrategy` 数据类，用于存储 LLM 生成的搜索策略：

```python
@dataclass(kw_only=True)
class SearchStrategy:
    """LLM 生成的搜索策略，定义什么是可靠的信息源。"""
    # 推荐的网站类型和具体域名
    reliable_source_types: list[str] = field(default_factory=list)  # e.g., ["academic", "official_docs", "expert_blogs"]
    preferred_domains: list[str] = field(default_factory=list)      # e.g., ["github.com", "arxiv.org"]

    # 要避免的信息源
    avoid_patterns: list[str] = field(default_factory=list)         # e.g., ["personal_blog", "content_farm"]

    # 搜索增强参数
    site_filter_query: str = ""                                     # 生成的 site: 查询片段
    search_operators: str = ""                                      # 其他搜索操作符 (e.g., "after:2020")

    # 策略元数据
    reasoning: str = ""                                             # LLM 的推理过程
    confidence: float = 0.0                                         # 策略的置信度

    # Backend 选择
    backend_override: str | None = None                             # 覆盖默认的 search backend
```

---

## Phase 2: Backend - 策略生成服务

### Task 2.1: 创建策略生成 Agent 的 Prompt
**文件:** `backend/src/prompts.py`

添加策略生成的系统 prompt：

```python
search_strategy_system_prompt = """
你是一个信息源评估专家。分析研究问题，判断什么样的信息源对这个问题是可靠的。

**分析思路：**

1. **这个问题需要什么类型的证据？**
   - 数据支持？→ 统计局、研究报告
   - 代码实现？→ GitHub、官方文档
   - 学术观点？→ 论文、学者博客
   - 行业实践？→ 公司技术博客、案例研究

2. **谁有资格回答这个问题？**
   - 学术权威、实践专家、官方机构等

3. **什么样的信号表示质量？**
   - 被引用次数、GitHub stars、同行评审等

**输出格式 (JSON):**
```json
{
  "reliable_source_types": ["学术文献", "官方文档"],
  "preferred_domains": ["arxiv.org", "github.com"],
  "avoid_patterns": ["个人博客"],
  "site_filter_query": "(site:arxiv.org OR site:github.com stars:>1000)",
  "search_operators": "after:2020",
  "reasoning": "这个问题需要最新的学术研究和实践代码...",
  "confidence": 0.85,
  "backend_override": "perplexity"
}
```

只输出 JSON，不要有其他内容。
"""
```

### Task 2.2: 创建策略生成服务
**文件:** `backend/src/services/strategy_generator.py` (新建)

创建 `StrategyGenerationService` 类：

```python
from hello_agents import HelloAgentsLLM, ToolAwareSimpleAgent
from .models import SearchStrategy

class StrategyGenerationService:
    """根据问题动态生成搜索策略。"""

    def __init__(self, llm: HelloAgentsLLM):
        self.llm = llm
        self.agent = ToolAwareSimpleAgent(
            name="搜索策略专家",
            llm=llm,
            system_prompt=search_strategy_system_prompt.strip(),
            enable_tool_calling=False,
        )

    def generate_strategy(
        self,
        query: str,
        intent: str,
        research_topic: str
    ) -> SearchStrategy | None:
        """为任务生成搜索策略。

        Returns:
            SearchStrategy or None: 如果生成失败返回 None
        """
        # 实现策略生成逻辑
        pass
```

---

## Phase 3: Backend - 搜索增强

### Task 3.1: 创建查询构建工具
**文件:** `backend/src/utils.py`

添加查询增强函数：

```python
def build_enhanced_query(
    base_query: str,
    strategy: SearchStrategy | None
) -> str:
    """根据策略增强搜索查询。

    Example:
        base_query = "Rust memory model"
        strategy.site_filter_query = "(site:github.com OR site:arxiv.org)"
        => "Rust memory model (site:github.com OR site:arxiv.org)"
    """
    if not strategy or not strategy.site_filter_query:
        return base_query

    parts = [base_query]
    if strategy.site_filter_query:
        parts.append(strategy.site_filter_query)
    if strategy.search_operators:
        parts.append(strategy.search_operators)

    return " ".join(parts)
```

### Task 3.2: 修改 dispatch_search 支持策略
**文件:** `backend/src/services/search.py`

修改 `dispatch_search` 函数签名和实现：

```python
def dispatch_search(
    query: str,
    config: Configuration,
    loop_count: int,
    strategy: SearchStrategy | None = None,  # 新增参数
) -> Tuple[dict[str, Any] | None, list[str], Optional[str], str]:
    """执行搜索，支持策略增强的查询。"""

    # 根据策略选择 backend
    backend = (
        strategy.backend_override if strategy and strategy.backend_override
        else get_config_value(config.search_api)
    )

    # 构建增强查询
    enhanced_query = build_enhanced_query(query, strategy)

    # 执行搜索
    # ... 现有逻辑，使用 enhanced_query 和 backend
```

---

## Phase 4: Backend - 配置与 API

### Task 4.1: 添加 Configuration 选项
**文件:** `backend/src/config.py`

添加精准搜索相关配置：

```python
class Configuration(BaseModel):
    # ... 现有字段 ...

    enable_precise_search: bool = Field(
        default=False,
        title="Enable Precise Search",
        description="Whether to enable LLM-based smart search strategy generation",
    )
    precise_search_by_default: bool = Field(
        default=False,
        title="Precise Search by Default",
        description="Whether to enable precise search for all tasks by default",
    )
```

### Task 4.2: 添加 TodoItem 精准搜索标记
**文件:** `backend/src/models.py`

修改 `TodoItem` 添加精准搜索标记：

```python
@dataclass(kw_only=True)
class TodoItem:
    # ... 现有字段 ...
    enable_precise_search: bool = field(default=False)  # 是否对此任务启用精准搜索
```

### Task 4.3: 修改 ResearchRequest API
**文件:** `backend/src/main.py`

添加 API 参数支持：

```python
class ResearchRequest(BaseModel):
    topic: str = Field(..., description="Research topic")
    search_api: SearchAPI | None = Field(default=None)

    # 新增：精准搜索控制
    enable_precise_search: bool | None = Field(
        default=None,
        description="Enable LLM-based smart search strategy (None = use config default)",
    )
    precise_search_tasks: list[int] | None = Field(
        default=None,
        description="List of task IDs to enable precise search for (optional)",
    )
```

### Task 4.4: 修改 _build_config 函数
**文件:** `backend/src/main.py`

```python
def _build_config(payload: ResearchRequest) -> Configuration:
    overrides: Dict[str, Any] = {}

    if payload.search_api is not None:
        overrides["search_api"] = payload.search_api
    if payload.enable_precise_search is not None:
        overrides["enable_precise_search"] = payload.enable_precise_search

    return Configuration.from_env(overrides=overrides)
```

---

## Phase 5: Backend - Agent 集成

### Task 5.1: 修改 DeepResearchAgent 初始化
**文件:** `backend/src/agent.py`

在 `__init__` 中添加策略生成服务：

```python
from services.strategy_generator import StrategyGenerationService

class DeepResearchAgent:
    def __init__(self, config: Configuration | None = None) -> None:
        # ... 现有初始化 ...

        # 新增：策略生成服务
        self.strategy_generator = StrategyGenerationService(self.llm)
```

### Task 5.2: 修改 _execute_task 支持策略
**文件:** `backend/src/agent.py`

在 `_execute_task` 方法中集成策略生成：

```python
def _execute_task(
    self,
    state: SummaryState,
    task: TodoItem,
    *,
    emit_stream: bool,
    step: int | None = None,
) -> Iterator[dict[str, Any]]:
    """执行任务，支持可选的精准搜索策略。"""

    task.status = "in_progress"

    strategy: SearchStrategy | None = None

    # 判断是否启用精准搜索
    enable_precise = (
        task.enable_precise_search or
        self.config.precise_search_by_default
    )

    if enable_precise and self.config.enable_precise_search:
        # 生成搜索策略
        strategy = self.strategy_generator.generate_strategy(
            query=task.query,
            intent=task.intent,
            research_topic=state.research_topic
        )

        if emit_stream and strategy:
            yield {
                "type": "search_strategy",
                "task_id": task.id,
                "strategy": {
                    "reasoning": strategy.reasoning,
                    "preferred_domains": strategy.preferred_domains,
                    "avoid_patterns": strategy.avoid_patterns,
                    "confidence": strategy.confidence,
                },
                "step": step,
            }

    # 使用策略执行搜索
    search_result, notices, answer_text, backend = dispatch_search(
        task.query,
        self.config,
        state.research_loop_count,
        strategy=strategy,  # 传入策略
    )

    # ... 现有逻辑继续 ...
```

### Task 5.3: 修改 run_stream 传递任务配置
**文件:** `backend/src/agent.py`

修改 `run_stream` 方法以支持任务级别的精准搜索配置：

```python
def run_stream(self, topic: str, precise_search_tasks: list[int] | None = None) -> Iterator[dict[str, Any]]:
    """执行研究流程，支持任务级别的精准搜索配置。"""

    # ... 现有初始化 ...

    # 标记需要精准搜索的任务
    if precise_search_tasks:
        for task in state.todo_items:
            if task.id in precise_search_tasks:
                task.enable_precise_search = True

    # ... 现有逻辑 ...
```

---

## Phase 6: Frontend - UI 控制

### Task 6.1: 添加表单选项
**文件:** `frontend/src/App.vue`

在初始表单中添加精准搜索开关：

```vue
<section class="options">
  <!-- 现有的搜索引擎选项 -->

  <!-- 新增：精准搜索选项 -->
  <label class="field option">
    <span>精准搜索</span>
    <select v-model="form.enablePreciseSearch">
      <option value="">沿用后端配置</option>
      <option value="true">启用</option>
      <option value="false">禁用</option>
    </select>
  </label>

  <label class="field option">
    <span>
      搜索模式
      <small style="display:block;opacity:0.6;font-weight:400;">
        全局 = 所有任务使用相同策略 | 选择 = 指定任务使用精准搜索
      </small>
    </span>
    <select v-model="form.preciseSearchMode">
      <option value="global">全局模式</option>
      <option value="selective">选择模式</option>
    </select>
  </label>
</section>
```

### Task 6.2: 添加响应式数据
**文件:** `frontend/src/App.vue`

```typescript
const form = reactive({
  topic: "",
  searchApi: "",
  enablePreciseSearch: "" as "" | "true" | "false",  // 新增
  preciseSearchMode: "global" as "global" | "selective",  // 新增
  preciseSearchTasks: [] as number[],  // 新增：在选择性模式下选择的任务 ID
});
```

### Task 6.3: 任务列表支持精准搜索标记
**文件:** `frontend/src/App.vue`

在任务清单中添加精准搜索控制：

```vue
<!-- 在任务列表中添加 -->
<li
  v-for="task in todoTasks"
  :key="task.id"
  :class="['task-item', { active: task.id === activeTaskId }]"
>
  <button type="button" class="task-button" @click="activeTaskId = task.id">
    <span class="task-title">{{ task.title }}</span>

    <!-- 新增：精准搜索指示器 -->
    <label
      v-if="form.preciseSearchMode === 'selective'"
      class="precise-toggle"
      title="为此任务启用精准搜索"
    >
      <input
        type="checkbox"
        :checked="form.preciseSearchTasks.includes(task.id)"
        @change="togglePreciseSearch(task.id)"
        :disabled="loading"
      />
      <span>精准</span>
    </label>
  </button>
</li>
```

### Task 6.4: 添加事件处理函数
**文件:** `frontend/src/App.vue`

```typescript
function togglePreciseSearch(taskId: number) {
  const index = form.preciseSearchTasks.indexOf(taskId);
  if (index > -1) {
    form.preciseSearchTasks.splice(index, 1);
  } else {
    form.preciseSearchTasks.push(taskId);
  }
}
```

### Task 6.5: 修改 API 调用
**文件:** `frontend/src/App.vue`

```typescript
const payload = {
  topic: form.topic.trim(),
  search_api: form.searchApi || undefined,
  enable_precise_search: form.enablePreciseSearch === "true" ? true :
                        form.enablePreciseSearch === "false" ? false :
                        undefined,
  precise_search_tasks: form.preciseSearchMode === "selective" &&
                        form.preciseSearchTasks.length > 0 ?
                        form.preciseSearchTasks : undefined,
};
```

### Task 6.6: 添加搜索策略事件显示
**文件:** `frontend/src/App.vue`

```typescript
// 在事件处理中添加
if (event.type === "search_strategy") {
  const strategy = event.strategy;
  progressLogs.value.push(
    `已生成搜索策略：${strategy.reasoning || '精准搜索已启用'}`
  );

  // 可选：在任务详情中显示策略
  const task = findTask(event.task_id);
  if (task) {
    task.searchStrategy = strategy;  // 扩展 TodoTaskView 接口
  }
  return;
}
```

### Task 6.7: 扩展 TodoTaskView 接口
**文件:** `frontend/src/App.vue`

```typescript
interface TodoTaskView {
  // ... 现有字段 ...
  searchStrategy?: {
    reasoning: string;
    preferred_domains: string[];
    avoid_patterns: string[];
    confidence: number;
  };
}
```

### Task 6.8: 添加策略显示 UI
**文件:** `frontend/src/App.vue`

在任务详情中添加策略展示：

```vue
<section
  v-if="currentTask?.searchStrategy"
  class="strategy-block"
>
  <h3>搜索策略</h3>
  <div class="strategy-content">
    <div v-if="currentTask.searchStrategy.reasoning" class="strategy-reasoning">
      <strong>策略分析：</strong>
      <p>{{ currentTask.searchStrategy.reasoning }}</p>
    </div>
    <div v-if="currentTask.searchStrategy.preferred_domains?.length" class="strategy-domains">
      <strong>推荐来源：</strong>
      <ul>
        <li v-for="domain in currentTask.searchStrategy.preferred_domains" :key="domain">
          {{ domain }}
        </li>
      </ul>
    </div>
    <div v-if="currentTask.searchStrategy.avoid_patterns?.length" class="strategy-avoid">
      <strong>避免来源：</strong>
      <ul>
        <li v-for="pattern in currentTask.searchStrategy.avoid_patterns" :key="pattern">
          {{ pattern }}
        </li>
      </ul>
    </div>
    <div class="strategy-confidence">
      <strong>置信度：</strong>
      <span>{{ (currentTask.searchStrategy.confidence * 100).toFixed(0) }}%</span>
    </div>
  </div>
</section>
```

### Task 6.9: 添加样式
**文件:** `frontend/src/App.vue` (在 `<style scoped>` 中)

```css
/* 精准搜索开关样式 */
.precise-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.3);
  font-size: 12px;
  cursor: pointer;
  user-select: none;
}

.precise-toggle input {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

.precise-toggle span {
  color: #3b82f6;
  font-weight: 500;
}

/* 搜索策略展示样式 */
.strategy-block {
  background: rgba(167, 139, 250, 0.08);
  border: 1px solid rgba(139, 92, 246, 0.25);
  border-radius: 16px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.strategy-block h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #5b21b6;
}

.strategy-content > div {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.strategy-content strong {
  font-size: 13px;
  color: #6d28d9;
}

.strategy-content p {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: #374151;
}

.strategy-content ul {
  margin: 0;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.strategy-content li {
  font-size: 13px;
  color: #374151;
}

.strategy-confidence span {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(139, 92, 246, 0.2);
  color: #5b21b6;
  font-size: 12px;
  font-weight: 600;
}
```

---

## Phase 7: 环境变量与文档

### Task 7.1: 添加环境变量支持
**文件:** `backend/.env.example`

```bash
# 精准搜索配置
ENABLE_PRECISE_SEARCH=false              # 启用 LLM 智能搜索策略生成
PRECISE_SEARCH_BY_DEFAULT=false          # 默认对所有任务启用精准搜索
```

### Task 7.2: 更新 CLAUDE.md
**文件:** `CLAUDE.md`

在适当位置添加精准搜索功能说明：

```markdown
## Precise Search Feature

The agent supports LLM-generated search strategies that dynamically determine
reliable information sources for each research question.

**How it works:**
1. For each task (when enabled), the strategy agent analyzes:
   - What type of evidence is needed
   - Who is qualified to answer
   - What quality signals matter

2. The strategy generates:
   - `site:` filters for reliable domains
   - Search operators (e.g., date filters)
   - Domain exclusion patterns

3. The enhanced query is sent to the search backend

**Configuration:**
- Global: `ENABLE_PRECISE_SEARCH` env var
- Per-request: `enable_precise_search` API parameter
- Per-task: `precise_search_tasks` API parameter list
```

---

## Phase 8: 测试

### Task 8.1: 集成测试
创建 `backend/tests/test_precise_search_integration.py`:

```python
import pytest
from agent import DeepResearchAgent
from config import Configuration

def test_precise_search_workflow():
    """测试精准搜索完整流程"""
    # Setup: enable precise search
    # Run research with specific task requiring precise search
    # Verify strategy generation
    # Verify enhanced query construction
    # Verify search execution
```

### Task 8.2: 前端测试
手动测试清单：
- [ ] 禁用精准搜索，验证正常搜索流程
- [ ] 启用全局精准搜索，验证所有任务都生成策略
- [ ] 选择性精准搜索，验证只有选定任务生成策略
- [ ] 验证搜索策略在 UI 中正确显示
- [ ] 验证策略失败不影响正常搜索流程

---

## 实施顺序建议

1. **Phase 1-3**: 核心功能 (数据模型、策略生成、搜索增强)
2. **Phase 4**: 配置和 API 支持
3. **Phase 5**: Agent 集成
4. **Phase 6**: Frontend UI
5. **Phase 7-8**: 文档和测试

每完成一个 Phase，建议运行一次完整测试，确保没有破坏现有功能。
