---
name: mdsync-cli
description: Reference for mdsync commands that synchronize Markdown with Google Docs and Confluence, including credentials, options, and mutation boundaries.
---

# mdsync CLI Reference

## At a glance

- mdsync synchronizes Markdown files/directories with Google Docs and Confluence.
- Main form: mdsync SOURCE [DESTINATION]; subcommands include auth, repl, list, pull, push, sync, and resolve.
- Use --diff to inspect differences without pushing or pulling content.
- push, sync, lock, unlock, and create operations can change remote documents; verify the target before running them.
- Google OAuth credentials and Confluence secrets are local configuration, never repository content.
- The central docs-local-task-sync skill retains document synchronization workflows.

## Activation contract

Before acting under this skill, read this entire SKILL.md from the first line to the last. The summary above is orientation only; it does not replace the complete instructions below. If dependencies, credentials, or a target document cannot be verified, stop and report the exact blocker.

## Installation and prerequisites

Install the package from its repository with pip install -e . or install from the published package source. The console entrypoint is mdsync. Python dependencies include Google API/Auth libraries, requests, YAML/frontmatter parsing, and Confluence support. Without installation, the repository documents running mdsync.py directly after installing requirements.

Google OAuth credentials may be stored as credentials.json in the project directory, ~/.config/mdsync/credentials.json, or ~/.mdsync/credentials.json. First use may open a browser for OAuth authorization.

Confluence credentials and permissions are supplied through secrets.yaml. Use --secrets-file PATH to select a file; otherwise mdsync searches the current directory, ~/.config/mdsync/, and ~/.mdsync/. Do not commit credentials or secrets files.

## Command catalog

| Command | Purpose |
|---|---|
| mdsync auth | Force Google authentication. |
| mdsync repl | Start the interactive REPL. |
| mdsync list [PATH] [--format text|json] [--check-status] [--diff] | List Markdown files and their sync metadata/status. PATH defaults to the current directory. |
| mdsync pull SOURCE [DESTINATION] [--parent] [--tab TAB] | Pull Google Docs content into a Markdown file or directory. |
| mdsync push SOURCE | Push a Markdown file or directory to its linked Google Docs tabs. |
| mdsync sync SOURCE | Three-way sync a Markdown file or directory with Google Docs. |
| mdsync resolve FILE | Confirm a manually resolved Google Docs sync conflict. |
| mdsync SOURCE DESTINATION [--diff] | Import/export or compare Google Docs, Confluence pages, and Markdown files. |

### Google Docs operations

- A Google Doc can be identified by URL or document ID.
- Pull from a document URL/ID requires a local destination. A .md destination writes one file; a directory destination pulls the document's tabs.
- --tab TAB selects one Google Docs tab and requires a Markdown file destination.
- --parent treats the destination as a parent directory and creates/uses a document-title subdirectory inside it.
- A Markdown file/directory can carry frontmatter or directory metadata linking it to a Google Doc.
- push reads the existing document relationship from that metadata.
- sync performs a three-way comparison; after a manual conflict resolution, run resolve on the resolved Markdown file.
- --diff displays a comparison without applying the change.

### Create and administration options

- --create creates a new Google Doc from a Markdown source. -u/--url-only prints only the resulting URL for piping.
- --create-empty creates an empty Google Doc.
- --directory FILE... creates a new Google Doc with one real tab per Markdown file; --directory-title sets the document title.
- --list-revisions lists a Google Doc's revision history.
- --list-comments lists comments; --unresolved-only filters to unresolved comments.
- --lock, --unlock, and --lock-status manage Google Docs editing locks; --lock-reason supplies the lock reason.
- --lock-confluence, --unlock-confluence, and --confluence-lock-status manage Confluence page restrictions.
- Confluence destinations use confluence:SPACE/PAGE_ID. mdsync can import Markdown into Confluence or export a Confluence page to Markdown.
- --version prints the CLI version.

## Mutation boundaries

- auth changes local OAuth authorization state.
- pull writes local Markdown files.
- push writes remote Google Docs/Confluence content.
- sync may write either side to reconcile changes.
- resolve updates synchronization metadata after a manual resolution.
- --create and --create-empty create remote Google Docs.
- lock/unlock operations change remote editing restrictions.
- Use --diff or list --diff first when the intended change is not already clear. Do not infer a document ID or Confluence page from a filename alone.
- Confirm the exact remote document/page and local source before a write.

## Related workflow skill

Use docs-local-task-sync in the central skills repository for the decision process and safe sequence for local task/document synchronization. This skill is the CLI reference.
