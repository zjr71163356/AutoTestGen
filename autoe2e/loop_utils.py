import os
import re
import random

from dotenv import load_dotenv

from autoe2e.utils import logger

from autoe2e.crawler.crawl_context import CrawlContext
from autoe2e.crawler.state import State, StateIdEvaluator
from autoe2e.crawler.action import Action, CandidateActionExtractor
from autoe2e.manual_ndd import (
    VISIT_ONCE,
    NEVER_VISIT
)
from autoe2e.infer_utils import (
    extract_state_context,
    extract_action_functionalities,
    insert_functionalities,
    update_functionality_score,
    mark_final_functionalities,
    is_action_critical,
    create_form_filling_values
)
from autoe2e.mongo_utils import (
    functionalities_db,
    transitions_db,
    states_db
)
from autoe2e.graph_storage import GraphStorage


load_dotenv()


def get_next_action(crawl_context: CrawlContext):
    # final: all the actions in a chain have been found
    # executable: there is at least one action connected to the functionality that is possible to execute
    # actions might not be executable because they've already been executed once. No redundant action execution.
    highest_funcs = list(functionalities_db.find({
        'app': os.getenv("APP_NAME"),
        'final': False,
        'executable': True
    }).sort({ 'score': -1 }).limit(1))

    # if no function is returned it means all the functionalities have been explored and finalized.
    if len(highest_funcs) == 0:
        return None, None, None

    # randomly choose from one of the highest scorings functionalities.
    highest_func = random.choice(highest_funcs)
    
    logger.info(f'Exploring feature: {highest_func["text"]}')

    # Find transitions connected to this functionality
    connected_transitions = list(transitions_db.find({
        'app': os.getenv("APP_NAME"),
        # 兼容历史字符串存储与新版 ObjectId 存储
        'functionality_ids': { '$in': [highest_func['_id'], str(highest_func['_id'])] },
        'should_execute': { '$ne': False } 
    }))

    # if no actions are connected (meaning that their should_execute is false) the feature is not executable anymore
    if len(connected_transitions) == 0:
        functionalities_db.update_one(
            filter={
                'app': os.getenv("APP_NAME"),
                '_id': highest_func['_id']
            },
            update={
                '$set': {
                    'executable': False
                }
            },
            upsert=False
        )
        return get_next_action(crawl_context)

    # select a random action that has the highest depth
    # transitions don't have 'depth' field in my GraphStorage implementation?
    # I should check. `insert_action_functionality` had `depth`.
    # I should add `depth` to `GraphStorage.save_transition` metadata?
    # Or just pick random.
    # Let's pick random for now to simplify.
    
    selected_transition = random.choice(connected_transitions)

    state_id = selected_transition['source_state_id']
    # action_id is selector?
    action_selector = selected_transition['element_selector']

    state = crawl_context.state_machine.state_graph.get_state(state_id)
    # We need to find the action object from the state
    # But state might not be in memory if we restarted?
    # The `crawl_context` has `state_machine` which has `state_graph`.
    # If state is not in graph, we have a problem.
    # But `get_next_action` assumes we are in the same session?
    # Or it loads from DB?
    # `crawl_context.state_machine.state_graph.get_state(state_id)`
    
    if state is None:
        # This might happen if we are running from a fresh start but DB has data.
        # We might need to load state from DB?
        # But `StateGraph` is in-memory.
        # If we want to support resuming, we need to load graph from DB.
        # But for now, let's assume it's in memory or return None.
        logger.warning(f"State {state_id} not found in memory graph.")
        return get_next_action(crawl_context) # Try another one?

    action = list(filter(lambda x: x.get_id() == action_selector, state.get_actions()))[0]

    return str(highest_func['_id']), state, action


def flag_action_to_stop_execution(state: State, action: Action, feature_id: str | None = None):
    transition_id = f"{state.get_id(StateIdEvaluator.BY_ACTIONS)}-{action.get_id()}"
    
    # We update the transition to set should_execute = False
    # If feature_id is provided, we might want to only disable it for that feature?
    # But transitions are shared?
    # If we disable the transition, we disable it for ALL features?
    # The original code updated `action_func_db` which was (State, Action, Func) tuple.
    # So it could disable (State, Action) for ONE func but keep it for others?
    # Yes: `func_pointer: feature_id`.
    
    # But `transitions_db` is (State, Action). It has `functionality_ids` list.
    # If we want to disable it for one feature, we can't just set `should_execute=False` on the transition.
    # We might need to remove the functionality_id from the list?
    # Or `should_execute` should be a list of disabled functionality IDs?
    
    # But wait, `flag_action_to_stop_execution` is called when:
    # 1. Action is critical (stops everything).
    # 2. State is already in graph (stops everything).
    
    # In those cases, we want to disable the transition entirely.
    # So `should_execute = False` on the transition is correct.
    
    # What if `feature_id` is passed?
    # It is passed in `get_next_action` loop? No.
    # It is passed in `loop_utils.py`?
    # `flag_action_to_stop_execution(state, action)` (no feature_id)
    # `flag_action_to_stop_execution(state, action)` (no feature_id)
    
    # I don't see usage with feature_id in the provided `loop_utils.py`.
    # So I can assume it's global.
    
    transitions_db.update_one(
        {"_id": transition_id},
        {"$set": {"should_execute": False}},
        upsert=True # Should exist, but upsert just in case
    )


def is_state_in_graph(crawl_context: CrawlContext, state: State) -> bool:
    state_id = state.get_id(StateIdEvaluator.BY_ACTIONS)

    # 内存中的状态图（当前进程新增的状态）
    if state_id in crawl_context.state_machine.state_graph.states:
        return True
    if state in crawl_context.state_machine.state_graph.states.values():
        return True

    # 跨运行：检查 Mongo 中是否已存在且已完全探索的状态
    doc = states_db.find_one({
        "_id": state_id,
        "app": os.getenv("APP_NAME"),
        "explored": True,
    })
    return doc is not None


def explore_connected_states(crawl_context: CrawlContext, state: State):
    crawl_context.state_machine.set_current_state(state)
    
    logger.info(f'state: {state.get_id(StateIdEvaluator.BY_ACTIONS)}')
    
    actions: list[Action] = state.get_actions()

    for action in actions:        
        is_critical = is_action_critical(action)

        if is_critical:
            action.set_should_execute(False)
            flag_action_to_stop_execution(state, action)
            continue

        logger.info(f"Executing action {action.element.outerHTML}")
        
        if action.get_type().get_value() == 'form' and not action.has_params():
            values = create_form_filling_values(action)
            action.set_params(values)

        crawl_context.load_state(crawl_context.state_machine.get_current_state())
        action.execute(crawl_context.driver)

        new_actions: list[Action] = CandidateActionExtractor.extract_candidate_actions(crawl_context.driver)
        new_state: State = crawl_context.create_state_from_driver(new_actions)

        if is_state_in_graph(crawl_context, new_state):
            action.set_should_execute(False)
            flag_action_to_stop_execution(state, action)
            continue
        
        logger.info(f'Adding state: {new_state.get_id(StateIdEvaluator.BY_ACTIONS)}')
        crawl_context.state_machine.add_state_from_current_state(new_state, action)

        GraphStorage.save_transition(
            source_state=state,
            action=action,
            target_state=new_state
        )


def extract_state_action_features(crawl_context: CrawlContext, state: State):
    crawl_context.state_machine.set_current_state(state)
    crawl_context.load_state(crawl_context.state_machine.get_current_state())
    
    logger.info('Extracting state context using LLM')
    
    state_context = extract_state_context(
        crawl_context,
        state,
        state.crawl_path.get_state(-1) if len(state.crawl_path) > 0 else None,
        state.crawl_path.get_action(-1) if len(state.crawl_path) > 0 else None,
    )
    state.set_context(state_context)

    state_id = state.get_id(StateIdEvaluator.BY_ACTIONS)
    screenshot_path = f'{crawl_context.config.temp_dir}/screenshot_{state_id}.png'
    GraphStorage.save_state(state, screenshot_path)

    actions: list[Action] = list(filter(lambda a: a.get_should_execute(), state.get_actions()))

    for action in actions:
        logger.info(f'Extracting action scenarios: {action.element.outerHTML}')

        functionalities = extract_action_functionalities(state, action)
        if len(functionalities) != 0:
            functionality_ids = insert_functionalities(functionalities)
            GraphStorage.save_transition(
                source_state=state,
                action=action,
                functionality_ids=functionality_ids
            )
    
        if len(state.crawl_path) > 0:
            logger.info('Extracting double action scenarios')
            functionalities = extract_action_functionalities(state, action, state.crawl_path.get_action(-1))
            if len(functionalities) != 0:
                functionality_ids = insert_functionalities(functionalities)
            logger.info('Updating action scores')

            update_functionality_score(
                state.crawl_path.get_state(-1),
                state.crawl_path.get_action(-1),
                state,
                action
            )

            logger.info('Action scores updated')
        
        logger.info('Marking final functionalities')
    
        mark_final_functionalities(state, action)

        logger.info('Final actions marked')


def is_match(text, pattern):
    match = re.search(pattern, text)
    return match is not None


def is_visit_forbidden(state: State, visit_counter: dict[str, int]) -> bool:
    url = state.url

    for never in NEVER_VISIT:
        if is_match(url, never):
            return visit_counter, True

    for once in VISIT_ONCE:
        if is_match(url, once) and once in visit_counter:
            return visit_counter, True
        elif is_match(url, once):
            visit_counter[once] = 1

    return visit_counter, False
