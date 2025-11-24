import os
import time
import json

from autoe2e.utils import *
from autoe2e.init_utils import *
from autoe2e.infer_utils import *
from autoe2e.loop_utils import *
from autoe2e.mongo_utils import *
from autoe2e.manual_ndd import *


APP_NAME = os.getenv('APP_NAME', 'PETCLINIC')


action_func_db.delete_many({ 'app': APP_NAME })
func_db.delete_many({ 'app': APP_NAME })


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

    for action in current_actions:
        if LOOP_COUNTER >= MAX_ACTIONS:
            logger.info(f"Reached MAX_ACTIONS={MAX_ACTIONS}, stopping crawl")
            should_stop = True
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
            if len(functionalities) != 0:
                functionality_ids = insert_functionalities(functionalities)
                insert_action_functionality(
                    func_ids=functionality_ids,
                    state_id=state.get_id(StateIdEvaluator.BY_ACTIONS),
                    state_url=state.url,
                    prev_state_id=state.crawl_path.get_state(-1).get_id(StateIdEvaluator.BY_ACTIONS) if len(state.crawl_path) > 0 else None,
                    action_id=action.get_id(),
                    prev_action_id=state.crawl_path.get_action(-1).get_id() if len(state.crawl_path) > 0 else None,
                    action_test_id=action.element.test_id,
                    action_depth=len(state.crawl_path),
                    action_type="SINGLE",
                    functionalities=functionalities,
                    state_context=current_state.context,
                    prev_state_context=state.crawl_path.get_state(-1).context if len(state.crawl_path) > 0 else None,
                    prev_state_url=state.crawl_path.get_state(-1).url if len(state.crawl_path) > 0 else None,
                    action_outer_html=action.element.outerHTML
                )
        
            if len(current_state.crawl_path) > 0:
                logger.info('Extracting double action scenarios')
                functionalities = extract_action_functionalities(current_state, action, current_state.crawl_path.get_action(-1))
                if len(functionalities) != 0:
                    functionality_ids = insert_functionalities(functionalities)
                    insert_action_functionality(
                        func_ids=functionality_ids,
                        state_id=state.get_id(StateIdEvaluator.BY_ACTIONS),
                        state_url=state.url,
                        prev_state_id=state.crawl_path.get_state(-1).get_id(StateIdEvaluator.BY_ACTIONS) if len(state.crawl_path) > 0 else None,
                        action_id=action.get_id(),
                        prev_action_id=state.crawl_path.get_action(-1).get_id() if len(state.crawl_path) > 0 else None,
                        action_test_id=action.element.test_id,
                        action_depth=len(state.crawl_path),
                        action_type="DOUBLE",
                        functionalities=functionalities,
                        state_context=current_state.context,
                        prev_state_context=state.crawl_path.get_state(-1).context if len(state.crawl_path) > 0 else None,
                        prev_state_url=state.crawl_path.get_state(-1).url if len(state.crawl_path) > 0 else None,
                        action_outer_html=action.element.outerHTML
                    )
                
                logger.info('Updating action scores')
    
                update_functionality_score(
                    current_state.crawl_path.get_state(-1),
                    current_state.crawl_path.get_action(-1),
                    current_state,
                    action
                )

                logger.info('Action scores updated')

            logger.info('Marking final functionalities')

            mark_final_functionalities(current_state, action)

            logger.info('Final actions marked')
        
        crawl_context.load_state(crawl_context.state_machine.get_current_state())

        logger.info("")

crawl_context.driver.quit()


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
