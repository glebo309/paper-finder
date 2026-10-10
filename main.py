#!/usr/bin/env python3
"""
Paper Finder - Main Entry Point

Multi-mode application supporting GUI, CLI, and Telegram bot interfaces.
"""

import sys
import argparse
import logging
import json
from contextlib import redirect_stdout
from pathlib import Path

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def _positive_limit(value):
    number = int(value)
    if not 1 <= number <= 50:
        raise argparse.ArgumentTypeError("limit must be between 1 and 50")
    return number


def _display_search(payload):
    print(f"Search: {payload.get('query', '')}")
    print(f"Status: {payload.get('status', 'unknown')}")
    for index, record in enumerate(payload.get("candidates", []), 1):
        print(f"\n{index}. {record.get('title') or 'Untitled record'}")
        authors = record.get("authors") or []
        print(f"   {', '.join(str(author) for author in authors[:4])} | {record.get('year') or 'year unknown'}")
        identifier = record.get("identifier") or {}
        print(f"   {record.get('doi') or identifier.get('value', 'No identifier')}")
        print(f"   Sources: {', '.join(record.get('sources') or [record.get('metadata_source') or 'unknown'])}")
        reasons = record.get("match_reasons") or []
        if reasons:
            print(f"   {'; '.join(reasons)}")
    for provider, error in payload.get("errors", {}).items():
        print(f"Provider warning ({provider}): {error}", file=sys.stderr)
    if payload.get("status") == "ambiguous":
        print("Choose a candidate or refine the query. To preserve this order, use search QUERY --save-results results.json, then acquire --from-results results.json --select N.")


def _run_paper_command(args):
    from src.cli.search_helpers import load_results, save_results, search_reference
    try:
        if args.command == 'acquire' and args.from_results:
            if args.reference:
                raise ValueError("Do not provide a reference with --from-results; select from the saved query.")
            payload = load_results(args.from_results)
        else:
            if not args.reference:
                raise ValueError("Provide a reference or --from-results FILE.")
            # Legacy providers print progress. Keep stdout valid JSON in machine mode.
            with redirect_stdout(sys.stderr):
                payload = search_reference(args.reference, limit=args.limit, mode=getattr(args, 'mode', 'identify'), refresh=args.refresh)
        if args.command == 'search':
            if args.save_results:
                save_results(args.save_results, payload)
            print(json.dumps(payload, ensure_ascii=False, default=str)) if args.json else _display_search(payload)
            return 1 if payload['status'] in ('not_found', 'unavailable') else 0

        candidates = payload.get('candidates', [])
        if args.select is not None:
            if not 1 <= args.select <= len(candidates):
                payload.update(status='invalid_selection', error=f'Choose a candidate from 1 to {len(candidates)}.')
                print(json.dumps(payload, ensure_ascii=False, default=str)) if args.json else print(payload['error'])
                return 2
            selected = candidates[args.select - 1]
        else:
            selected = payload.get('selected') if payload.get('status') == 'matched' else None
        if selected is None:
            print(json.dumps(payload, ensure_ascii=False, default=str)) if args.json else _display_search(payload)
            return 2 if payload.get('status') == 'ambiguous' else 1

        with redirect_stdout(sys.stderr):
            from paper_finder import PaperFinder
            from src.core.config import load_config
            config = load_config(args.config) if Path(args.config).exists() else None
            finder = PaperFinder(config=config, silent_init=True)
            output_dir = Path(args.output).expanduser()
            output_dir.mkdir(parents=True, exist_ok=True)
            captured_url = {'url': None}

            def browser_callback(identifier, url):
                captured_url['url'] = url

            result = finder.find_record(selected, output_dir=str(output_dir), browser_callback=browser_callback,
                                        recent_sources=not args.skip_recent_sources, contact_email=args.email)
        outcome = {
            'success': result.success,
            'status': getattr(result, 'status', None) or ('downloaded' if result.success and result.filepath else 'link_available' if result.success else 'failed'),
            'filepath': str(result.filepath) if result.filepath else None,
            'source': result.source,
            'url': captured_url['url'],
            'error': result.error,
            'metadata': result.metadata,
            'verification': getattr(result, 'verification', None),
        }
        if args.json:
            print(json.dumps(outcome, ensure_ascii=False, default=str))
        elif result.success and result.filepath:
            print(f"Saved: {result.filepath}\nSource: {result.source}")
        elif result.success:
            print(f"Paper link available via {result.source}; no local PDF was saved.")
        elif outcome['status'] == 'located':
            print(f"Document link found; no verified PDF was saved.\n{captured_url['url'] or result.error}")
        elif outcome['status'] == 'unverifiable':
            print(f"Document identity could not be verified. Review file: {result.filepath or 'none'}")
            if result.error:
                print(result.error)
        elif outcome['status'] == 'mismatch':
            print(f"Retrieved document does not match the selected paper: {result.error}")
        else:
            print(f"Acquisition failed: {result.error or 'No verified document found'}")
        return 0 if result.success else 1
    except Exception as exc:
        payload = {'success': False, 'status': 'error', 'error': str(exc)}
        print(json.dumps(payload, ensure_ascii=False)) if args.json else print(f"Error: {exc}", file=sys.stderr)
        return 1


def _run_copies_command(args):
    """Locate version-labelled links for one supplied DOI without downloading."""
    from src.acquisition.recent_open_access import RecentOpenAccessDiscovery, _doi
    try:
        doi = _doi(args.doi)
        if not doi:
            raise ValueError('Provide an exact DOI or doi.org URL; use search to identify a paper first.')
        with redirect_stdout(sys.stderr):
            result = RecentOpenAccessDiscovery(email=args.email).discover(doi)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, default=str))
        else:
            print(f"Full-text locations for {doi}\nStatus: {result.get('status', 'unknown')}")
            groups = (('locations', 'Available locations'),
                      ('alternatives', 'Alternative versions: inspect before selecting'),
                      ('embargoed', 'Embargoed copies'), ('closed', 'Closed locations'))
            for key, label in groups:
                if not result.get(key):
                    continue
                print(f"\n{label}:")
                for location in result[key]:
                    print(f"  {location.get('version') or 'unknown version'} | "
                          f"licence: {location.get('license') or 'unknown'} | "
                          f"source: {location.get('source') or 'unknown'}")
                    print(f"  {location.get('url') or location.get('landing_page_url') or location.get('pdf_url')}")
                    if location.get('available_from'):
                        print(f"  Available from: {location['available_from']}")
            for provider, error in result.get('errors', {}).items():
                print(f"Provider warning ({provider}): {error}", file=sys.stderr)
            print('\nNo files downloaded. Links and version labels require inspection; downloads still need identity verification.')
        return 0 if result.get('locations') or result.get('alternatives') else 1
    except Exception as exc:
        payload = {'success': False, 'status': 'error', 'error': str(exc)}
        print(json.dumps(payload, ensure_ascii=False)) if args.json else print(f"Error: {exc}", file=sys.stderr)
        return 1


def main():
    """Main entry point with subcommand support."""
    parser = argparse.ArgumentParser(
        prog='paper-finder',
        description='Find, compare, select, and acquire academic papers'
    )
    
    # Add subparsers for different modes
    subparsers = parser.add_subparsers(
        dest='command',
        help='Available commands'
    )
    
    # GUI mode (default)
    gui_parser = subparsers.add_parser(
        'gui',
        help='Launch graphical interface (default)'
    )
    
    # CLI acquisition mode
    acquire_parser = subparsers.add_parser(
        'acquire',
        help='Acquire a paper via command line'
    )
    acquire_parser.add_argument(
        'reference',
        nargs='?',
        help='DOI, URL, or citation; omit when using --from-results'
    )
    acquire_parser.add_argument(
        '--output',
        '-o',
        help='Output directory for PDF',
        default='downloads'
    )
    acquire_parser.add_argument(
        '--config',
        '-c',
        help='Configuration file path',
        default='config.yaml'
    )
    
    acquire_parser.add_argument('--refresh', action='store_true', help='Bypass cached discovery metadata; provider cooldowns still apply')
    acquire_parser.add_argument('--skip-recent-sources', action='store_true', help='Skip checking current repository and open-access copy locations')
    acquire_parser.add_argument('--email', help='Contact email for Unpaywall (or set UNPAYWALL_EMAIL)')
    acquire_parser.add_argument('--from-results', metavar='FILE', help='Use saved candidates without repeating discovery')
    acquire_parser.add_argument('--select', type=int, help='Explicitly select candidate N (1-based)')
    acquire_parser.add_argument('--json', action='store_true', help='Emit machine-readable JSON')
    acquire_parser.add_argument('--limit', type=_positive_limit, default=10, help='Candidate count, 1–50 (default: 10)')

    search_parser = subparsers.add_parser('search', help='Search metadata and compare candidates; never download')
    search_parser.add_argument('reference', help='Title, citation, description, DOI, ISBN, arXiv ID, or URL')
    search_parser.add_argument('--refresh', action='store_true', help='Bypass cached discovery metadata; provider cooldowns still apply')
    search_parser.add_argument('--save-results', metavar='FILE', help='Save the displayed candidate order for later acquisition')
    search_parser.add_argument('--json', action='store_true', help='Emit machine-readable JSON')
    search_parser.add_argument('--limit', type=_positive_limit, default=10, help='Candidate count, 1–50 (default: 10)')
    search_parser.add_argument('--mode', choices=['identify', 'discover'], default='identify', help='Identify one paper, or explore a topic')

    copies_parser = subparsers.add_parser('copies', help='Find current full-text locations and versions for an exact DOI; never download')
    copies_parser.add_argument('doi', help='Exact DOI or doi.org URL')
    copies_parser.add_argument('--email', help='Contact email for Unpaywall (or set UNPAYWALL_EMAIL)')
    copies_parser.add_argument('--json', action='store_true', help='Emit machine-readable JSON')

    # Telegram bot mode
    bot_parser = subparsers.add_parser(
        'bot',
        help='Run Telegram bot interface'
    )
    bot_parser.add_argument(
        '--config',
        '-c',
        help='Configuration file path',
        default='config.yaml'
    )
    bot_parser.add_argument(
        '--token',
        help='Telegram bot token (overrides config/env)',
        default=None
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    # Default to GUI if no command specified
    if args.command is None:
        args.command = 'gui'
    
    # Execute based on command
    if args.command == 'gui':
        # Launch GUI
        from gui import main as gui_main
        gui_main()
    
    elif args.command in ('search', 'acquire'):
        sys.exit(_run_paper_command(args))

    elif args.command == 'copies':
        sys.exit(_run_copies_command(args))

    elif args.command == 'bot':
        # Telegram bot mode
        import os
        from src.core.config import load_config, Config
        from src.cli.telegram_bot import run_telegram_bot
        
        try:
            # Load configuration
            config_path = Path(args.config)
            if config_path.exists():
                config = load_config(str(config_path))
            else:
                # Create minimal config
                config = Config()
            
            # Override token if provided via CLI
            if args.token:
                if not hasattr(config, 'telegram'):
                    from types import SimpleNamespace
                    config.telegram = SimpleNamespace()
                config.telegram.token = args.token
            elif not hasattr(config, 'telegram') or not config.telegram.token:
                # Try environment variable
                token = os.environ.get('TELEGRAM_BOT_TOKEN')
                if token:
                    if not hasattr(config, 'telegram'):
                        from types import SimpleNamespace
                        config.telegram = SimpleNamespace()
                    config.telegram.token = token
                else:
                    print("❌ Error: Telegram bot token not provided")
                    print("   Set TELEGRAM_BOT_TOKEN environment variable or use --token flag")
                    sys.exit(1)
            
            # Run the bot
            print("🤖 Starting Telegram bot...")
            print(f"   Bot: @paper_finder_helper_bot")
            print("   Mode: Long polling")
            print("   Press Ctrl+C to stop")
            
            run_telegram_bot(config)
            
        except KeyboardInterrupt:
            print("\n👋 Bot stopped")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Bot failed: {e}", exc_info=True)
            print(f"❌ Error: {e}")
            sys.exit(1)


if __name__ == '__main__':
    main()
