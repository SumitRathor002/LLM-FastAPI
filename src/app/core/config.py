import os
from enum import Enum
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    APP_NAME: str = "LLM-FastAPI app"
    APP_VERSION: str | None = "0.0.1" 


class LLMSettings(BaseSettings):
    # handles cases where LLMs get stuck in recursive loop
    # catch if model starts looping the same chunk while streaming. 
    # Uses high default (100) to prevent false positives.
    # refer: https://docs.litellm.ai/docs/completion/stream#error-handling---infinite-loops
    LLM_REPEATED_STREAMING_CHUNK_LIMIT: int = 100
    # handles cases where we miss required params or do not follow provide specific format
    # applies to non openAI params only
    # refer: https://docs.litellm.ai/docs/completion/message_sanitization
    MODIFY_PARAMS: bool = True
    MOCK_RESPONSE: bool = False
    # Passing a parameter which is not supported to a model will raise error
    # litellm.drop_params already handles this.
    # refer: https://docs.litellm.ai/docs/completion/input#input-params-1
    DROP_PARAMS: bool = True
    OPENAI_API_KEY: str 
    # we can name different provider API key in the similar fashion,
    # i.e PROVIDER (IN upper case) + API_KEY
    # refer litellm.types.utils.LlmProviders 
    # adding an API_KEY enables the provider to use. 
    # Not checked for every LLM provider, But should work as per the LiteLLM documentation, minimal code, basic guardrails 


class FileLoggerSettings(BaseSettings):
    FILE_LOG_MAX_BYTES: int = 10 * 1024 * 1024
    FILE_LOG_BACKUP_COUNT: int = 5
    FILE_LOG_FORMAT_JSON: bool = True
    FILE_LOG_LEVEL: str = "INFO"

    # Include request ID, path, method, client host, and status code in the file log
    FILE_LOG_INCLUDE_REQUEST_ID: bool = True
    FILE_LOG_INCLUDE_PATH: bool = True
    FILE_LOG_INCLUDE_METHOD: bool = True
    FILE_LOG_INCLUDE_CLIENT_HOST: bool = True
    FILE_LOG_INCLUDE_STATUS_CODE: bool = True


class ConsoleLoggerSettings(BaseSettings):
    CONSOLE_LOG_LEVEL: str = "INFO"
    CONSOLE_LOG_FORMAT_JSON: bool = False

    # Include request ID, path, method, client host, and status code in the console log
    CONSOLE_LOG_INCLUDE_REQUEST_ID: bool = True
    CONSOLE_LOG_INCLUDE_PATH: bool = True
    CONSOLE_LOG_INCLUDE_METHOD: bool = True
    CONSOLE_LOG_INCLUDE_CLIENT_HOST: bool = True
    CONSOLE_LOG_INCLUDE_STATUS_CODE: bool = True


class PostgresSettings(BaseSettings):
    POSTGRES_USER: str 
    POSTGRES_PASSWORD: str 
    POSTGRES_SERVER: str 
    POSTGRES_PORT: int 
    POSTGRES_DB: str 
    POSTGRES_ASYNC_PREFIX: str = "postgresql+asyncpg://"
    POSTGRES_POOL_SIZE: int = 10
    POSTGRES_MAX_OVERFLOW: int = 20
    POSTGRES_POOL_TIMEOUT: int = 30
   

    @computed_field  # type: ignore[prop-decorator]
    @property
    def POSTGRES_URL(self) -> str:
        credentials = f"{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
        location = f"{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        return f"{self.POSTGRES_ASYNC_PREFIX}{credentials}@{location}"


class RedisCacheSettings(BaseSettings):
    REDIS_CACHE_HOST: str
    REDIS_CACHE_PORT: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_CACHE_URL(self) -> str:
        return f"redis://{self.REDIS_CACHE_HOST}:{self.REDIS_CACHE_PORT}"


class ChatStreamSettings(BaseSettings):
    REDIS_FLUSH_EVERY_N: int = 25     # append to Redis every N chunks
    DB_FLUSH_EVERY_M : int = 150      # partial DB write every M chunks
    SSE_RECONNECTION_DELAY_MS: int | float = 30000 # ms. reconnect after 30 seconds if SSE gets disconnected

    # Most of the provider, return thinking blocks while the llm is reasoning or planning
    # but still needed to implement some timeout so our couroutine does not run forever.
    TOTAL_RESPONSE_TIMEOUT_S: int = 600 # 10 min
    ALIVE_INTERVAL_S : int | float = 20.0  # Send a heartbeat if the LLM is stuck 

    # when the client gets disconnected and tries reconnecting, we stream the content by polling on redis
    RECONNECT_POLL_INTERVAL_REDIS_S : int | float = 0.5
    RECONNECT_POLL_INTERVAL_DB_S : int | float = 3

    # unusual token which we will use while producing stream so we know our couroutine is alive
    HEARTBEAT_PLACEHOLDER : str = "<:<alive>:>" 
    INTERRUPTED_PLACEHOLDER : str = "<:<interrupt>:>" 
    FAILED_PLACEHOLDER : str = "<:<failed>:>" 
    DONE_PLACEHOLDER : str = "<:<done>:>" 
    REDIS_TTL_S : int = 3_600   # 1 hour


class EnvironmentOption(str, Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class EnvironmentSettings(BaseSettings):
    ENVIRONMENT: EnvironmentOption = EnvironmentOption.LOCAL


class CORSSettings(BaseSettings):
    CORS_ORIGINS: list[str] = ["*"]
    CORS_METHODS: list[str] = ["*"]
    CORS_HEADERS: list[str] = ["*"]


class Settings(
    AppSettings,
    LLMSettings,
    PostgresSettings,
    RedisCacheSettings,
    ChatStreamSettings,
    EnvironmentSettings,
    CORSSettings,
    FileLoggerSettings,
    ConsoleLoggerSettings,
):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
