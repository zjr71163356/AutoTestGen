import os
import time
import json
import datetime

from autoe2e.utils import *
from autoe2e.init_utils import *
from autoe2e.infer_utils import *
from autoe2e.loop_utils import *
from autoe2e.mongo_utils import *
from autoe2e.manual_ndd import *
from autoe2e.graph_storage import GraphStorage
from autoe2e.scenario_storage import save_step_assertions
from autoe2e.task_synthesis import synthesize_tasks_for_app


APP_NAME = os.getenv('APP_NAME', 'PETCLINIC')
RESET_EXPLORATION = os.getenv('RESET_EXPLORATION', 'false').lower() == 'true'

# 根据需要决定是否从头重置探索状态
if RESET_EXPLORATION:
    logger.info(f"RESET_EXPLORATION=True, 清空 {APP_NAME} 的探索相关数据")
    states_db.delete_many({ 'app': APP_NAME })
    transitions_db.delete_many({ 'app': APP_NAME })
    functionalities_db.delete_many({ 'app': APP_NAME })
    feature_scenarios_db.drop()
    step_assertions_db.delete_many({ 'app': APP_NAME })
    scenarios_db.delete_many({ 'app': APP_NAME })
    tasks_db.delete_many({ 'app': APP_NAME })
    exploration_state_db.delete_one({ '_id': APP_NAME })
else:
    meta = exploration_state_db.find_one({ '_id': APP_NAME })
    if meta and meta.get('completed'):
        logger.info(f"应用 {APP_NAME} 已经完成探索，本次跳过爬取，仅基于现有数据重建 tasks")
        # 重新生成任务，确保使用最新的合成逻辑
        tasks_db.delete_many({ 'app': APP_NAME })
        synthesize_tasks_for_app(APP_NAME)
        raise SystemExit(0)

# 迁移/清理废弃的 feature_scenarios 集合（将数据复制到 step_assertions，随后删除）
try:
    legacy_docs = list(feature_scenarios_db.find({ 'app': APP_NAME }))
    if legacy_docs:
        logger.info(f\"检测到 legacy feature_scenarios {len(legacy_docs)} 条，开始迁移到 step_assertions\")
        step_assertions_db.insert_many(legacy_docs)
    feature_scenarios_db.drop()
    if legacy_docs:
        logger.info(\"迁移完成并删除 feature_scenarios 集合\")
except Exception as exc:
    logger.warning(f\"迁移/删除 feature_scenarios 失败: {exc}\")


crawl_context: CrawlContext = CrawlContext()
crawl_context = crawl_context.set_temp_var('config_path', f'./configs/{APP_NAME}.json')

config: dict = read_config(config_path=crawl_context.temp_vars.get('config_path', None))
config_obj: Config = Config.from_dict(config)

if config_obj.base_url is None:
    raise ValueError('base_url is required in config')

crawl_context = crawl_context.set_config(config_obj)

driver = initialize_driver(config_obj)
crawl_context = crawl_context.set_driver(driver)

crawl_context = initialize_variables(crawl_context)


LOOP_COUNTER = 0

# 安全终止阈值（可通过环境变量覆盖）
MAX_STATES = int(os.getenv('MAX_STATES', '200'))
MAX_ACTIONS = int(os.getenv('MAX_ACTIONS', '1000'))

# 访问频控，用于近重复/爆炸路径控制
visit_counter: dict[str, int] = {}


should_stop = False

while len(crawl_context.crawl_queue) > 0 and \
        len(crawl_context.state_machine.state_graph.states) < MAX_STATES and \
        not should_stop:
    state: State = crawl_context.crawl_queue.dequeue()
    logger.info(f"Visiting state {state.get_id(StateIdEvaluator.BY_ACTIONS)}")
    crawl_context.state_machine.set_current_state(state)
    
    current_state: State = crawl_context.state_machine.get_current_state()
    current_actions: list[Action] = current_state.get_actions()

    crawl_context.load_state(current_state)

    logger.info('Extracting state context using LLM')

    state_context = extract_state_context(
        crawl_context,
        current_state,
        current_state.crawl_path.get_state(-1) if len(current_state.crawl_path) > 0 else None,
        current_state.crawl_path.get_action(-1) if len(current_state.crawl_path) > 0 else None,
    )
    current_state.set_context(state_context)
    
    state_id = current_state.get_id(StateIdEvaluator.BY_ACTIONS)
    screenshot_path = f'{crawl_context.config.temp_dir}/screenshot_{state_id}.png'
    # 保存当前状态快照，并将 explored 标记为 False（处理完所有动作后再置 True）
    GraphStorage.save_state(current_state, screenshot_path)

    state_fully_processed = True

    for action in current_actions:
        if LOOP_COUNTER >= MAX_ACTIONS:
            logger.info(f"Reached MAX_ACTIONS={MAX_ACTIONS}, stopping crawl")
            should_stop = True
            state_fully_processed = False
            break
        LOOP_COUNTER += 1
        
        logger.info(f'Executing action {action.element.outerHTML}')
        
        # This variable is true unless an action leads to near-duplicate state.
        # Using this variable we can extract the functionality if even if the action is critical and we wouldn't execute it.
        should_extract_func = True

        is_critical = is_action_critical(action)
        
        if not is_critical:
            if action.get_type().get_value() == 'form':
                values = create_form_filling_values(action)
                action.set_params(values)
            
            action.execute(crawl_context.driver)

            new_actions = []

            for i in range(10):
                try:
                    new_actions: list[Action] = CandidateActionExtractor.extract_candidate_actions(crawl_context.driver)
                    break
                except:
                    time.sleep(0.1)

            if len(new_actions) == 0:
                raise Exception("no new actions")
            
            new_state: State = crawl_context.create_state_from_driver(new_actions)
            
            if not is_state_in_graph(crawl_context, new_state):
                # 近重复/访问限制控制
                visit_counter, forbidden = is_visit_forbidden(new_state, visit_counter)
                if forbidden:
                    logger.info(f"Skip visiting state (forbidden by rules): {new_state.url}")
                else:
                    print('Adding state', new_state.get_id(StateIdEvaluator.BY_ACTIONS))
                    crawl_context.crawl_queue.enqueue(new_state)
                    crawl_context.state_machine.add_state_from_current_state(new_state, action)
            else:
                should_extract_func = False

        if should_extract_func:
            logger.info(f'Extracting action scenarios: {action.element.outerHTML}')

            functionalities = extract_action_functionalities(current_state, action)
            functionality_ids = []
            finality_map = {}

            if len(functionalities) != 0:
                functionality_ids = insert_functionalities(functionalities)
                
                GraphStorage.save_transition(
                    source_state=current_state,
                    action=action,
                    functionality_ids=[str(fid) for fid in functionality_ids],
                    score=geometric_score(0) # Default score?
                )
        
                # Double action scenarios not fully supported in new schema yet
                # But we can save them as transitions if we had a way to represent them.
                # For now, skipping to match infer_utils refactor.

                logger.info('Marking final functionalities')
                finality_map = mark_final_functionalities(current_state, action)
                logger.info('Final actions marked')

                save_step_assertions(
                    state=current_state,
                    action=action,
                    functionalities=functionalities,
                    functionality_ids=functionality_ids,
                    is_critical_action=is_critical,
                    finality_map=finality_map,
                )
            else:
                logger.info('Marking final functionalities')
                mark_final_functionalities(current_state, action)
                logger.info('Final actions marked')
        
        # 当前动作完成后回到当前状态对应的页面
        crawl_context.load_state(crawl_context.state_machine.get_current_state())

        logger.info("")

    # 当前状态已完成本轮动作处理，标记 explored
    states_db.update_one(
        {
            "_id": state_id,
            "app": APP_NAME,
        },
        {
            "$set": {
                "explored": state_fully_processed,
            }
        },
        upsert=True
    )

crawl_context.driver.quit()


# 记录本次探索是否已经完成（队列为空且未触发安全终止）
exploration_completed = (not should_stop) and (len(crawl_context.crawl_queue) == 0)
exploration_state_db.update_one(
    { "_id": APP_NAME },
    {
        "$set": {
            "app": APP_NAME,
            "completed": exploration_completed,
            "last_updated": datetime.datetime.utcnow(),
        }
    },
    upsert=True
)


states_converted = {}

for state_id, state_obj in crawl_context.state_machine.state_graph.states.items():
    states_converted[state_id] = {
        'url': state_obj.url,
        'context': state_obj.context,
        'actions': [{
                'type': a.action_type.get_value(),
                'id': a.element.get_id(),
                'outerHTML': clean_children_html(a.element.outerHTML),
                'testId': a.element.test_id
            } for a in state_obj.get_actions()
        ],
        'prev_state': state_obj.crawl_path.get_state(-1).get_id() if len(state.crawl_path) > 0 else None,
        'prev_action': state_obj.crawl_path.get_action(-1).get_id() if len(state.crawl_path) > 0 else None,
    }


adj_list_converted = {}

for state_id, neighbor_list in crawl_context.state_machine.state_graph.adjacency_list.items():
    adj_list_converted[state_id] = {}

    for action_obj, n_state_id in neighbor_list.items():
        adj_list_converted[state_id][action_obj.get_id()] = n_state_id


os.makedirs('./report', exist_ok=True)

json.dump(
    {
        'nodes': states_converted,
        'edges': adj_list_converted
    },
    open(f'./report/{APP_NAME}.json', 'w+')
)

# 基于已经写入 MongoDB 的 functionalities + step_assertions/scenarios 合成任务
tasks_db.delete_many({ 'app': APP_NAME })
synthesize_tasks_for_app(APP_NAME)
