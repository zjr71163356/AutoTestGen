import os
from dotenv import load_dotenv

import pymongo

load_dotenv()


client = pymongo.MongoClient(os.getenv("ATLAS_URI"))
db = client.myDatabase


# action-functionality collection
# action_func_db = db["action-functionality"]
# func_db = db["functionality"]

# new graph collections
states_db = db["states"]
transitions_db = db["transitions"]
tasks_db = db["tasks"]
functionalities_db = db["functionalities"]
scenarios_db = db["scenarios"]
step_assertions_db = db["step_assertions"]
feature_scenarios_db = db["feature_scenarios"]  # legacy, kept for迁移/清理
exploration_state_db = db["exploration_state"]
