import io
import json
import os
import sys
import tempfile
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

from .auth import get_credentials
from .frontmatter import extract_frontmatter_metadata, strip_frontmatter_for_remote_sync, update_frontmatter_gdoc_url


def _sync_compare_content(content):
    """Canonical form used only to detect remote changes."""
    import re
    content = strip_frontmatter_for_remote_sync(content).replace("\r\n", "\n").replace("\r", "\n").strip()
    content = re.sub(r'(?<!~)~([^~\n]+)~(?!~)', r'~~\1~~', content)
    return content.rstrip("\n")


def get_drive_file_version(doc_id, creds):
    """Return Google Drive's monotonically increasing file version."""
    drive_service = build('drive', 'v3', credentials=creds)
    metadata = drive_service.files().get(fileId=doc_id, fields='version').execute()
    return metadata.get('version')


def check_gdoc_frozen_status(doc_id: str, creds) -> bool:
    """Check if a Google Doc is frozen (locked) at runtime."""
    try:
        # Use the existing check_lock_status function
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Get file metadata
        file_metadata = drive_service.files().get(
            fileId=doc_id,
            fields='contentRestrictions'
        ).execute()
        
        # Check if there are content restrictions
        restrictions = file_metadata.get('contentRestrictions', [])
        if restrictions:
            for restriction in restrictions:
                if restriction.get('readOnly') == True:
                    return True
        
        return False
    except Exception:
        # If we can't check, assume not frozen
        return False


def list_revisions(doc_id: str, creds):
    """List all revisions for a Google Doc."""
    try:
        # Build the Drive service
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Get all revisions
        revisions = drive_service.revisions().list(
            fileId=doc_id,
            fields='revisions(id,modifiedTime,lastModifyingUser,keepForever)',
            pageSize=1000
        ).execute()
        
        revision_list = revisions.get('revisions', [])
        
        if not revision_list:
            print("No revisions found.")
            return
        
        print(f"\nRevision History for Document: {doc_id}")
        print("=" * 80)
        
        for rev in reversed(revision_list):  # Show newest first
            rev_id = rev['id']
            mod_time = rev.get('modifiedTime', 'Unknown')
            user = rev.get('lastModifyingUser', {})
            user_name = user.get('displayName', 'Unknown')
            user_email = user.get('emailAddress', '')
            kept = ' [KEPT]' if rev.get('keepForever', False) else ''
            
            print(f"\nRevision ID: {rev_id}{kept}")
            print(f"  Modified: {mod_time}")
            print(f"  By: {user_name}", end='')
            if user_email:
                print(f" ({user_email})", end='')
            print()
        
        print("\n" + "=" * 80)
        print(f"Total revisions: {len(revision_list)}")
        print("\nNote: Google Drive API does not support exporting historical revisions")
        print("in Markdown format. To view revision content, open the document in")
        print("Google Docs and use File > Version history.")
        
    except HttpError as error:
        print(f"An error occurred: {error}", file=sys.stderr)
        sys.exit(1)


def lock_document(doc_id: str, creds, reason: str = "Document locked via mdsync"):
    """Lock a Google Doc to prevent editing."""
    try:
        # Build the Drive service
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Set content restrictions to lock the file
        file_metadata = {
            'contentRestrictions': [{
                'readOnly': True,
                'reason': reason
            }]
        }
        
        updated_file = drive_service.files().update(
            fileId=doc_id,
            body=file_metadata,
            fields='contentRestrictions'
        ).execute()
        
        print(f"✓ Document locked: {doc_id}")
        print(f"  Reason: {reason}")
        print(f"  URL: https://docs.google.com/document/d/{doc_id}/edit")
        
    except HttpError as error:
        print(f"An error occurred: {error}", file=sys.stderr)
        if error.resp.status == 403:
            print("Note: You need editor access to lock/unlock documents.", file=sys.stderr)
        sys.exit(1)


def unlock_document(doc_id: str, creds):
    """Unlock a Google Doc to allow editing."""
    try:
        # Build the Drive service
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Remove content restrictions to unlock the file
        file_metadata = {
            'contentRestrictions': [{
                'readOnly': False
            }]
        }
        
        updated_file = drive_service.files().update(
            fileId=doc_id,
            body=file_metadata,
            fields='contentRestrictions'
        ).execute()
        
        print(f"✓ Document unlocked: {doc_id}")
        print(f"  URL: https://docs.google.com/document/d/{doc_id}/edit")
        
    except HttpError as error:
        print(f"An error occurred: {error}", file=sys.stderr)
        if error.resp.status == 403:
            print("Note: You need editor access to lock/unlock documents.", file=sys.stderr)
        sys.exit(1)


def check_lock_status(doc_id: str, creds):
    """Check if a Google Doc is locked."""
    try:
        # Build the Drive service
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Get file metadata including content restrictions
        file = drive_service.files().get(
            fileId=doc_id,
            fields='name,contentRestrictions,owners,modifiedTime'
        ).execute()
        
        doc_name = file.get('name', 'Unknown')
        content_restrictions = file.get('contentRestrictions', [])
        owners = file.get('owners', [])
        modified_time = file.get('modifiedTime', 'Unknown')
        
        print(f"\nDocument: {doc_name}")
        print(f"ID: {doc_id}")
        print(f"URL: https://docs.google.com/document/d/{doc_id}/edit")
        print(f"Last Modified: {modified_time}")
        
        if owners:
            owner_names = ', '.join([o.get('displayName', 'Unknown') for o in owners])
            print(f"Owner(s): {owner_names}")
        
        print("\n" + "=" * 60)
        
        if content_restrictions:
            for restriction in content_restrictions:
                if restriction.get('readOnly', False):
                    print("🔒 Status: LOCKED")
                    reason = restriction.get('reason', 'No reason provided')
                    print(f"   Reason: {reason}")
                    restricting_user = restriction.get('restrictingUser', {})
                    if restricting_user:
                        print(f"   Locked by: {restricting_user.get('displayName', 'Unknown')}")
                    restrict_time = restriction.get('restrictionTime', '')
                    if restrict_time:
                        print(f"   Locked at: {restrict_time}")
                else:
                    print("🔓 Status: UNLOCKED")
        else:
            print("🔓 Status: UNLOCKED")
        
        print("=" * 60)
        
    except HttpError as error:
        print(f"An error occurred: {error}", file=sys.stderr)
        sys.exit(1)


def list_comments(doc_id: str, creds, unresolved_only: bool = False, output_format: str = 'text'):
    """List all comments from a Google Doc."""
    try:
        # Build the Drive service
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Get file name
        file = drive_service.files().get(fileId=doc_id, fields='name').execute()
        doc_name = file.get('name', 'Unknown')
        
        # Get all comments
        comments_result = drive_service.comments().list(
            fileId=doc_id,
            fields='comments(id,content,author,createdTime,modifiedTime,resolved,quotedFileContent,replies,anchor)',
            pageSize=100
        ).execute()
        
        all_comments = comments_result.get('comments', [])
        
        # Handle pagination
        while 'nextPageToken' in comments_result:
            comments_result = drive_service.comments().list(
                fileId=doc_id,
                fields='comments(id,content,author,createdTime,modifiedTime,resolved,quotedFileContent,replies,anchor)',
                pageSize=100,
                pageToken=comments_result['nextPageToken']
            ).execute()
            all_comments.extend(comments_result.get('comments', []))
        
        # Filter if needed
        if unresolved_only:
            all_comments = [c for c in all_comments if not c.get('resolved', False)]
        
        if not all_comments:
            if unresolved_only:
                print("No unresolved comments found.")
            else:
                print("No comments found.")
            return
        
        # Output based on format
        if output_format == 'json':
            print(json.dumps(all_comments, indent=2))
        elif output_format == 'markdown':
            print_comments_markdown(doc_name, doc_id, all_comments)
        else:  # text
            print_comments_text(doc_name, doc_id, all_comments)
        
    except HttpError as error:
        print(f"An error occurred: {error}", file=sys.stderr)
        sys.exit(1)


def print_comments_text(doc_name: str, doc_id: str, comments: list):
    """Print comments in text format."""
    print(f"\nComments for: {doc_name}")
    print(f"Document ID: {doc_id}")
    print(f"URL: https://docs.google.com/document/d/{doc_id}/edit")
    print(f"Total comments: {len(comments)}")
    print("=" * 80)
    
    for i, comment in enumerate(comments, 1):
        author = comment.get('author', {})
        author_name = author.get('displayName', 'Unknown')
        created = comment.get('createdTime', 'Unknown')
        resolved = comment.get('resolved', False)
        content = comment.get('content', '')
        quoted = comment.get('quotedFileContent', {}).get('value', '')
        
        status = "✓ RESOLVED" if resolved else "○ OPEN"
        
        print(f"\n[{i}] {status}")
        print(f"Author: {author_name}")
        print(f"Created: {created}")
        
        if quoted:
            print(f"Quoted text: \"{quoted}\"")
        
        print(f"Comment: {content}")
        
        # Print replies
        replies = comment.get('replies', [])
        if replies:
            print(f"  Replies ({len(replies)}):")
            for reply in replies:
                reply_author = reply.get('author', {}).get('displayName', 'Unknown')
                reply_content = reply.get('content', '')
                reply_time = reply.get('createdTime', 'Unknown')
                print(f"    → {reply_author} ({reply_time}): {reply_content}")
        
        print("-" * 80)


def print_comments_markdown(doc_name: str, doc_id: str, comments: list):
    """Print comments in Markdown format."""
    print(f"# Comments: {doc_name}\n")
    print(f"**Document ID:** {doc_id}  ")
    print(f"**URL:** [Open Document](https://docs.google.com/document/d/{doc_id}/edit)  ")
    print(f"**Total comments:** {len(comments)}\n")
    print("---\n")
    
    for i, comment in enumerate(comments, 1):
        author = comment.get('author', {})
        author_name = author.get('displayName', 'Unknown')
        created = comment.get('createdTime', 'Unknown')
        resolved = comment.get('resolved', False)
        content = comment.get('content', '')
        quoted = comment.get('quotedFileContent', {}).get('value', '')
        
        status = "✓ RESOLVED" if resolved else "○ OPEN"
        
        print(f"## Comment {i} - {status}\n")
        print(f"**Author:** {author_name}  ")
        print(f"**Created:** {created}\n")
        
        if quoted:
            print(f"> {quoted}\n")
        
        print(f"{content}\n")
        
        # Print replies
        replies = comment.get('replies', [])
        if replies:
            print(f"### Replies ({len(replies)})\n")
            for reply in replies:
                reply_author = reply.get('author', {}).get('displayName', 'Unknown')
                reply_content = reply.get('content', '')
                reply_time = reply.get('createdTime', 'Unknown')
                print(f"- **{reply_author}** ({reply_time}): {reply_content}")
            print()
        
        print("---\n")


def export_gdoc_to_markdown(doc_id: str, creds, output_path: str = None) -> str:
    """Export a Google Doc to Markdown format."""
    try:
        # Build the Drive service (used for export)
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Fetch document metadata (title, created/modified dates)
        file_metadata = drive_service.files().get(
            fileId=doc_id,
            fields='name,createdTime,modifiedTime'
        ).execute()
        
        doc_title = file_metadata.get('name', '')
        created_time = file_metadata.get('createdTime', '')
        modified_time = file_metadata.get('modifiedTime', '')
        
        # Export the current version as Markdown
        # Google Docs now supports text/markdown as an export format
        request = drive_service.files().export_media(
            fileId=doc_id,
            mimeType='text/markdown'
        )
        
        file_stream = io.BytesIO()
        downloader = MediaIoBaseDownload(file_stream, request)
        
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        # Get the content as string
        markdown_content = file_stream.getvalue().decode('utf-8')
        
        # If output path provided, add frontmatter with gdoc_url and metadata
        if output_path:
            gdoc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
            
            # Check if content already has frontmatter
            if markdown_content.startswith('---'):
                # Parse existing frontmatter and add/update metadata
                try:
                    import frontmatter
                    post = frontmatter.loads(markdown_content)
                    post.metadata['title'] = doc_title
                    post.metadata['gdoc_url'] = gdoc_url
                    post.metadata['gdoc_created'] = created_time
                    post.metadata['gdoc_modified'] = modified_time
                    frontmatter_content = frontmatter.dumps(post)
                except Exception:
                    # Fallback: prepend frontmatter
                    frontmatter_content = f"---\ntitle: {doc_title}\ngdoc_url: {gdoc_url}\ngdoc_created: {created_time}\ngdoc_modified: {modified_time}\n---\n\n{markdown_content}"
            else:
                # Add frontmatter to the content
                frontmatter_content = f"---\ntitle: {doc_title}\ngdoc_url: {gdoc_url}\ngdoc_created: {created_time}\ngdoc_modified: {modified_time}\n---\n\n{markdown_content}"
            
            # Write to file
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(frontmatter_content)
            
            return frontmatter_content
        else:
            return markdown_content
        
    except HttpError as error:
        print(f"An error occurred: {error}", file=sys.stderr)
        sys.exit(1)


def _flatten_document_tabs(tabs):
    """Return all document tabs, including nested child tabs, in display order."""
    result = []

    def visit(tab):
        result.append(tab)
        for child in tab.get('childTabs', []):
            visit(child)

    for tab in tabs or []:
        visit(tab)
    return result


def _get_document_tabs(docs_service, doc_id: str):
    """Fetch all Google Docs tabs, including their document bodies."""
    document = docs_service.documents().get(
        documentId=doc_id,
        includeTabsContent=True,
    ).execute()
    return document, _flatten_document_tabs(document.get('tabs', []))


def _find_tab_by_id(tabs, tab_id: str):
    """Find a tab by its immutable Google Docs tab ID."""
    for tab in tabs:
        if tab.get('tabProperties', {}).get('tabId') == tab_id:
            return tab
    return None


def _tab_title(tab: dict) -> str:
    """Return a tab's user-visible title."""
    return tab.get('tabProperties', {}).get('title', '')


def _tab_text(tab: dict) -> str:
    """Extract plain text from a document tab body."""
    body = tab.get('documentTab', {}).get('body', {})
    text = []
    for element in body.get('content', []):
        paragraph = element.get('paragraph')
        if paragraph:
            for child in paragraph.get('elements', []):
                run = child.get('textRun')
                if run:
                    text.append(run.get('content', ''))
            continue

        # Tables contain nested table rows/cells rather than paragraph elements
        # directly. Include their text so the no-op comparison remains useful.
        table = element.get('table')
        if table:
            for row in table.get('tableRows', []):
                for cell in row.get('tableCells', []):
                    cell_body = {'documentTab': {'body': {'content': cell.get('content', [])}}}
                    text.append(_tab_text(cell_body))
    return ''.join(text)


def _find_tab_by_title(tabs, title: str):
    """Find a tab by exact, case-insensitive title."""
    wanted = title.strip().casefold()
    for tab in tabs:
        if _tab_title(tab).strip().casefold() == wanted:
            return tab
    return None


def _converted_document_body(markdown_content: str, creds):
    """Convert Markdown through Drive and return its first tab's document body."""
    temp_path = None
    temp_doc_id = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as temp:
            temp.write(markdown_content)
            temp_path = temp.name

        drive_service = build('drive', 'v3', credentials=creds)
        docs_service = build('docs', 'v1', credentials=creds)
        media = MediaFileUpload(temp_path, mimetype='text/markdown', resumable=True)
        created = drive_service.files().create(
            body={'name': 'mdsync-tab-conversion', 'mimeType': 'application/vnd.google-apps.document'},
            media_body=media,
            fields='id',
        ).execute()
        temp_doc_id = created['id']
        _, tabs = _get_document_tabs(docs_service, temp_doc_id)
        if not tabs:
            raise RuntimeError('Converted Markdown document has no tabs')
        return tabs[0]
    finally:
        if temp_doc_id:
            try:
                drive_service.files().delete(fileId=temp_doc_id).execute()
            except Exception:
                pass
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def _replace_tab_content(docs_service, doc_id: str, tab_id: str, source_tab: dict):
    """Replace one target tab with the converted content of another document tab."""
    _, target_tabs = _get_document_tabs(docs_service, doc_id)
    target = _find_tab_by_id(target_tabs, tab_id)
    if not target:
        raise ValueError(f'Tab not found: {tab_id}')

    target_body = target.get('documentTab', {}).get('body', {}).get('content', [])
    font_family = _prevailing_font_family(target)
    if not target_body:
        raise ValueError(f'Tab has no writable body: {tab_id}')

    requests = []
    last_element = target_body[-1]
    end_index = last_element.get('endIndex', 1)
    if end_index > 2:
        requests.append({
            'deleteContentRange': {
                'range': {'startIndex': 1, 'endIndex': end_index - 1, 'tabId': tab_id}
            }
        })

    source_body = source_tab.get('documentTab', {}).get('body', {}).get('content', [])
    source_text = _tab_text(source_tab)
    if source_text:
        requests.append({
            'insertText': {
                'location': {'index': 1, 'tabId': tab_id},
                'text': source_text,
            }
        })

    if requests:
        docs_service.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()

    # Re-read after insertion because indexes and the final paragraph changed.
    _, updated_tabs = _get_document_tabs(docs_service, doc_id)
    updated_target = next((tab for tab in updated_tabs if tab.get('tabProperties', {}).get('tabId') == tab_id), None)
    if not updated_target:
        raise ValueError(f'Tab disappeared during update: {tab_id}')

    # Reapply paragraph and basic text styles from the converted source.
    formatting_requests = []
    font_requests = []
    position = 1
    for element in source_body:
        paragraph = element.get('paragraph')
        if not paragraph:
            continue
        paragraph_text = ''.join(
            child.get('textRun', {}).get('content', '')
            for child in paragraph.get('elements', [])
            if 'textRun' in child
        )
        if not paragraph_text:
            continue
        paragraph_end = position + len(paragraph_text)
        paragraph_style = paragraph.get('paragraphStyle', {})
        named_style = paragraph_style.get('namedStyleType')
        if named_style:
            formatting_requests.append({
                'updateParagraphStyle': {
                    'range': {'startIndex': position, 'endIndex': paragraph_end, 'tabId': tab_id},
                    'paragraphStyle': {'namedStyleType': named_style},
                    'fields': 'namedStyleType',
                }
            })
        text_position = position
        for child in paragraph.get('elements', []):
            run = child.get('textRun')
            if not run:
                continue
            run_text = run.get('content', '')
            run_end = text_position + len(run_text)
            style = run.get('textStyle', {})
            fields = []
            update = {}
            for key in ('bold', 'italic', 'underline', 'strikethrough'):
                if key in style:
                    update[key] = style[key]
                    fields.append(key)
            if font_family:
                update.pop('weightedFontFamily', None)
            if fields:
                formatting_requests.append({
                    'updateTextStyle': {
                        'range': {'startIndex': text_position, 'endIndex': run_end, 'tabId': tab_id},
                        'textStyle': update,
                        'fields': ','.join(fields),
                    }
                })
            if font_family and run_text:
                font_requests.append({
                    'updateTextStyle': {
                        'range': {'startIndex': text_position, 'endIndex': run_end, 'tabId': tab_id},
                        'textStyle': {'weightedFontFamily': {'fontFamily': font_family}},
                        'fields': 'weightedFontFamily',
                    }
                })
            text_position = run_end
        position = paragraph_end

    formatting_requests.extend(font_requests)
    if formatting_requests:
        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={'requests': formatting_requests},
        ).execute()




def _paragraph_spans(tab):
    spans = []
    for element in tab.get("documentTab", {}).get("body", {}).get("content", []):
        if not isinstance(element, dict):
            continue
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        text = "".join(child.get("textRun", {}).get("content", "") for child in paragraph.get("elements", []) if "textRun" in child)
        spans.append({"start": element.get("startIndex", 1), "end": element.get("endIndex", element.get("startIndex", 1) + len(text)), "text": text, "paragraph": paragraph})
    if spans and spans[-1]["text"] == "\n":
        spans.pop()
    return spans


def _markdown_lines(content):
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    # Google Docs always exposes its terminal paragraph as a lone newline.
    # It is document structure, not a Markdown content line, so do not let it
    # create a phantom diff when a tab is empty.
    if not content.strip():
        return []
    return content.splitlines(keepends=True)



def _source_paragraphs(source_tab):
    """Return source paragraphs, excluding Docs' terminal structural paragraph."""
    paragraphs = []
    body = source_tab.get("documentTab", {}).get("body", {}).get("content", [])
    for element in body:
        if not isinstance(element, dict):
            continue
        paragraph = element.get("paragraph")
        if paragraph is not None:
            text = "".join(
                child.get("textRun", {}).get("content", "")
                for child in paragraph.get("elements", [])
                if "textRun" in child
            )
            paragraphs.append((paragraph, text))
    if paragraphs and paragraphs[-1][1] == "\n":
        paragraphs.pop()
    return paragraphs


def _source_text(source_tab, source_markdown=None):
    """Extract converted text, removing importer-only blank paragraphs.

    The Google Docs Markdown importer currently inserts an empty paragraph
    between consecutive Markdown lines. Those paragraphs are not present in
    the Markdown source and must not become part of the target document.
    Intentional blank Markdown lines are restored from ``source_markdown``.
    """
    paragraphs = [
        (paragraph, text)
        for paragraph, text in _source_paragraphs(source_tab)
        if text != "\n"
    ]
    if source_markdown is None:
        return "".join(text for _, text in paragraphs)

    lines = _markdown_lines(source_markdown)
    result = []
    paragraph_index = 0
    for line in lines:
        if line.strip() == "":
            result.append("\n")
            continue
        if paragraph_index >= len(paragraphs):
            raise RuntimeError("Converted Markdown paragraphs do not match source Markdown")
        result.append(paragraphs[paragraph_index][1])
        paragraph_index += 1
    if paragraph_index != len(paragraphs):
        raise RuntimeError("Converted Markdown paragraphs do not match source Markdown")
    return "".join(result)


def _source_formatting_requests(source_tab, start_index, tab_id, source_markdown):
    requests = []
    position = start_index
    source_lines = _markdown_lines(source_markdown)
    line_index = 0
    paragraphs = [
        (paragraph, text)
        for paragraph, text in _source_paragraphs(source_tab)
        if text != "\n"
    ]
    paragraph_index = 0
    bullet_group = None

    def flush_bullet_group():
        nonlocal bullet_group
        if bullet_group is None:
            return
        group_start, group_end, preset = bullet_group
        requests.append({
            "createParagraphBullets": {
                "range": {"startIndex": group_start, "endIndex": group_end, "tabId": tab_id},
                "bulletPreset": preset,
            }
        })
        bullet_group = None

    for source_line in source_lines:
        if source_line.strip() == "":
            flush_bullet_group()
            position += 1
            line_index += 1
            continue
        if paragraph_index >= len(paragraphs):
            raise RuntimeError("Converted Markdown paragraphs do not match source Markdown")
        paragraph, paragraph_text = paragraphs[paragraph_index]
        paragraph_index += 1
        end = position + len(paragraph_text)
        named = paragraph.get("paragraphStyle", {}).get("namedStyleType")
        if named:
            requests.append({"updateParagraphStyle": {"range": {"startIndex": position, "endIndex": end, "tabId": tab_id}, "paragraphStyle": {"namedStyleType": named}, "fields": "namedStyleType"}})

        if paragraph.get("bullet"):
            source_line = source_lines[line_index].lstrip()
            preset = "BULLET_CHECKBOX" if source_line.startswith(("- [ ] ", "- [x] ", "- [X] ")) else "BULLET_DISC_CIRCLE_SQUARE"
            if bullet_group is not None and bullet_group[2] == preset and bullet_group[1] == position:
                bullet_group = (bullet_group[0], end, preset)
            else:
                flush_bullet_group()
                bullet_group = (position, end, preset)
        else:
            flush_bullet_group()

        text_position = position
        for child in paragraph.get("elements", []):
            run = child.get("textRun")
            if not run:
                continue
            run_text = run.get("content", "")
            run_end = text_position + len(run_text)
            style = run.get("textStyle", {})
            update = {k: style[k] for k in ("bold", "italic", "underline", "strikethrough") if k in style}
            if update:
                requests.append({"updateTextStyle": {"range": {"startIndex": text_position, "endIndex": run_end, "tabId": tab_id}, "textStyle": update, "fields": ",".join(update.keys())}})
            text_position = run_end
        position = end
        line_index += 1

    if paragraph_index != len(paragraphs):
        raise RuntimeError("Converted Markdown paragraphs do not match source Markdown")
    flush_bullet_group()
    # Apply the target document's font last. Structural requests such as
    # createParagraphBullets can cause Docs to recalculate paragraph styles;
    # applying the inherited font after those requests makes the font choice
    # authoritative instead of allowing the importer/default (often Arial) to
    # win.
    requests.extend(font_requests)
    return requests


def _is_html_comment(line):
    """Return whether a line is a standalone HTML comment.

    HTML comments are non-rendering Markdown/HTML content, so Google Docs'
    Markdown importer correctly omits them instead of creating a paragraph.
    """
    stripped = line.strip()
    return stripped.startswith("<!--") and stripped.endswith("-->")


def _empty_checkbox_source_tab():
    """Build the minimal Docs-like structure for an empty Markdown checkbox.

    The Drive Markdown importer drops ``- [ ]`` when there is no item text,
    but the target document can still represent it as a checkbox paragraph.
    """
    return {
        "documentTab": {
            "body": {
                "content": [{
                    "startIndex": 1,
                    "endIndex": 2,
                    "paragraph": {
                        "elements": [{"textRun": {"content": "\n"}}],
                        "bullet": {"listId": "mdsync-empty-checkbox"},
                    },
                }]
            }
        }
    }


def _is_thematic_break(line):
    """Return whether a standalone Markdown line is a thematic break."""
    stripped = line.strip()
    if len(stripped) < 3:
        return False
    for marker in ("-", "*", "_"):
        if all(char == marker or char.isspace() for char in stripped) and stripped.count(marker) >= 3:
            return True
    return False


def _converted_markdown_lines(lines, creds):
    """Convert each Markdown line independently so Docs cannot merge adjacent structures."""
    converted = []
    for line in lines:
        if line.strip() == "":
            converted.append((None, "\n", line))
            continue
        if _is_html_comment(line):
            # HTML comments are intentionally not rendered by Google Docs.
            # Keep them out of the remote document while retaining the local
            # Markdown line so a comment-only insertion is a no-op remotely.
            converted.append((None, "", line))
            continue
        if line.strip() in ("- [ ]", "- [x]", "- [X]") and line.rstrip().endswith("]"):
            converted.append((_empty_checkbox_source_tab(), "\n", line))
            continue
        source_tab = _converted_document_body(line, creds)
        paragraphs = [(p, text) for p, text in _source_paragraphs(source_tab) if text != "\n"]
        if len(paragraphs) != 1:
            if len(paragraphs) == 0 and _is_thematic_break(line):
                # A Markdown thematic break has no paragraph in the importer.
                # Represent it as a structural sentinel; _format_converted_lines
                # turns the inserted paragraph into a Docs horizontal rule.
                converted.append((None, "\n", line))
                continue
            raise RuntimeError(
                f"Markdown line converted to {len(paragraphs)} Google Docs paragraphs: {line!r}"
            )
        converted.append((source_tab, paragraphs[0][1], line))
    return converted


def _paragraph_font_family(paragraph):
    if not isinstance(paragraph, dict):
        return None
    elements = paragraph.get('elements', [])
    if not isinstance(elements, list):
        return None
    for element in elements:
        if not isinstance(element, dict):
            continue
        run = element.get('textRun')
        if not isinstance(run, dict):
            continue
        style = run.get('textStyle', {})
        if not isinstance(style, dict):
            continue
        family = style.get('weightedFontFamily', {})
        if isinstance(family, dict):
            family = family.get('fontFamily')
            if family:
                return family
    return None


def _prevailing_font_family(tab, preferred_index=None):
    paragraphs = [(p, text) for p, text in _source_paragraphs(tab) if text != '\n']
    if not paragraphs:
        return None
    if preferred_index is not None:
        for paragraph, text in paragraphs:
            if not isinstance(paragraph, dict):
                continue
            if paragraph.get('startIndex', 1) <= preferred_index <= paragraph.get('endIndex', preferred_index):
                family = _paragraph_font_family(paragraph)
                if family:
                    return family
    for paragraph, _ in paragraphs:
        if not isinstance(paragraph, dict):
            continue
        family = _paragraph_font_family(paragraph)
        if family:
            return family
    return None


def _format_converted_lines(converted, start_index, tab_id, font_family=None):
    requests = []
    font_requests = []
    position = start_index
    bullet_group = None

    def flush_bullet_group():
        nonlocal bullet_group
        if bullet_group is None:
            return
        group_start, group_end, preset = bullet_group
        requests.append({
            "createParagraphBullets": {
                "range": {"startIndex": group_start, "endIndex": group_end, "tabId": tab_id},
                "bulletPreset": preset,
            }
        })
        bullet_group = None

    for source_tab, paragraph_text, source_line in converted:
        if font_family and paragraph_text:
            font_requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": position, "endIndex": position + len(paragraph_text), "tabId": tab_id},
                    "textStyle": {"weightedFontFamily": {"fontFamily": font_family}},
                    "fields": "weightedFontFamily",
                }
            })
        if source_tab is None:
            flush_bullet_group()
            if paragraph_text and _is_thematic_break(source_line):
                requests.append({
                    "updateParagraphStyle": {
                        "range": {"startIndex": position, "endIndex": position + 1, "tabId": tab_id},
                        "paragraphStyle": {
                            "borderBottom": {
                                "color": {"color": {"rgbColor": {"red": 0, "green": 0, "blue": 0}}},
                                "width": {"magnitude": 1, "unit": "PT"},
                                "padding": {"magnitude": 1, "unit": "PT"},
                                "dashStyle": "SOLID",
                            }
                        },
                        "fields": "borderBottom",
                    }
                })
            if paragraph_text:
                position += len(paragraph_text)
            continue

        paragraphs = _source_paragraphs(source_tab)
        paragraph = next((p for p, text in paragraphs if text != "\n"), None)
        if paragraph is None and source_line.strip() in ("- [ ]", "- [x]", "- [X]"):
            # The Markdown importer drops empty task text into a paragraph
            # containing only its terminating newline. Keep that paragraph
            # here so it can still be converted to a Docs checkbox.
            paragraph = paragraphs[0][0] if paragraphs else None
        if paragraph is None:
            # Structural Markdown such as a thematic break has no paragraph
            # to style. Its text representation has already been inserted;
            # just advance the position for subsequent lines.
            position += len(paragraph_text)
            continue
        end = position + len(paragraph_text)
        named = paragraph.get("paragraphStyle", {}).get("namedStyleType")
        if named:
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": position, "endIndex": end, "tabId": tab_id},
                    "paragraphStyle": {"namedStyleType": named},
                    "fields": "namedStyleType",
                }
            })

        if paragraph.get("bullet"):
            stripped = source_line.lstrip()
            preset = (
                "BULLET_CHECKBOX"
                if stripped.startswith(("- [ ] ", "- [x] ", "- [X] "))
                else "BULLET_DISC_CIRCLE_SQUARE"
            )
            if bullet_group is not None and bullet_group[2] == preset and bullet_group[1] == position:
                bullet_group = (bullet_group[0], end, preset)
            else:
                flush_bullet_group()
                bullet_group = (position, end, preset)
        else:
            flush_bullet_group()
            # insertText inherits the paragraph/list properties at the insertion
            # point. A plain Markdown line inserted at the start of an existing
            # list can therefore become a list item even though its source line
            # is not a list. Explicitly remove inherited bullets from this range.
            requests.append({
                "deleteParagraphBullets": {
                    "range": {"startIndex": position, "endIndex": end, "tabId": tab_id}
                }
            })

        text_position = position
        for child in paragraph.get("elements", []):
            run = child.get("textRun")
            if not run:
                continue
            run_text = run.get("content", "")
            run_end = text_position + len(run_text)
            style = run.get("textStyle", {})
            update = {
                k: style[k]
                for k in ("bold", "italic", "underline", "strikethrough")
                if k in style
            }
            if update:
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": text_position, "endIndex": run_end, "tabId": tab_id},
                        "textStyle": update,
                        "fields": ",".join(update.keys()),
                    }
                })
            text_position = run_end
        position = end

    flush_bullet_group()
    # Font inheritance must be applied after all structural formatting.
    # Otherwise Google Docs can restore the paragraph/list default font.
    requests.extend(font_requests)
    return requests


def apply_markdown_diff_to_tab(docs_service, doc_id, tab_id, baseline, local_content, creds):
    import difflib
    _, tabs = _get_document_tabs(docs_service, doc_id)
    if not _find_tab_by_id(tabs, tab_id):
        raise ValueError(f"Tab not found: {tab_id}")
    remote_content = export_tab_to_markdown(docs_service, doc_id, tab_id)
    # A newly-created Google Docs tab contains its mandatory terminating newline,
    # while its logical content is empty. Treat that as the empty baseline used
    # when creating a local tab, so the first directory push can populate it.
    remote_matches_baseline = _sync_compare_content(remote_content) == _sync_compare_content(baseline)
    if not remote_matches_baseline and not (
        not _sync_compare_content(baseline) and not _sync_compare_content(remote_content)
    ):
        raise RuntimeError("Google Docs tab changed since the last pull; pull again before pushing to avoid overwriting remote changes.")
    base_lines = _markdown_lines(baseline)
    local_lines = _markdown_lines(local_content)
    changed = [op for op in difflib.SequenceMatcher(a=base_lines, b=local_lines, autojunk=False).get_opcodes() if op[0] != "equal"]
    if not changed:
        return False
    for tag, i1, i2, j1, j2 in reversed(changed):
        _, tabs = _get_document_tabs(docs_service, doc_id)
        target = _find_tab_by_id(tabs, tab_id)
        spans = _paragraph_spans(target)
        if i1 > len(spans) or i2 > len(spans):
            raise RuntimeError("Could not map Markdown diff to Google Docs paragraphs")
        font_family = _prevailing_font_family(target, spans[i1]["start"] if i1 < len(spans) else None)
        if i1 == i2:
            insert_at = spans[i1]["start"] if i1 < len(spans) else (spans[-1]["end"] - 1 if spans else 1)
            delete_start = delete_end = insert_at
        else:
            delete_start = spans[i1]["start"]
            # A Google Docs paragraph's endIndex includes its terminating
            # newline. deleteContentRange is not allowed to consume that
            # paragraph newline, so keep the final newline in the document and
            # replace only the paragraph content.
            delete_end = spans[i2 - 1]["end"] - 1
            insert_at = delete_start
        new_lines = local_lines[j1:j2]
        converted = _converted_markdown_lines(new_lines, creds)
        source_text = "".join(text for _, text, _ in converted)
        requests = []
        if delete_end > delete_start:
            requests.append({"deleteContentRange": {"range": {"startIndex": delete_start, "endIndex": delete_end, "tabId": tab_id}}})
        if source_text:
            requests.append({"insertText": {"location": {"index": insert_at, "tabId": tab_id}, "text": source_text}})
        if requests:
            docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
        if source_text:
            formatting = _format_converted_lines(converted, insert_at, tab_id, font_family)
            if formatting:
                docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": formatting}).execute()
    return True

def create_document_tab(docs_service, doc_id, title, parent_tab_id=None):
    """Create a real Google Docs tab, optionally nested under a parent tab."""
    properties = {'title': title}
    if parent_tab_id:
        properties['parentTabId'] = parent_tab_id
    response = docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={'requests': [{'addDocumentTab': {'tabProperties': properties}}]},
    ).execute()
    for reply in response.get('replies', []):
        properties = reply.get('addDocumentTab', {}).get('tabProperties', {})
        tab_id = properties.get('tabId')
        if tab_id:
            return tab_id
    _, tabs = _get_document_tabs(docs_service, doc_id)
    tab = _find_tab_by_title(tabs, title)
    if not tab:
        raise RuntimeError(f"Google Docs did not return the created tab '{title}'")
    return tab['tabProperties']['tabId']


def _apply_markdown_inline_style(text, style):
    """Apply Markdown inline styling without consuming surrounding whitespace."""
    if not text:
        return text

    leading_len = len(text) - len(text.lstrip())
    trailing_len = len(text) - len(text.rstrip())
    leading = text[:leading_len]
    trailing = text[len(text) - trailing_len:] if trailing_len else ''
    core_end = len(text) - trailing_len if trailing_len else len(text)
    core = text[leading_len:core_end]

    if not core:
        return text

    link = style.get('link', {}).get('url')
    if link:
        core = f'[{core}]({link})'
    if style.get('bold'):
        core = f'**{core}**'
    if style.get('italic'):
        core = f'*{core}*'
    if style.get('strikethrough'):
        core = f'~~{core}~~'
    if style.get('underline') and not link:
        core = f'<u>{core}</u>'
    return leading + core + trailing


def _markdown_inline_from_runs(runs):
    """Convert Docs text runs to Markdown while preserving inline style boundaries."""
    result = []
    for element in runs:
        run = element.get('textRun')
        if not run:
            continue
        raw_text = run.get('content', '')
        style = run.get('textStyle', {})
        text = raw_text.rstrip('\n')
        newline = '\n' * (len(raw_text) - len(text))
        result.append(_apply_markdown_inline_style(text, style) + newline)
    return ''.join(result)


def _is_horizontal_rule_paragraph(paragraph):
    """Return whether a Docs paragraph is styled as a horizontal rule."""
    return bool(paragraph.get("paragraphStyle", {}).get("borderBottom"))


def _paragraph_to_markdown(paragraph):
    if _is_horizontal_rule_paragraph(paragraph):
        return "---"
    text = _markdown_inline_from_runs(paragraph.get('elements', []))
    style = paragraph.get('paragraphStyle', {})
    named = style.get('namedStyleType', '')
    if named.startswith('HEADING_'):
        try:
            level = int(named.split('_', 1)[1])
        except (ValueError, IndexError):
            level = 1
        return f"{'#' * level} {text.rstrip()}"
    bullet = paragraph.get('bullet')
    if bullet:
        nesting = bullet.get('nestingLevel', 0)
        # The Docs API exposes checklist items as checkbox bullet lists, but
        # does not expose the checked state on Paragraph/Bullet. Represent
        # list items as Markdown task-list items so the checklist semantics
        # survive the tab export. Checked-state preservation requires a
        # separate export path and is intentionally handled separately.
        return f"{'  ' * nesting}- [ ] {text.rstrip()}"
    return text.rstrip('\n')


def export_tab_to_markdown(docs_service, doc_id, tab_id):
    """Export one Google Docs tab to Markdown using the Docs API."""
    _, tabs = _get_document_tabs(docs_service, doc_id)
    tab = _find_tab_by_id(tabs, tab_id)
    if not tab:
        raise ValueError(f'Tab not found: {tab_id}')
    lines = []
    for element in tab.get('documentTab', {}).get('body', {}).get('content', []):
        paragraph = element.get('paragraph')
        if paragraph:
            lines.append(_paragraph_to_markdown(paragraph))
            continue
        table = element.get('table')
        if table:
            rows = []
            for row in table.get('tableRows', []):
                cells = []
                for cell in row.get('tableCells', []):
                    cell_text = []
                    for cell_element in cell.get('content', []):
                        cell_para = cell_element.get('paragraph')
                        if cell_para:
                            cell_text.append(_paragraph_to_markdown(cell_para))
                    cells.append(' '.join(x for x in cell_text if x))
                rows.append(cells)
            if rows:
                lines.append('| ' + ' | '.join(rows[0]) + ' |')
                lines.append('| ' + ' | '.join('---' for _ in rows[0]) + ' |')
                for row in rows[1:]:
                    lines.append('| ' + ' | '.join(row) + ' |')
    return '\n'.join(lines).rstrip() + '\n'


def create_tabbed_document_from_markdown(markdown_files, title, creds, quiet=False):
    """Create one Google Doc and one real tab for each Markdown file."""
    docs_service = build('docs', 'v1', credentials=creds)
    doc = docs_service.documents().create(body={'title': title}).execute()
    doc_id = doc['documentId']
    _, initial_tabs = _get_document_tabs(docs_service, doc_id)
    default_tab = initial_tabs[0] if initial_tabs else None
    for index, markdown_path in enumerate(markdown_files):
        content = Path(markdown_path).read_text(encoding='utf-8')
        metadata = extract_frontmatter_metadata(content)
        tab_title = metadata.get('title') or Path(markdown_path).stem
        if index == 0 and default_tab:
            tab_id = default_tab['tabProperties']['tabId']
            docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={'requests': [{
                    'updateDocumentTabProperties': {
                        'tabProperties': {'tabId': tab_id, 'title': tab_title},
                        'fields': 'title',
                    }
                }]}
            ).execute()
        else:
            tab_id = create_document_tab(docs_service, doc_id, tab_title)
        source_tab = _converted_document_body(strip_frontmatter_for_remote_sync(content), creds)
        _replace_tab_content(docs_service, doc_id, tab_id, source_tab)
        from .directory import set_tab_metadata
        set_tab_metadata(markdown_path, tab_id, tab_title)
        if not quiet:
            print(f"  ✓ {markdown_path} -> {tab_title}")
    return doc_id

def import_markdown_to_gdoc(markdown_path: str, doc_id: str, creds, quiet: bool = False):
    """Import a Markdown file to a Google Doc, updating a matching batch tab when configured."""
    try:
        # Read the markdown file
        with open(markdown_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
        
        # Strip frontmatter for Google Doc (frontmatter is for markdown processing only)
        content_for_gdoc = strip_frontmatter_for_remote_sync(markdown_content)

        # Batch files map to individual Google Docs tabs by the stored heading title.
        metadata = extract_frontmatter_metadata(markdown_content)
        batch_info = metadata.get('batch')
        if isinstance(batch_info, dict) and batch_info.get('doc_id') == doc_id:
            heading_title = batch_info.get('heading_title')
            if heading_title:
                docs_service = build('docs', 'v1', credentials=creds)
                _, tabs = _get_document_tabs(docs_service, doc_id)
                target_tab = _find_tab_by_title(tabs, heading_title)
                if not target_tab:
                    raise ValueError(
                        f"Google Docs tab '{heading_title}' was not found in document {doc_id}"
                    )

                source_tab = _converted_document_body(content_for_gdoc, creds)
                source_text = _tab_text(source_tab)
                target_text = _tab_text(target_tab)
                if source_text != target_text:
                    _replace_tab_content(
                        docs_service,
                        doc_id,
                        target_tab['tabProperties']['tabId'],
                        source_tab,
                    )
                    if not quiet:
                        print(f"Successfully updated Google Doc tab: {heading_title}")
                elif not quiet:
                    print(f"No changes for Google Doc tab: {heading_title}")

                gdoc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
                update_frontmatter_gdoc_url(markdown_path, gdoc_url)
                return
        
        # Non-batch files retain the existing whole-document sync path.
        # Create a temporary file with the cleaned content
        temp_file_path = f"{markdown_path}.temp"
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            f.write(content_for_gdoc)
        
        try:
            # Build the Drive service
            drive_service = build('drive', 'v3', credentials=creds)
            
            # Update the document by uploading the cleaned markdown
            media = MediaFileUpload(
                temp_file_path,
                mimetype='text/markdown',
                resumable=True
            )
            
            file_metadata = {
                'mimeType': 'application/vnd.google-apps.document'
            }
            
            updated_file = drive_service.files().update(
                fileId=doc_id,
                media_body=media,
                body=file_metadata
            ).execute()
            
            if not quiet:
                print(f"Successfully updated Google Doc: {doc_id}")
            
            # Update frontmatter with sync date
            gdoc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
            update_frontmatter_gdoc_url(markdown_path, gdoc_url)
            
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
        
    except HttpError as error:
        print(f"An error occurred: {error}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"Error: Markdown file not found: {markdown_path}", file=sys.stderr)
        sys.exit(1)


def create_new_gdoc_from_markdown_with_title(markdown_path: str, title: str, creds, quiet: bool = False) -> str:
    """Create a new Google Doc from a Markdown file with a specific title."""
    try:
        # Read the markdown file
        with open(markdown_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
        
        # Strip frontmatter for Google Doc (frontmatter is for markdown processing only)
        content_for_gdoc = strip_frontmatter_for_remote_sync(markdown_content)
        
        # Create a temporary file with the cleaned content
        temp_file_path = f"{markdown_path}.temp"
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            f.write(content_for_gdoc)
        
        try:
            # Build the Drive service
            drive_service = build('drive', 'v3', credentials=creds)
            
            # Upload the cleaned markdown file and convert it to Google Docs format
            file_metadata = {
                'name': title,
                'mimeType': 'application/vnd.google-apps.document'
            }
            
            media = MediaFileUpload(
                temp_file_path,
                mimetype='text/markdown',
                resumable=True
            )
            
            # Create the Google Doc
            file = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            
            doc_id = file.get('id')
            
            if not quiet:
                print(f'Created new Google Doc with ID: {doc_id}')
                print(f'URL: https://docs.google.com/document/d/{doc_id}/edit')
            
            return doc_id
            
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                
    except Exception as e:
        print(f'Error creating Google Doc: {e}', file=sys.stderr)
        return None


def create_new_gdoc_from_markdown(markdown_path: str, creds, quiet: bool = False) -> str:
    """Create a new Google Doc from a Markdown file."""
    try:
        # Read the markdown file
        with open(markdown_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
        
        # Extract frontmatter metadata for title
        metadata = extract_frontmatter_metadata(markdown_content)
        
        # Strip frontmatter for Google Doc (frontmatter is for markdown processing only)
        content_for_gdoc = strip_frontmatter_for_remote_sync(markdown_content)
        
        # Create a temporary file with the cleaned content
        temp_file_path = f"{markdown_path}.temp"
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            f.write(content_for_gdoc)
        
        try:
            # Build the Drive service
            drive_service = build('drive', 'v3', credentials=creds)
            
            # Get the document name (frontmatter title takes priority over filename)
            doc_name = metadata.get('title') or Path(markdown_path).stem
            
            # Upload the cleaned markdown file and convert it to Google Docs format
            file_metadata = {
                'name': doc_name,
                'mimeType': 'application/vnd.google-apps.document'
            }
            
            media = MediaFileUpload(
                temp_file_path,
                mimetype='text/markdown',
                resumable=True
            )
            
            file = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            
            doc_id = file.get('id')
            gdoc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
            
            # Update frontmatter with the Google Doc URL
            update_frontmatter_gdoc_url(markdown_path, gdoc_url)
            
            if not quiet:
                print(f"Created new Google Doc with ID: {doc_id}")
                print(f"URL: {gdoc_url}")
                print(f"Updated frontmatter in {markdown_path}")
            
            return doc_id
        
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
        
    except HttpError as error:
        print(f"An error occurred: {error}", file=sys.stderr)
        sys.exit(1)


def create_empty_document(title: str, quiet: bool = False) -> str:
    """
    Create an empty Google Doc for tab management.
    
    This function creates a new Google Doc that can be used as a container
    for multiple tabs. Each tab will be added as an H1 heading, which
    Google Docs displays as separate tabs in the UI.
    
    Args:
        title (str): Title for the new document
        quiet (bool): If True, suppress output messages
        
    Returns:
        str: Document ID of the created document, or None if failed
        
    Example:
        doc_id = create_empty_document("Project Documentation")
        # Returns: "1ABC123def456GHI789jkl"
    """
    try:
        creds = get_credentials()
        docs_service = build('docs', 'v1', credentials=creds)
        
        # Create empty document
        doc = docs_service.documents().create(body={'title': title}).execute()
        doc_id = doc['documentId']
        
        if not quiet:
            print(f'✓ Created empty document: "{title}"')
            print(f'  Document ID: {doc_id}')
            print(f'  URL: https://docs.google.com/document/d/{doc_id}/edit')
        
        return doc_id
        
    except HttpError as error:
        print(f'Google API error: {error}', file=sys.stderr)
        return None
    except Exception as e:
        print(f'Error creating empty document: {e}', file=sys.stderr)
        return None
