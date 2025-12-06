import os
import json
import re
import ast

from dotenv import load_dotenv
from bson.objectid import ObjectId

from autoe2e.utils import logger

from autoe2e.browser.utils import save_screenshot
from autoe2e.crawler.crawl_context import CrawlContext
from autoe2e.crawler.state import State, StateIdEvaluator
from autoe2e.crawler.action import Action

from autoe2e.llm_api_call import (
    sonnet_chain,
    haiku_chain,
    openai_embeddings
)
from autoe2e.prompts import (
    CONTEXT_EXTRACTION_SYSTEM_PROMPT,
    FUNCTIONALITY_EXTRACTION_SYSTEM_PROMPT,
    SIMILARITY_SYSTEM_PROMPT,
    CRITICAL_ACTION_SYSTEM_PROMPT,
    FORM_VALUE_SYSTEM_PROMPT,
    FINALITY_SYSTEM_PROMPT,
    create_context_user_messages,
    create_functionality_user_messages,
    create_similarity_user_messages,
    create_simple_user_messages,
    create_finality_user_messages
)
from autoe2e.utils import (
    png_to_base64,
    extract_response_content,
    geometric_score
)
from autoe2e.mongo_utils import (
    functionalities_db,
    transitions_db
)
from autoe2e.graph_storage import GraphStorage


load_dotenv()


def parse_bool_list(text: str | None) -> list[bool]:
    """Parse a list of booleans from model output robustly.

    Accepts JSON (e.g., [true,false]), Python literal (e.g., [True, False]),
    or any text containing a sequence of true/false tokens. Returns [] if
    nothing parsable is found.
    """
    if text is None:
        return []
    s = text.strip()
    # Try JSON first
    try:
        v = json.loads(s)
        if isinstance(v, list):
            return [bool(x) for x in v]
    except Exception:
        pass
    # Try Python literal
    try:
        v = ast.literal_eval(s)
        if isinstance(v, list):
            return [bool(x) for x in v]
    except Exception:
        pass
    # Heuristic: extract tokens true/false, case-insensitive
    tokens = re.findall(r"\b(true|false)\b", s, flags=re.I)
    if tokens:
        return [t.lower() == 'true' for t in tokens]
    return []


def extract_state_context(
    crawl_context: CrawlContext,
    state: State,
    prev_state: State | None = None,
    prev_action: Action | None = None
) -> str:
    state_id = state.get_id(StateIdEvaluator.BY_ACTIONS)
    
    screenshot_path = f'{crawl_context.config.temp_dir}/screenshot_{state_id}.png'
    save_screenshot(crawl_context.driver, screenshot_path)
    logger.info(f'Saved screenshot to {screenshot_path}')
    
    context_text = sonnet_chain(
        CONTEXT_EXTRACTION_SYSTEM_PROMPT,
        create_context_user_messages(
            {
                "description": "None",
                "previous_state": "None. This is the first state." if prev_state is None else prev_state.get_context(),
                "previous_action": "None. This is the first state." if prev_action is None else prev_action.element.outerHTML,
            },
            png_to_base64(screenshot_path)
        )
    )
    
    return context_text


def extract_action_functionalities(
    state: State,
    action: Action,
    prev_action: Action | None = None
) -> list[dict]:
    res = sonnet_chain(
        FUNCTIONALITY_EXTRACTION_SYSTEM_PROMPT,
        create_functionality_user_messages(
            state.context,
            action.element.outerHTML,
            prev_action.element.outerHTML if prev_action is not None else None
        )
    )

    functionalities = json.loads(extract_response_content(res) or "[]")

    # functionalities = list(map(lambda x: x['feature'], functionalities))

    return functionalities


def extract_action_functionalities_dict(
    state,
    action,
    prev_action = None
) -> list[str]:
    res = sonnet_chain(
        FUNCTIONALITY_EXTRACTION_SYSTEM_PROMPT,
        create_functionality_user_messages(
            state['context'],
            action['outerHTML'],
            prev_action['outerHTML'] if prev_action is not None else None
        )
    )

    functionalities = json.loads(extract_response_content(res) or "[]")

    functionalities = list(map(lambda x: x['feature'], functionalities))

    return functionalities


def query_similar_functionalities(embedding):
    query = [
        {
            '$vectorSearch': {
                'index': 'vector_index', 
                'path': 'embedding', 
                'queryVector': embedding, 
                'limit': 50,
                'numCandidates': 200
            }
        },
        {
            '$match': {
                'app': os.getenv("APP_NAME"),
            }
        },
        {
            '$limit': 5
        }
    ]
    
    # Use functionalities_db
    similar_funcs = list(functionalities_db.aggregate(query))
    return similar_funcs


def get_exact_match_indices(text, similar_funcs):
    indices = []
    
    for i in range(len(similar_funcs)):
        if similar_funcs[i]['text'] == text:
            indices.append(i)
    
    return indices


def map_similar_func_to_exact_match(func_info):
    rank, func_data, embedding, similar_funcs = func_info
    text = func_data['feature']
    
    exact_match_indices = get_exact_match_indices(text, similar_funcs)
    
    if len(exact_match_indices) > 0:
        match = {
            'match': True,
            'match_index': exact_match_indices,
            'combined_text': text
        }
    else:
        match = {
            'match': False
        }
    
    if len(similar_funcs) != 0:
        res = sonnet_chain(
            SIMILARITY_SYSTEM_PROMPT,
            create_similarity_user_messages(
                text,
                '\n'.join(map(lambda x: x['text'], similar_funcs))
            )
        )
        
        match_res = json.loads(extract_response_content(res) or "{}")
        
        # Merge LLM result with exact match result
        if 'match_index' in match_res:
            match['match'] = match_res.get('match', False) # Assuming LLM returns match boolean
            match['match_index'] = list(set(match_res['match_index'] + exact_match_indices))
            if 'combined_text' in match_res:
                match['combined_text'] = match_res['combined_text']
        elif len(exact_match_indices) > 0:
            match['match'] = True
            match['match_index'] = exact_match_indices
            match['combined_text'] = text
            
        # If LLM says match but no index, it might be an issue, but let's trust LLM response structure if it matches existing code logic
        # The existing code overwrote 'match' variable. 
        # Let's try to preserve the existing logic but fix the variable shadowing if possible, or just adapt to it.
        # The existing code:
        # match = json.loads(...)
        # if 'match_index' in match: ...
        
        # It seems the LLM response is expected to have 'match_index' if it found a match.
        # And 'match' key (boolean).
        
        if 'match' in match_res:
             match.update(match_res)
             if 'match_index' in match_res:
                 match['match_index'] = list(set(match_res['match_index'] + exact_match_indices))
             elif len(exact_match_indices) > 0:
                 match['match_index'] = exact_match_indices
    
    if match['match']:
        if type(match['match_index']) == int:
            match['match_id'] = [similar_funcs[match['match_index']]['_id']]
        else:
            match['match_id'] = [similar_funcs[m]['_id'] for m in match['match_index']]
    
    match['rank'] = rank
    match['text'] = text
    match['embedding'] = embedding
    match['func_data'] = func_data
    
    return match


def no_match_insert(match):
    func_data = match.get('func_data', {})
    res = functionalities_db.insert_one({
        "app": os.getenv("APP_NAME"),
        "text": match['text'],
        "embedding": match['embedding'],
        "score": geometric_score(match['rank']),
        "final": False,
        "executable": True,
        "is_goal": func_data.get('is_goal', False),
    })
    return res.inserted_id


def match_update(match):
    func_data = match.get('func_data', {})
    update_fields = {
        'text': match.get('combined_text', match['text']),
        'embedding': openai_embeddings.embed_query(match.get('combined_text', match['text']))
    }
    
    if 'is_goal' in func_data:
        update_fields['is_goal'] = func_data['is_goal']

    # update the text for the initial match
    # update the text for the initial match
    functionalities_db.update_one(
        filter={
            'app': os.getenv("APP_NAME"),
            '_id': match['match_id'][0]
        },
        update={
            '$set': update_fields
        },
        upsert=False
    )

    if len(match['match_id']) > 1:
        # remove other documents as they are duplicates of the initial one
        functionalities_db.delete_many(
            {
                'app': { '$eq': os.getenv("APP_NAME") },
                '_id': { '$in': match['match_id'][1:] }
            }
        )
        # 将 transitions 中的旧功能引用替换为保留的功能 ID
        kept_id = match['match_id'][0]
        removed_ids = match['match_id'][1:]
        removal_candidates = removed_ids + list(map(str, removed_ids))

        transitions_db.update_many(
            {
                'app': os.getenv("APP_NAME"),
                'functionality_ids': { '$in': removal_candidates }
            },
            {
                '$addToSet': { 'functionality_ids': kept_id },
                '$pull': { 'functionality_ids': { '$in': removal_candidates } }
            }
        )
    
    return match['match_id'][0]


def update_databases_with_match(match):
    if match['match']:
        return match_update(match)
    return no_match_insert(match)


def insert_functionalities(functionalities: list[dict]):
    texts = [f['feature'] for f in functionalities]
    embeddings = openai_embeddings.embed_documents(texts)

    similar_funcs = map(query_similar_functionalities, embeddings)

    matches = map(
        map_similar_func_to_exact_match,
        zip(
            range(len(functionalities)),
            functionalities,
            embeddings,
            similar_funcs
        )
    )

    insertion_ids = list(map(update_databases_with_match, matches))
    
    return insertion_ids


# insert_action_functionality removed


def update_functionality_score(prev_state, prev_action, curr_state, curr_action):
    # TODO: Implement scoring update for new schema if needed.
    # Currently transitions_db does not explicitly store "DOUBLE" action types in the same way.
    pass


# update_functionality_score_dict removed



def mark_final_functionalities(curr_state, curr_action) -> dict[str, bool]:
    # Find transition to get functionality IDs
    transition_id = f"{curr_state.get_id(StateIdEvaluator.BY_ACTIONS)}-{curr_action.get_id()}"
    transition = transitions_db.find_one({"_id": transition_id})
    
    if not transition or "functionality_ids" not in transition:
        return {}

    func_ids = [
        fid if isinstance(fid, ObjectId) else ObjectId(fid)
        for fid in transition.get("functionality_ids", [])
    ]
    
    retreived_funcs = list(functionalities_db.find({
        'app': { '$eq': os.getenv("APP_NAME") },
        '_id': { '$in': func_ids }
    }))

    if len(retreived_funcs) == 0:
        return {}
    
    res = sonnet_chain(
        FINALITY_SYSTEM_PROMPT,
        create_finality_user_messages(
            curr_state.context,
            curr_action.element.outerHTML,
            '\n'.join(map(lambda x: x['text'], retreived_funcs))
        )
    )

    finality = parse_bool_list(extract_response_content(res))

    finality_map: dict[str, bool] = {}

    for i in range(len(retreived_funcs)):
        func_doc = retreived_funcs[i]
        is_final = i < len(finality) and bool(finality[i])
        finality_map[str(func_doc['_id'])] = is_final

        if is_final:
            functionalities_db.update_one(
                filter={
                    'app': os.getenv("APP_NAME"),
                    '_id': func_doc['_id']
                },
                update={
                    '$set': {
                        'final': True,
                    }
                },
                upsert=False
            )
            # We don't need to update action_func_db anymore

    return finality_map


# mark_final_functionalities_dict removed


def is_action_critical(action: Action) -> bool:
    element_html = action.get_element().outerHTML

    res = haiku_chain(
        CRITICAL_ACTION_SYSTEM_PROMPT,
        create_simple_user_messages(element_html)
    )

    return eval(res)


def create_form_filling_values(action: Action):
    element_html = action.get_element().outerHTML

    res = sonnet_chain(
        FORM_VALUE_SYSTEM_PROMPT,
        create_simple_user_messages(element_html)
    )

    return json.loads(res)
