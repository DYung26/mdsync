import os
import re
import sys
import time
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .auth import get_credentials
from .diffing import show_diff
from .frontmatter import extract_frontmatter_metadata, strip_frontmatter_for_remote_sync, update_frontmatter_metadata
from .gdocs import (
    _get_document_tabs,
    _find_tab_by_title,
    _tab_text,
    create_new_gdoc_from_markdown_with_title,
)
from .toc import check_for_formatted_h1_headings, create_working_toc_links_in_gdoc, extract_h1_headings_from_markdown, generate_table_of_contents


def generate_batch_id(title: str) -> str:
    """
    Generate a clean, short batch ID from a title.
    
    Examples:
        "Software Assurance Maturity Plan" -> "samp"
        "API Documentation" -> "api-docs"
        "Project Alpha v2.0" -> "project-alpha-v2-0"
    
    Args:
        title (str): Human-readable batch title
        
    Returns:
        str: Clean batch ID suitable for command-line usage
    """
    import re
    
    # Convert to lowercase and replace spaces/special chars with hyphens
    clean_id = re.sub(r'[^a-zA-Z0-9\s-]', '', title.lower())
    clean_id = re.sub(r'\s+', '-', clean_id.strip())
    
    # Remove multiple consecutive hyphens
    clean_id = re.sub(r'-+', '-', clean_id)
    
    # Remove leading/trailing hyphens
    clean_id = clean_id.strip('-')
    
    # If empty or too short, generate from first letters
    if len(clean_id) < 3:
        words = title.split()
        if len(words) >= 2:
            clean_id = ''.join(word[0].lower() for word in words[:3])
        else:
            clean_id = title.lower()[:8]
    
    # Ensure it starts with a letter
    if clean_id and not clean_id[0].isalpha():
        clean_id = 'batch-' + clean_id
    
    return clean_id or 'batch'


def create_batch_document_simple(markdown_files: list, title: str, quiet: bool = False, include_headers: bool = False, include_horizontal_sep: bool = False, include_title: bool = True, include_toc: bool = False) -> str:
    """
    Create a Google Doc by combining multiple markdown files client-side.
    
    This function combines multiple markdown files into a single temporary markdown
    file, then syncs that as one Google Doc using the existing, proven sync logic.
    This preserves all formatting and avoids the complexity of individual heading management.
    
    Args:
        markdown_files (list): List of markdown file paths
        title (str): Title for the new document
        quiet (bool): If True, suppress output messages
        include_headers (bool): If True, include file titles as headers in the document
        include_horizontal_sep (bool): If True, add horizontal separators between files
        include_title (bool): If True, include the batch title as the main document title
        include_toc (bool): If True, generate and include a table of contents for H1 headings
        
    Returns:
        str: Document ID of the created document, or None if failed
    """
    try:
        import tempfile
        import uuid
        
        if not quiet:
            print(f'Combining {len(markdown_files)} files into single document...')
        
        # Create a temporary combined markdown file
        combined_content = ""
        all_h1_headings = []  # Collect all H1 headings for TOC generation
        
        # Note: We don't add the title to content when include_title=True
        # because the document title will be set separately
        
        for i, markdown_path in enumerate(markdown_files):
            if not quiet:
                print(f'  Processing {i+1}/{len(markdown_files)}: {markdown_path}')
            
            try:
                # Read markdown file
                with open(markdown_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
                
                # Extract metadata
                metadata = extract_frontmatter_metadata(markdown_content)
                
                # Get heading title from frontmatter or filename
                heading_title = metadata.get('title')
                if not heading_title:
                    heading_title = Path(markdown_path).stem.replace('_', ' ').replace('-', ' ').title()
                
                # Strip frontmatter for the combined document
                content_for_combined = strip_frontmatter_for_remote_sync(markdown_content)
                
                # Check for formatted H1 headings that might break TOC
                if include_toc:
                    check_for_formatted_h1_headings(content_for_combined, quiet=quiet)
                
                # Collect H1 headings for TOC if requested
                if include_toc:
                    if include_headers:
                        # When using headers, the file title becomes an H1 heading
                        all_h1_headings.append(heading_title)
                    else:
                        # Without headers, collect H1 headings from the content
                        h1_headings = extract_h1_headings_from_markdown(content_for_combined)
                        all_h1_headings.extend(h1_headings)
                
                # Add content with or without headers
                if include_headers:
                    # When using headers, make the file title an H1 heading for proper anchor creation
                    combined_content += f"# {heading_title}\n\n{content_for_combined}\n\n"
                else:
                    # Without headers, ensure any existing H1 headings remain as H1
                    # (they should already be H1 from the original markdown)
                    combined_content += f"{content_for_combined}\n\n"
                
                # Add horizontal separator after each file (except the last one) if requested
                if include_horizontal_sep and i < len(markdown_files) - 1:
                    combined_content += "\n\n---\n\n"
                
                if not quiet:
                    print(f'    ✓ Added: {heading_title}')
                    
            except Exception as e:
                if not quiet:
                    print(f'    Error processing {markdown_path}: {e}')
                continue
        
        # Generate and prepend table of contents if requested
        if include_toc and all_h1_headings:
            toc_content = generate_table_of_contents(all_h1_headings)
            combined_content = toc_content + "\n" + combined_content
            if not quiet:
                print(f'✓ Generated table of contents with {len(all_h1_headings)} headings')
        
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8')
        temp_file.write(combined_content)
        temp_file.close()
        
        try:
            # Use the existing create_new_gdoc_from_markdown function
            creds = get_credentials()
            doc_id = create_new_gdoc_from_markdown_with_title(temp_file.name, title, creds, quiet=quiet)
            
            if doc_id and not quiet:
                print(f'✓ Created batch document: "{title}"')
                print(f'  Document ID: {doc_id}')
                print(f'  URL: https://docs.google.com/document/d/{doc_id}/edit')
            
            # Create working TOC links if requested
            if doc_id and include_toc and all_h1_headings:
                if not quiet:
                    print("⏳ Waiting for document to be ready...")
                import time
                time.sleep(2)  # Give Google Docs time to process the document
                create_working_toc_links_in_gdoc(doc_id, all_h1_headings, creds, quiet=quiet)
            
            # Update frontmatter for all individual files with batch information
            if doc_id:
                # Generate a clean batch ID from the title
                batch_id = generate_batch_id(title)
                for i, markdown_path in enumerate(markdown_files):
                    try:
                        # Read the file again to get current content
                        with open(markdown_path, 'r', encoding='utf-8') as f:
                            current_content = f.read()
                        
                        # Extract metadata to get heading title
                        metadata = extract_frontmatter_metadata(current_content)
                        heading_title = metadata.get('title')
                        if not heading_title:
                            heading_title = Path(markdown_path).stem.replace('_', ' ').replace('-', ' ').title()
                        
                        # Create batch info
                        from datetime import datetime
                        current_time = datetime.now().isoformat()
                        
                        batch_info = {
                            'batch_id': batch_id,
                            'batch_title': title,
                            'doc_id': doc_id,
                            'heading_title': heading_title,
                            'url': f"https://docs.google.com/document/d/{doc_id}/edit",
                            'created': current_time,
                            'modified': current_time
                        }
                        
                        # Update frontmatter
                        updated_content = update_frontmatter_metadata(current_content, {'batch': batch_info})
                        with open(markdown_path, 'w', encoding='utf-8') as f:
                            f.write(updated_content)
                        
                        if not quiet:
                            print(f'  ✓ Updated frontmatter in {os.path.basename(markdown_path)}')
                            
                    except Exception as e:
                        if not quiet:
                            print(f'  Warning: Could not update frontmatter in {os.path.basename(markdown_path)}: {e}')
            
            # Print batch info at the end
            if doc_id and not quiet:
                print(f"\nbatch: {title}")
                print(f"batch_id: {batch_id}")
                print(f"URL: https://docs.google.com/document/d/{doc_id}/edit")
            
            return doc_id
            
        finally:
            # Clean up temporary file
            os.unlink(temp_file.name)
        
    except Exception as e:
        print(f'Error creating batch document: {e}', file=sys.stderr)
        return None


def diff_batch_against_gdoc(doc_id: str, quiet: bool = False) -> None:
    """
    Diff an entire batch against its Google Doc.
    
    This function finds all markdown files that belong to the specified batch
    document and compares each one against its corresponding section in the
    Google Doc, showing differences for each heading section.
    
    Args:
        doc_id (str): Google Doc ID to diff against
        quiet (bool): If True, suppress output messages
        
    Example:
        diff_batch_against_gdoc("1ABC123def456")
        # Shows differences for all files in the batch
    """
    try:
        from collections import defaultdict
        
        # Find all markdown files that belong to this batch
        batch_files = []
        for root, dirs, files in os.walk('.'):
            for file in files:
                if file.endswith('.md'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        metadata = extract_frontmatter_metadata(content)
                        
                        if 'batch' in metadata and isinstance(metadata['batch'], dict):
                            batch_info = metadata['batch']
                            if batch_info.get('doc_id') == doc_id:
                                batch_files.append({
                                    'file_path': file_path,
                                    'heading_title': batch_info.get('heading_title', 'Unknown'),
                                    'batch_info': batch_info
                                })
                    except Exception:
                        continue
        
        if not batch_files:
            if not quiet:
                print(f"No batch files found for document {doc_id}")
            return
        
        if not quiet:
            print(f"Diffing batch document {doc_id} against {len(batch_files)} files")
            print("=" * 60)
        
        # Get the Google Doc content
        creds = get_credentials()
        docs_service = build('docs', 'v1', credentials=creds)
        
        try:
            doc, tabs = _get_document_tabs(docs_service, doc_id)
            doc_title = doc.get('title', 'Unknown')
        except Exception as e:
            print(f"Error accessing Google Doc: {e}", file=sys.stderr)
            return
        
        if not quiet:
            print(f"Document: {doc_title}")
            print(f"URL: https://docs.google.com/document/d/{doc_id}/edit")
            print()
        
        # For each batch file, find its corresponding section in the Google Doc
        for file_info in batch_files:
            file_path = file_info['file_path']
            heading_title = file_info['heading_title']
            
            if not quiet:
                print(f"Checking: {os.path.basename(file_path)} -> {heading_title}")
            
            try:
                # Read the markdown file
                with open(file_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
                
                # Strip frontmatter for comparison
                content_for_gdoc = strip_frontmatter_for_remote_sync(markdown_content)
                
                # Find the corresponding Google Docs tab by its stored title.
                target_tab = _find_tab_by_title(tabs, heading_title)
                heading_section = _tab_text(target_tab) if target_tab else ""
                
                if target_tab:
                    # Compare the content in the tab only.
                    if content_for_gdoc.strip() != heading_section.strip():
                        if not quiet:
                            print(f"  ⚠️  Differences found in '{heading_title}'")
                            show_diff(
                                heading_section,
                                content_for_gdoc,
                                f"Google Doc '{heading_title}'",
                                f"Markdown '{os.path.basename(file_path)}'"
                            )
                        else:
                            print(f"DIFF: {file_path}")
                    else:
                        if not quiet:
                            print(f"  ✓  No differences in '{heading_title}'")
                else:
                    if not quiet:
                        print(f"  ❌  Heading '{heading_title}' not found in Google Doc")
                    else:
                        print(f"MISSING: {file_path}")
                
                if not quiet:
                    print()
                    
            except Exception as e:
                if not quiet:
                    print(f"  Error processing {file_path}: {e}")
                else:
                    print(f"ERROR: {file_path}")
        
    except Exception as e:
        print(f'Error diffing batch: {e}', file=sys.stderr)


def update_batch_by_name(batch_identifier: str, quiet: bool = False) -> None:
    """
    Update an existing batch by finding all files that belong to it.
    
    This function can find a batch by either:
    1. Batch ID (searches for files with matching batch_id)
    2. Batch title (searches for files with matching batch_title)
    3. Google Doc ID (searches for files with matching doc_id)
    
    It then updates the Google Doc with all the found files in the correct order.
    
    Args:
        batch_identifier (str): Batch ID, batch title, or Google Doc ID
        quiet (bool): If True, suppress output messages
        
    Example:
        update_batch_by_name("samp")  # Batch ID
        update_batch_by_name("Software Assurance Maturity Plan")  # Batch title
        update_batch_by_name("1ABC123def456")  # Google Doc ID
    """
    try:
        # Find all markdown files that belong to this batch
        batch_files = []
        doc_id = None
        batch_title = None
        
        # First pass: find the target batch
        target_batch_info = None
        for root, dirs, files in os.walk('.'):
            for file in files:
                if file.endswith('.md'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        metadata = extract_frontmatter_metadata(content)
                        
                        if 'batch' in metadata and isinstance(metadata['batch'], dict):
                            batch_info = metadata['batch']
                            batch_doc_id = batch_info.get('doc_id', '')
                            batch_name = batch_info.get('batch_title', '')
                            batch_id = batch_info.get('batch_id', '')
                            
                            # Check if this file belongs to the specified batch
                            # Match by batch_id, doc_id, or batch_title (exact or partial)
                            if (batch_identifier == batch_id or
                                batch_identifier == batch_doc_id or 
                                batch_identifier.lower() == batch_name.lower() or
                                (len(batch_identifier) > 3 and batch_identifier.lower() in batch_name.lower())):
                                
                                # Store the target batch info from first match
                                if target_batch_info is None:
                                    target_batch_info = batch_info
                                    doc_id = batch_doc_id
                                    batch_title = batch_name
                                    
                    except Exception:
                        continue
        
        if target_batch_info is None:
            if not quiet:
                print(f"No batch found matching '{batch_identifier}'")
                print("Available batches:")
                list_batch_groupings('.', quiet=True)
            return
        
        # Second pass: find all files that belong to the target batch
        for root, dirs, files in os.walk('.'):
            for file in files:
                if file.endswith('.md'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        metadata = extract_frontmatter_metadata(content)
                        
                        if 'batch' in metadata and isinstance(metadata['batch'], dict):
                            batch_info = metadata['batch']
                            batch_doc_id = batch_info.get('doc_id', '')
                            
                            # Only include files from the target batch
                            if batch_doc_id == doc_id:
                                batch_files.append({
                                    'file_path': file_path,
                                    'heading_title': batch_info.get('heading_title', 'Unknown'),
                                    'batch_info': batch_info
                                })
                                    
                    except Exception:
                        continue
        
        if not batch_files:
            if not quiet:
                print(f"No batch files found for '{batch_identifier}'")
                print("Available batches:")
                list_batch_groupings('.', quiet=True)
            return
        
        if not doc_id:
            if not quiet:
                print(f"Error: Could not determine document ID for batch '{batch_identifier}'")
            return
        
        if not quiet:
            print(f"Updating batch: {batch_title}")
            print(f"Document ID: {doc_id}")
            print(f"Found {len(batch_files)} files to update")
            print("=" * 50)
        
        # Sort files by their original order (we'll use filename as a proxy for now)
        # In a real implementation, you might want to store the original order in frontmatter
        batch_files.sort(key=lambda x: x['file_path'])
        
        # Get credentials
        creds = get_credentials()
        docs_service = build('docs', 'v1', credentials=creds)
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Clear the existing document content (keep the title)
        try:
            doc = docs_service.documents().get(documentId=doc_id).execute()
            doc_title = doc.get('title', 'Unknown')
            
            # Delete all content except the first paragraph (which contains the title)
            body_content = doc.get('body', {}).get('content', [])
            if len(body_content) > 1:
                # Delete everything after the first paragraph
                # Find the last element that's not just a newline
                last_content_index = 1
                for i in range(len(body_content) - 1, 0, -1):
                    element = body_content[i]
                    if 'paragraph' in element or 'table' in element or 'tableOfContents' in element:
                        last_content_index = i
                        break
                
                # Get the end index of the last content element, excluding trailing newline
                last_element = body_content[last_content_index]
                end_index = last_element.get('endIndex', 1)
                
                # Ensure we don't include the final newline character
                if end_index > 1:
                    end_index = end_index - 1
                
                delete_requests = [{
                    'deleteContentRange': {
                        'range': {
                            'startIndex': body_content[1].get('startIndex', 1),
                            'endIndex': end_index
                        }
                    }
                }]
                
                docs_service.documents().batchUpdate(
                    documentId=doc_id,
                    body={'requests': delete_requests}
                ).execute()
                
        except Exception as e:
            if not quiet:
                print(f"Warning: Could not clear existing content: {e}")
        
        # Now add each file as a heading section in order
        for i, file_info in enumerate(batch_files):
            file_path = file_info['file_path']
            heading_title = file_info['heading_title']
            
            if not quiet:
                print(f"  Processing {i+1}/{len(batch_files)}: {os.path.basename(file_path)} -> {heading_title}")
            
            try:
                # Read markdown file
                with open(file_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
                
                # Extract metadata
                metadata = extract_frontmatter_metadata(markdown_content)
                
                # Strip frontmatter for Google Doc
                content_for_gdoc = strip_frontmatter_for_remote_sync(markdown_content)
                
                # Create a temporary markdown file with the heading
                temp_file_path = f"{file_path}.temp_batch_update"
                with open(temp_file_path, 'w', encoding='utf-8') as f:
                    f.write(f"# {heading_title}\n\n{content_for_gdoc}")
                
                try:
                    # Convert markdown to Google Doc format using Drive API
                    media = MediaFileUpload(
                        temp_file_path,
                        mimetype='text/markdown',
                        resumable=True
                    )
                    
                    file_metadata = {
                        'mimeType': 'application/vnd.google-apps.document'
                    }
                    
                    # Create a temporary document with converted content
                    temp_doc = docs_service.documents().create(body={'title': f'temp_batch_update_{i}'}).execute()
                    temp_doc_id = temp_doc['documentId']
                    
                    # Update the temporary doc with converted content
                    drive_service.files().update(
                        fileId=temp_doc_id,
                        media_body=media,
                        body=file_metadata
                    ).execute()
                    
                    # Get the converted content
                    temp_doc_content = docs_service.documents().get(documentId=temp_doc_id).execute()
                    
                    # Get current document content to find insertion point
                    current_doc = docs_service.documents().get(documentId=doc_id).execute()
                    insert_position = max(1, current_doc.get('body', {}).get('content', [{}])[-1].get('endIndex', 1) - 1)
                    
                    # Copy content from temp doc to main doc
                    body_content = temp_doc_content.get('body', {}).get('content', [])
                    
                    # First, insert all text content at once to avoid index issues
                    all_text = ''
                    for element in body_content:
                        if 'paragraph' in element:
                            para = element['paragraph']
                            for text_run in para.get('elements', []):
                                if 'textRun' in text_run:
                                    all_text += text_run['textRun'].get('content', '')
                    
                    # Insert all text at once
                    if all_text.strip():
                        docs_service.documents().batchUpdate(
                            documentId=doc_id,
                            body={'requests': [{
                                'insertText': {
                                    'location': {
                                        'index': insert_position
                                    },
                                    'text': all_text
                                }
                            }]}
                        ).execute()
                        
                        # Now apply formatting in a separate batch
                        requests = []
                        current_position = insert_position
                        
                        for element in body_content:
                            if 'paragraph' in element:
                                para = element['paragraph']
                                
                                # Extract text content
                                text = ''
                                for text_run in para.get('elements', []):
                                    if 'textRun' in text_run:
                                        text += text_run['textRun'].get('content', '')
                                
                                if text.strip():  # Only process non-empty paragraphs
                                    # Apply paragraph style if it exists
                                    if 'paragraphStyle' in para and 'namedStyleType' in para['paragraphStyle']:
                                        style_type = para['paragraphStyle']['namedStyleType']
                                        if style_type in ['HEADING_1', 'HEADING_2', 'HEADING_3', 'HEADING_4', 'HEADING_5', 'HEADING_6']:
                                            requests.append({
                                                'updateParagraphStyle': {
                                                    'range': {
                                                        'startIndex': current_position,
                                                        'endIndex': current_position + len(text)
                                                    },
                                                    'paragraphStyle': {
                                                        'namedStyleType': style_type
                                                    },
                                                    'fields': 'namedStyleType'
                                                }
                                            })
                                    
                                    # Apply text formatting for each text run
                                    text_start = current_position
                                    for text_run in para.get('elements', []):
                                        if 'textRun' in text_run:
                                            run_text = text_run['textRun'].get('content', '')
                                            run_length = len(run_text)
                                            
                                            if 'textStyle' in text_run['textRun']:
                                                text_style = text_run['textRun']['textStyle']
                                                
                                                # Apply bold formatting
                                                if text_style.get('bold'):
                                                    requests.append({
                                                        'updateTextStyle': {
                                                            'range': {
                                                                'startIndex': text_start,
                                                                'endIndex': text_start + run_length
                                                            },
                                                            'textStyle': {
                                                                'bold': True
                                                            },
                                                            'fields': 'bold'
                                                        }
                                                    })
                                                
                                                # Apply italic formatting
                                                if text_style.get('italic'):
                                                    requests.append({
                                                        'updateTextStyle': {
                                                            'range': {
                                                                'startIndex': text_start,
                                                                'endIndex': text_start + run_length
                                                            },
                                                            'textStyle': {
                                                                'italic': True
                                                            },
                                                            'fields': 'italic'
                                                        }
                                                    })
                                            
                                            text_start += run_length
                                    
                                    current_position += len(text)
                        
                        # Execute formatting requests
                        if requests:
                            docs_service.documents().batchUpdate(
                                documentId=doc_id,
                                body={'requests': requests}
                            ).execute()
                    
                    # Clean up temporary document
                    drive_service.files().delete(fileId=temp_doc_id).execute()
                    
                    if not quiet:
                        print(f"    ✓ Updated heading: {heading_title}")
                    
                finally:
                    # Clean up temporary file
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)
                        
            except Exception as e:
                if not quiet:
                    print(f"    Error processing {file_path}: {e}")
                continue
        
        if not quiet:
            print(f"✓ Batch update completed")
            print(f"URL: https://docs.google.com/document/d/{doc_id}/edit")
        else:
            print(f"https://docs.google.com/document/d/{doc_id}/edit")
        
    except Exception as e:
        print(f'Error updating batch: {e}', file=sys.stderr)


def find_heading_section_in_gdoc(doc: dict, heading_title: str) -> str:
    """
    Find a heading section in a Google Doc and return its content.
    
    Args:
        doc (dict): Google Doc document object
        heading_title (str): Title of the heading to find
        
    Returns:
        str: Content of the heading section, or empty string if not found
    """
    try:
        content = doc.get('body', {}).get('content', [])
        
        # Find the target heading
        heading_start = None
        heading_end = None
        
        for element in content:
            if 'paragraph' in element:
                para = element['paragraph']
                if 'paragraphStyle' in para:
                    style = para['paragraphStyle']
                    if 'namedStyleType' in style and style['namedStyleType'] == 'HEADING_1':
                        # Extract text from the paragraph
                        text = ''
                        for text_run in para.get('elements', []):
                            if 'textRun' in text_run:
                                text += text_run['textRun'].get('content', '')
                        
                        if heading_title.lower() in text.lower():
                            heading_start = element.get('endIndex', 0)
                            break
        
        if heading_start is None:
            return ""
        
        # Find the end of the heading section (next H1 heading or end of document)
        for element in content:
            if element.get('startIndex', 0) > heading_start:
                if 'paragraph' in element:
                    para = element['paragraph']
                    if 'paragraphStyle' in para:
                        style = para['paragraphStyle']
                        if 'namedStyleType' in style and style['namedStyleType'] == 'HEADING_1':
                            heading_end = element.get('startIndex', 0)
                            break
        
        if heading_end is None:
            # Use end of document
            heading_end = content[-1].get('endIndex', 0)
        
        # Extract the content between heading_start and heading_end
        section_content = ""
        for element in content:
            start_idx = element.get('startIndex', 0)
            end_idx = element.get('endIndex', 0)
            
            if start_idx >= heading_start and end_idx <= heading_end:
                if 'paragraph' in element:
                    para = element['paragraph']
                    for text_run in para.get('elements', []):
                        if 'textRun' in text_run:
                            section_content += text_run['textRun'].get('content', '')
        
        return section_content.strip()
        
    except Exception:
        return ""


def list_batch_groupings(directory: str, quiet: bool = False) -> None:
    """
    List all batch groupings in markdown files.
    
    This function scans a directory for markdown files and groups them by
    their batch metadata, showing which files belong to which batch documents.
    
    Args:
        directory (str): Directory to scan for markdown files
        quiet (bool): If True, suppress output messages
        
    Example:
        list_batch_groupings("/path/to/markdown/files")
        # Shows grouped batch information
    """
    try:
        from collections import defaultdict
        
        # Find all markdown files
        markdown_files = []
        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.endswith('.md'):
                    markdown_files.append(os.path.join(root, file))
        
        if not markdown_files:
            if not quiet:
                print("No markdown files found in directory")
            return
        
        # Group files by batch
        batch_groups = defaultdict(list)
        ungrouped_files = []
        
        for file_path in markdown_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                metadata = extract_frontmatter_metadata(content)
                
                if 'batch' in metadata and isinstance(metadata['batch'], dict):
                    batch_info = metadata['batch']
                    batch_id = batch_info.get('batch_id', 'unknown')
                    batch_groups[batch_id].append({
                        'file': file_path,
                        'batch_info': batch_info
                    })
                else:
                    ungrouped_files.append(file_path)
                    
            except Exception as e:
                if not quiet:
                    print(f"Warning: Could not read {file_path}: {e}")
                continue
        
        if not quiet:
            print(f"Batch Groupings in {directory}")
            print("=" * 50)
            
            if batch_groups:
                for batch_id, files in batch_groups.items():
                    # Get batch info from first file
                    batch_info = files[0]['batch_info']
                    batch_title = batch_info.get('batch_title', 'Unknown Title')
                    doc_id = batch_info.get('doc_id', 'Unknown')
                    
                    print(f"\nBatch: {batch_title}")
                    print(f"  Batch ID: {batch_id}")
                    print(f"  Document ID: {doc_id}")
                    print(f"  URL: https://docs.google.com/document/d/{doc_id}/edit")
                    print(f"  Files ({len(files)}):")
                    
                    for file_info in files:
                        file_path = file_info['file']
                        heading_title = file_info['batch_info'].get('heading_title', 'Unknown')
                        print(f"    - {os.path.basename(file_path)} -> {heading_title}")
            else:
                print("No batch groupings found")
            
            if ungrouped_files:
                print(f"\nUngrouped files ({len(ungrouped_files)}):")
                for file_path in ungrouped_files:
                    print(f"  - {os.path.basename(file_path)}")
        
        if quiet:
            for batch_id, files in batch_groups.items():
                batch_info = files[0]['batch_info']
                doc_id = batch_info.get('doc_id', '')
                if doc_id:
                    print(f"https://docs.google.com/document/d/{doc_id}/edit")
        
    except Exception as e:
        print(f'Error listing batch groupings: {e}', file=sys.stderr)
