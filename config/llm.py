import os
from dotenv import load_dotenv
from enums.llm_config import LLMType
from config.llm_connector import LLMConnector

def make_llm():
    load_dotenv()
    llm_type_env = (os.getenv("LLM_TYPE", "openai") or "openai").lower()
    model_name = os.getenv("LLM_MODEL_NAME", "gpt-4o-mini")
    temperature = float(os.getenv("LLM_TEMPERATURE", 0.2))
    max_retries = int(os.getenv("LLM_MAX_RETRIES", 2))
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")

    if llm_type_env == "azure_openai":
        llm_type = LLMType.AZURE_OPENAI_AI
    elif llm_type_env == "groq":
        llm_type = LLMType.GROQ_AI
    else:
        llm_type = LLMType.OPEN_AI

    connector = LLMConnector(
        model_name=model_name,
        temperature=temperature,
        llm_type=llm_type,
        endpoint=endpoint,
        max_retries=max_retries,
    )
    return connector()
