import os
from typing import Any, Dict, List

import datetime
from bson import ObjectId

from autoe2e.mongo_utils import (
    functionalities_db,
    step_assertions_db,
    scenarios_db,
)
from autoe2e.graph_storage import GraphStorage
from autoe2e.utils import logger


def _build_steps_for_feature(app_name: str, feature_id) -> List[Dict[str, Any]]:
    """根据 step_assertions 重建一条沿 State-Action 图可走通的场景路径。

    设计要点：
    - 仍然以 step_assertions 为“步”级别存储，但在这里按 prev_state_id/source_state_id 串联成一条路径；
    - 优先选择 is_final_on_path=True 的场景作为终点，并沿 prev_state_id 反向回溯；
    - 回溯过程中，每一步选择同一 feature 在 prev_state_id 上、深度最接近的场景，保证 action_depth 单调递增；
    - 最终仅返回一条从起点到终点的有向路径，避免把来自不同分支的离散步简单拼接成“伪路径”。
    """
    scenarios: List[Dict[str, Any]] = list(
        step_assertions_db.find(
            {
                "app": app_name,
                "feature_id": feature_id,
            }
        )
    )

    if not scenarios:
        return []

    # 按 (action_depth, rank) 排序，便于后续选择“最近的上一跳”
    scenarios.sort(
        key=lambda s: (
            s.get("action_depth", 0),
            s.get("rank", 0),
        )
    )

    # 按 source_state_id 建索引：同一状态下可能存在多个与同一 feature 相关的场景
    by_state: Dict[str, List[Dict[str, Any]]] = {}
    for s in scenarios:
        source_state_id = s.get("source_state_id")
        if source_state_id is None:
            continue
        by_state.setdefault(source_state_id, []).append(s)

    # 终点优先选择 is_final_on_path=True 的场景；若不存在，则退化为“最深的一步”
    final_candidates = [s for s in scenarios if bool(s.get("is_final_on_path", False))]
    if final_candidates:
        # 在多个终点中，优先选择 action_depth 最大、score 最大的
        end = max(
            final_candidates,
            key=lambda s: (
                s.get("action_depth", 0),
                s.get("score", 0.0),
            ),
        )
    else:
        # 没有明确的 final 标记时，选择最深的一步作为终点
        end = max(
            scenarios,
            key=lambda s: (
                s.get("action_depth", 0),
                s.get("score", 0.0),
            ),
        )

    # 通过 prev_state_id 反向回溯，构造一条从起点到终点的路径
    path: List[Dict[str, Any]] = [end]
    visited_ids = {end.get("_id")}

    current = end
    current_depth = current.get("action_depth", 0)
    prev_state_id = current.get("prev_state_id")

    while prev_state_id is not None:
        candidates = by_state.get(prev_state_id, [])
        if not candidates:
            break

        # 选择在该 prev_state_id 上、action_depth < current_depth 的“最近上一跳”
        prev_candidates = [
            s for s in candidates if s.get("action_depth", 0) < current_depth
        ]
        if not prev_candidates:
            break

        prev = max(
            prev_candidates,
            key=lambda s: (
                s.get("action_depth", 0),
                -s.get("rank", 0),
            ),
        )

        # 防止异常数据导致循环
        if prev.get("_id") in visited_ids:
            break

        path.append(prev)
        visited_ids.add(prev.get("_id"))
        current = prev
        current_depth = current.get("action_depth", 0)
        prev_state_id = current.get("prev_state_id")

    # 反转为从起点到终点的顺序
    path.reverse()

    steps: List[Dict[str, Any]] = []
    for idx, s in enumerate(path):
        steps.append(
            {
                "scenario_id": str(s.get("_id")),
                "feature_id": str(s.get("feature_id")),
                "transition_id": s.get("transition_id"),
                "source_state_id": s.get("source_state_id"),
                "target_state_id": s.get("target_state_id"),  # 可能不存在
                "state_url": s.get("state_url"),
                "prev_state_id": s.get("prev_state_id"),
                "prev_state_url": s.get("prev_state_url"),
                "state_context": s.get("state_context"),
                "prev_state_context": s.get("prev_state_context"),
                "action_outer_html": s.get("action_outer_html"),
                "action_test_id": s.get("action_test_id"),
                "action_type": s.get("action_type"),
                "action_depth": s.get("action_depth"),
                "rank": s.get("rank"),
                "score": s.get("score"),
                "assertion_ref_id": str(s.get("_id")) if s.get("_id") else None,
                "is_final_on_path": bool(s.get("is_final_on_path", False)),
                "is_critical_action": bool(s.get("is_critical_action", False)),
                # 逻辑上的场景内序号，便于后续按路径维度分析
                "step_index": idx,
            }
        )

    return steps


def _build_and_save_scenario_for_feature(app_name: str, feature_doc: Dict[str, Any]) -> Dict[str, Any] | None:
    """基于 step_assertions 聚合出一条完整路径级场景并写入 scenarios 集合。"""
    feature_id = feature_doc["_id"]
    steps = _build_steps_for_feature(app_name, feature_id)
    if not steps:
        return None

    # 路径级聚合信息
    path_scores = [s.get("score", 0.0) for s in steps]
    scenario_score = min(path_scores) if path_scores else 0.0
    is_critical_path = any(bool(s.get("is_critical_action")) for s in steps)
    start_state_id = steps[0].get("source_state_id")
    end_state_id = steps[-1].get("source_state_id")

    now = datetime.datetime.utcnow()
    existing = scenarios_db.find_one({"app": app_name, "feature_id": feature_id})

    scenario_doc: Dict[str, Any] = {
        "app": app_name,
        "feature_id": feature_id if isinstance(feature_id, ObjectId) else ObjectId(feature_id),
        "goal_text": feature_doc.get("text", ""),
        "status": "generated",
        "start_state_id": start_state_id,
        "end_state_id": end_state_id,
        "is_critical_path": is_critical_path,
        "score": scenario_score,
        "steps": steps,
        "created_at": existing.get("created_at", now) if existing else now,
        "updated_at": now,
    }

    if existing and "_id" in existing:
        scenario_doc["_id"] = existing["_id"]
        scenarios_db.replace_one({"_id": existing["_id"]}, scenario_doc, upsert=True)
    else:
        scenarios_db.insert_one(scenario_doc)

    return scenario_doc


def synthesize_tasks_for_app(app_name: str) -> List[str]:
    """基于 functionalities + step_assertions/scenarios 合成任务并写入 tasks 集合。

    规则（首版）：
    - 只针对当前 app 的功能；
    - 选取 is_goal=True 且 final=True 的功能作为任务目标；
    - 对每个功能，从 step_assertions 中取出所有场景，按 depth/rank 串联构成路径步骤列表；
    - 每个功能生成一个 task，steps 为该功能的一组场景。
    """
    logger.info(f"Synthesizing tasks for app={app_name} ...")

    cursor = functionalities_db.find(
        {
            "app": app_name,
            "is_goal": True,
            "final": True,
        }
    )

    feature_docs = list(cursor)
    if not feature_docs:
        logger.info("No goal+final functionalities found; skip task synthesis.")
        return []

    task_ids: List[str] = []

    for func in feature_docs:
        feature_id = func["_id"]
        feature_text = func.get("text", "")

        scenario_doc = _build_and_save_scenario_for_feature(app_name, func)
        if scenario_doc is None:
            # 没有场景就不生成任务
            continue

        steps = scenario_doc.get("steps", [])
        goal = f"[{app_name}] {feature_text}"
        task_id = GraphStorage.save_task(goal=goal, steps=steps, status="generated")
        task_ids.append(task_id)
        logger.info(
            f"Generated task for feature {feature_id}: task_id={task_id} scenario_id={scenario_doc.get('_id')}"
        )

    logger.info(f"Task synthesis finished; total tasks={len(task_ids)}")
    return task_ids


def synthesize_scenarios_for_app(app_name: str) -> List[str]:
    """仅生成路径级场景（不写入 tasks），便于独立校验或导出。"""
    cursor = functionalities_db.find(
        {
            "app": app_name,
            "is_goal": True,
            "final": True,
        }
    )

    feature_docs = list(cursor)
    scenario_ids: List[str] = []

    for func in feature_docs:
        scenario_doc = _build_and_save_scenario_for_feature(app_name, func)
        if scenario_doc:
            scenario_ids.append(str(scenario_doc.get("_id")))

    logger.info(f"Scenario synthesis finished; total scenarios={len(scenario_ids)}")
    return scenario_ids


__all__ = [
    "synthesize_tasks_for_app",
    "synthesize_scenarios_for_app",
]
