import difflib
import sys

from .confluence import check_confluence_frozen_status, export_confluence_to_markdown, parse_confluence_destination
from .frontmatter import strip_frontmatter_for_remote_sync
from .gdocs import check_gdoc_frozen_status, export_gdoc_to_markdown


def show_diff(content1: str, content2: str, label1: str, label2: str):
    """Show a unified diff between two content strings."""
    # Normalize line endings
    content1 = content1.replace('\r\n', '\n').replace('\r', '\n')
    content2 = content2.replace('\r\n', '\n').replace('\r', '\n')
    
    # Split into lines for diff
    lines1 = content1.splitlines(keepends=True)
    lines2 = content2.splitlines(keepends=True)
    
    # Generate unified diff
    diff = difflib.unified_diff(
        lines1, lines2,
        fromfile=label1,
        tofile=label2,
        lineterm=''
    )
    
    # Print the diff
    diff_lines = list(diff)
    if diff_lines:
        print("=" * 60)
        print("DIFF (DRY RUN - No changes made):")
        print("=" * 60)
        for line in diff_lines:
            print(line, end='')
        print("=" * 60)
    else:
        print("No differences found - files are identical")


def diff_markdown_to_gdoc(markdown_path: str, doc_id: str, creds):
    """Show diff between markdown file and Google Doc (dry run)."""
    try:
        # Check if Google Doc is frozen
        if check_gdoc_frozen_status(doc_id, creds):
            print(f"⚠️  Google Doc is frozen (locked) - diff not available")
            print(f"Use --unlock to enable syncing to this document")
            return
        
        # Read markdown file
        with open(markdown_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
        
        # Strip frontmatter for comparison (same as what would be synced)
        markdown_for_gdoc = strip_frontmatter_for_remote_sync(markdown_content)
        
        # Export Google Doc to markdown for comparison
        gdoc_markdown = export_gdoc_to_markdown(doc_id, creds)
        
        # Show diff
        show_diff(
            gdoc_markdown, 
            markdown_for_gdoc,
            f"Google Doc {doc_id}",
            f"Local file {markdown_path}"
        )
        
    except FileNotFoundError:
        print(f"Error: Markdown file not found: {markdown_path}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error during diff: {e}", file=sys.stderr)
        sys.exit(1)


def diff_gdoc_to_markdown(doc_id: str, markdown_path: str, creds):
    """Show diff between Google Doc and markdown file (dry run)."""
    try:
        # Export Google Doc to markdown
        gdoc_markdown = export_gdoc_to_markdown(doc_id, creds)
        
        # Read local markdown file
        with open(markdown_path, 'r', encoding='utf-8') as f:
            local_markdown = f.read()
        
        # Show diff
        show_diff(
            local_markdown,
            gdoc_markdown,
            f"Local file {markdown_path}",
            f"Google Doc {doc_id}"
        )
        
    except FileNotFoundError:
        print(f"Error: Markdown file not found: {markdown_path}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error during diff: {e}", file=sys.stderr)
        sys.exit(1)


def diff_markdown_to_confluence(markdown_path: str, confluence_dest: str, confluence):
    """Show diff between markdown file and Confluence page (dry run)."""
    try:
        # Parse Confluence destination
        dest_info = parse_confluence_destination(confluence_dest)
        page_id = dest_info['page_id']
        
        # Check if Confluence page is frozen
        if check_confluence_frozen_status(page_id, confluence):
            print(f"⚠️  Confluence page is frozen (locked) - diff not available")
            print(f"Use --unlock-confluence to enable syncing to this page")
            return
        
        # Read markdown file
        with open(markdown_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
        
        # Strip frontmatter for comparison
        markdown_for_confluence = strip_frontmatter_for_remote_sync(markdown_content)
        
        # Export Confluence page to markdown
        confluence_markdown = export_confluence_to_markdown(page_id, confluence)
        
        # Show diff
        show_diff(
            confluence_markdown,
            markdown_for_confluence,
            f"Confluence page {page_id}",
            f"Local file {markdown_path}"
        )
        
    except FileNotFoundError:
        print(f"Error: Markdown file not found: {markdown_path}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error during diff: {e}", file=sys.stderr)
        sys.exit(1)


def diff_confluence_to_markdown(confluence_dest: str, markdown_path: str, confluence):
    """Show diff between Confluence page and markdown file (dry run)."""
    try:
        # Parse Confluence destination
        dest_info = parse_confluence_destination(confluence_dest)
        page_id = dest_info['page_id']
        
        # Check if Confluence page is frozen
        if check_confluence_frozen_status(page_id, confluence):
            print(f"⚠️  Confluence page is frozen (locked) - diff not available")
            print(f"Use --unlock-confluence to enable syncing to this page")
            return
        
        # Export Confluence page to markdown
        confluence_markdown = export_confluence_to_markdown(page_id, confluence)
        
        # Read local markdown file
        with open(markdown_path, 'r', encoding='utf-8') as f:
            local_markdown = f.read()
        
        # Show diff
        show_diff(
            local_markdown,
            confluence_markdown,
            f"Local file {markdown_path}",
            f"Confluence page {page_id}"
        )
        
    except FileNotFoundError:
        print(f"Error: Markdown file not found: {markdown_path}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error during diff: {e}", file=sys.stderr)
        sys.exit(1)


def check_sync_status(markdown_path: str, destination_type: str, destination_id: str, creds=None, confluence=None) -> str:
    """Check sync status between markdown and remote destination."""
    try:
        # Read markdown file
        with open(markdown_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
        
        # Strip frontmatter for comparison
        markdown_for_remote = strip_frontmatter_for_remote_sync(markdown_content)
        
        if destination_type == 'Google Doc':
            if not creds:
                return "❓ (no credentials)"
            
            # Check if frozen first
            if check_gdoc_frozen_status(destination_id, creds):
                return "🔒 (frozen)"
            
            # Export Google Doc to markdown for comparison
            try:
                gdoc_markdown = export_gdoc_to_markdown(destination_id, creds)
                
                # Compare content
                if markdown_for_remote.strip() == gdoc_markdown.strip():
                    return "✅ (synced)"
                else:
                    return "⚠️  (differs)"
            except Exception as e:
                return f"❌ (error: {str(e)[:30]}...)"
        
        elif destination_type == 'Confluence':
            if not confluence:
                return "❓ (no confluence client)"
            
            # Export Confluence to markdown for comparison
            try:
                confluence_markdown = export_confluence_to_markdown(destination_id, confluence)
                
                # Compare content
                if markdown_for_remote.strip() == confluence_markdown.strip():
                    return "✅ (synced)"
                else:
                    return "⚠️  (differs)"
            except Exception as e:
                return f"❌ (error: {str(e)[:30]}...)"
        
        return "❓ (unknown type)"
        
    except Exception as e:
        return f"❌ (error: {str(e)[:30]}...)"
