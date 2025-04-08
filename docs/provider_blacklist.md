# Provider Blacklist

G4F supports maintaining a blacklist of providers that will be excluded from provider selection.
This is useful if you want to avoid certain providers for any reason, such as rate limiting,
inconsistent performance, or privacy concerns.

## Using the Command Line Interface

The `g4f` command line tool provides commands to manage the provider blacklist:

### View the Blacklist

To see which providers are currently blacklisted:

```bash
python -m g4f blacklist list
```

### Add Providers to Blacklist

To add one or more providers to the blacklist:

```bash
python -m g4f blacklist add Blackbox cloudflare duckduckgo
```

### Remove Providers from Blacklist

To remove providers from the blacklist:

```bash
python -m g4f blacklist remove Blackbox
```

### Clear the Entire Blacklist

To clear all entries from the blacklist:

```bash
python -m g4f blacklist clear
```

## Using the Blacklist in Code

You can also manage the blacklist programmatically in your Python code:

```python
from g4f.config import blacklist

# Get the current blacklist
current_blacklist = blacklist.get_blacklist()
print(f"Current blacklist: {current_blacklist}")

# Add a provider to the blacklist
blacklist.add_to_blacklist("Blackbox")

# Check if a provider is blacklisted
is_blacklisted = blacklist.is_blacklisted("Blackbox")
print(f"Is Blackbox blacklisted? {is_blacklisted}")

# Remove a provider from the blacklist
blacklist.remove_from_blacklist("Blackbox")

# Clear the entire blacklist
blacklist.save_blacklist([])
```

## Blacklist Location

The blacklist is stored in a JSON file at `g4f/config/provider_blacklist.json`. This file is automatically created the first time you use the blacklist feature.

## Behavior with Blacklisted Providers

When a provider is blacklisted:

1. It won't appear in the list of available providers from the API
2. If specifically requested in a function call, it will raise a `ProviderNotFoundError`
3. In retry providers, blacklisted providers are filtered out of the retry list
4. When using `Model.best_provider`, if the best provider is blacklisted, G4F will try to find an alternative provider

The blacklist takes precedence over other provider selection mechanisms, ensuring blacklisted providers are never used. 