from pydantic import BaseModel, model_validator
from typing import Dict, Any, List, Optional, Literal, Union
from typing_extensions import Annotated

class Message(BaseModel):
    role: str
    content: str

class AssistantMessage(Message):
    role: str = "assistant"

class SystemMessage(Message):
    role: str = "system"

class UserMessage(Message):
    role: str = "user"




class BasePropertySchema(BaseModel):
    description: Optional[str] = None

class StringProperty(BasePropertySchema):
    type: Literal["string"]
    enum: Optional[List[str]] = None

class NumberProperty(BasePropertySchema):
    type: Literal["number", "integer"]

class BooleanProperty(BasePropertySchema):
    type: Literal["boolean"]

class NullProperty(BasePropertySchema):
    type: Literal["null"]


# Forward references for recursive types
class ArrayProperty(BasePropertySchema):
    type: Literal["array"]
    items: Optional["PropertySchema"] = None  # recursive

    @model_validator(mode="after")
    def check_items(self):
        if self.items is None:
            raise ValueError("'array' type must define 'items'")
        return self


class ObjectProperty(BasePropertySchema):
    type: Literal["object"]
    properties: Optional[Dict[str, "PropertySchema"]] = None  # recursive
    required: Optional[List[str]] = None
    additionalProperties: Optional[bool] = None

    @model_validator(mode="after")
    def check_required_fields_exist(self):
        if self.required and self.properties:
            missing = [r for r in self.required if r not in self.properties]
            if missing:
                raise ValueError(
                    f"'required' lists fields not in 'properties': {missing}"
                )
        return self


# Union of all property types — discriminated by 'type'
PropertySchema = Annotated[
    Union[
        ObjectProperty,
        ArrayProperty,
        StringProperty,
        NumberProperty,
        BooleanProperty,
        NullProperty,
    ],
    "PropertySchema"
]

# Rebuild models to resolve forward references
ArrayProperty.model_rebuild()
ObjectProperty.model_rebuild()


class FunctionParameters(BaseModel):
    type: Literal["object"]
    properties: Dict[str, PropertySchema]
    required: Optional[List[str]] = None
    additionalProperties: Optional[bool] = None

    @model_validator(mode="after")
    def check_required_fields_exist(self):
        if self.required:
            missing = [r for r in self.required if r not in self.properties]
            if missing:
                raise ValueError(
                    f"'required' lists fields not in 'properties': {missing}"
                )
        return self

class FunctionDef(BaseModel):
    name: str
    description: Optional[str] = None
    parameters: FunctionParameters


class ToolDef(BaseModel):
    type: Literal["function"] = "function"
    function: FunctionDef


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