import os
import time
from dotenv import load_dotenv

from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.callbacks import get_openai_callback

from autoe2e.utils import logger
from .utils import log_user_messages


load_dotenv()

SILICONFLOW_BASE_URL = os.getenv(
    "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn"
)
OPENAI_BASE_URL = f"{SILICONFLOW_BASE_URL.rstrip('/')}/v1"
LOCAL_CHAT_MODEL = os.getenv("LOCAL_CHAT_MODEL", "Qwen/Qwen3-8B")
LOCAL_EMBED_MODEL = os.getenv("LOCAL_EMBED_MODEL", "Qwen/Qwen3-Embedding-8B")
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
LLM_RETRY_DELAY_SECONDS = float(os.getenv("LLM_RETRY_DELAY_SECONDS", "5"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1024"))


def create_model_chain(model):
    def invoke_model_chain(system_prompt, user_messages):
        logger.info('Prompt:')
        log_user_messages(user_messages.content)

        prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=system_prompt),
            user_messages
        ])
        output_parser = StrOutputParser()

        chain = prompt | model | output_parser

        attempts = max(1, LLM_MAX_RETRIES)
        last_error = None

        for attempt in range(1, attempts + 1):
            try:
                with get_openai_callback() as cb:
                    res = chain.invoke({})
                    logger.info("Response:")
                    logger.info(res)
                    logger.info(cb)
                    logger.info("")
                    return res
            except Exception as exc:
                last_error = exc
                logger.warn(
                    f"LLM call failed on attempt {attempt}/{attempts}: {exc}"
                )
                if attempt == attempts:
                    raise
                time.sleep(LLM_RETRY_DELAY_SECONDS)

        raise last_error

    return invoke_model_chain


local_llm = ChatOpenAI(
    model=LOCAL_CHAT_MODEL,
    max_tokens=LLM_MAX_TOKENS,
    temperature=0,
    base_url=OPENAI_BASE_URL,
    timeout=LLM_TIMEOUT_SECONDS,
    max_retries=0,
)

local_chain = create_model_chain(local_llm)
gpt4o_chain = local_chain
gpt35_chain = local_chain
sonnet_chain = local_chain
haiku_chain = local_chain

openai_embeddings = OpenAIEmbeddings(
    model=LOCAL_EMBED_MODEL,
    base_url=OPENAI_BASE_URL,
    timeout=LLM_TIMEOUT_SECONDS,
    max_retries=LLM_MAX_RETRIES,
)
