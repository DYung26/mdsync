import json
import os
import sys
from typing import Optional

from .auth import get_credentials
from .confluence import check_confluence_frozen_status, get_confluence_client, parse_confluence_destination
from .diffing import check_sync_status, show_diff
from .frontmatter import extract_frontmatter_metadata
from .gdocs import check_gdoc_frozen_status
from .urls import extract_doc_id, extract_doc_id_from_url


def list_markdown_files(path: str, output_format: str = 'text', check_status: bool = False, show_diff: bool = False, secrets_file_path: Optional[str] = None):
    """List frontmatter information for markdown files."""
    import glob
    import json
    
    # Determine if path is file or directory
    if os.path.isfile(path):
        if not path.endswith('.md'):
            print(f"Error: {path} is not a markdown file", file=sys.stderr)
            sys.exit(1)
        files = [path]
    elif os.path.isdir(path):
        # Find all markdown files in directory (exclude common build/cache directories)
        pattern = os.path.join(path, '**', '*.md')
        all_files = glob.glob(pattern, recursive=True)
        
        # Filter out common build/cache directories
        exclude_dirs = {'venv', 'env', '.venv', '.env', 'node_modules', '.git', '__pycache__', '.pytest_cache', 'build', 'dist', '.tox'}
        files = []
        for file_path in all_files:
            # Check if any part of the path contains excluded directories
            path_parts = file_path.split(os.sep)
            if not any(part in exclude_dirs for part in path_parts):
                files.append(file_path)
        
        if not files:
            print(f"No markdown files found in {path}")
            return
    else:
        print(f"Error: {path} is not a valid file or directory", file=sys.stderr)
        sys.exit(1)
    
    # Get credentials if status checking is enabled
    creds = None
    confluence = None
    if check_status:
        creds = get_credentials()
        confluence = get_confluence_client(secrets_file_path)
    
    results = []
    
    for file_path in files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Extract frontmatter metadata
            metadata = extract_frontmatter_metadata(content)
            
            # Determine export locations
            export_locations = []
            
            # Check Google Doc
            if metadata.get('gdoc_url'):
                gdoc_info = {
                    'type': 'Google Doc',
                    'url': metadata['gdoc_url']
                }
                
                if check_status and creds:
                    doc_id = extract_doc_id_from_url(metadata['gdoc_url'])
                    if doc_id:
                        is_frozen = check_gdoc_frozen_status(doc_id, creds)
                        gdoc_info['frozen'] = is_frozen
                        gdoc_info['status'] = 'frozen' if is_frozen else 'available'
                
                if show_diff and creds:
                    doc_id = extract_doc_id_from_url(metadata['gdoc_url'])
                    if doc_id:
                        sync_status = check_sync_status(file_path, 'Google Doc', doc_id, creds, confluence)
                        gdoc_info['sync_status'] = sync_status
                
                export_locations.append(gdoc_info)
            
            # Check Confluence
            if metadata.get('confluence_url'):
                confluence_info = {
                    'type': 'Confluence',
                    'url': metadata['confluence_url']
                }
                
                if check_status and confluence:
                    dest_info = parse_confluence_destination(metadata['confluence_url'])
                    page_id = dest_info.get('page_id')
                    if page_id:
                        is_frozen = check_confluence_frozen_status(page_id, confluence)
                        confluence_info['frozen'] = is_frozen
                        confluence_info['status'] = 'frozen' if is_frozen else 'available'
                
                if show_diff and confluence:
                    dest_info = parse_confluence_destination(metadata['confluence_url'])
                    page_id = dest_info.get('page_id')
                    if page_id:
                        sync_status = check_sync_status(file_path, 'Confluence', page_id, creds, confluence)
                        confluence_info['sync_status'] = sync_status
                
                export_locations.append(confluence_info)
            
            # Check Batch Document
            if metadata.get('batch') and isinstance(metadata['batch'], dict):
                batch_info = metadata['batch']
                batch_url = batch_info.get('url')
                batch_title = batch_info.get('batch_title', 'Unknown Batch')
                heading_title = batch_info.get('heading_title', 'Unknown Heading')
                
                if batch_url:
                    batch_info_display = {
                        'type': f'Batch Document ({batch_title})',
                        'url': batch_url,
                        'heading': heading_title
                    }
                    
                    if check_status and creds:
                        doc_id = batch_info.get('doc_id')
                        if doc_id:
                            is_frozen = check_gdoc_frozen_status(doc_id, creds)
                            batch_info_display['frozen'] = is_frozen
                            batch_info_display['status'] = 'frozen' if is_frozen else 'available'
                    
                    export_locations.append(batch_info_display)
            
            file_info = {
                'file': file_path,
                'title': metadata.get('title'),
                'labels': metadata.get('labels', []),
                'export_locations': export_locations
            }
            
            results.append(file_info)
            
        except Exception as e:
            print(f"Error reading {file_path}: {e}", file=sys.stderr)
            continue
    
    # Display results
    if output_format == 'json':
        print(json.dumps(results, indent=2))
    else:
        display_frontmatter_info(results, check_status, show_diff)


def display_frontmatter_info(results, check_status: bool = False, show_diff: bool = False):
    """Display frontmatter information in a readable format."""
    if not results:
        print("No markdown files with frontmatter found")
        return
    
    # Group results by batch and individual exports
    batch_groups = {}
    individual_files = []
    
    for info in results:
        # Check if this file is part of a batch
        batch_info = None
        for location in info['export_locations']:
            if 'Batch Document' in location['type']:
                batch_info = location
                break
        
        if batch_info:
            # Extract batch key (doc_id from URL)
            batch_url = batch_info['url']
            batch_key = batch_url.split('/d/')[-1].split('/')[0] if '/d/' in batch_url else batch_url
            
            if batch_key not in batch_groups:
                batch_groups[batch_key] = {
                    'batch_info': batch_info,
                    'files': []
                }
            
            batch_groups[batch_key]['files'].append(info)
        else:
            individual_files.append(info)
    
    status_text = " (with live status)" if check_status else ""
    print(f"Found {len(results)} markdown file(s) with frontmatter{status_text}:")
    print("=" * 80)
    
    # Display batch groups first
    if batch_groups:
        for batch_key, batch_data in batch_groups.items():
            batch_info = batch_data['batch_info']
            files = batch_data['files']
            
            print(f"\n📦 Batch: {batch_info['type']}")
            print(f"   URL: {batch_info['url']}")
            
            status_icon = ""
            status_text = ""
            if check_status and 'status' in batch_info:
                if batch_info['status'] == 'frozen':
                    status_icon = " ❄️"
                    status_text = " (frozen)"
                elif batch_info['status'] == 'available':
                    status_icon = " ✅"
                    status_text = " (available)"
            
            print(f"   Status: {status_icon}{status_text}")
            print(f"   Files ({len(files)}):")
            
            for file_info in files:
                heading = None
                for location in file_info['export_locations']:
                    if 'heading' in location:
                        heading = location['heading']
                        break
                
                if heading:
                    print(f"     • {os.path.basename(file_info['file'])} → {heading}")
                else:
                    print(f"     • {os.path.basename(file_info['file'])}")
    
    # Display individual files
    if individual_files:
        for info in individual_files:
            print(f"\n📄 {info['file']}")
            
            if info['title']:
                print(f"   Title: {info['title']}")
            
            if info['labels']:
                print(f"   Labels: {', '.join(info['labels'])}")
            
            if info['export_locations']:
                print("   Export Locations:")
                for location in info['export_locations']:
                    status_icon = ""
                    status_text = ""
                    
                    if check_status and 'status' in location:
                        if location['status'] == 'frozen':
                            status_icon = " ❄️"
                            status_text = " (frozen)"
                        elif location['status'] == 'available':
                            status_icon = " ✅"
                            status_text = " (available)"
                    
                    if show_diff and 'sync_status' in location:
                        sync_status = location['sync_status']
                        print(f"     • {location['type']}: {location['url']} {sync_status}")
                    else:
                        print(f"     • {location['type']}: {location['url']}{status_icon}{status_text}")
            else:
                print("   Export Locations: None")


def check_existing_gdoc_confirmation(markdown_path: str, force: bool = False, destination_doc_id: str = None) -> bool:
    """
    Check if markdown file has existing gdoc_url and ask for confirmation if not forcing.
    
    Args:
        markdown_path (str): Path to markdown file
        force (bool): If True, skip confirmation
        destination_doc_id (str): Optional destination document ID to compare with existing
        
    Returns:
        bool: True if should proceed, False if should skip
    """
    try:
        with open(markdown_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        metadata = extract_frontmatter_metadata(content)
        existing_gdoc_url = metadata.get('gdoc_url')
        
        if existing_gdoc_url and not force:
            # Extract doc ID from existing URL
            existing_doc_id = extract_doc_id(existing_gdoc_url)
            
            # If destination_doc_id provided, check if it's the same document
            if destination_doc_id and existing_doc_id == destination_doc_id:
                # Same document, no warning needed - just updating content
                return True
            
            # Different document or creating new - show warning
            print(f"\n⚠️  Warning: {os.path.basename(markdown_path)} already has a Google Doc link:")
            print(f"   {existing_gdoc_url}")
            if destination_doc_id:
                print(f"\nThis operation will update the link to point to a different document.")
            else:
                print(f"\nThis operation will update the link to point to a new document.")
            
            try:
                response = input("Do you want to continue? [y/N]: ").strip().lower()
                if response in ['y', 'yes']:
                    return True
                elif response in ['n', 'no', '']:
                    print("Operation cancelled.")
                    return False
                else:
                    print("Please enter 'y' for yes or 'n' for no.")
                    return False
            except (EOFError, KeyboardInterrupt):
                print("\nOperation cancelled.")
                return False
        
        return True
        
    except Exception as e:
        print(f"Warning: Could not check existing frontmatter in {markdown_path}: {e}")
        return True
