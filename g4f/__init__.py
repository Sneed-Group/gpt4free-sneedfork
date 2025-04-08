from __future__ import annotations

import os
import logging
from typing import Union, Optional, Coroutine, Dict, Any

from . import debug, version
from .models import Model, ModelUtils
from .client import Client, AsyncClient
from .typing import Messages, CreateResult, AsyncResult, ImageType
from .errors import StreamNotSupportedError
from .cookies import get_cookies, set_cookies
from .providers.types import ProviderType
from .providers.helper import concat_chunks, async_concat_chunks
from .client.service import get_model_and_provider
from .completions import auto_continue_response

#Configure "g4f" logger
logger = logging.getLogger(__name__)
log_handler = logging.StreamHandler()
log_handler.setFormatter(logging.Formatter(logging.BASIC_FORMAT))
logger.addHandler(log_handler)

logger.setLevel(logging.ERROR)

class ChatCompletion:
    @staticmethod
    def create(model    : Union[Model, str],
               messages : Messages,
               provider : Union[ProviderType, str, None] = None,
               stream   : bool = False,
               image    : ImageType = None,
               image_name: Optional[str] = None,
               ignore_working: bool = False,
               ignore_stream: bool = False,
               auto_continue: bool = True,
               completion_model: Optional[str] = None,
               continuation_attempts: Optional[int] = None,
               **kwargs) -> Union[CreateResult, str]:
        if image is not None:
            kwargs["media"] = [(image, image_name)]
        elif "images" in kwargs:
            kwargs["media"] = kwargs.pop("images")
        model, provider = get_model_and_provider(
            model, provider, stream,
            ignore_working,
            ignore_stream,
            has_images="media" in kwargs,
        )
        if "proxy" not in kwargs:
            proxy = os.environ.get("G4F_PROXY")
            if proxy:
                kwargs["proxy"] = proxy
        if ignore_stream:
            kwargs["ignore_stream"] = True

        # Skip auto-continue for streaming responses as that's handled separately
        if auto_continue and not stream and not ignore_stream:
            import asyncio
            # Run in synchronous context
            try:
                return asyncio.run(auto_continue_response(
                    model=model,
                    messages=messages,
                    provider=provider,
                    completion_model=completion_model,
                    max_attempts=continuation_attempts or 3,
                    stream=stream,
                    **kwargs
                ))
            except Exception as e:
                # If auto-continue fails, try to find an alternative provider from the model's list
                model_obj = None
                if isinstance(model, str):
                    for model_name, candidate_model in ModelUtils.convert.items():
                        if model_name == model:
                            model_obj = candidate_model
                            break
                else:
                    model_obj = model
                
                if model_obj and model_obj.best_provider:
                    logger.warning(f"Auto-continue failed with provider {provider.__name__ if hasattr(provider, '__name__') else type(provider).__name__}. Trying alternative providers.")
                    # Try with the model's best_provider directly
                    return asyncio.run(auto_continue_response(
                        model=model if isinstance(model, str) else model.name,
                        messages=messages,
                        provider=model_obj.best_provider,
                        completion_model=completion_model,
                        max_attempts=continuation_attempts or 3,
                        stream=stream,
                        **kwargs
                    ))
                else:
                    # If we can't find alternatives, re-raise the original error
                    raise e
        else:
            result = provider.get_create_function()(model, messages, stream=stream, **kwargs)
            return result if stream or ignore_stream else concat_chunks(result)

    @staticmethod
    def create_async(model    : Union[Model, str],
                     messages : Messages,
                     provider : Union[ProviderType, str, None] = None,
                     stream   : bool = False,
                     image    : ImageType = None,
                     image_name: Optional[str] = None,
                     ignore_stream: bool = False,
                     ignore_working: bool = False,
                     auto_continue: bool = True,
                     completion_model: Optional[str] = None,
                     continuation_attempts: Optional[int] = None,
                     **kwargs) -> Union[AsyncResult, Coroutine[str]]:
        if image is not None:
            kwargs["media"] = [(image, image_name)]
        elif "images" in kwargs:
            kwargs["media"] = kwargs.pop("images")
        model, provider = get_model_and_provider(model, provider, False, ignore_working, has_images="media" in kwargs)
        if "proxy" not in kwargs:
            proxy = os.environ.get("G4F_PROXY")
            if proxy:
                kwargs["proxy"] = proxy
        if ignore_stream:
            kwargs["ignore_stream"] = True

        # Use auto-continue response if enabled
        if auto_continue:
            try:
                return auto_continue_response(
                    model=model,
                    messages=messages,
                    provider=provider,
                    completion_model=completion_model,
                    max_attempts=continuation_attempts or 3,
                    stream=stream,
                    **kwargs
                )
            except Exception as e:
                # If auto-continue fails, try to find an alternative provider from the model's list
                model_obj = None
                if isinstance(model, str):
                    for model_name, candidate_model in ModelUtils.convert.items():
                        if model_name == model:
                            model_obj = candidate_model
                            break
                else:
                    model_obj = model
                
                if model_obj and model_obj.best_provider:
                    logger.warning(f"Auto-continue failed with provider {provider.__name__ if hasattr(provider, '__name__') else type(provider).__name__}. Trying alternative providers.")
                    # Try with the model's best_provider directly
                    return auto_continue_response(
                        model=model if isinstance(model, str) else model.name,
                        messages=messages,
                        provider=model_obj.best_provider,
                        completion_model=completion_model,
                        max_attempts=continuation_attempts or 3,
                        stream=stream,
                        **kwargs
                    )
                else:
                    # If we can't find alternatives, re-raise the original error
                    raise e
        else:
            # Use standard flow without auto-continue
            result = provider.get_async_create_function()(model, messages, stream=stream, **kwargs)
            
            if not stream and not ignore_stream:
                if hasattr(result, "__aiter__"):
                    result = async_concat_chunks(result)
                    
            return result