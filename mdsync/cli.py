#!/usr/bin/env python3
"""Command-line interface for mdsync."""

import argparse
import sys
from pathlib import Path

from googleapiclient.discovery import build

from .auth import authenticate, get_credentials
from .confluence import (
    CONFLUENCE_AVAILABLE,
    create_confluence_page,
    get_confluence_client,
    get_confluence_permissions_config,
    import_markdown_to_confluence,
    lock_confluence_page,
    unlock_confluence_page,
    check_confluence_lock_status,
    parse_confluence_destination,
)
from .diffing import (
    check_sync_status,
    diff_confluence_to_markdown,
    diff_gdoc_to_markdown,
    diff_markdown_to_confluence,
    diff_markdown_to_gdoc,
)
from .frontmatter import extract_frontmatter_metadata
from .directory import get_document_id, get_tab_id, load_directory_metadata
from .tab_sync import (pull_document_to_directory, pull_tab_to_file, push_directory, push_file, resolve_file, sync_directory, sync_file, create_directory_document)
from .gdocs import (
    _find_tab_by_title,
    _get_document_tabs,
    _tab_text,
    check_gdoc_frozen_status,
    create_empty_document,
    create_new_gdoc_from_markdown,
    create_new_gdoc_from_markdown_with_title,
    export_gdoc_to_markdown,
    import_markdown_to_gdoc,
    list_comments,
    list_revisions,
    lock_document,
    print_comments_markdown,
    print_comments_text,
    unlock_document,
)
from .listing import list_markdown_files
from .urls import extract_doc_id, extract_doc_id_from_url, is_google_doc, is_confluence_page


def main():
    parser = argparse.ArgumentParser(
        description='Sync between Google Docs, Confluence, and Markdown files',
        epilog='Commands:\n'
               '  auth                              Authenticate with Google\n'
               '  repl                              Start the interactive REPL\n'
               '  list [PATH]                       List Markdown files and metadata\n'
               '  pull SOURCE [DESTINATION]         Pull Google Docs content into Markdown\n'
               '  push SOURCE                       Push Markdown changes to Google Docs\n'
               '  sync SOURCE                       Three-way sync local and remote changes\n'
               '  resolve FILE                      Confirm a manually resolved conflict\n\n'
               'Examples:\n'
               '  # Pull a Google Doc\n'
               '  %(prog)s pull DOC_ID ./docs/chronix-test\n'
               '  %(prog)s pull DOC_ID ./docs/chronix-test/todo.md --tab todo\n'
               '  %(prog)s pull DOC_ID ./docs --parent  # creates/uses ./docs/chronix-test/\n'
               '  %(prog)s pull ./docs/chronix-test/todo.md\n\n'
               '  # Push local changes\n'
               '  %(prog)s push ./docs/chronix-test/todo.md\n'
               '  %(prog)s push ./docs/chronix-test\n\n'
               '  # Three-way sync\n'
               '  %(prog)s sync ./docs/chronix-test/todo.md\n'
               '  %(prog)s sync ./docs/chronix-test\n'
               '  # After manually resolving a conflict:\n'
               '  %(prog)s resolve ./docs/chronix-test/todo.md\n\n'
               '  # Create a new Google Doc\n'
               '  %(prog)s input.md --create\n'
               '  %(prog)s input.md --create -u | pbcopy\n'
               '  %(prog)s --directory file1.md file2.md --directory-title "Project Documentation"\n'
               '  %(prog)s --create-empty\n\n'
               '  # Google Docs administration\n'
               '  %(prog)s DOC_ID --list-revisions\n'
               '  %(prog)s DOC_ID --list-comments\n'
               '  %(prog)s DOC_ID --lock --lock-reason "Maintenance"\n'
               '  %(prog)s DOC_ID --lock-status\n'
               '  %(prog)s DOC_ID --unlock\n\n'
               '  # Confluence\n'
               '  %(prog)s input.md confluence:SPACE/123456\n'
               '  %(prog)s confluence:SPACE/123456 output.md\n'
               '  %(prog)s input.md confluence:SPACE/123456 --diff\n\n'
               '  # Diff without changing either side\n'
               '  %(prog)s file.md gdoc_url --diff\n'
               '  %(prog)s gdoc_url file.md --diff\n'
               '  %(prog)s file.md confluence:SPACE/123 --diff\n\n'
               'Run %(prog)s -h for the complete option list.',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('source', nargs='?', help='Command, source URL/ID, or Markdown file')
    parser.add_argument('destination', nargs='?', help='Destination URL/ID or Markdown file')
    parser.add_argument('--create', action='store_true', help='Create a new Google Doc (use with markdown source)')
    parser.add_argument('--list-revisions', action='store_true', help='List revision history for a Google Doc')
    parser.add_argument('--lock', action='store_true', help='Lock a Google Doc to prevent editing')
    parser.add_argument('--unlock', action='store_true', help='Unlock a Google Doc to allow editing')
    parser.add_argument('--lock-status', action='store_true', help='Check if a Google Doc is locked')
    parser.add_argument('--lock-reason', type=str, metavar='REASON', help='Reason for locking (use with --lock)')
    parser.add_argument('--lock-confluence', action='store_true', help='Lock a Confluence page (restrict editing to allowed editors from secrets.yaml)')
    parser.add_argument('--unlock-confluence', action='store_true', help='Unlock a Confluence page (remove all edit restrictions)')
    parser.add_argument('--confluence-lock-status', action='store_true', help='Check if a Confluence page is locked')
    parser.add_argument('--list-comments', action='store_true', help='List all comments from a Google Doc')
    parser.add_argument('--unresolved-only', action='store_true', help='Show only unresolved comments (use with --list-comments)')
    parser.add_argument('--secrets-file', type=str, metavar='PATH', help='Path to secrets.yaml file (default: searches in current dir, ~/.config/mdsync/, ~/.mdsync/)')
    parser.add_argument('--create-empty', action='store_true', help='Create empty Google Doc')
    parser.add_argument('--directory', nargs='+', metavar='MARKDOWN_FILE', help='Create a new Google Doc with one real tab per Markdown file')
    parser.add_argument('--directory-title', type=str, metavar='TITLE', help='Title for a new directory-backed Google Doc')
    parser.add_argument('-u', '--url-only', action='store_true', help='Output only the URL (perfect for piping to pbcopy)')
    parser.add_argument('--diff', action='store_true', help='Show diff between source and destination (markdown as common format)')
    parser.add_argument('--version', action='version', version='mdsync 0.3.2', help='Show version information and exit')

    if len(sys.argv) > 1 and sys.argv[1] == 'auth':
        try:
            authenticate(force=True)
            print('Google authentication successful.')
        except Exception as exc:
            print(f'Error: {exc}', file=sys.stderr)
            sys.exit(1)
        return

    if len(sys.argv) > 1 and sys.argv[1] == 'repl':
        from .repl import run_repl
        run_repl()
        return

    if len(sys.argv) > 1 and sys.argv[1] == 'list':
        list_parser = argparse.ArgumentParser()
        list_parser.add_argument('path', nargs='?', default='.', help='File or directory to scan (default: current directory)')
        list_parser.add_argument('--format', type=str, choices=['text', 'json'], default='text')
        list_parser.add_argument('--check-status', action='store_true')
        list_parser.add_argument('--diff', action='store_true')
        list_parser.add_argument('--secrets-file', type=str, metavar='PATH')
        try:
            a = list_parser.parse_args(sys.argv[2:])
        except SystemExit:
            return
        list_markdown_files(a.path, a.format, a.check_status, a.diff, a.secrets_file or None)
        return

    if len(sys.argv) > 1 and sys.argv[1] == 'sync':
        sp = argparse.ArgumentParser(prog='mdsync sync', description='Three-way sync a Markdown file or directory with Google Docs')
        sp.add_argument('source', help='Markdown file or directory to sync')
        sp.add_argument('--secrets-file', type=str, metavar='PATH')
        try:
            a = sp.parse_args(sys.argv[2:])
        except SystemExit:
            return
        try:
            creds = get_credentials()
            source = Path(a.source)
            if source.is_dir():
                sync_directory(source, creds)
            else:
                sync_file(source, creds)
            return
        except Exception as exc:
            print(f'Error: {exc}', file=sys.stderr)
            sys.exit(1)

    if len(sys.argv) > 1 and sys.argv[1] == 'resolve':
        rp = argparse.ArgumentParser(prog='mdsync resolve', description='Confirm a manually resolved Google Docs sync conflict')
        rp.add_argument('source', help='Markdown file with a resolved conflict')
        rp.add_argument('--secrets-file', type=str, metavar='PATH')
        try:
            a = rp.parse_args(sys.argv[2:])
        except SystemExit:
            return
        try:
            creds = get_credentials()
            source = Path(a.source)
            if source.is_dir():
                raise ValueError('resolve requires a Markdown file, not a directory')
            resolve_file(source, creds)
            return
        except Exception as exc:
            print(f'Error: {exc}', file=sys.stderr)
            sys.exit(1)

    if len(sys.argv) > 1 and sys.argv[1] in {'push', 'pull'}:
        cmd = sys.argv[1]
        pp = argparse.ArgumentParser(
            prog=f'mdsync {cmd}',
            description=(
                'Push Markdown changes to the linked Google Docs tabs'
                if cmd == 'push' else
                'Pull Google Docs content into Markdown files or directories'
            ),
        )
        pp.add_argument('source', help='Markdown file/directory for push, or Google Doc/file/directory for pull')
        if cmd == 'pull':
            pp.add_argument('destination', nargs='?', help='Local Markdown file or directory')
            pp.add_argument('--parent', action='store_true', help='Treat destination as a parent directory and create/use a document-title subdirectory inside it')
            pp.add_argument('--tab', metavar='TAB', help='Pull only the named Google Docs tab into the destination file')
        pp.add_argument('--secrets-file', type=str, metavar='PATH')
        try:
            a = pp.parse_args(sys.argv[2:])
        except SystemExit:
            return
        try:
            creds = get_credentials()
            source = Path(a.source)
            if cmd == 'push':
                if source.is_dir():
                    push_directory(source, creds)
                else:
                    push_file(source, creds)
                return

            # pull: a local file/directory means the remote relationship is already known.
            if source.is_dir():
                metadata = load_directory_metadata(source)
                doc_id = get_document_id(metadata)
                if not doc_id:
                    raise ValueError(f'No Google Doc metadata found in {source}')
                pull_document_to_directory(get_document_id(metadata), source, creds)
                return

            if source.is_file():
                metadata = extract_frontmatter_metadata(source.read_text(encoding='utf-8'))
                tab_id = metadata.get('gdoc_tab_id') or get_tab_id(source)
                if tab_id:
                    directory = source.parent
                    doc_id = get_document_id(load_directory_metadata(directory))
                    if not doc_id:
                        raise ValueError(f'No Google Doc metadata found in {directory}')
                    pull_tab_to_file(doc_id, tab_id, source, creds)
                    return
                gdoc_url = metadata.get('gdoc_url')
                if not gdoc_url:
                    raise ValueError(f'No remote Google Doc metadata found in {source}')
                from .gdocs import export_gdoc_to_markdown
                export_gdoc_to_markdown(_doc_id(gdoc_url), str(source), creds)
                return

            # pull URL/ID -> local file or directory. A directory destination means all tabs.
            doc_id = extract_doc_id_from_url(str(source)) or extract_doc_id(str(source))
            if not doc_id:
                raise ValueError(f'Could not extract Google Doc ID from: {source}')
            if not a.destination:
                raise ValueError('A local destination is required when pulling from a Google Doc')
            destination = Path(a.destination)
            if destination.suffix.lower() == '.md':
                if a.tab:
                    from .gdocs import _find_tab_by_title, _get_document_tabs
                    _, tabs = _get_document_tabs(build('docs', 'v1', credentials=creds), doc_id)
                    tab = _find_tab_by_title(tabs, a.tab)
                    if not tab:
                        raise ValueError(f"Google Docs tab not found: {a.tab}")
                    pull_tab_to_file(doc_id, tab['tabProperties']['tabId'], destination, creds)
                else:
                    from .gdocs import export_gdoc_to_markdown
                    export_gdoc_to_markdown(doc_id, str(destination), creds)
            else:
                if a.tab:
                    raise ValueError('--tab requires a Markdown destination file')
                pull_document_to_directory(doc_id, destination, creds, parent=a.parent)
            return
        except Exception as exc:
            print(f'Error: {exc}', file=sys.stderr)
            sys.exit(1)

    args = parser.parse_args()
    secrets_file_path = args.secrets_file or None

    if args.source and args.destination and is_google_doc(args.destination) and not is_google_doc(args.source):
        doc_id = extract_doc_id_from_url(args.destination) or extract_doc_id(args.destination)
        creds = get_credentials()
        if args.diff:
            return diff_markdown_to_gdoc(args.source, doc_id, creds)
        return import_markdown_to_gdoc(args.source, doc_id, creds)

    if args.source and args.destination and is_google_doc(args.source) and not is_google_doc(args.destination):
        doc_id = extract_doc_id_from_url(args.source) or extract_doc_id(args.source)
        creds = get_credentials()
        if args.diff:
            return diff_gdoc_to_markdown(doc_id, args.destination, creds)
        return export_gdoc_to_markdown(doc_id, args.destination, creds)

    if args.create and args.source:
        creds = get_credentials()
        return create_new_gdoc_from_markdown(args.source, creds, url_only=args.url_only)

    if args.create_empty:
        return create_empty_document(get_credentials())

    if args.source and args.list_revisions:
        return list_revisions(extract_doc_id_from_url(args.source) or extract_doc_id(args.source), get_credentials())
    if args.source and args.list_comments:
        return list_comments(extract_doc_id_from_url(args.source) or extract_doc_id(args.source), get_credentials(), args.unresolved_only)
    if args.source and args.lock:
        return lock_document(extract_doc_id_from_url(args.source) or extract_doc_id(args.source), get_credentials(), args.lock_reason)
    if args.source and args.unlock:
        return unlock_document(extract_doc_id_from_url(args.source) or extract_doc_id(args.source), get_credentials())
    if args.source and args.lock_status:
        return check_gdoc_frozen_status(extract_doc_id_from_url(args.source) or extract_doc_id(args.source), get_credentials())

    if args.directory:
        return create_directory_document(args.directory, Path.cwd(), args.directory_title or Path(args.directory[0]).stem)

    if args.source and args.destination and args.diff:
        if is_confluence_page(args.source):
            return diff_confluence_to_markdown(args.source, args.destination, get_confluence_client(secrets_file_path))
        if is_confluence_page(args.destination):
            return diff_markdown_to_confluence(args.source, args.destination, get_confluence_client(secrets_file_path))

    if args.lock_confluence and args.source:
        return lock_confluence_page(parse_confluence_destination(args.source), get_confluence_client(secrets_file_path), get_confluence_permissions_config(secrets_file_path))
    if args.unlock_confluence and args.source:
        return unlock_confluence_page(parse_confluence_destination(args.source), get_confluence_client(secrets_file_path))
    if args.confluence_lock_status and args.source:
        return check_confluence_lock_status(parse_confluence_destination(args.source), get_confluence_client(secrets_file_path))

    if args.source and args.destination and is_confluence_page(args.destination):
        return import_markdown_to_confluence(args.source, parse_confluence_destination(args.destination)['page_id'], get_confluence_client(secrets_file_path))
    if args.source and args.destination and is_confluence_page(args.source):
        from .confluence import export_confluence_to_markdown
        return export_confluence_to_markdown(parse_confluence_destination(args.source)['page_id'], args.destination, get_confluence_client(secrets_file_path))

    if args.source and not args.destination:
        parser.error(f"unknown command: {args.source}")

    parser.print_help()
