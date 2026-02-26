# 搜索结果质量过滤任务 (Source Quality Filtering Tasks)

## 任务概述

为搜索结果添加质量过滤机制，确保只有符合任务意图的高质量信息源被用于研究总结。

## 任务分解

### 任务 1: 两阶段搜索策略（关键优化）

**问题分析**:
当前 `dispatch_search()` 会一次性抓取所有网页的完整内容 (`fetch_full_page=True`)，然后我们再验证并丢弃不相关的源。这造成了资源浪费。

**正确的流程应该是**:
```
阶段1: 轻量搜索 (fetch_full_page=False)  → 只获取 title + snippet
       ↓
阶段2: 验证源相关性 (基于 title + snippet)
       ↓
阶段3: 只为有效源抓取完整内容
```

**位置**: `backend/src/services/search.py`

**需要新增/修改的函数**:

1. **修改 `dispatch_search()` 支持轻量模式**:
   ```python
   def dispatch_search(
       query: str,
       config: Configuration,
       loop_count: int,
       fetch_full_page: bool | None = None,  # 新增：覆盖全局配置
   ) -> Tuple[dict[str, Any] | None, list[str], Optional[str], str]:
       """执行搜索，可选择是否抓取完整内容。

       Args:
           fetch_full_page: 如果为 None，使用 config.fetch_full_page；
                          如果显式指定，覆盖全局配置（用于两阶段搜索）
       """
       # 使用显式参数或回退到配置
       should_fetch_full = (
           fetch_full_page if fetch_full_page is not None
           else config.fetch_full_page
       )

       raw_response = _GLOBAL_SEARCH_TOOL.run({
           "input": query,
           "backend": search_api,
           "mode": "structured",
           "fetch_full_page": should_fetch_full,  # ← 使用计算后的值
           "max_results": 5,
           "max_tokens_per_source": MAX_TOKENS_PER_SOURCE,
           "loop_count": loop_count,
       })
       # ... 后续逻辑不变
   ```

   **为什么要这么做**:
   - 保持向后兼容：不传 `fetch_full_page` 时行为不变
   - 支持两阶段：第一阶段调用 `dispatch_search(..., fetch_full_page=False)`

2. **新增 `fetch_full_content_for_sources()` 函数**:
   ```python
   def fetch_full_content_for_sources(
       sources: list[dict],
       config: Configuration,
   ) -> list[dict]:
       """为指定的信息源抓取完整页面内容。

       这是两阶段搜索的第二阶段：只对通过验证的有效源抓取完整内容。

       Args:
           sources: 包含 url 字段的信息源列表（来自第一阶段轻量搜索）

       Returns:
           带有 raw_content 字段的信息源列表

       注意：
           兼容所有搜索后端 (duckduckgo, tavily, perplexity, searxng)
           - duckduckgo: 使用 httpx 抓取
           - tavily/perplexity: 它们可能有各自的 API
           - searxng: 使用其内置的 full content 抓取
       """
       # 实现方案 A: 使用 SearchTool 逐个抓取
       # 实现方案 B: 直接用 httpx/requests 抓取并解析
       # ...
   ```

3. **修改 `prepare_research_context()` 签名**:
   ```python
   def prepare_research_context(
       search_result: dict[str, Any] | None,
       answer_text: Optional[str],
       config: Configuration,
       valid_sources: list[dict] | None = None,  # 新增参数
   ) -> tuple[str, str]:
   ```

   **为什么要这么做**:
   - 允许传入过滤后的有效源列表
   - 保持向后兼容，`valid_sources=None` 时使用原有逻辑

---

### 任务 2: 创建信息源质量验证服务
**位置**: 新增 `backend/src/services/validator.py`

**设计模式**: 与 `PlanningService` 一致
- Service 接收 `agent` 和 `config` 作为构造参数
- Agent 由 `agent.py` 中统一创建，传入 service

**需要新增的类和函数**:

1. **SourceValidator 类**:
   ```python
   class SourceValidator:
       """使用 LLM 判断信息源是否符合任务意图。

       设计模式参考 PlanningService：
       - agent 由外部创建传入
       - service 提供领域特定的接口
       """

       def __init__(self, validator_agent: ToolAwareSimpleAgent, config: Configuration) -> None:
           self._agent = validator_agent
           self._config = config

       def validate_sources(
           self,
           sources: list[dict],
           task_intent: str,
           task_query: str,
       ) -> tuple[list[dict], list[dict]]:
           """验证信息源并返回有效/无效源列表。

           Args:
               sources: 待验证的信息源列表
               task_intent: 任务意图描述
               task_query: 任务搜索查询

           Returns:
               (valid_sources, invalid_sources) 元组
           """
           valid = []
           invalid = []

           for source in sources:
               prompt = self._build_validation_prompt(source, task_intent, task_query)
               response = self._agent.run(prompt)
               self._agent.clear_history()  # 与 PlanningService 一致

               is_valid = self._parse_validation_response(response)
               if is_valid:
                   valid.append(source)
               else:
                   invalid.append(source)

           return valid, invalid

       def _build_validation_prompt(
           self,
           source: dict,
           task_intent: str,
           task_query: str,
       ) -> str:
           """构建单个源的验证 prompt。"""
           title = source.get("title", "")
           content = source.get("content", "")
           url = source.get("url", "")

           return f"""请判断以下信息源是否与任务相关：

<任务意图>
{task_intent}

<搜索查询>
{task_query}

<信息源>
标题: {title}
URL: {url}
摘要: {content}

请判断该信息源是否符合任务意图，输出格式：
VALID - [原因]
或
INVALID - [原因]
"""

       def _parse_validation_response(self, response: str) -> bool:
           """解析 LLM 的判断结果。"""
           text = response.strip().upper()
           return text.startswith("VALID")
   ```

2. **添加验证 Prompt 到 `prompts.py`**:
   ```python
   source_validator_system_prompt = """
   You are a source quality evaluator. Your task is to determine whether a web source
   is relevant and suitable for a given research task.

   <EVALUATION_CRITERIA>
   1. **Relevance**: Does the source address the task's core intent?
   2. **Quality**: Is the source from a credible domain (not spam/farm content)?
   3. **Utility**: Can the source provide unique information for the research?
   4. **Language**: Does the source match the expected information context?
   </EVALUATION_CRITERIA>

   <OUTPUT_FORMAT>
   Respond with ONLY "VALID" or "INVALID" followed by a brief reason.
   Example: "VALID - Directly addresses the research question with official data."
   Example: "INVALID - Unrelated content about different topic."
   </OUTPUT_FORMAT>
   """
   ```

   **为什么要这么做**:
   - **复用现有 Agent 框架**: 使用与 `summarizer` 相同的 agent factory 模式
   - **单一职责**: 验证逻辑独立于搜索和总结，便于测试和维护
   - **可扩展性**: 未来可以添加更多验证规则（如域名黑名单、内容类型检测）

---

### 任务 3: 实现带重试的搜索与验证循环
**位置**: `backend/src/agent.py` 中的 `_execute_task()` 方法

**当前实现**:
- `_execute_task()` 调用一次 `dispatch_search()`，如果结果为空则跳过任务
- 没有重试机制，也没有源质量验证

**需要修改的逻辑**:

1. **在 `DeepResearchAgent.__init__()` 中创建 validation_agent 并初始化 validator**:
   ```python
   # 在 __init__ 中，与其他 agent 一起创建
   self.validation_agent = self._create_tool_aware_agent(
       name="信息源验证专家",
       system_prompt=source_validator_system_prompt.strip(),
   )

   # 创建 validator service（如果启用）
   self.validator: SourceValidator | None = None
   if self.config.enable_source_validation:
       from services.validator import SourceValidator
       self.validator = SourceValidator(self.validation_agent, self.config)
   ```

2. **修改 `_execute_task()` 实现两阶段搜索 + 重试循环**:

2. **修改 `_execute_task()` 实现两阶段搜索 + 重试循环**:
   ```python
   def _execute_task(...) -> Iterator[dict[str, Any]]:
       # 修改部分：
       MAX_SEARCH_ROUNDS = 3
       MIN_VALID_SOURCES = 3

       valid_sources = []
       search_round = 0

       while search_round < MAX_SEARCH_ROUNDS:
           search_round += 1

           # === 阶段1: 轻量搜索 (不抓完整内容) ===
           search_result, notices, answer_text, backend = dispatch_search(
               task.query,
               self.config,
               state.research_loop_count,
               fetch_full_page=False,  # ← 关键：第一阶段不抓完整内容
           )

           if not search_result or not search_result.get("results"):
               # 搜索无结果，继续下一轮
               continue

           lightweight_sources = search_result.get("results", [])

           # === 阶段2: 验证源质量（基于 title + snippet）===
           if self.validator:  # ← 直接使用 validator service
               valid_sources, invalid_sources = self.validator.validate_sources(
                   lightweight_sources,  # ← 只用轻量级元数据验证
                   task.intent,
                   task.query,
               )

               # 记录被过滤的源
               if emit_stream and invalid_sources:
                   yield {
                       "type": "sources_filtered",
                       "task_id": task.id,
                       "filtered_count": len(invalid_sources),
                       "valid_count": len(valid_sources),
                       "round": search_round,
                   }

               # 如果有效源足够，退出循环
               if len(valid_sources) >= MIN_VALID_SOURCES:
                   break
           else:
               # 未启用验证，使用所有源
               valid_sources = lightweight_sources
               break

       # === 阶段3: 只为有效源抓取完整内容 ===
       if self.config.fetch_full_page and valid_sources:
           valid_sources = fetch_full_content_for_sources(
               valid_sources,
               self.config,
           )

       # 使用有效源准备上下文
       search_result["results"] = valid_sources
       sources_summary, context = prepare_research_context(
           search_result, answer_text, self.config, valid_sources
       )
       # ... 后续逻辑保持不变
   ```

   **为什么要这么做**:
   - **节省资源**: 完整内容只抓取一次，只为有效源
   - **向后兼容**: 未启用验证时，原有逻辑不变
   - **可配置**: 通过 `enable_source_validation` 控制是否启用
   - **透明反馈**: 通过 SSE 事件通知前端过滤情况

---

### 任务 4: 配置和状态管理

1. **新增配置项到 `config.py`**:
   ```python
   class Configuration(BaseSettings):
       # ... 现有配置 ...

       # Source validation
       enable_source_validation: bool = True
       min_valid_sources_threshold: int = 3
       max_search_retries: int = 3
   ```

2. **更新 `SummaryState` 添加过滤统计** (可选，用于调试):
   ```python
   @dataclass(kw_only=True)
   class SummaryState:
       # ... 现有字段 ...
       sources_filtered_count: int = 0  # 被过滤的源总数
       search_retry_count: int = 0      # 搜索重试次数
   ```

---

## 架构设计说明

### 现有框架利用

| 组件 | 复用方式 | 参考 |
|------|----------|------|
| `ToolAwareSimpleAgent` | 创建 `validation_agent`，与 `todo_agent`、`report_agent` 一致 | `agent.py:58-65` |
| `Service 包装模式` | `SourceValidator` 参考 `PlanningService` 设计 | `services/planner.py:24-29` |
| `HelloAgentsLLM` | 共享 LLM 实例 | - |
| `Configuration` | 新增配置项 | - |
| `emit_stream` 模式 | 扩展事件类型 (`sources_filtered`) | - |
| `_execute_task()` | 内部逻辑扩展，接口不变 | - |

### 扩展性考虑

1. **验证规则可插拔**: `SourceValidator` 可扩展为支持多种验证策略
   - LLM 判断（当前实现）
   - 域名黑名单/白名单
   - 内容长度/质量阈值
   - 语言检测

2. **Prompt 优化**: 验证 prompt 可独立演化，不影响其他组件

3. **向后兼容**: 所有修改保持原有接口，新功能可通过配置开关

### 数据流图（两阶段搜索）

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         _execute_task()                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    while round < MAX_ROUNDS                      │   │
│  │                                                                  │   │
│  │  ┌─────────────────────────────────────────────────────────┐    │   │
│  │  │ 阶段1: 轻量搜索 (fetch_full_page=False)                  │    │   │
│  │  │ dispatch_search(..., fetch_full_page=False)              │    │   │
│  │  │   └─► 只返回 title + snippet (无 raw_content)             │    │   │
│  │  └────────────────────┬────────────────────────────────────┘    │   │
│  │                       │                                          │   │
│  │                       ▼                                          │   │
│  │  ┌─────────────────────────────────────────────────────────┐    │   │
│  │  │ 阶段2: 验证源质量 (基于 title + snippet)                 │    │   │
│  │  │ SourceValidator.validate(lightweight_sources)            │    │   │
│  │  │   └─► LLM 判断每个源是否相关                              │    │   │
│  │  │   └─► 返回 (valid_sources, invalid_sources)               │    │   │
│  │  └────────────────────┬────────────────────────────────────┘    │   │
│  │                       │                                          │   │
│  │                       ▼                                          │   │
│  │  ┌─────────────────────────────────────────────────────────┐    │   │
│  │  │ len(valid_sources) >= MIN_THRESHOLD ?                   │    │   │
│  │  └──────┬──────────────────────┬───────────────────────────┘    │   │
│  │         │ Yes                   │ No                            │   │
│  │    break                  continue (下一轮搜索)                 │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                           │                                              │
│                           ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 阶段3: 只为有效源抓取完整内容                                     │   │
│  │ if config.fetch_full_page:                                      │   │
│  │     valid_sources = fetch_full_content_for_sources(valid)        │   │
│  │       └─► 只对 valid_sources 抓取 raw_content                     │   │
│  └────────────────────┬────────────────────────────────────────────┘   │
│                       │                                                  │
│                       ▼                                                  │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ prepare_research_context(valid_sources_with_full_content)       │   │
│  └────────────────────┬────────────────────────────────────────────┘   │
│                       │                                                  │
│                       ▼                                                  │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │              summarizer.summarize_task()                         │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

**关键优化点**:
- 阶段1 使用 `fetch_full_page=False`，快速获取搜索结果
- 阶段2 只基于 `title + snippet` 验证，无需完整内容
- 阶段3 只为通过验证的源抓取完整内容，节省带宽和时间

---

## 实现挑战与方案选择

### 挑战: `fetch_full_content_for_sources()` 的跨后端兼容性

不同搜索后端对"抓取完整内容"的支持不同：

| 后端 | 轻量搜索支持 | 完整内容抓取方案 | 优先级 |
|------|-------------|----------------|--------|
| **tavily** | ✅ 支持 `search` (snippet) | 有独立的 `extract` API | **P0** |
| **perplexity** | ✅ 支持 `search` (snippet) | 可能需要单独调用 extract | **P0** |
| **duckduckgo** | ✅ 原生返回 snippet | 需要自己用 httpx 抓取 | **P1** |
| **searxng** | ✅ 原生返回 snippet | 部署实例可能自带 | **P1** |

**P0 实现: Tavily + Perplexity**

这两个是付费 API，通常有专门的 extract 功能：

```python
def fetch_full_content_for_sources(
    sources: list[dict],
    config: Configuration,
) -> list[dict]:
    """为指定的信息源抓取完整页面内容。

    P0: 先实现 tavily 和 perplexity 的支持
    P1: 后续实现 duckduckgo 和 searxng
    """
    search_api = get_config_value(config.search_api)

    # P0: Tavily
    if search_api == "tavily":
        return _fetch_tavily_content(sources, config)

    # P0: Perplexity
    if search_api == "perplexity":
        return _fetch_perplexity_content(sources, config)

    # P1: 其他后端暂时使用备用方案或跳过
    logger.warning(f"Full content fetch not yet supported for {search_api}, using lightweight sources only")
    return sources


def _fetch_tavily_content(sources: list[dict], config: Configuration) -> list[dict]:
    """使用 Tavily Extract API 抓取完整内容。

    Tavily 有独立的 /extract 端点：
    https://docs.tavily.com/docs/tavily-api/rest/endpoints/extract
    """
    import httpx

    api_key = config.tavily_api_key or os.getenv("TAVILY_API_KEY")
    if not api_key:
        logger.warning("TAVILY_API_KEY not set, skipping full content fetch")
        return sources

    headers = {"Authorization": f"Bearer {api_key}"}

    for source in sources:
        try:
            response = httpx.post(
                "https://api.tavily.com/extract",
                json={"urls": [source["url"]]},
                headers=headers,
                timeout=30,
            )
            result = response.json()
            if result.get("results"):
                source["raw_content"] = result["results"][0].get("content", "")
        except Exception as e:
            logger.warning(f"Tavily extract failed for {source['url']}: {e}")

    return sources


def _fetch_perplexity_content(sources: list[dict], config: Configuration) -> list[dict]:
    """使用 Perplexity Online API 抓取完整内容。

    需要调研 Perplexity API 是否有独立的 extract 功能，
    或者通过其搜索 API 获取完整内容。
    """
    # TODO: 调研 Perplexity API 文档
    # 目前先用通用备用方案
    return _fetch_with_httpx(sources, config)


# P1: 通用备用方案（用于 duckduckgo, searxng）
def _fetch_with_httpx(sources: list[dict], config: Configuration) -> list[dict]:
    """直接用 httpx + BeautifulSoup 抓取（备用方案）。"""
    import httpx
    from bs4 import BeautifulSoup

    headers = {"User-Agent": "Mozilla/5.0 (compatible; DeepResearch/1.0)"}

    for source in sources:
        try:
            response = httpx.get(source["url"], headers=headers, timeout=10)
            soup = BeautifulSoup(response.content, "html.parser")

            for script in soup(["script", "style"]):
                script.decompose()

            text = soup.get_text(separator="\n", strip=True)
            source["raw_content"] = text[:MAX_TOKENS_PER_SOURCE * CHARS_PER_TOKEN]
        except Exception as e:
            logger.warning(f"HTTP fetch failed for {source['url']}: {e}")
            source["raw_content"] = ""

    return sources
```

**推荐实现顺序**:
1. **P0**: 先实现 Tavily (文档完善，有独立 extract API)
2. **P0**: 再调研 Perplexity (可能需要不同方案)
3. **P1**: 实现通用 httpx 方案 (用于 duckduckgo, searxng)
4. **P1**: 优化 searxng (如果部署实例自带 full content)

---

## 实现优先级

### P0 (核心功能)
1. 修改 `dispatch_search()` 支持 `fetch_full_page` 参数覆盖
2. 实现 `fetch_full_content_for_sources()` 函数 **(仅 Tavily + Perplexity)**
   - `_fetch_tavily_content()` 使用 Tavily Extract API
   - `_fetch_perplexity_content()` 调研 Perplexity API 实现
3. `SourceValidator` 类和验证 prompt
4. `_execute_task()` 两阶段搜索 + 重试循环逻辑
5. 配置项添加 (`enable_source_validation`, `min_valid_sources_threshold`, `max_search_retries`)

### P1 (扩展功能)
1. 实现 `fetch_full_content_for_sources()` **(DuckDuckGo + Searxng)**
   - `_fetch_with_httpx()` 通用方案
   - searxng 特殊处理（如果部署实例支持）
2. 前端事件 (`sources_filtered`)
3. 单元测试
   - `SourceValidator` 测试（mock LLM 响应）
   - 两阶段搜索流程测试
   - 重试逻辑测试
   - 各后端的内容抓取测试

### P2 (可选优化)
1. 验证缓存（相同 URL + intent 不重复验证）
2. 批量验证优化（单个 LLM 调用验证多个源，减少 API 调用）
3. 验证结果持久化（用于分析哪些源被过滤）