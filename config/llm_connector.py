import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_groq import ChatGroq
from langchain_openai import AzureChatOpenAI
from enums.llm_config import LLMType

class LLMConnector:
    def __init__(
        self,
        model_name: str,
        temperature: float = 0.0,
        llm_type: LLMType = LLMType.GROQ_AI,
        api_key: str = None,
        endpoint: str = None,
        max_retries: int = 2,
    ):
        load_dotenv()
        self.model = model_name
        self.temperature = temperature
        self.llm_type = llm_type

        if api_key is None:
            if self.llm_type == LLMType.OPEN_AI:
                self.api_key = os.getenv("OPENAI_API_KEY")
            elif self.llm_type == LLMType.AZURE_OPENAI_AI:
                self.api_key = os.getenv("AZURE_OPENAI_API_KEY")
            else:
                self.api_key = os.getenv("GROQ_API_KEY")
        else:
            self.api_key = api_key

        if endpoint is None:
            if self.llm_type == LLMType.AZURE_OPENAI_AI:
                self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            else:
                self.endpoint = None
        else:
            self.endpoint = endpoint

        self.max_retries = max_retries

    def __call__(self):
        if not self.model:
            raise ValueError("Model is not defined")
        if not self.api_key:
            raise ValueError("API key is not defined")

        if self.llm_type == LLMType.OPEN_AI:
            return self.get_openai_llm()
        elif self.llm_type == LLMType.AZURE_OPENAI_AI:
            return self.get_azure_llm()
        else:
            return self.get_groq_llm()

    def get_openai_llm(self):
        return ChatOpenAI(
            model_name=self.model,
            openai_api_key=self.api_key,
            temperature=self.temperature,
            max_retries=self.max_retries,
            model_kwargs={"seed": 1234},
        )

    def get_groq_llm(self):
        return ChatGroq(
            model=self.model,
            temperature=self.temperature,
            api_key=self.api_key,
            max_retries=self.max_retries,
            model_kwargs={"seed": 1234},
        )

    def get_azure_llm(self):
        if self.endpoint is None:
            raise ValueError("Endpoint is not defined")
        return AzureChatOpenAI(
            azure_endpoint=self.endpoint,
            api_version="2024-12-01-preview",
            azure_deployment=self.model,
            temperature=self.temperature,
            api_key=self.api_key,
            max_retries=self.max_retries,
            seed=1234,
        )
