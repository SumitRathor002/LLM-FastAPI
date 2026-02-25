
from pydantic import BaseModel

class Message(BaseModel):
    role: str
    content: str

class AssistantMessage(Message):
    role: str = "assistant"

class SystemMessage(Message):
    role: str = "system"

class UserMessage(Message):
    role: str = "user"

# Native to LiteLLM /  OpenAI
# refer: https://docs.litellm.ai/docs/completion/input#input-params-1

# TODO: Need to add validation before an LLM call. 
# class LLMParams(BaseModel):
#     model: str
    
#     messages: List = []
#     functions: Optional[List] = None
#     function_call: Optional[str] = None
#     timeout: Optional[Union[float, int]] = None
#     temperature: Optional[float] = None
#     top_p: Optional[float] = None
#     n: Optional[int] = None
#     stream: Optional[bool] = None
#     stream_options: Optional[dict] = None
#     stop=None
#     max_tokens: Optional[int] = None
#     max_completion_tokens: Optional[int] = None
#     modalities: Optional[List[ChatCompletionModality]] = None
#     prediction: Optional[ChatCompletionPredictionContentParam] = None
#     audio: Optional[ChatCompletionAudioParam] = None
#     presence_penalty: Optional[float] = None
#     frequency_penalty: Optional[float] = None
#     logit_bias: Optional[dict] = None
#     user: Optional[str] = None

#     response_format: Optional[Union[dict, Type[BaseModel]]] = None
#     seed: Optional[int] = None
#     tools: Optional[List] = None
#     tool_choice: Optional[Union[str, dict]] = None
#     parallel_tool_calls: Optional[bool] = None
#     logprobs: Optional[bool] = None
#     top_logprobs: Optional[int] = None
#     reasoning_effort: Optional[
#         Literal["none", "minimal", "low", "medium", "high", "xhigh", "default"]
#     ] = None
#     verbosity: Optional[Literal["low", "medium", "high"]] = None
#     safety_identifier: Optional[str] = None
#     service_tier: Optional[str] = None

#     # set api_base, api_version, api_key
#     base_url: Optional[str] = None
#     api_version: Optional[str] = None
#     api_key: Optional[str] = None
#     model_list: Optional[list] = None
#     extra_headers: Optional[dict] = None

#     # Optional liteLLM function params
#     thinking: Optional[AnthropicThinkingParam] = None
#     web_search_options: Optional[OpenAIWebSearchOptions] = None


# @ TODO: Need to add params and handle them in prompt calls. 
# Not added as we do not know what Providers are we going to use
# class ProviderSpecificParams: