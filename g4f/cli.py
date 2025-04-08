from __future__ import annotations

import argparse
from argparse import ArgumentParser

from g4f import Provider
from g4f.gui.run import gui_parser, run_gui_args
import g4f.cookies
from g4f.config import blacklist

def get_api_parser():
    api_parser = ArgumentParser(description="Run the API and GUI")
    api_parser.add_argument("--bind", default=None, help="The bind string. (Default: 0.0.0.0:1337)")
    api_parser.add_argument("--port", "-p", default=None, help="Change the port of the server.")
    api_parser.add_argument("--debug", "-d", action="store_true", help="Enable verbose logging.")
    api_parser.add_argument("--gui", "-g", default=None, action="store_true", help="Start also the gui.")
    api_parser.add_argument("--model", default=None, help="Default model for chat completion. (incompatible with --reload and --workers)")
    api_parser.add_argument("--provider", choices=[provider.__name__ for provider in Provider.__providers__ if provider.working],
                            default=None, help="Default provider for chat completion. (incompatible with --reload and --workers)")
    api_parser.add_argument("--image-provider", choices=[provider.__name__ for provider in Provider.__providers__ if provider.working and hasattr(provider, "image_models")],
                            default=None, help="Default provider for image generation. (incompatible with --reload and --workers)"),
    api_parser.add_argument("--proxy", default=None, help="Default used proxy. (incompatible with --reload and --workers)")
    api_parser.add_argument("--workers", type=int, default=None, help="Number of workers.")
    api_parser.add_argument("--disable-colors", action="store_true", help="Don't use colors.")
    api_parser.add_argument("--ignore-cookie-files", action="store_true", help="Don't read .har and cookie files. (incompatible with --reload and --workers)")
    api_parser.add_argument("--g4f-api-key", type=str, default=None, help="Sets an authentication key for your API. (incompatible with --reload and --workers)")
    api_parser.add_argument("--ignored-providers", nargs="+", choices=[provider.__name__ for provider in Provider.__providers__ if provider.working],
                            default=[], help="List of providers to ignore when processing request. (incompatible with --reload and --workers)")
    api_parser.add_argument("--cookie-browsers", nargs="+", choices=[browser.__name__ for browser in g4f.cookies.browsers],
                            default=[], help="List of browsers to access or retrieve cookies from. (incompatible with --reload and --workers)")
    api_parser.add_argument("--reload", action="store_true", help="Enable reloading.")
    api_parser.add_argument("--demo", action="store_true", help="Enable demo mode.")
    api_parser.add_argument("--disable-auto-continue", action="store_true", help="Disable auto-continuation of incomplete responses.")
    api_parser.add_argument("--completion-model", type=str, default=None, help="Model to use for checking response completeness. Default: claude-3.7-sonnet")
    api_parser.add_argument("--continuation-attempts", type=int, default=3, help="Maximum number of continuation attempts for incomplete responses.")
	
    api_parser.add_argument("--ssl-keyfile", type=str, default=None, help="Path to SSL key file for HTTPS.")
    api_parser.add_argument("--ssl-certfile", type=str, default=None, help="Path to SSL certificate file for HTTPS.")
    api_parser.add_argument("--log-config", type=str, default=None, help="Custom log config.")
	
    return api_parser

def get_blacklist_parser():
    """Get the blacklist command parser."""
    blacklist_parser = ArgumentParser(description="Manage provider blacklist")
    subparsers = blacklist_parser.add_subparsers(dest="blacklist_cmd", help="Blacklist commands")
    
    # Add to blacklist
    add_parser = subparsers.add_parser("add", help="Add provider(s) to blacklist")
    add_parser.add_argument("providers", nargs="+", 
                          choices=[provider.__name__ for provider in Provider.__providers__],
                          help="Provider name(s) to blacklist")
    
    # Remove from blacklist
    remove_parser = subparsers.add_parser("remove", help="Remove provider(s) from blacklist")
    remove_parser.add_argument("providers", nargs="+", help="Provider name(s) to remove from blacklist")
    
    # List blacklisted providers
    subparsers.add_parser("list", help="List all blacklisted providers")
    
    # Clear blacklist
    subparsers.add_parser("clear", help="Clear the entire provider blacklist")
    
    return blacklist_parser

def main():
    parser = argparse.ArgumentParser(description="Run gpt4free")
    subparsers = parser.add_subparsers(dest="mode", help="Mode to run the g4f in.")
    subparsers.add_parser("api", parents=[get_api_parser()], add_help=False)
    subparsers.add_parser("gui", parents=[gui_parser()], add_help=False)
    subparsers.add_parser("blacklist", parents=[get_blacklist_parser()], add_help=False)

    args = parser.parse_args()
    if args.mode == "api":
        run_api_args(args)
    elif args.mode == "gui":
        run_gui_args(args)
    elif args.mode == "blacklist":
        run_blacklist_args(args)
    else:
        parser.print_help()
        exit(1)

def run_api_args(args):
    from g4f.api import AppConfig, run_api

    AppConfig.set_config(
        ignore_cookie_files=args.ignore_cookie_files,
        ignored_providers=args.ignored_providers,
        g4f_api_key=args.g4f_api_key,
        provider=args.provider,
        image_provider=args.image_provider,
        proxy=args.proxy,
        model=args.model,
        gui=args.gui,
        demo=args.demo,
        auto_continue=not args.disable_auto_continue,
        completion_model=args.completion_model,
        continuation_attempts=args.continuation_attempts,
    )
    if args.cookie_browsers:
        g4f.cookies.browsers = [g4f.cookies[browser] for browser in args.cookie_browsers]
    run_api(
        bind=args.bind,
        port=args.port,
        debug=args.debug,
        workers=args.workers,
        use_colors=not args.disable_colors,
        reload=args.reload,
        ssl_keyfile=args.ssl_keyfile,
        ssl_certfile=args.ssl_certfile,
        log_config=args.log_config,
    )

def run_blacklist_args(args):
    """Handle blacklist command line arguments."""
    if not hasattr(args, 'blacklist_cmd') or not args.blacklist_cmd:
        parser = argparse.ArgumentParser(description="Manage provider blacklist")
        parser.parse_args(["blacklist", "--help"])
        return

    if args.blacklist_cmd == "add":
        # Add providers to blacklist
        for provider in args.providers:
            blacklist.add_to_blacklist(provider)
        print(f"Added {len(args.providers)} provider(s) to blacklist")
        blacklisted = blacklist.get_blacklist()
        if blacklisted:
            print(f"Current blacklist: {', '.join(blacklisted)}")
    
    elif args.blacklist_cmd == "remove":
        # Remove providers from blacklist
        for provider in args.providers:
            blacklist.remove_from_blacklist(provider)
        print(f"Removed {len(args.providers)} provider(s) from blacklist")
        blacklisted = blacklist.get_blacklist()
        if blacklisted:
            print(f"Current blacklist: {', '.join(blacklisted)}")
        else:
            print("Blacklist is now empty")
    
    elif args.blacklist_cmd == "list":
        # List blacklisted providers
        blacklisted = blacklist.get_blacklist()
        if blacklisted:
            print(f"Blacklisted providers ({len(blacklisted)}):")
            for provider in blacklisted:
                try:
                    if provider in Provider.ProviderUtils.convert:
                        label = getattr(Provider.ProviderUtils.convert[provider], 'label', provider)
                        print(f" - {provider}: {label}")
                    else:
                        print(f" - {provider}")
                except:
                    print(f" - {provider}")
        else:
            print("No providers are blacklisted")
    
    elif args.blacklist_cmd == "clear":
        # Clear the blacklist
        blacklist.save_blacklist([])
        print("Provider blacklist cleared")

if __name__ == "__main__":
    main()
