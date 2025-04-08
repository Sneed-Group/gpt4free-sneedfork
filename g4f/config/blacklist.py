"""
Provider blacklist configuration file.

This module provides functionality to manage a list of blacklisted providers
that will be excluded from provider selection.
"""
from __future__ import annotations

from typing import List, Set, Optional
import os
import json
from pathlib import Path

# Default blacklist file location
_config_dir = os.path.dirname(os.path.abspath(__file__))
_default_blacklist_file = os.path.join(_config_dir, "provider_blacklist.json")

# In-memory cache of blacklisted providers
_blacklisted_providers: Set[str] = set()

def _ensure_blacklist_file_exists():
    """Ensure the blacklist file exists, creating it if necessary."""
    if not os.path.exists(_default_blacklist_file):
        with open(_default_blacklist_file, 'w') as f:
            json.dump([], f)

def load_blacklist(file_path: Optional[str] = None) -> List[str]:
    """
    Load the blacklisted providers from a file.
    
    Args:
        file_path: Optional path to the blacklist file. If not provided, uses the default path.
        
    Returns:
        List of blacklisted provider names
    """
    global _blacklisted_providers
    
    path = file_path or _default_blacklist_file
    _ensure_blacklist_file_exists()
    
    try:
        with open(path, 'r') as f:
            blacklist = json.load(f)
            _blacklisted_providers = set(blacklist)
            return blacklist
    except (json.JSONDecodeError, FileNotFoundError):
        # If file is empty or invalid, return empty list
        _blacklisted_providers = set()
        return []

def save_blacklist(providers: List[str], file_path: Optional[str] = None) -> None:
    """
    Save the blacklisted providers to a file.
    
    Args:
        providers: List of provider names to blacklist
        file_path: Optional path to the blacklist file. If not provided, uses the default path.
    """
    global _blacklisted_providers
    
    path = file_path or _default_blacklist_file
    
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    with open(path, 'w') as f:
        json.dump(providers, f, indent=2)
    
    _blacklisted_providers = set(providers)

def add_to_blacklist(provider_name: str, file_path: Optional[str] = None) -> List[str]:
    """
    Add a provider to the blacklist.
    
    Args:
        provider_name: Name of the provider to blacklist
        file_path: Optional path to the blacklist file. If not provided, uses the default path.
        
    Returns:
        Updated list of blacklisted provider names
    """
    providers = load_blacklist(file_path)
    
    # Add provider if not already in the list
    if provider_name not in providers:
        providers.append(provider_name)
        save_blacklist(providers, file_path)
    
    return providers

def remove_from_blacklist(provider_name: str, file_path: Optional[str] = None) -> List[str]:
    """
    Remove a provider from the blacklist.
    
    Args:
        provider_name: Name of the provider to remove from blacklist
        file_path: Optional path to the blacklist file. If not provided, uses the default path.
        
    Returns:
        Updated list of blacklisted provider names
    """
    providers = load_blacklist(file_path)
    
    # Remove provider if in the list
    if provider_name in providers:
        providers.remove(provider_name)
        save_blacklist(providers, file_path)
    
    return providers

def get_blacklist() -> List[str]:
    """
    Get the current blacklisted providers.
    
    Returns:
        List of blacklisted provider names
    """
    if not _blacklisted_providers:
        load_blacklist()
    
    return list(_blacklisted_providers)

def is_blacklisted(provider_name: str) -> bool:
    """
    Check if a provider is blacklisted.
    
    Args:
        provider_name: Name of the provider to check
        
    Returns:
        True if the provider is blacklisted, False otherwise
    """
    if not _blacklisted_providers:
        load_blacklist()
    
    return provider_name in _blacklisted_providers

# Initialize the blacklist on module import
load_blacklist() 