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
from g4f.providers.retry_provider import IterListProvider

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
    # Claude-specific pattern for mid-sentence truncation
    r'(?<!\w)(?<!\.)$',        # Response ends mid-sentence without punctuation
    r'if\s+you\s+have\s+any.*?$',  # Ends with partial closing statement
    r'hope\s+this\s+helps.*?$',    # Ends with partial closing statement
    r'(?<!\w)(to|with|by|in|on|at|from|as|for|about|through|like|into)\s+$', # Ends with preposition
    r'(?<!\w)(is|am|are|was|were|be|been|being)\s+$',  # Ends with form of "to be"
    r'(?<!\w)(a|an|the)\s+$',  # Ends with article
    r'(?<!\w)(if|unless|while|when|whenever|wherever|because|since|as|although|though|even though|whereas|whether|rather|until)\s+$',  # Ends with subordinating conjunction
    r'(?<!\w)(can|could|may|might|must|shall|should|will|would)\s+$',  # Ends with modal verb
    r'(?<!\w)(let me know|please let me|do you have|would you like|if you need)\s+$', # Ends with transitional phrase
    r'(?<!\w)(by implementing|by using|next steps)\s+$', # Ends with instructional transition
    r'(?<!\w)(I(\s+would)?(\s+recommend)?|You(\s+should)?|We(\s+can)?)\s+$', # Ends with recommendation start
]

MAX_CONTINUATION_ATTEMPTS = 3
# Fallback completion model if the current model can't be used
DEFAULT_COMPLETION_MODEL = "claude-3.7-sonnet"

def get_provider_specific_model_name(model: str, provider: Any) -> str:
    """
    Convert a standard model name to the provider-specific model name.
    
    Some providers use different names for the same models. This function
    ensures we use the correct model name for each provider.
    
    Args:
        model: The standard model name
        provider: The provider to use
        
    Returns:
        The provider-specific model name
    """
    # No provider specified, return the original model name
    if provider is None:
        return model
    
    # For Blackbox provider, check model aliases
    if hasattr(provider, 'model_aliases') and model.lower() in {k.lower() for k in provider.model_aliases}:
        # Find the case-insensitive match and return the properly aliased model name
        for k, v in provider.model_aliases.items():
            if k.lower() == model.lower():
                logger.info(f"Converting model name '{model}' to provider-specific name '{v}' for {provider.__name__ if hasattr(provider, '__name__') else type(provider).__name__}")
                return v
    
    return model

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
            logger.info(f"Detected incomplete pattern: {pattern}")
            return True

    # Check for unbalanced parentheses, brackets, braces, etc.
    if not is_balanced(text, '(', ')'):
        logger.info("Detected unbalanced parentheses")
        return True
    if not is_balanced(text, '[', ']'):
        logger.info("Detected unbalanced brackets")
        return True
    if not is_balanced(text, '{', '}'):
        logger.info("Detected unbalanced braces")
        return True
    
    # Check for incomplete code blocks
    if not is_code_block_complete(text):
        logger.info("Detected incomplete code blocks")
        return True
    
    # Check for sentences that end abruptly or cut off
    sentences = re.split(r'(?<=[.!?])\s+', text)
    if sentences and len(sentences[-1]) > 5 and not re.search(r'[.!?]$', sentences[-1]):
        logger.info("Detected sentence ending abruptly")
        return True
    
    # Additional check for responses that seem too short to be complete
    word_count = len(text.split())
    
    # If the response is very short and doesn't end with punctuation, it's likely incomplete
    if word_count < 50 and not re.search(r'[.!?:]$', text.strip()):
        logger.info("Detected short response without proper ending punctuation")
        return True
    
    # Check for ending with a non-terminal conjunction or preposition
    if re.search(r'(?<!\w)(in|on|at|to|with|from|as|by|for|about|like|through)\s*$', text):
        logger.info("Detected response ending with non-terminal preposition")
        return True
    
    return False

async def get_completion_check(text: str, model: str) -> bool:
    """
    Use an LLM to determine if a response is complete.
    
    Args:
        text: The text to analyze
        model: The model to use for analysis
        
    Returns:
        True if the response is complete, False if it's incomplete
    """
    # First check with heuristics for efficiency
    if is_response_incomplete(text):
        return False
        
    try:
        messages = [
            {
                "role": "system", 
                "content": "You are an AI completeness detector. Your task is to determine if the provided text appears to be a complete response or if it seems to be cut off mid-response or incomplete in any way. Pay close attention to whether the response finishes its thoughts and provides a proper conclusion. Respond with ONLY 'COMPLETE' or 'INCOMPLETE'."
            },
            {
                "role": "user", 
                "content": f"Analyze the following text and determine if it's a complete response or if it appears to be cut off or incomplete in any way:\n\n{text}"
            }
        ]
        
        response = await g4f.ChatCompletion.create_async(
            model=model,
            messages=messages,
            stream=False
        )
        
        # Look for definitive markers in the response
        if "INCOMPLETE" in response.upper():
            logger.info(f"LLM determined response is incomplete")
            return False
        elif "COMPLETE" in response.upper():
            logger.info(f"LLM determined response is complete")
            return True
        else:
            # Default to heuristic check if the LLM response is unclear
            logger.info(f"LLM response unclear, using heuristic check")
            return not is_response_incomplete(text)
    except Exception as e:
        logger.warning(f"Error using LLM to check completion status: {e}")
        # Fall back to heuristic check if LLM check fails
        return not is_response_incomplete(text)

def get_continuation_prompt(model: str) -> str:
    """
    Get a model-specific continuation prompt.
    
    Different models respond better to different continuation prompts.
    This function returns an appropriate prompt for the given model.
    
    Args:
        model: The model name
        
    Returns:
        A continuation prompt suitable for the model
    """
    # Claude-specific prompts
    if 'claude' in model.lower():
        return "Please continue your response exactly from where you left off, completing any incomplete sentences or thoughts. Do not repeat information you've already provided and do not summarize. Just continue as if you were never interrupted."
    
    # GPT-specific prompts
    elif 'gpt' in model.lower():
        return "Continue from where you left off. Do not repeat anything you've already said."
    
    # Default prompt for other models
    else:
        return "Continue from where you left off."

async def auto_continue_response(
    model: str,
    messages: Messages,
    provider: Any = None,
    completion_model: Optional[str] = None,
    max_attempts: int = MAX_CONTINUATION_ATTEMPTS,
    **kwargs
) -> Union[str, AsyncResult]:
    """
    Process a response and automatically continue it if it appears incomplete.
    
    Args:
        model: The model to use for the initial and continuation responses
        messages: The conversation messages
        provider: The provider to use
        completion_model: The model to use for checking completion (defaults to current model if None)
        max_attempts: Maximum number of continuation attempts
        **kwargs: Additional arguments to pass to the create_async function
        
    Returns:
        The complete response
    """
    is_streaming = kwargs.get('stream', False)
    full_response = ""
    
    # Use the current model for completion check if not specified
    if completion_model is None:
        completion_model = model
    
    # Get the provider-specific model name
    provider_model = get_provider_specific_model_name(model, provider)
    logger.info(f"Using provider {provider.__name__ if hasattr(provider, '__name__') else type(provider).__name__} with model {provider_model}")
    
    # Initial request
    try:
        response = await g4f.ChatCompletion.create_async(
            model=provider_model,
            messages=messages,
            provider=provider,
            **kwargs
        )
    except Exception as e:
        logger.error(f"Error during initial request with provider {provider.__name__ if hasattr(provider, '__name__') else type(provider).__name__}: {e}")
        # Try to get an alternative provider if there was an error
        try:
            # Get the model object to find alternative providers
            model_obj = None
            for model_name, model_obj in g4f.models.ModelUtils.convert.items():
                if model_name.lower() == model.lower():
                    break
            
            # If we found a model object and it has alternative providers
            if model_obj and model_obj.best_provider:
                if model_obj.best_provider != provider:
                    # Try the best provider first if it's not the one that failed
                    logger.info(f"Trying alternative provider {model_obj.best_provider.__name__ if hasattr(model_obj.best_provider, '__name__') else type(model_obj.best_provider).__name__} for model {model}")
                    try:
                        response = await g4f.ChatCompletion.create_async(
                            model=get_provider_specific_model_name(model, model_obj.best_provider),
                            messages=messages,
                            provider=model_obj.best_provider,
                            **kwargs
                        )
                        # Update provider for future continuation attempts
                        provider = model_obj.best_provider
                    except Exception as alt_e:
                        logger.error(f"Alternative provider also failed: {alt_e}")
                        # If best provider also fails, try other providers if available
                        if isinstance(model_obj.best_provider, IterListProvider):
                            for alt_provider in model_obj.best_provider.providers:
                                # Skip providers we've already tried
                                if alt_provider == provider:
                                    continue
                                
                                logger.info(f"Trying provider {alt_provider.__name__ if hasattr(alt_provider, '__name__') else type(alt_provider).__name__} for model {model}")
                                try:
                                    response = await g4f.ChatCompletion.create_async(
                                        model=get_provider_specific_model_name(model, alt_provider),
                                        messages=messages,
                                        provider=alt_provider,
                                        **kwargs
                                    )
                                    # Update provider for future continuation attempts
                                    provider = alt_provider
                                    break
                                except Exception as p_e:
                                    logger.error(f"Provider {alt_provider.__name__ if hasattr(alt_provider, '__name__') else type(alt_provider).__name__} also failed: {p_e}")
                                    continue
                            else:
                                # If we've tried all providers and none worked, re-raise the original error
                                raise e
                else:
                    # If the best provider is the one that failed, try other providers if available
                    if isinstance(model_obj.best_provider, IterListProvider):
                        for alt_provider in model_obj.best_provider.providers:
                            # Skip providers we've already tried
                            if alt_provider == provider:
                                continue
                            
                            logger.info(f"Trying provider {alt_provider.__name__ if hasattr(alt_provider, '__name__') else type(alt_provider).__name__} for model {model}")
                            try:
                                response = await g4f.ChatCompletion.create_async(
                                    model=get_provider_specific_model_name(model, alt_provider),
                                    messages=messages,
                                    provider=alt_provider,
                                    **kwargs
                                )
                                # Update provider for future continuation attempts
                                provider = alt_provider
                                break
                            except Exception as p_e:
                                logger.error(f"Provider {alt_provider.__name__ if hasattr(alt_provider, '__name__') else type(alt_provider).__name__} also failed: {p_e}")
                                continue
                        else:
                            # If we've tried all providers and none worked, re-raise the original error
                            raise e
            else:
                # Re-raise if we couldn't find an alternative
                raise e
        except Exception:
            # If all alternatives fail, re-raise the original error
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
    logger.info(f"Received initial response of length {len(full_response)} characters")
    attempts = 0
    
    # Force check and continue requesting more content if needed
    # Always check at least once, even for seemingly complete responses
    is_complete = False
    while (not is_complete and attempts < max_attempts):
        # Check if response is complete
        is_complete = await get_completion_check(full_response, completion_model)
        if is_complete:
            logger.info("Response determined to be complete")
            break
            
        logger.info(f"Detected incomplete response. Attempting continuation ({attempts+1}/{max_attempts})")
        
        # Get the appropriate continuation prompt for this model
        continuation_prompt = get_continuation_prompt(model)
        logger.info(f"Using model-specific prompt for {model}: {continuation_prompt[:50]}...")
        
        # Create continuation messages
        continuation_messages = messages.copy()
        continuation_messages.append({"role": "assistant", "content": full_response})
        continuation_messages.append({"role": "user", "content": continuation_prompt})
        
        try:
            # Get continuation
            logger.info(f"Requesting continuation from provider {provider.__name__ if hasattr(provider, '__name__') else type(provider).__name__}")
            continuation = await g4f.ChatCompletion.create_async(
                model=get_provider_specific_model_name(model, provider),
                messages=continuation_messages,
                provider=provider,
                stream=False,
                **{k: v for k, v in kwargs.items() if k != 'stream'}
            )
            
            # Append continuation to full response
            logger.info(f"Received continuation of length {len(continuation)} characters")
            full_response += "\n" + continuation
            attempts += 1
        except Exception as e:
            logger.error(f"Error during continuation attempt with provider {provider.__name__ if hasattr(provider, '__name__') else type(provider).__name__}: {e}")
            
            # Try with a different provider
            try:
                # Get model object to find alternative providers
                model_obj = None
                for model_name, model_obj in g4f.models.ModelUtils.convert.items():
                    if model_name.lower() == model.lower():
                        break
                
                alternative_provider_found = False
                # Check if we have a model object and if it has a best provider
                if model_obj and model_obj.best_provider:
                    # If the best provider is a list of providers (IterListProvider)
                    if isinstance(model_obj.best_provider, IterListProvider):
                        # Get a list of providers from the retry provider
                        for alt_provider in model_obj.best_provider.providers:
                            # Skip the provider that just failed
                            if alt_provider == provider:
                                continue
                            
                            logger.info(f"Trying alternative provider {alt_provider.__name__ if hasattr(alt_provider, '__name__') else type(alt_provider).__name__} for continuation")
                            try:
                                continuation = await g4f.ChatCompletion.create_async(
                                    model=get_provider_specific_model_name(model, alt_provider),
                                    messages=continuation_messages,
                                    provider=alt_provider,
                                    stream=False,
                                    **{k: v for k, v in kwargs.items() if k != 'stream'}
                                )
                                # Append continuation to full response
                                logger.info(f"Received continuation from alternative provider of length {len(continuation)} characters")
                                full_response += "\n" + continuation
                                # Update provider for future continuation attempts
                                provider = alt_provider
                                alternative_provider_found = True
                                break
                            except Exception as alt_e:
                                logger.error(f"Alternative provider also failed: {alt_e}")
                                continue
                    # If the best provider is a single provider
                    elif model_obj.best_provider != provider:
                        # Try the best provider if it's not the one that failed
                        logger.info(f"Trying alternative provider {model_obj.best_provider.__name__ if hasattr(model_obj.best_provider, '__name__') else type(model_obj.best_provider).__name__} for continuation")
                        try:
                            continuation = await g4f.ChatCompletion.create_async(
                                model=get_provider_specific_model_name(model, model_obj.best_provider),
                                messages=continuation_messages,
                                provider=model_obj.best_provider,
                                stream=False,
                                **{k: v for k, v in kwargs.items() if k != 'stream'}
                            )
                            # Append continuation to full response
                            logger.info(f"Received continuation from best provider of length {len(continuation)} characters")
                            full_response += "\n" + continuation
                            # Update provider for future continuation attempts
                            provider = model_obj.best_provider
                            alternative_provider_found = True
                        except Exception as alt_e:
                            logger.error(f"Alternative provider also failed: {alt_e}")
                
                # If no alternative provider was found or all failed, count this as a failed attempt
                if not alternative_provider_found:
                    logger.warning("No alternative provider was found or all failed")
                    attempts += 1
                    
            except Exception:
                # If all alternatives fail, count this as a failed attempt
                logger.warning("Exception while trying to find alternative providers")
                attempts += 1
    
    # Final check if we couldn't get a complete response after maximum attempts
    if not is_complete:
        logger.warning(f"Could not get a complete response after {max_attempts} attempts. Returning best effort.")

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
    
    Args:
        response: The initial streaming response
        model: The model to use for the initial and continuation responses
        messages: The conversation messages
        provider: The provider to use
        completion_model: The model to use for checking completion
        max_attempts: Maximum number of continuation attempts
        **kwargs: Additional arguments to pass to the create_async function
        
    Returns:
        AsyncGenerator yielding response chunks
    """
    full_response = ""
    attempts = 0
    
    # Stream the initial response, collecting all chunks
    try:
        async for chunk in response:
            full_response += chunk
            # We stream the chunks directly since we'll handle completeness
            # after the entire initial response is received
            yield chunk
        
        # After getting the full initial response, check for completeness and continue if needed
        # Always check at least once, even for seemingly complete responses
        is_complete = False
        while (not is_complete and attempts < max_attempts):
            # Check if the response is complete
            is_complete = await get_completion_check(full_response, completion_model)
            if is_complete:
                logger.info("Streaming response determined to be complete")
                break
                
            logger.info(f"Detected incomplete streamed response. Attempting continuation ({attempts+1}/{max_attempts})")
            
            # Get the appropriate continuation prompt for this model
            continuation_prompt = get_continuation_prompt(model)
            logger.info(f"Using model-specific prompt for {model}: {continuation_prompt[:50]}...")
            
            # Create continuation messages
            continuation_messages = messages.copy()
            continuation_messages.append({"role": "assistant", "content": full_response})
            continuation_messages.append({"role": "user", "content": continuation_prompt})
            
            try:
                # Get continuation (non-streaming for simplicity)
                logger.info(f"Requesting continuation from provider {provider.__name__ if hasattr(provider, '__name__') else type(provider).__name__}")
                continuation = await g4f.ChatCompletion.create_async(
                    model=get_provider_specific_model_name(model, provider),
                    messages=continuation_messages,
                    provider=provider,
                    stream=False,
                    **{k: v for k, v in kwargs.items() if k != 'stream'}
                )
                
                # Append continuation to full response and yield
                logger.info(f"Received continuation of length {len(continuation)} characters")
                full_response += "\n" + continuation
                yield "\n" + continuation
                attempts += 1
            except Exception as e:
                logger.error(f"Error during streaming continuation attempt with provider {provider.__name__ if hasattr(provider, '__name__') else type(provider).__name__}: {e}")
                
                # Try with a different provider
                try:
                    # Get model object to find alternative providers
                    model_obj = None
                    for model_name, model_obj in g4f.models.ModelUtils.convert.items():
                        if model_name.lower() == model.lower():
                            break
                    
                    alternative_provider_found = False
                    # Check if we have a model object and if it has a best provider
                    if model_obj and model_obj.best_provider:
                        # If the best provider is a list of providers (IterListProvider)
                        if isinstance(model_obj.best_provider, IterListProvider):
                            # Get a list of providers from the retry provider
                            for alt_provider in model_obj.best_provider.providers:
                                # Skip the provider that just failed
                                if alt_provider == provider:
                                    continue
                                
                                logger.info(f"Trying alternative provider {alt_provider.__name__ if hasattr(alt_provider, '__name__') else type(alt_provider).__name__} for streaming continuation")
                                try:
                                    continuation = await g4f.ChatCompletion.create_async(
                                        model=get_provider_specific_model_name(model, alt_provider),
                                        messages=continuation_messages,
                                        provider=alt_provider,
                                        stream=False,
                                        **{k: v for k, v in kwargs.items() if k != 'stream'}
                                    )
                                    # Append continuation to full response
                                    logger.info(f"Received continuation from alternative provider of length {len(continuation)} characters")
                                    full_response += "\n" + continuation
                                    yield "\n" + continuation
                                    # Update provider for future continuation attempts
                                    provider = alt_provider
                                    alternative_provider_found = True
                                    break
                                except Exception as alt_e:
                                    logger.error(f"Alternative streaming provider also failed: {alt_e}")
                                    continue
                        # If the best provider is a single provider
                        elif model_obj.best_provider != provider:
                            # Try the best provider if it's not the one that failed
                            logger.info(f"Trying alternative provider {model_obj.best_provider.__name__ if hasattr(model_obj.best_provider, '__name__') else type(model_obj.best_provider).__name__} for streaming continuation")
                            try:
                                continuation = await g4f.ChatCompletion.create_async(
                                    model=get_provider_specific_model_name(model, model_obj.best_provider),
                                    messages=continuation_messages,
                                    provider=model_obj.best_provider,
                                    stream=False,
                                    **{k: v for k, v in kwargs.items() if k != 'stream'}
                                )
                                # Append continuation to full response and yield
                                logger.info(f"Received continuation from best provider of length {len(continuation)} characters")
                                full_response += "\n" + continuation
                                yield "\n" + continuation
                                # Update provider for future continuation attempts
                                provider = model_obj.best_provider
                                alternative_provider_found = True
                            except Exception as alt_e:
                                logger.error(f"Alternative streaming provider also failed: {alt_e}")
                    
                    # If no alternative provider was found or all failed, count this as a failed attempt
                    if not alternative_provider_found:
                        logger.warning("No alternative provider was found or all failed")
                        attempts += 1
                        
                except Exception:
                    # If all alternatives fail, count this as a failed attempt
                    logger.warning("Exception while trying to find alternative providers")
                    attempts += 1
        
        # Final check if we couldn't get a complete response after maximum attempts
        if not is_complete:
            logger.warning(f"Could not get a complete streaming response after {max_attempts} attempts. Returning best effort.")
    
    except Exception as e:
        # If streaming fails, log error and yield nothing more
        logger.error(f"Error during streaming: {e}")
        # We don't raise here as we've already yielded some content 