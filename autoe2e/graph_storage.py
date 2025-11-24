import os
import uuid
import datetime
from typing import Optional

from autoe2e.mongo_utils import states_db, transitions_db, tasks_db
from autoe2e.crawler.state import State, StateIdEvaluator
from autoe2e.crawler.action import Action
from autoe2e.crawler.state.state_graph import StateGraph

class GraphStorage:
    @staticmethod
    def save_state(state: State, screenshot_path: Optional[str] = None):
        state_id = state.get_id(StateIdEvaluator.BY_ACTIONS)
        
        doc = {
            "_id": state_id,
            "url": state.url,
            "app": os.getenv("APP_NAME"),
            "context": state.context,
            "created_at": datetime.datetime.utcnow()
        }
        
        if screenshot_path:
            doc["screenshot_path"] = screenshot_path
            
        states_db.update_one(
            {"_id": state_id}, 
            {"$set": doc}, 
            upsert=True
        )

    @staticmethod
    def save_transition(
        source_state: State, 
        action: Action, 
        target_state: Optional[State] = None, 
        functionality_ids: list[str] = None,
        score: float = 0.0,
        metadata: dict = None
    ):
        source_id = source_state.get_id(StateIdEvaluator.BY_ACTIONS)
        # target_state might be None if we just explored the action but didn't land on a new state yet? 
        # But usually we have a target state. 
        # In insert_action_functionality, we might not have the target state object if it's just "action functionality" extraction?
        # Let's check insert_action_functionality arguments.
        
        # It has state_id (source), prev_state_id (which is actually the source of the PREVIOUS transition).
        # Wait, insert_action_functionality is called for the current state and its actions.
        # So it's saving "Potential Transitions" or "Edges from Current State".
        
        # If we are in state S, and we have action A. We don't know where A leads yet unless we executed it.
        # But insert_action_functionality is called AFTER execution?
        # No, extract_state_action_features is called on `state`.
        # And it iterates over `state.get_actions()`.
        # These actions are "available" actions. We don't know where they lead yet.
        
        # However, the loop in loop_utils.py:
        # 1. explore_connected_states -> executes action -> gets new_state -> adds to graph.
        # 2. extract_state_action_features -> called on `state`.
        
        # So when we are in `extract_state_action_features`, we are analyzing the actions of the CURRENT state.
        # We don't necessarily know the target state for all actions.
        
        # But the `transitions` collection usually implies a known edge (Source -> Action -> Target).
        # If we only know Source -> Action, that's just an "Available Action".
        
        # The user wants "State-Action graph".
        # If we only have Source -> Action, we can store it with target=None.
        
        # But wait, `loop_utils.py` calls `crawl_context.state_machine.add_state_from_current_state(new_state, action)`.
        # This implies we DO know the transition: Current -> Action -> NewState.
        
        # I should probably call save_transition THERE (in loop_utils or state_machine) if I want to capture the graph structure.
        
        # But `insert_action_functionality` is about "semantics" (functionalities).
        # It links (State, Action) -> Functionality.
        
        # My plan said: "Call GraphStorage.save_state and GraphStorage.save_transition in insert_action_functionality".
        # If insert_action_functionality is only about (State, Action), then `target_state` will be None.
        
        # Let's look at `insert_action_functionality` in `infer_utils.py` again.
        # It takes `state_id`, `action_id`, `prev_state_id`.
        # It seems to be storing the "Path" so far? Or just the node?
        
        # It stores:
        # "state": state_id (The state where action is available)
        # "prev_state": prev_state_id (The state we came from)
        # "action": action_id (The action we took to get HERE? No, the action available HERE?)
        
        # Let's check `loop_utils.py`:
        # extract_state_action_features(crawl_context, state)
        #   actions = state.get_actions()
        #   for action in actions:
        #       insert_action_functionality(..., state_id=state.get_id(), action_id=action.get_id(), ...)
        
        # So it stores (State, Action) pairs that are AVAILABLE at State.
        # It also stores `prev_state_id` which is how we got to `State`.
        
        # So `insert_action_functionality` is actually populating the "Edges" leaving `State`.
        # But we don't know the Target State yet.
        
        # The `transitions` collection in my plan has `target_state_id`.
        # If I want to fill `target_state_id`, I need to know where the action leads.
        
        # `state_machine.add_state_from_current_state` knows the target.
        # I should probably add a method `save_transition_target` or similar, or just save the transition when we execute it.
        
        # Let's implement `save_transition` to handle optional target.
        
        transition_id = f"{source_id}-{action.get_id()}"
        
        doc = {
            "_id": transition_id,
            "source_state_id": source_id,
            "action_type": action.get_type().get_value(),
            "element_selector": action.get_id(), # using ID as selector for now
            "element_html": action.get_element().outerHTML,
            # "params": ... # Action doesn't strictly have params unless set
        }
        
        if target_state:
            doc["target_state_id"] = target_state.get_id(StateIdEvaluator.BY_ACTIONS)
            
        if functionality_ids:
            doc["functionality_ids"] = functionality_ids
            
        if score:
            doc["score"] = score
            
        if metadata:
            doc.update(metadata)
            
        transitions_db.update_one(
            {"_id": transition_id},
            {"$set": doc},
            upsert=True
        )

    @staticmethod
    def save_task(goal: str, steps: list[dict], status: str = "generated"):
        task_id = str(uuid.uuid4()) # or hash of goal?
        # If we want to deduplicate tasks, maybe hash of goal.
        
        doc = {
            "goal": goal,
            "steps": steps,
            "status": status,
            "created_at": datetime.datetime.utcnow()
        }
        
        tasks_db.insert_one(doc)
        return task_id

    @staticmethod
    def get_graph() -> StateGraph:
        # TODO: Implement reconstruction if needed
        return StateGraph()
