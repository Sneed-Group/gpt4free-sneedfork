"""
G4F Completions module.

This module contains functionality related to completing and enhancing AI responses.
"""

from .auto_continue import (
    auto_continue_response,
    is_response_incomplete,
    get_completion_check,
    DEFAULT_COMPLETION_MODEL,
    MAX_CONTINUATION_ATTEMPTS
) 