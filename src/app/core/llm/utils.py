import random
import traceback
from typing import Any, List, Optional
from litellm import (
    acompletion,
    aresponses,
    get_valid_models,
    validate_environment,
    model_list_set,
    models_by_provider,
    get_model_info
)
from litellm.utils import get_provider_info
from .schemas import SystemMessage, ToolDef, UserMessage, Message
from ..config import settings
import structlog
from faker import Faker

fake = Faker()

logger = structlog.get_logger(__name__)


async def completion_call(
    model: str,
    user_prompt: str,
    system_prompt: str | None = None,
    previous_messages: List[Message] | None = None,
    tools: Optional[List[ToolDef]]=None,
    stream: bool = False,
    mock: bool = False,
) -> object | None:
    """
    Make an async LLM completion call via LiteLLM.

    Args:
        model: The model identifier (e.g. "openai/gpt-4o").
        user_prompt: The user-facing prompt to send to the model.
        system_prompt: Optional system-level instruction prepended to the conversation.
        stream: If True, returns a streaming response object.
        mock: If True, substitutes a fake response instead of calling the API.
                      Useful for testing without consuming API credits.

    Returns:
        The LiteLLM response object, or None if an exception occurred.
    """
    try:
        kws = {}
        if mock or settings.MOCK_RESPONSE:
            kws["mock_response"] = get_mock_response() 

        if stream:
            # enables token usage details in last chunk of the streaming response.
            kws.setdefault("stream_options", {})["include_usage"] = True

        # copy previous messages if any
        messages: List[Message] = [*previous_messages]

        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))

        messages.append(UserMessage(content=user_prompt))

        serialized_msg = [msg.model_dump(exclude_none=True) for msg in messages]
        serialized_tools = [tool.model_dump(exclude_none=True) for tool in tools] if tools else None

        # refer for schema
        # https://docs.litellm.ai/docs/#streaming-response-format-openai-format
        # https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events
        response = await acompletion(
            model=model,
            messages=serialized_msg,
            stream=stream,
            tools=serialized_tools,
            **kws,
        )
        logger.debug("LLM response received", response=response)
        return response

    except Exception:
        # No need to import traceback separately — structlog captures it via logger.exception
        logger.exception("An exception occurred during completion call.", model=model)
        return None


# TODO: Define the new responses schema from API better suited for reasoning models

def get_mock_response() -> str:
    """
    Generate a semi-random mock LLM response for testing purposes using the Faker library.
    Constructs a realistic-looking multi-sentence response by combining various
    faker-generated text components so each call produces a unique but coherent-looking reply.

    Returns:
        A mock response string.
    """
    strategies = [
        lambda: f"Based on my analysis, {fake.bs()}. {fake.catch_phrase()}. "
                f"I would recommend the following: {fake.paragraph(nb_sentences=3)}",

        lambda: f"Here's a summary of the findings:\n\n"
                f"{fake.paragraph(nb_sentences=2)}\n\n"
                f"Key takeaway: {fake.bs().capitalize()}. "
                f"Overall, {fake.paragraph(nb_sentences=2)}",

        lambda: f"After careful consideration of your request, {fake.paragraph(nb_sentences=4)} "
                f"In conclusion, {fake.bs()}.",

        lambda: f"Great question. {fake.paragraph(nb_sentences=2)} "
                f"To elaborate further: {fake.paragraph(nb_sentences=3)} "
                f"The core insight here is that {fake.bs()}.",

        lambda: f"There are a few things to consider here:\n\n"
                f"1. {fake.paragraph(nb_sentences=2)}\n"
                f"2. {fake.paragraph(nb_sentences=2)}\n"
                f"3. {fake.paragraph(nb_sentences=2)}\n\n"
                f"My recommendation: {fake.bs().capitalize()}.",

        lambda: f"The data suggests that {fake.bs()}. "
                f"{fake.paragraph(nb_sentences=3)} "
                f"This aligns with the principle that {fake.catch_phrase().lower()}.",
    ]

    return random.choice(strategies)()



# LiteLLM response helpers 
def extract_chunk_text(chunk: Any) -> str | None:
    try:
        return chunk.choices[0].delta.content or ""
    except (AttributeError, IndexError):
        return None


def extract_usage(response: Any) -> dict[str, int | None]:
    usage = getattr(response, "usage", None)
    if not usage:
        return {}
    return {
        "total_tokens": getattr(usage, "total_tokens",      None),
        "input_tokens": getattr(usage, "prompt_tokens",     None),
        "output_tokens": getattr(usage, "completion_tokens", None),
        "reasoning_tokens": getattr(usage, "reasoning_tokens",  None),
    }


def get_available_models_for_us(
    check_provider_endpoint: Optional[bool] = None,
    custom_llm_provider: Optional[str] = None,
) -> list:
    """
    Return models available based on API keys currently set in the environment.

    Args:
        check_provider_endpoint: If True, validates against the provider's live endpoint.
        custom_llm_provider: Restrict results to a specific provider (e.g. "openai").

    Returns:
        A list of available model identifiers.
    """
    return get_valid_models(check_provider_endpoint, custom_llm_provider)


def verify_models_availability(model_name: str) -> dict:
    """
    Validate that the environment is correctly configured for a given model.

    Args:
        model_name: Model identifier in "provider/model" format,
                    e.g. "openai/gpt-3.5-turbo".

    Returns:
        A dict describing which required env vars are present or missing.
    """
    return validate_environment(model_name)


def get_available_models_by_litellm() -> list:
    """
    Return the full list of models that LiteLLM supports.

    This reflects LiteLLM's internal registry and is not filtered by
    which API keys are configured locally.

    Returns:
        A list of all model identifiers known to LiteLLM.
    """
    return list(model_list_set)


def get_models_by_specific_provider(provider: str) -> list:
    """
    Return all models available for a given LLM provider.

    Args:
        provider: Provider name (e.g. "openai", "anthropic", "cohere").

    Returns:
        A list of model identifiers for that provider, or an empty list
        if the provider is not recognized.
    """
    return list(models_by_provider.get(provider, []))


def get_available_providers() -> list: 
    """
    Return the set of all LLM providers registered in LiteLLM.

    Returns:
        A set of provider name strings.
    """
    return list(set(models_by_provider.keys()))


def get_model_information(model: str) -> dict:
    """
    Retrieve metadata for a specific model.

    Args:
        model: Model identifier (e.g. "gpt-4o" or "openai/gpt-4o").

    Returns:
        A dict containing model metadata such as context window,
        pricing, and supported features.
    """
    return get_model_info(model=model)


def get_provider_information(
    custom_llm_provider: str,
    model: Optional[str] = None,
) -> dict:
    """
    Retrieve configuration and capability information for a provider.

    If no model is specified, an arbitrary model from that provider's
    list is used as a representative for the lookup.

    Args:
        custom_llm_provider: Provider name (e.g. "anthropic").
        model: Optional specific model to use for the provider info lookup.
               Defaults to the first model in the provider's model list.

    Returns:
        A dict with provider-level information such as base URL,
        required environment variables, and supported parameters.

    Raises:
        KeyError: If the provider is not found in the models_by_provider registry.
        IndexError: If the provider has no models registered.
    """
    if model is None:
        model = list(models_by_provider[custom_llm_provider])[0]

    return get_provider_info(model, custom_llm_provider)