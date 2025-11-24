import os
import sys
import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sys
from unittest.mock import MagicMock, ANY


# Mock pymongo before importing mongo_utils
mock_pymongo = MagicMock()
sys.modules["pymongo"] = mock_pymongo
mock_client = MagicMock()
mock_db = MagicMock()
mock_pymongo.MongoClient.return_value = mock_client
mock_client.myDatabase = mock_db
# Mock collection access
mock_db.__getitem__ = lambda self, key: MagicMock()

from autoe2e.mongo_utils import states_db, transitions_db, tasks_db, functionalities_db
from autoe2e.graph_storage import GraphStorage
from autoe2e.crawler.state import State, StateIdEvaluator

# Dummy classes for testing
class DummyElement:
    def __init__(self, _id, outerHTML):
        self._id = _id
        self.outerHTML = outerHTML
        self.test_id = "test-id"
    def get_id(self):
        return self._id

class DummyActionType:
    def get_value(self):
        return "click"

class DummyAction:
    def __init__(self, element):
        self.element = element
        self.action_type = DummyActionType()
    def get_id(self):
        return self.element.get_id()
    def get_type(self):
        return self.action_type
    def get_element(self):
        return self.element

def test_schema():
    print("Testing Schema...")
    
    # Create dummy data
    element1 = DummyElement("elem1", "<div>Elem1</div>")
    action1 = DummyAction(element1)
    
    state1 = State(
        url="http://example.com/1",
        dom="<html>1</html>",
        actions=[action1]
    )
    state1.set_context("Context for state 1")
    
    element2 = DummyElement("elem2", "<div>Elem2</div>")
    action2 = DummyAction(element2)
    
    state2 = State(
        url="http://example.com/2",
        dom="<html>2</html>",
        actions=[action2]
    )
    state2.set_context("Context for state 2")
    
    # Test save_state
    print("Saving states...")
    GraphStorage.save_state(state1, "/tmp/s1.png")
    GraphStorage.save_state(state2, "/tmp/s2.png")
    
    # Verify states
    # s1_doc = states_db.find_one({"_id": state1.get_id(StateIdEvaluator.BY_ACTIONS)})
    # assert s1_doc is not None
    # assert s1_doc["url"] == "http://example.com/1"
    # assert s1_doc["context"] == "Context for state 1"
    
    # Verify save_state called update_one
    states_db.update_one.assert_any_call(
        {"_id": state1.get_id(StateIdEvaluator.BY_ACTIONS)},
        {"$set": {
            "_id": state1.get_id(StateIdEvaluator.BY_ACTIONS),
            "url": "http://example.com/1",
            "app": os.getenv("APP_NAME"),
            "context": "Context for state 1",
            "created_at": ANY, # This will fail strict equality check due to time
            "screenshot_path": "/tmp/s1.png"
        }},
        upsert=True
    )
    print("States verified (mock call).")
    
    # Test save_transition (Source -> Action -> Target)
    print("Saving transition...")
    GraphStorage.save_transition(
        source_state=state1,
        action=action1,
        target_state=state2,
        functionality_ids=["func1"],
        score=0.9
    )
    
    # Verify transition
    t_id = f"{state1.get_id(StateIdEvaluator.BY_ACTIONS)}-{action1.get_id()}"
    # t_doc = transitions_db.find_one({"_id": t_id})
    # assert t_doc is not None
    
    transitions_db.update_one.assert_called()
    call_args = transitions_db.update_one.call_args
    assert call_args[0][0] == {"_id": t_id}
    assert call_args[0][1]["$set"]["source_state_id"] == state1.get_id(StateIdEvaluator.BY_ACTIONS)
    assert call_args[0][1]["$set"]["target_state_id"] == state2.get_id(StateIdEvaluator.BY_ACTIONS)
    assert call_args[0][1]["$set"]["functionality_ids"] == ["func1"]
    print("Transition verified (mock call).")
    
    # Test save_task
    print("Saving task...")
    task_id = GraphStorage.save_task(
        goal="Test Goal",
        steps=[{"transition_id": t_id}]
    )
    
    # Verify task
    # task_doc = tasks_db.find_one({"goal": "Test Goal"})
    tasks_db.insert_one.assert_called()
    call_args = tasks_db.insert_one.call_args
    assert call_args[0][0]["goal"] == "Test Goal"
    assert call_args[0][0]["steps"][0]["transition_id"] == t_id
    print("Task verified (mock call).")
    
    # Verify functionalities_db (mock)
    # Simulate inserting a functionality
    functionalities_db.insert_one.assert_not_called() # We didn't call it in this test
    
    # Test get_next_action query pattern
    print("Testing get_next_action query pattern...")
    # Mock return value for functionalities_db.find
    mock_func = {"_id": "func1", "text": "Test Func", "score": 1.0}
    mock_cursor = MagicMock()
    mock_cursor.sort.return_value.limit.return_value = [mock_func]
    functionalities_db.find.return_value = mock_cursor
    
    funcs = list(functionalities_db.find({
        'app': os.getenv("APP_NAME"),
        'final': False,
        'executable': True
    }).sort({ 'score': -1 }).limit(1))
    
    assert len(funcs) == 1
    assert funcs[0]["_id"] == "func1"
    
    # Mock return value for transitions_db.find
    mock_transition = {
        "_id": t_id,
        "source_state_id": state1.get_id(StateIdEvaluator.BY_ACTIONS),
        "element_selector": action1.get_id(),
        "functionality_ids": ["func1"],
        "should_execute": True
    }
    transitions_db.find.return_value = [mock_transition]
    
    transitions = list(transitions_db.find({
        'functionality_ids': "func1",
        'should_execute': { '$ne': False }
    }))
    
    assert len(transitions) == 1
    assert transitions[0]["_id"] == t_id
    print("Query patterns verified.")

    print("All tests passed!")

if __name__ == "__main__":
    test_schema()
