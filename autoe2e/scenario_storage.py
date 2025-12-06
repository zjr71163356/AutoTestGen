import os
import datetime
from typing import Optional, List, Dict, Any

from autoe2e.mongo_utils import step_assertions_db
from autoe2e.crawler.state import State, StateIdEvaluator
from autoe2e.crawler.action import Action
from autoe2e.utils import geometric_score


def save_step_assertions(
    state: State,
    action: Action,
    functionalities: List[Dict[str, Any]],
    functionality_ids: List[Any],
    is_critical_action: bool = False,
    finality_map: Optional[Dict[str, bool]] = None,
) -> List[Any]:
    """
    将某个状态下某个动作对应的一组功能的前置/断言信息写入 step_assertions 集合。

    一个 (state, action) 可能对应多条功能，每条功能在这里对应一个场景文档。
    """
    if not functionalities or not functionality_ids:
        return []

    app_name = os.getenv("APP_NAME")

    source_state_id = state.get_id(StateIdEvaluator.BY_ACTIONS)
    transition_id = f"{source_state_id}-{action.get_id()}"

    prev_state = state.crawl_path.get_state(-1) if len(state.crawl_path) > 0 else None
    prev_state_id = (
        prev_state.get_id(StateIdEvaluator.BY_ACTIONS) if prev_state is not None else None
    )
    prev_state_url = prev_state.url if prev_state is not None else None
    prev_state_context = prev_state.context if prev_state is not None else None

    state_url = state.url
    state_context = state.context

    element = action.get_element()
    action_outer_html = element.outerHTML
    action_test_id = getattr(element, "test_id", None)
    action_type = action.get_type().get_value()
    action_depth = len(state.crawl_path)

    created_at = datetime.datetime.utcnow()
    finality_map = finality_map or {}

    docs = []
    for rank, (func, fid) in enumerate(zip(functionalities, functionality_ids)):
        func_id_str = str(fid)
        is_final_on_path = bool(finality_map.get(func_id_str, False))

        doc = {
            "app": app_name,
            "feature_id": fid,
            "transition_id": transition_id,
            "source_state_id": source_state_id,
            "state_url": state_url,
            "prev_state_id": prev_state_id,
            "prev_state_url": prev_state_url,
            "state_context": state_context,
            "prev_state_context": prev_state_context,
            "action_outer_html": action_outer_html,
            "action_test_id": action_test_id,
            "action_type": action_type,
            "action_depth": action_depth,
            "preconditions": func.get("preconditions", []),
            "assertions": func.get("assertions", []),
            "is_final_on_path": is_final_on_path,
            "is_critical_action": is_critical_action,
            "rank": rank,
            "score": geometric_score(rank),
            "created_at": created_at,
        }
        docs.append(doc)

    if not docs:
        return []

    result = step_assertions_db.insert_many(docs)
    return result.inserted_ids


__all__ = [
    "save_step_assertions",
]
