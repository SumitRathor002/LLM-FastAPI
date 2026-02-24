from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from ...core.llm.utils import (
    get_available_models_by_litellm,
    get_available_models_for_us,
    get_available_providers,
    get_model_information,
    get_models_by_specific_provider,
    get_provider_information,
    verify_models_availability,
)


router = APIRouter(prefix="/help", tags=["help"])


@router.get("/available-models")
def available_models(
    check_provider_endpoint: Optional[bool] = Query(None),
    custom_llm_provider: Optional[str] = Query(None),
):
    return get_available_models_for_us(check_provider_endpoint, custom_llm_provider)


@router.get("/verify-model")
def verify_model(model_name: str = Query(..., description='e.g. "openai/gpt-3.5-turbo"')):
    return verify_models_availability(model_name)


@router.get("/litellm-models")
def litellm_models():
    return get_available_models_by_litellm()


@router.get("/provider-models")
def provider_models(provider: str = Query(...)):
    return get_models_by_specific_provider(provider)


@router.get("/providers")
def providers():
    return get_available_providers()


@router.get("/model-info")
def model_info(model: str = Query(..., description='e.g. "gpt-4o" or "openai/gpt-4o"')):
    try:
        return get_model_information(model)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/provider-info")
def provider_info(
    custom_llm_provider: str = Query(...),
    model: Optional[str] = Query(None),
):
    try:
        return get_provider_information(custom_llm_provider, model)
    except (KeyError, IndexError) as e:
        raise HTTPException(status_code=404, detail=str(e))