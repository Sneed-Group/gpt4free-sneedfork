"""
Auto-completion feature for detecting and continuing incomplete AI responses.

This module provides functionality to detect when an AI response is truncated
or incomplete, and automatically send follow-up requests to get the full response.
"""
from __future__ import annotations

import re
import logging
from typing import List, Optional, Callable, Any, Union, AsyncGenerator, Dict

import g4f
from g4f.typing import Messages, AsyncResult
from g4f.errors import ProviderNotFoundError
from g4f.Provider import BaseRetryProvider

logger = logging.getLogger(__name__)

# Common patterns that indicate an incomplete response
INCOMPLETE_PATTERNS = [
    r'(?<!\w)(?<!\.)\.{2,}$',  # Ends with multiple dots (ellipsis)
    r'(?<!\w),\s*$',           # Ends with a comma followed by optional whitespace
    r'(?<!\w);$',              # Ends with a semicolon
    r'\([^\)]*$',              # Contains an opening parenthesis with no matching closing parenthesis
    r'\[[^\]]*$',              # Contains an opening bracket with no matching closing bracket
    r'\{[^\}]*$',              # Contains an opening brace with no matching closing brace
    r'"[^"]*$',                # Contains an opening double quote with no matching closing quote
    r"'[^']*$",                # Contains an opening single quote with no matching closing quote
    r'(?<!\w)and\s*$',         # Ends with "and" followed by optional whitespace
    r'(?<!\w)or\s*$',          # Ends with "or" followed by optional whitespace
    r'(?<!\w)but\s*$',         # Ends with "but" followed by optional whitespace
    r'(?<!\w)so\s*$',          # Ends with "so" followed by optional whitespace
    r'(?<!\w)because\s*$',     # Ends with "because" followed by optional whitespace
    r'(?<!\w)then\s*$',        # Ends with "then" followed by optional whitespace
    r'(?<!\w)that\s*$',        # Ends with "that" followed by optional whitespace
    r'(?<!\w)which\s*$',       # Ends with "which" followed by optional whitespace
    r'(?<!\w)additionally\s*$',# Ends with "additionally" followed by optional whitespace
    r'(?<!\w)for\s+example\s*$',  # Ends with "for example" followed by optional whitespace
    r'(?<!\w)such\s+as\s*$',      # Ends with "such as" followed by optional whitespace
    r'(?<!\w)including\s*$',       # Ends with "including" followed by optional whitespace
    r'^\s*\d+\.\s+[^\n]*$',    # Numbered list item without a following item
    r'^\s*-\s+[^\n]*$',        # Bullet point without a following item
]

MAX_CONTINUATION_ATTEMPTS = 3
DEFAULT_COMPLETION_MODEL = "claude-3.7-sonnet"

def is_balanced(text: str, open_char: str, close_char: str) -> bool:
    """Check if opening/closing characters (like brackets) are balanced."""
    count = 0
    for char in text:
        if char == open_char:
            count += 1
        elif char == close_char:
            count -= 1
            if count < 0:
                return False
    return count == 0

def is_code_block_complete(text: str) -> bool:
    """Check if all code blocks are properly closed."""
    pattern = r'```[\w]*\n[\s\S]*?```'
    matches = re.findall(pattern, text)
    
    # Count the number of code block openings and closings
    open_blocks = len(re.findall(r'```[\w]*\n', text))
    close_blocks = len(re.findall(r'```$', text, re.MULTILINE))
    
    return open_blocks == close_blocks

def is_response_incomplete(text: str) -> bool:
    """
    Detect if a response appears to be incomplete.
    
    Args:
        text: The text to analyze
        
    Returns:
        True if the response appears incomplete, False otherwise
    """
    # Check for basic patterns that suggest an incomplete response
    for pattern in INCOMPLETE_PATTERNS:
        if re.search(pattern, text):
            return True

    # Check for unbalanced parentheses, brackets, braces, etc.
    if not is_balanced(text, '(', ')'):
        return True
    if not is_balanced(text, '[', ']'):
        return True
    if not is_balanced(text, '{', '}'):
        return True
    
    # Check for incomplete code blocks
    if not is_code_block_complete(text):
        return True
    
    # Check for sentences that end abruptly or cut off
    sentences = re.split(r'(?<=[.!?])\s+', text)
    if sentences and len(sentences[-1]) > 5 and not re.search(r'[.!?]$', sentences[-1]):
        return True
    
    return False

async def get_completion_check(text: str, model: str = DEFAULT_COMPLETION_MODEL) -> bool:
    """
    Use an LLM to determine if a response is complete.
    
    Args:
        text: The text to analyze
        model: The model to use for analysis
        
    Returns:
        True if the response is complete, False if it's incomplete
    """
    try:
        messages = [
            {
                "role": "system", 
                "content": "You are an AI completeness detector. Your task is to determine if the provided text appears to be a complete response or if it seems to be cut off mid-response. Respond with ONLY 'COMPLETE' or 'INCOMPLETE'."
            },
            {
                "role": "user", 
                "content": f"Analyze the following text and determine if it's a complete response or if it appears to be cut off:\n\n{text}"
            }
        ]
        
        response = await g4f.ChatCompletion.create_async(
            model=model,
            messages=messages,
            stream=False
        )
        
        # Look for definitive markers in the response
        if "INCOMPLETE" in response.upper():
            return False
        elif "COMPLETE" in response.upper():
            return True
        else:
            # Default to heuristic check if the LLM response is unclear
            return not is_response_incomplete(text)
    except Exception as e:
        logger.warning(f"Error using LLM to check completion status: {e}")
        # Fall back to heuristic check if LLM check fails
        return not is_response_incomplete(text)

async def auto_continue_response(
    model: str,
    messages: Messages,
    provider: Any = None,
    completion_model: str = DEFAULT_COMPLETION_MODEL,
    max_attempts: int = MAX_CONTINUATION_ATTEMPTS,
    **kwargs
) -> Union[str, AsyncResult]:
    """
    Process a response and automatically continue it if it appears incomplete.
    
    Args:
        model: The model to use for the initial and continuation responses
        messages: The conversation messages
        provider: The provider to use
        completion_model: The model to use for checking completion
        max_attempts: Maximum number of continuation attempts
        **kwargs: Additional arguments to pass to the create_async function
        
    Returns:
        The complete response
    """
    is_streaming = kwargs.get('stream', False)
    full_response = ""
    
    # Initial request
    try:
        response = await g4f.ChatCompletion.create_async(
            model=model,
            messages=messages,
            provider=provider,
            **kwargs
        )
    except Exception as e:
        logger.error(f"Error during initial request: {e}")
        # Try to get an alternative provider if there was an error
        try:
            model_obj = None
            for model_name, model_obj in g4f.models.ModelUtils.convert.items():
                if model_name == model:
                    break
            
            if model_obj and model_obj.best_provider and model_obj.best_provider != provider:
                logger.info(f"Trying alternative provider for model {model}")
                response = await g4f.ChatCompletion.create_async(
                    model=model,
                    messages=messages,
                    provider=model_obj.best_provider,
                    **kwargs
                )
                # Update provider for future continuation attempts
                provider = model_obj.best_provider
            else:
                # Re-raise if we couldn't find an alternative
                raise
        except Exception:
            # If alternative also fails, re-raise the original error
            raise e
    
    # Handle streaming response differently
    if is_streaming:
        return _handle_streaming_response(
            response, 
            model, 
            messages, 
            provider, 
            completion_model,
            max_attempts,
            **kwargs
        )
    
    # For non-streaming response
    full_response = response
    attempts = 0
    
    # Continue requesting more content if needed
    while attempts < max_attempts:
        # Check if response is complete
        is_complete = await get_completion_check(full_response, completion_model)
        if is_complete:
            break
            
        logger.info(f"Detected incomplete response. Attempting continuation ({attempts+1}/{max_attempts})")
        
        # Create continuation messages
        continuation_messages = messages.copy()
        continuation_messages.append({"role": "assistant", "content": full_response})
        continuation_messages.append({"role": "user", "content": "Continue from where you left off."})
        
        try:
            # Get continuation
            continuation = await g4f.ChatCompletion.create_async(
                model=model,
                messages=continuation_messages,
                provider=provider,
                stream=False,
                **{k: v for k, v in kwargs.items() if k != 'stream'}
            )
            
            # Append continuation to full response
            full_response += "\n" + continuation
            attempts += 1
        except Exception as e:
            logger.error(f"Error during continuation attempt with provider {provider.__name__ if hasattr(provider, '__name__') else type(provider).__name__}: {e}")
            
            # Try with a different provider
            try:
                model_obj = None
                for model_name, model_obj in g4f.models.ModelUtils.convert.items():
                    if model_name == model:
                        break
                
                if model_obj and model_obj.best_provider and isinstance(model_obj.best_provider, g4f.Provider.BaseRetryProvider):
                    # Get a list of providers from the retry provider
                    for alt_provider in model_obj.best_provider.providers:
                        # Skip the provider that just failed
                        if alt_provider == provider:
                            continue
                        
                        logger.info(f"Trying alternative provider {alt_provider.__name__ if hasattr(alt_provider, '__name__') else type(alt_provider).__name__} for continuation")
                        try:
                            continuation = await g4f.ChatCompletion.create_async(
                                model=model,
                                messages=continuation_messages,
                                provider=alt_provider,
                                stream=False,
                                **{k: v for k, v in kwargs.items() if k != 'stream'}
                            )
                            # Append continuation to full response
                            full_response += "\n" + continuation
                            # Update provider for future continuation attempts
                            provider = alt_provider
                            break
                        except Exception as alt_e:
                            logger.error(f"Alternative provider also failed: {alt_e}")
                            continue
                    
                attempts += 1
            except Exception:
                # If all alternatives fail, count this as a failed attempt
                attempts += 1
    
    return full_response

async def _handle_streaming_response(
    response: AsyncResult,
    model: str,
    messages: Messages,
    provider: Any,
    completion_model: str,
    max_attempts: int,
    **kwargs
) -> AsyncGenerator[str, None]:
    """
    Handle streaming response with auto-continuation.
    
    This is a more complex case as we need to buffer the stream to check completeness,
    then potentially request more content and continue streaming.
    """
    full_response = ""
    attempts = 0
    
    # Stream the initial response
    try:
        async for chunk in response:
            full_response += chunk
            yield chunk
            
        # Continue streaming if response is incomplete
        while attempts < max_attempts:
            # Check if the response is complete
            is_complete = await get_completion_check(full_response, completion_model)
            if is_complete:
                break
                
            logger.info(f"Detected incomplete streamed response. Attempting continuation ({attempts+1}/{max_attempts})")
            
            # Create continuation messages
            continuation_messages = messages.copy()
            continuation_messages.append({"role": "assistant", "content": full_response})
            continuation_messages.append({"role": "user", "content": "Continue from where you left off."})
            
            try:
                # Get continuation (non-streaming for simplicity)
                continuation = await g4f.ChatCompletion.create_async(
                    model=model,
                    messages=continuation_messages,
                    provider=provider,
                    stream=False,
                    **{k: v for k, v in kwargs.items() if k != 'stream'}
                )
                
                # Append continuation to full response and yield
                full_response += "\n" + continuation
                yield "\n" + continuation
                attempts += 1
            except Exception as e:
                logger.error(f"Error during streaming continuation attempt with provider {provider.__name__ if hasattr(provider, '__name__') else type(provider).__name__}: {e}")
                
                # Try with a different provider
                try:
                    model_obj = None
                    for model_name, model_obj in g4f.models.ModelUtils.convert.items():
                        if model_name == model:
                            break
                    
                    if model_obj and model_obj.best_provider and isinstance(model_obj.best_provider, g4f.Provider.BaseRetryProvider):
                        # Get a list of providers from the retry provider
                        for alt_provider in model_obj.best_provider.providers:
                            # Skip the provider that just failed
                            if alt_provider == provider:
                                continue
                            
                            logger.info(f"Trying alternative provider {alt_provider.__name__ if hasattr(alt_provider, '__name__') else type(alt_provider).__name__} for streaming continuation")
                            try:
                                continuation = await g4f.ChatCompletion.create_async(
                                    model=model,
                                    messages=continuation_messages,
                                    provider=alt_provider,
                                    stream=False,
                                    **{k: v for k, v in kwargs.items() if k != 'stream'}
                                )
                                # Append continuation to full response
                                full_response += "\n" + continuation
                                yield "\n" + continuation
                                # Update provider for future continuation attempts
                                provider = alt_provider
                                break
                            except Exception as alt_e:
                                logger.error(f"Alternative streaming provider also failed: {alt_e}")
                                continue
                        
                    attempts += 1
                except Exception:
                    # If all alternatives fail, count this as a failed attempt
                    attempts += 1
    except Exception as e:
        # If streaming fails, log error and yield nothing more
        logger.error(f"Error during streaming: {e}")
        # We don't raise here as we've already yielded some content 