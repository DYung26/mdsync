"""Interactive command interface for mdsync."""

import cmd
from pathlib import Path

from .tab_sync import pull_document_to_directory, pull_tab_to_file, push_directory, push_file


class MdsyncShell(cmd.Cmd):
    intro = 'mdsync interactive mode. Type help or ? to list commands.'
    prompt = 'mdsync> '

    def do_push(self, arg):
        """push PATH — push a Markdown file or directory."""
        path = Path(arg.strip())
        if not arg.strip():
            print('usage: push PATH')
            return
        try:
            push_directory(path) if path.is_dir() else push_file(path)
        except Exception as exc:
            print(f'Error: {exc}')

    def do_pull(self, arg):
        """pull PATH | URL DESTINATION — pull a linked file/directory or a Google Doc."""
        parts = arg.split(maxsplit=1)
        if not parts:
            print('usage: pull PATH | URL DESTINATION')
            return
        try:
            source = Path(parts[0])
            if source.is_dir():
                from .directory import get_document_id, load_directory_metadata
                doc_id = get_document_id(load_directory_metadata(source))
                if not doc_id:
                    raise ValueError(f'No Google Doc metadata found in {source}')
                pull_document_to_directory(doc_id, source)
                return
            if source.is_file():
                from .directory import get_document_id, get_tab_id, load_directory_metadata
                tab_id = get_tab_id(source)
                doc_id = get_document_id(load_directory_metadata(source.parent))
                if not (tab_id and doc_id):
                    raise ValueError(f'No directory tab metadata found for {source}')
                pull_tab_to_file(doc_id, tab_id, source)
                return
            if len(parts) != 2:
                raise ValueError('Google Doc pulls require a destination')
            from .urls import extract_doc_id, extract_doc_id_from_url
            doc_id = extract_doc_id_from_url(parts[0]) or extract_doc_id(parts[0])
            destination = Path(parts[1])
            if destination.suffix.lower() == '.md':
                from .gdocs import export_gdoc_to_markdown
                export_gdoc_to_markdown(doc_id, str(destination))
            else:
                pull_document_to_directory(doc_id, destination)
        except Exception as exc:
            print(f'Error: {exc}')

    def do_quit(self, arg):
        """quit — leave interactive mode."""
        return True

    def do_exit(self, arg):
        """exit — leave interactive mode."""
        return True

    def do_EOF(self, arg):
        print()
        return True


def run_repl():
    MdsyncShell().cmdloop()
