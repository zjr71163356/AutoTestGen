 ## workflow图和文件对应关系
 III.B Exploration Loop

  - Webpage
      - autoe2e/browser/driver.py:12 Chrome/WebDriver 容器 DriverContainer
      - autoe2e/crawler/crawl_context.py:35 load_state 复现状态到页面
  - Extract Actions → Action List
      - autoe2e/crawler/action/candidate_action_extractor.py:12 extract_candidate_actions
      - autoe2e/crawler/state/state.py:45 get_actions
  - Action
      - autoe2e/crawler/action/action.py:18 抽象 Action
      - autoe2e/crawler/action/click_action.py:20 点击执行
      - autoe2e/crawler/action/form_action.py:31 表单执行
      - autoe2e/crawler/action/element.py:16 元素元数据 outerHTML/test_id
  - Execute
      - autoe2e/crawler/action/click_action.py:20、autoe2e/crawler/action/form_action.py:31
  - Crawling Queue
      - autoe2e/utils/queue.py:12 通用 Queue（enqueue/dequeue at 39/48）
      - autoe2e/crawler/crawl_context.py:16 在上下文中持有 crawl_queue
  - Next Action
      - 宽度优先版本：main.py:40 主循环从队列取状态并对其动作迭代
      - 特征驱动版本：autoe2e/loop_utils.py:35 get_next_action 基于FD/AFD分数挑选动作
  - State Graph/State Machine
      - autoe2e/crawler/state/state_machine.py:44 由当前状态添加新状态 add_state_from_current_state
      - autoe2e/crawler/state/state_graph.py:1 状态图结构

  输入与页面元信息

  - Screenshot
      - autoe2e/browser/utils.py:35 save_screenshot（被 infer_utils.extract_state_context 调用）
  - Metadata（URL、DOM、元素HTML）
      - autoe2e/crawler/crawl_context.py:41 create_state_from_driver 取 current_url、page_source
      - autoe2e/crawler/action/element.py:16 采集元素 outerHTML/data-testid

  III.C Feature Inference

  - Context Extractor（LLM）
      - autoe2e/infer_utils.py:46 extract_state_context（保存截图并调用 LLM）
      - autoe2e/prompts.py:8 CONTEXT_EXTRACTION_SYSTEM_PROMPT
      - autoe2e/llm_api_call.py:56 sonnet_chain（Anthropic）
  - Feature Extractor（LLM）
      - autoe2e/infer_utils.py:73 extract_action_functionalities
      - autoe2e/prompts.py:25 FUNCTIONALITY_EXTRACTION_SYSTEM_PROMPT
      - 其他推理：关键动作判别与表单值
          - autoe2e/infer_utils.py:489 is_action_critical（Haiku）
          - autoe2e/infer_utils.py:500 create_form_filling_values（Sonnet）
  - Feature List
      - 由 extract_action_functionalities 返回的功能列表（传入聚合阶段）

  III.D Feature Aggregation

  - Map（相似功能归并）
      - autoe2e/infer_utils.py:115 query_similar_functionalities（Mongo 向量检索）
      - autoe2e/prompts.py:48 SIMILARITY_SYSTEM_PROMPT
      - autoe2e/infer_utils.py:150 map_similar_func_to_exact_match
  - Insert（入库）
      - autoe2e/infer_utils.py:256 insert_functionalities（Functionalities）
      - autoe2e/graph_storage.py: save_transition（Transitions）
  - Update Scores（特征分数）
      - (已移除/重构)
  - Mark Final（终结性判定）
      - autoe2e/prompts.py:68 FINALITY_SYSTEM_PROMPT
      - autoe2e/infer_utils.py:389 mark_final_functionalities
  - Databases
      - autoe2e/mongo_utils.py:15 Functionalities DB functionalities_db
      - autoe2e/mongo_utils.py:14 Transitions DB transitions_db
      - autoe2e/mongo_utils.py:13 States DB states_db

  管道编排与初始化

  - 配置与驱动
      - autoe2e/init_utils.py:13 read_config
      - autoe2e/init_utils.py:20 initialize_driver
      - autoe2e/init_utils.py:25 initialize_variables
      - configs/PETCLINIC.json:1 示例配置（其它应用同目录）
  - 主循环与报表
      - main.py:40 BFS 式探索与特征抽取
      - main.py:185 导出状态图 report/APP.json

  III.E Test Cases（缺失项）

  - 过滤并导出测试用例：未发现将 FD/AFD 过滤并生成可执行 E2E 测试的实现文件。
      - 可参考但未集成：baseline-prompts.md:6、:27、:47 中的测试用例生成提示词
      - 当前代码仅在 main.py:185 导出状态/边报告；未见测试脚本生成或落盘

## 技术路线
  - 探索与状态图构建（III.B）
      - 采集可执行动作与建状态：autoe2e/crawler/action/candidate_action_extractor.py:12, autoe2e/crawler/
        crawl_context.py:41
      - 入图与轨迹维护：autoe2e/crawler/state/state_machine.py:44, main.py:40
  - 语义推断与感知（III.C）
      - 截图与页面语义摘要：autoe2e/infer_utils.py:46, autoe2e/browser/utils.py:35, autoe2e/prompts.py:8
      - 动作→功能推断与关键动作识别：autoe2e/infer_utils.py:73, autoe2e/prompts.py:25, autoe2e/infer_utils.py:489,
        autoe2e/infer_utils.py:500
  - 功能聚合与打分（III.D）
      - 相似检索与合并：autoe2e/infer_utils.py:115, autoe2e/infer_utils.py:150
      - 入库与指针（Functionalities/Transitions）：autoe2e/infer_utils.py:256, autoe2e/graph_storage.py, autoe2e/mongo_utils.py:14,
        autoe2e/mongo_utils.py:15
      - 分数更新与终结判定：autoe2e/infer_utils.py:308, autoe2e/infer_utils.py:389, autoe2e/prompts.py:68
  - 决策与路径规划
      - 基线：BFS 按状态队列推进：main.py:40
      - 特征驱动选择（可插拔策略入口）：autoe2e/loop_utils.py:35, autoe2e/loop_utils.py:174
  - 报告与评估
      - 导出状态-转移报告：main.py:185
      - 可选覆盖率服务（人工/自动对齐）：benchmark/_log-server/coverage.py:1, benchmark/_log-server/extract.py:1