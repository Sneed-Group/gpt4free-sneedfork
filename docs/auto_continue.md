# Auto-Continue Feature

G4F includes a feature to detect incomplete AI responses and automatically continue them. This is especially useful for providers like Blackbox that might truncate responses if they exceed a specific token limit.

## How It Works

The auto-continue feature works by:

1. Analyzing AI responses to detect signs of incompleteness using both pattern-based heuristics and LLM-based analysis
2. When an incomplete response is detected, automatically sending a follow-up request to continue from where the model left off
3. Combining the fragments into a seamless, complete response for the user

By default, this feature uses Claude 3.7 Sonnet to detect whether a response is complete, but you can configure it to use other models.

## Configuration

### API Configuration

When using the API, you can configure auto-continue through:

1. Command line options when starting the server:
```bash
# Disable auto-continue
python -m g4f api --disable-auto-continue

# Change the model used for completion checking
python -m g4f api --completion-model "gpt-4o"

# Set maximum number of continuation attempts
python -m g4f api --continuation-attempts 5
```

2. Request parameters when calling the API:
```json
{
  "model": "gpt-4o-mini",
  "provider": "Blackbox",
  "auto_continue": true,
  "completion_model": "claude-3.7-sonnet", 
  "continuation_attempts": 3,
  "messages": [
    {"role": "user", "content": "Write a comprehensive analysis of quantum computing..."}
  ]
}
```

### Using in Code

When using G4F directly in your Python code:

```python
import g4f

response = g4f.ChatCompletion.create(
    model="gpt-4o-mini",
    provider="Blackbox",
    auto_continue=True,  # Enable auto-continuation (default is True)
    completion_model="claude-3.7-sonnet",  # Model to use for checking completeness
    continuation_attempts=3,  # Maximum number of continuation attempts
    messages=[
        {"role": "user", "content": "Write a comprehensive analysis of quantum computing..."}
    ]
)

print(response)
```

For async usage:

```python
import g4f
import asyncio

async def get_response():
    response = await g4f.ChatCompletion.create_async(
        model="gpt-4o-mini",
        provider="Blackbox",
        auto_continue=True,
        messages=[
            {"role": "user", "content": "Write a comprehensive analysis of quantum computing..."}
        ]
    )
    return response

response = asyncio.run(get_response())
print(response)
```

## Handling Streaming Responses

The auto-continue feature also works with streaming responses, but with a slight delay when a continuation is needed:

```python
import g4f
import asyncio

async def stream_response():
    response = await g4f.ChatCompletion.create_async(
        model="gpt-4o-mini",
        provider="Blackbox",
        auto_continue=True,
        stream=True,
        messages=[
            {"role": "user", "content": "Write a comprehensive analysis of quantum computing..."}
        ]
    )
    
    async for chunk in response:
        print(chunk, end="", flush=True)
    print()

asyncio.run(stream_response())
```

## Completeness Detection

The auto-continue system uses two methods to detect incomplete responses:

1. **Heuristic Detection**: Pattern matching for common indicators of incomplete responses like unbalanced brackets, sentences ending with conjunctions or prepositions, and more.

2. **LLM-Based Detection**: For more nuanced cases, asking an LLM (default: Claude 3.7 Sonnet) to determine if a response is complete.

Combining these approaches provides more reliable detection than either method alone.

## Limitations

- The feature may sometimes incorrectly identify a complete response as incomplete, leading to unnecessary continuation requests.
- With providers that don't reliably continue from where they left off, there may be repetition or inconsistency between the original response and the continuation.
- Streaming responses will experience a delay when a continuation is needed as the system needs to process the entire response to check completeness.

For sensitive applications, it's recommended to test this feature with your specific use case to ensure it meets your requirements. 