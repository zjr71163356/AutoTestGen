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
