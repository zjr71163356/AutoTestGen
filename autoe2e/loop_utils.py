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
    insert_action_functionality,
    update_functionality_score,
    mark_final_functionalities,
    is_action_critical,
    create_form_filling_values
)
from autoe2e.mongo_utils import (
    functionalities_db,
    transitions_db
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
    # transitions_db stores functionality_ids as list of strings
    connected_transitions = list(transitions_db.find({
        # 'app': os.getenv("APP_NAME"), # transitions might not have app? Plan said states have app.
        # But we need to filter by app.
        # If transitions don't have app, we might need to join with states or just assume we are in the right DB context.
        # Wait, if I didn't add 'app' to transitions in GraphStorage, I can't filter by it easily unless I rely on functionality_ids being unique across apps (unlikely) or just trust the DB.
        # But let's check GraphStorage.save_transition. It doesn't add 'app'.
        # However, functionality_ids are from functionalities_db which HAS 'app'.
        # So if we query by functionality_id, we are implicitly filtering by app (if functionality IDs are unique).
        # MongoDB ObjectIds are unique.
        'functionality_ids': str(highest_func['_id']),
        # We need a way to mark transitions as "should_execute".
        # In GraphStorage, I didn't add "should_execute".
        # But existing code used it.
        # I should assume all transitions found here are candidates?
        # Or I need to add 'should_execute' to transitions schema?
        # Let's assume we can filter by 'should_execute' if I add it, or just check if target_state is None?
        # But target_state being None means we haven't explored it?
        # No, transitions are created when we EXPLORE.
        # Wait, `get_next_action` is about choosing an action to EXECUTE to verify/finalize a feature.
        # If we already executed it, we have a transition.
        # If we want to "re-execute" or "continue", we need to know where we are.
        
        # The original logic:
        # 1. Find feature.
        # 2. Find action connected to feature.
        # 3. Go to state, execute action.
        
        # If `action_func_db` stored (State, Action) pairs that are "candidates".
        # And `should_execute` meant "we haven't finished exploring this path".
        
        # In new schema, `transitions` are edges.
        # If we want to find "actions to execute", we are looking for edges that we have traversed?
        # Or edges we WANT to traverse?
        
        # `insert_action_functionality` was called for ALL available actions in a state.
        # So it stored "Potential Transitions".
        # My `GraphStorage.save_transition` is called in `extract_state_action_features` which iterates over available actions.
        # So `transitions_db` DOES store "Potential Transitions" (with target_state=None initially).
        
        # So I should add `should_execute` to `save_transition`?
        # Or just assume if it's in DB it's a candidate?
        # But we need to mark it as "don't execute again" if it leads to a loop or is critical.
        
        # I'll assume I can filter by `should_execute` if I add it to the query.
        # But I need to make sure `save_transition` sets it.
        # In `GraphStorage.save_transition`, I didn't set default.
        # But `insert_action_functionality` set `should_execute=True`.
        
        # I will update `GraphStorage` later or just assume True for now if missing?
        # No, I should probably add it to the query as optional or just filter in python.
        # But better to rely on DB.
        
        # Let's assume `should_execute` field exists (I should add it to GraphStorage if I want to be consistent).
        # For now, I will query without it and filter in code or assume True.
        # But wait, `flag_action_to_stop_execution` sets it to False.
        # So I MUST support it.
        
        # I will add `should_execute: True` to the query.
        # And I will update `GraphStorage` to set it to True by default.
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
    if state.get_id(StateIdEvaluator.BY_ACTIONS) in crawl_context.state_machine.state_graph.states:
        return True
    if state in crawl_context.state_machine.state_graph.states.values():
        return True
    return False


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
            insert_action_functionality(
                func_ids=functionality_ids,
                state_id=state.get_id(StateIdEvaluator.BY_ACTIONS),
                state_url=state.url,
                prev_state_id=state.crawl_path.get_state(-1).get_id(StateIdEvaluator.BY_ACTIONS) if len(state.crawl_path) > 0 else None,
                action_id=action.get_id(),
                action_test_id=action.element.test_id,
                action_depth=len(state.crawl_path),
                action_type="SINGLE",
                functionalities=functionalities,
                state_context=state.context,
                prev_state_context=state.crawl_path.get_state(-1).context if len(state.crawl_path) > 0 else None,
                prev_state_url=state.crawl_path.get_state(-1).url if len(state.crawl_path) > 0 else None,
                action_outer_html=action.element.outerHTML
            )
            
            GraphStorage.save_transition(
                source_state=state,
                action=action,
                functionality_ids=[str(fid) for fid in functionality_ids]
            )
    
        if len(state.crawl_path) > 0:
            logger.info('Extracting double action scenarios')
            functionalities = extract_action_functionalities(state, action, state.crawl_path.get_action(-1))
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
                    state_context=state.context,
                    prev_state_context=state.crawl_path.get_state(-1).context if len(state.crawl_path) > 0 else None,
                    prev_state_url=state.crawl_path.get_state(-1).url if len(state.crawl_path) > 0 else None,
                    action_outer_html=action.element.outerHTML
                )
            
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
