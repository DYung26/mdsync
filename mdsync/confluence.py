import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Optional

import yaml

try:
    from atlassian import Confluence
    CONFLUENCE_AVAILABLE = True
except ImportError:
    CONFLUENCE_AVAILABLE = False
    Confluence = None

from .frontmatter import (
    extract_frontmatter_metadata,
    strip_frontmatter_for_remote_sync,
    update_frontmatter_confluence_url,
)


def parse_confluence_destination(dest: str) -> dict:
    """Parse Confluence destination into components."""
    result = {'type': None, 'space': None, 'page_id': None, 'page_title': None, 'url': None}
    
    if dest.startswith('confluence:'):
        # Format: confluence:SPACE/PAGE_ID or confluence:SPACE/Page+Title
        parts = dest[11:].split('/', 1)  # Remove 'confluence:' prefix
        result['type'] = 'confluence'
        result['space'] = parts[0] if parts else None
        if len(parts) > 1:
            if parts[1].isdigit():
                result['page_id'] = parts[1]
            else:
                result['page_title'] = parts[1].replace('+', ' ')
    
    elif 'atlassian.net/wiki' in dest:
        # Parse Confluence URL
        result['type'] = 'confluence'
        result['url'] = dest
        # Extract space and page ID from URL
        import re
        space_match = re.search(r'/spaces/([^/]+)', dest)
        page_match = re.search(r'/pages/(\d+)', dest)
        if space_match:
            result['space'] = space_match.group(1)
        if page_match:
            result['page_id'] = page_match.group(1)
    
    elif dest.isdigit():
        # Just a page ID
        result['type'] = 'confluence'
        result['page_id'] = dest
    
    return result


def get_confluence_credentials(secrets_file_path: Optional[str] = None):
    """Get Confluence credentials as a dict (for direct API calls).
    
    Args:
        secrets_file_path: Optional explicit path to secrets.yaml file
    """
    # Look for Confluence credentials in multiple locations
    confluence_url = os.getenv('CONFLUENCE_URL')
    confluence_username = os.getenv('CONFLUENCE_USERNAME')
    confluence_token = os.getenv('CONFLUENCE_API_TOKEN') or os.getenv('CONFLUENCE_TOKEN')
    
    # Try secrets.yaml first (preferred method)
    secrets_paths = []
    if secrets_file_path:
        # Explicit path provided
        secrets_paths = [Path(secrets_file_path)]
    else:
        # Default search paths
        secrets_paths = [
            Path.cwd() / 'secrets.yaml',
            Path.cwd() / 'secrets.yml',
            Path.home() / '.config' / 'mdsync' / 'secrets.yaml',
            Path.home() / '.mdsync' / 'secrets.yaml',
        ]
    
    for secrets_path in secrets_paths:
        if secrets_path.exists():
            try:
                with open(secrets_path, 'r') as f:
                    secrets = yaml.safe_load(f)
                    if secrets and 'confluence' in secrets:
                        conf = secrets['confluence']
                        confluence_url = confluence_url or conf.get('url')
                        confluence_username = confluence_username or conf.get('username')
                        confluence_token = confluence_token or conf.get('api_token') or conf.get('token')
                        break
            except Exception:
                pass
    
    # Try confluence.json as fallback
    if not all([confluence_url, confluence_username, confluence_token]):
        config_paths = [
            Path.cwd() / 'confluence.json',
            Path.home() / '.config' / 'mdsync' / 'confluence.json',
            Path.home() / '.mdsync' / 'confluence.json',
        ]
        
        for config_path in config_paths:
            if config_path.exists():
                try:
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                        confluence_url = confluence_url or config.get('url')
                        confluence_username = confluence_username or config.get('username')
                        confluence_token = confluence_token or config.get('api_token') or config.get('token')
                        break
                except Exception:
                    pass
    
    if not all([confluence_url, confluence_username, confluence_token]):
        return None
    
    return {
        'url': confluence_url,
        'username': confluence_username,
        'api_token': confluence_token
    }


def get_confluence_client(secrets_file_path: Optional[str] = None):
    """Get Confluence API client from secrets.yaml, environment variables, or config.
    
    Args:
        secrets_file_path: Optional explicit path to secrets.yaml file
    """
    if not CONFLUENCE_AVAILABLE:
        print("Error: Confluence support not available. Install with: pip install atlassian-python-api", file=sys.stderr)
        sys.exit(1)
    
    # Look for Confluence credentials in multiple locations
    confluence_url = os.getenv('CONFLUENCE_URL')
    confluence_username = os.getenv('CONFLUENCE_USERNAME')
    confluence_token = os.getenv('CONFLUENCE_API_TOKEN') or os.getenv('CONFLUENCE_TOKEN')
    
    # Try secrets.yaml first (preferred method)
    secrets_paths = []
    if secrets_file_path:
        # Explicit path provided
        secrets_paths = [Path(secrets_file_path)]
    else:
        # Default search paths
        secrets_paths = [
            Path.cwd() / 'secrets.yaml',
            Path.cwd() / 'secrets.yml',
            Path.home() / '.config' / 'mdsync' / 'secrets.yaml',
            Path.home() / '.mdsync' / 'secrets.yaml',
        ]
    
    for secrets_path in secrets_paths:
        if secrets_path.exists():
            try:
                with open(secrets_path, 'r') as f:
                    secrets = yaml.safe_load(f)
                    if secrets and 'confluence' in secrets:
                        conf = secrets['confluence']
                        confluence_url = confluence_url or conf.get('url')
                        confluence_username = confluence_username or conf.get('username')
                        confluence_token = confluence_token or conf.get('api_token') or conf.get('token')
                        break
            except Exception:
                pass
    
    # Fallback to JSON config files
    if not all([confluence_url, confluence_username, confluence_token]):
        config_paths = [
            Path.home() / '.config' / 'mdsync' / 'confluence.json',
            Path.home() / '.mdsync' / 'confluence.json',
            Path.cwd() / 'confluence.json',
        ]
        
        for config_path in config_paths:
            if config_path.exists():
                try:
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                        confluence_url = confluence_url or config.get('url')
                        confluence_username = confluence_username or config.get('username')
                        confluence_token = confluence_token or config.get('token')
                        break
                except Exception:
                    pass
    
    if not all([confluence_url, confluence_username, confluence_token]):
        print("Error: Confluence credentials not found!", file=sys.stderr)
        print("\nOption 1: Create secrets.yaml in current directory:", file=sys.stderr)
        print("  confluence:", file=sys.stderr)
        print("    url: https://yoursite.atlassian.net", file=sys.stderr)
        print("    username: your-email@domain.com", file=sys.stderr)
        print("    api_token: your-api-token", file=sys.stderr)
        print("\nOption 2: Set environment variables:", file=sys.stderr)
        print("  CONFLUENCE_URL=https://yoursite.atlassian.net", file=sys.stderr)
        print("  CONFLUENCE_USERNAME=your-email@domain.com", file=sys.stderr)
        print("  CONFLUENCE_API_TOKEN=your-api-token", file=sys.stderr)
        print("\nSee secrets.yaml.example for template", file=sys.stderr)
        sys.exit(1)
    
    return Confluence(
        url=confluence_url,
        username=confluence_username,
        password=confluence_token,
        cloud=True
    )


def markdown_to_confluence_storage(markdown_content: str) -> str:
    """Convert markdown to Confluence storage format using proper HTML conversion.
    
    Uses the markdown library with extensions for better formatting support,
    similar to the md2confluence project approach.
    """
    import markdown
    
    # Convert markdown to HTML with extensions (similar to md2confluence)
    html_content = markdown.markdown(
        markdown_content,
        extensions=[
            'tables',          # Support for tables
            'fenced_code',     # Support for ```code blocks```
            'codehilite',      # Syntax highlighting
            'nl2br',           # Convert newlines to <br>
            'sane_lists'       # Better list handling
        ]
    )
    
    # Convert to Confluence Storage Format
    confluence_content = html_content
    
    # Generate Confluence-compatible anchor IDs from heading text
    # Confluence auto-generates anchors from heading text, so we need to match that format
    def generate_confluence_anchor(heading_text):
        """Generate a Confluence-compatible anchor ID from heading text.
        
        Confluence generates anchors by:
        1. Preserving original case (NOT lowercasing)
        2. Replacing spaces with hyphens
        3. URL encoding special characters (:, [, ], etc.)
        """
        import urllib.parse
        # Handle None case
        if heading_text is None:
            return ''
        # Confluence preserves case and uses URL encoding
        anchor = heading_text.strip()
        # Remove markdown formatting but preserve the text structure
        anchor = re.sub(r'\*\*([^*]+)\*\*', r'\1', anchor)  # Remove bold
        anchor = re.sub(r'\*([^*]+)\*', r'\1', anchor)  # Remove italic
        anchor = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', anchor)  # Remove links
        # Unescape escaped brackets (from markdown like \[IN PROGRESS\])
        anchor = re.sub(r'\\\[', '[', anchor)  # Match \ followed by [
        anchor = re.sub(r'\\\]', ']', anchor)  # Match \ followed by ]
        # Replace spaces with hyphens (but keep case)
        anchor = re.sub(r'\s+', '-', anchor)
        # URL encode (Confluence uses URL encoding for anchors)
        # Don't encode hyphens, they're part of the anchor format
        return urllib.parse.quote(anchor, safe='-')
    
    # Update heading IDs to match Confluence's auto-generated format
    def fix_heading_anchor(match):
        heading_tag = match.group(1)
        existing_id = match.group(2) if match.group(2) else None
        heading_text = match.group(3)  # The actual heading text content
        
        # Handle None case (shouldn't happen, but be safe)
        if heading_text is None:
            return match.group(0)  # Return original if something's wrong
        
        # Remove markdown anchor syntax {#anchor} from heading text if present
        # This is formatting noise from Google Docs that shouldn't be displayed
        clean_heading_text = re.sub(r'\s*\{#[^}]+\}\s*$', '', heading_text).strip()
        
        # Generate anchor from CLEAN heading text (without the {#...} part)
        anchor_id = generate_confluence_anchor(clean_heading_text)
        
        # Use the clean heading text for display
        return f'<h{heading_tag} id="{anchor_id}">{clean_heading_text}</h{heading_tag}>'
    
    # Update headings to have Confluence-compatible anchor IDs
    confluence_content = re.sub(
        r'<h([1-6])(?:\s+id="([^"]*)")?>(.*?)</h\1>',
        fix_heading_anchor,
        confluence_content
    )
    
    # Map of markdown anchor names to Confluence anchors (for TOC links)
    # We'll build this by scanning the markdown content before conversion
    anchor_to_heading_map = {}
    heading_pattern = r'^#{1,6}\s+(.+?)(?:\s+\{#([^}]+)\})?$'
    for line in markdown_content.split('\n'):
        match = re.match(heading_pattern, line)
        if match:
            heading_text = match.group(1).strip()
            explicit_anchor = match.group(2) if match.group(2) else None
            
            # Remove markdown anchor syntax {#anchor} from heading text if present
            # This is formatting noise that shouldn't be part of the anchor generation
            clean_heading = re.sub(r'\s*\{#[^}]+\}\s*$', '', heading_text).strip()
            
            # Remove markdown link syntax from heading text for anchor generation
            clean_heading = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean_heading)  # Remove links
            clean_heading = re.sub(r'\\\[([^\]]+)\\\]', r'[\1]', clean_heading)  # Unescape brackets
            
            # Generate anchor from CLEAN heading text (Confluence's way - without the {#...} part)
            confluence_anchor = generate_confluence_anchor(clean_heading)
            
            # Map explicit anchor (if present) to the Confluence-generated anchor
            if explicit_anchor:
                anchor_to_heading_map[explicit_anchor] = confluence_anchor
            
            # Also map variations of the heading text to the anchor
            anchor_to_heading_map[clean_heading.lower()] = confluence_anchor
            anchor_to_heading_map[heading_text.lower()] = confluence_anchor
    
    # Update anchor links to match Confluence's generated anchors
    def fix_anchor_link(match):
        # Regex already extracted the anchor name (without #) from href="#anchor"
        anchor_name = match.group(1)  # This is already without the #
        text = match.group(2)
        
        # Try to find the matching Confluence anchor
        # First check if we have a mapping for this anchor
        if anchor_name in anchor_to_heading_map:
            confluence_anchor = anchor_to_heading_map[anchor_name]
        else:
            # Generate anchor from the link text (fallback)
            confluence_anchor = generate_confluence_anchor(text)
        return f'<a href="#{confluence_anchor}">{text}</a>'
    
    # Fix anchor links before the general link conversion
    # This regex matches <a href="#anchor">text</a> and extracts anchor (without #) and text
    confluence_content = re.sub(
        r'<a href="#([^"]+)">(.*?)</a>',
        fix_anchor_link,
        confluence_content
    )
    
    # Convert code blocks to simpler format (remove codehilite divs)
    confluence_content = re.sub(
        r'<div class="codehilite"><pre><span></span><code[^>]*>(.*?)</code></pre></div>',
        r'<pre><code>\1</code></pre>',
        confluence_content,
        flags=re.DOTALL
    )
    
    # Remove syntax highlighting spans from code blocks
    confluence_content = re.sub(
        r'<span class="[^"]*">([^<]*)</span>',
        r'\1',
        confluence_content
    )
    
    # Convert special syntax for Confluence macros (:::note, :::warning, etc.)
    def convert_special_macro(match):
        macro_type = match.group(1).lower()
        title = match.group(2) if match.group(2) else ""
        content = match.group(3).strip()
        
        # Remove any <p> tags that markdown might have added
        content = re.sub(r'^<p>|</p>$', '', content)
        
        # Handle success type - use info macro with checkmark emoji
        if macro_type == 'success':
            macro_type = 'info'
            if not title:
                title = "✅ Success"
            elif not title.startswith('✅'):
                title = f"✅ {title}"
        
        # Build the macro with optional title
        macro_params = ""
        if title:
            macro_params = f'  <ac:parameter ac:name="title">{title}</ac:parameter>\n'
        
        return f'''<ac:structured-macro ac:name="{macro_type}" ac:schema-version="1" ac:macro-id="{uuid.uuid4()}">
{macro_params}  <ac:rich-text-body>
    <p>{content}</p>
  </ac:rich-text-body>
</ac:structured-macro>'''
    
    # Convert :::type [title] content ::: syntax
    confluence_content = re.sub(
        r':::(\w+)(?:\s+([^\n]+))?\n(.*?)\n:::',
        convert_special_macro,
        confluence_content,
        flags=re.DOTALL
    )
    
    # Convert block quotes to Confluence note macros
    def convert_blockquote_to_note(match):
        content = match.group(1).strip()
        # Remove any <p> tags that markdown might have added
        content = re.sub(r'^<p>|</p>$', '', content)
        return f'''<ac:structured-macro ac:name="note">
  <ac:rich-text-body>
    <p>{content}</p>
  </ac:rich-text-body>
</ac:structured-macro>'''
    
    confluence_content = re.sub(
        r'<blockquote>(.*?)</blockquote>',
        convert_blockquote_to_note,
        confluence_content,
        flags=re.DOTALL
    )
    
    # Convert links - distinguish between anchor links, external URLs, and internal pages
    def convert_link(match):
        href = match.group(1)
        text = match.group(2)
        
        # Anchor link (starts with #) - same page anchor
        if href.startswith('#'):
            anchor_name = href[1:]  # Remove the #
            # For same-page anchors, use Confluence anchor format
            # Note: Confluence will auto-generate anchors from headings, but we preserve explicit ones
            return f'<a href="#{anchor_name}">{text}</a>'
        # External URL (starts with http/https)
        elif href.startswith(('http://', 'https://', 'mailto:')):
            return f'<a href="{href}">{text}</a>'
        # Internal page link - convert to Confluence format
        else:
            return f'<ac:link><ri:page ri:content-title="{href}"/><ac:link-body>{text}</ac:link-body></ac:link>'
    
    confluence_content = re.sub(
        r'<a href="([^"]+)">(.*?)</a>',
        convert_link,
        confluence_content
    )
    
    return confluence_content


def export_confluence_to_markdown(page_id: str, confluence, output_path: str = None) -> str:
    """Export a Confluence page to Markdown format using html2text for better conversion."""
    try:
        import html2text
        from bs4 import BeautifulSoup
        
        # Get page content
        page = confluence.get_page_by_id(page_id, expand='body.storage')
        
        if not page:
            print(f"Error: Page {page_id} not found", file=sys.stderr)
            sys.exit(1)
        
        # Get the storage format content
        storage_content = page['body']['storage']['value']
        
        # Pre-process Confluence-specific tags before conversion
        soup = BeautifulSoup(storage_content, 'html.parser')
        
        # Convert Confluence internal links to regular HTML links
        for link in soup.find_all('ac:link'):
            page_ref = link.find('ri:page')
            if page_ref and page_ref.get('ri:content-title'):
                page_title = page_ref.get('ri:content-title')
                link_body = link.find('ac:link-body')
                link_text = link_body.get_text() if link_body else page_title
                # Create a simple markdown-style link
                new_link = soup.new_tag('a', href=page_title)
                new_link.string = link_text
                link.replace_with(new_link)
        
        # Convert back to HTML string
        cleaned_html = str(soup)
        
        # Use html2text for proper HTML to Markdown conversion
        h = html2text.HTML2Text()
        h.body_width = 0  # Don't wrap lines
        h.ignore_links = False
        h.ignore_images = False
        h.ignore_emphasis = False
        h.skip_internal_links = False
        h.inline_links = True
        h.protect_links = True
        h.unicode_snob = True  # Use unicode instead of HTML entities
        
        markdown_content = h.handle(cleaned_html)
        
        # If output path provided, add frontmatter with confluence_url
        if output_path:
            space_key = page.get('space', {}).get('key', '')
            # Remove /wiki from the end of confluence.url if present
            base_url = confluence.url.rstrip('/')
            if base_url.endswith('/wiki'):
                base_url = base_url[:-5]  # Remove '/wiki'
            confluence_url = f"{base_url}/wiki/spaces/{space_key}/pages/{page_id}"
            
            # Check if content already has frontmatter
            if markdown_content.startswith('---'):
                # Parse existing frontmatter and add confluence_url
                try:
                    import frontmatter
                    post = frontmatter.loads(markdown_content)
                    post.metadata['confluence_url'] = confluence_url
                    frontmatter_content = frontmatter.dumps(post)
                except Exception:
                    # Fallback: prepend frontmatter
                    frontmatter_content = f"---\nconfluence_url: {confluence_url}\n---\n\n{markdown_content}"
            else:
                # Add frontmatter to the content
                frontmatter_content = f"---\nconfluence_url: {confluence_url}\n---\n\n{markdown_content}"
            
            # Write to file
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(frontmatter_content)
            
            return frontmatter_content
        else:
            return markdown_content.strip()
        
    except Exception as error:
        print(f"An error occurred: {error}", file=sys.stderr)
        sys.exit(1)


def import_markdown_to_confluence(markdown_path: str, page_id: str, confluence, quiet: bool = False):
    """Import a Markdown file to an existing Confluence page."""
    try:
        # Read the markdown file
        with open(markdown_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
        
        # Extract metadata from frontmatter
        frontmatter = extract_frontmatter_metadata(markdown_content)
        frontmatter_labels = frontmatter['labels']
        
        # Get existing page to preserve space and version
        page = confluence.get_page_by_id(page_id, expand='version,space')
        
        if not page:
            print(f"Error: Page {page_id} not found", file=sys.stderr)
            sys.exit(1)
        
        space_key = page.get('space', {}).get('key', '')
        title = page.get('title', '')
        
        # Generate Confluence URL
        # Remove /wiki from the end of confluence.url if present
        base_url = confluence.url.rstrip('/')
        if base_url.endswith('/wiki'):
            base_url = base_url[:-5]  # Remove '/wiki'
        confluence_url = f"{base_url}/wiki/spaces/{space_key}/pages/{page_id}"
        
        # Resolve internal markdown links to Confluence URLs
        base_dir = os.path.dirname(os.path.abspath(markdown_path))
        resolved_content = resolve_markdown_links_to_confluence(markdown_content, base_dir)
        
        # Strip frontmatter and convert markdown to Confluence storage format
        content_for_confluence = strip_frontmatter_for_remote_sync(resolved_content)
        storage_content = markdown_to_confluence_storage(content_for_confluence)
        
        # Update the page
        confluence.update_page(
            page_id=page_id,
            title=title,
            body=storage_content,
            parent_id=page.get('ancestors', [{}])[-1].get('id') if page.get('ancestors') else None,
            type='page',
            representation='storage'
        )
        
        # Update frontmatter with Confluence URL
        update_frontmatter_confluence_url(markdown_path, confluence_url)
        
        # Set labels authoritatively if any in frontmatter
        if frontmatter_labels:
            confluence_creds = get_confluence_credentials()
            if confluence_creds:
                set_confluence_labels(
                    page_id, 
                    frontmatter_labels, 
                    confluence_creds['url'],
                    confluence_creds['username'],
                    confluence_creds['api_token']
                )
        
        if not quiet:
            print(f"✓ Successfully updated Confluence page: {title}")
            print(f"  Page ID: {page_id}")
            print(f"  Space: {space_key}")
            print(f"  URL: {confluence_url}")
            if frontmatter_labels:
                print(f"  Labels: {', '.join(frontmatter_labels)}")
            print(f"  Updated frontmatter in {markdown_path}")
        
    except FileNotFoundError:
        print(f"Error: Markdown file not found: {markdown_path}", file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print(f"An error occurred: {error}", file=sys.stderr)
        sys.exit(1)


def resolve_markdown_links_to_confluence(markdown_content: str, base_dir: str = None) -> str:
    """Resolve internal markdown links to Confluence URLs based on frontmatter."""
    if not base_dir:
        base_dir = os.getcwd()
    
    # Pattern to match [text](file.md) links
    link_pattern = r'\[([^\]]+)\]\(([^)]+\.md)\)'
    
    def replace_link(match):
        link_text = match.group(1)
        file_path = match.group(2)
        
        # Convert relative path to absolute
        if not os.path.isabs(file_path):
            file_path = os.path.join(base_dir, file_path)
        
        # Check if the referenced file exists and has confluence_url in frontmatter
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Extract confluence_url from frontmatter
                metadata = extract_frontmatter_metadata(content)
                confluence_url = metadata.get('confluence_url')
                
                if confluence_url:
                    return f'[{link_text}]({confluence_url})'
            except Exception:
                pass
        
        # If no confluence_url found, return original link
        return match.group(0)
    
    # Replace all markdown links
    return re.sub(link_pattern, replace_link, markdown_content)


def check_confluence_frozen_status(page_id: str, confluence) -> bool:
    """Check if a Confluence page is frozen (locked) at runtime."""
    try:
        # Get page restrictions
        confluence_creds = get_confluence_credentials()
        if not confluence_creds:
            return False
        
        # Use the existing check_confluence_lock_status logic
        import requests
        
        url = f"{confluence_creds['url']}/rest/api/content/{page_id}/restriction"
        auth = (confluence_creds['username'], confluence_creds['api_token'])
        
        response = requests.get(url, auth=auth)
        if response.status_code == 200:
            restrictions = response.json()
            # Check if there are UPDATE restrictions
            for restriction in restrictions.get('restrictions', {}).get('update', {}).get('restrictions', []):
                if restriction.get('type') == 'user' or restriction.get('type') == 'group':
                    return True
        
        return False
    except Exception:
        # If we can't check, assume not frozen
        return False


def get_confluence_permissions_config(secrets_file_path: Optional[str] = None):
    """Get default permissions configuration from secrets.yaml.
    
    Args:
        secrets_file_path: Optional explicit path to secrets.yaml file
    """
    secrets_paths = []
    if secrets_file_path:
        # Explicit path provided
        secrets_paths = [Path(secrets_file_path)]
    else:
        # Default search paths
        secrets_paths = [
            Path.cwd() / 'secrets.yaml',
            Path.cwd() / 'secrets.yml',
            Path.home() / '.config' / 'mdsync' / 'secrets.yaml',
            Path.home() / '.mdsync' / 'secrets.yaml',
        ]
    
    for secrets_path in secrets_paths:
        if secrets_path.exists():
            try:
                with open(secrets_path, 'r') as f:
                    secrets = yaml.safe_load(f)
                    if secrets and 'confluence' in secrets:
                        perms = secrets['confluence'].get('permissions', {})
                        if perms:
                            return perms
            except Exception:
                pass
    
    return None


def lock_confluence_page(page_id: str, confluence_url: str, username: str, api_token: str, 
                        allowed_editors: dict = None, secrets_file_path: Optional[str] = None) -> bool:
    """Lock a Confluence page by setting edit restrictions.
    
    Similar to md2confluence's _apply_page_permissions.
    Sets UPDATE restriction so only specified users/groups can edit.
    Everyone else can view but not edit (read-only).
    """
    try:
        import requests
        import json
        
        # Get default permissions from config if not provided
        if not allowed_editors:
            # First check environment variable for allowed editor groups
            env_groups = os.getenv('MDSYNC_ALLOWED_EDITORS_GROUPS')
            env_users = os.getenv('MDSYNC_ALLOWED_EDITORS_USERS')
            
            if env_groups or env_users:
                # Parse comma-separated values
                groups = [g.strip() for g in env_groups.split(',')] if env_groups else []
                users = [u.strip() for u in env_users.split(',')] if env_users else []
                allowed_editors = {'users': users, 'groups': groups}
            else:
                # Fallback to secrets.yaml if available
                perms_config = get_confluence_permissions_config(secrets_file_path)
                if perms_config and 'allowed_editors' in perms_config:
                    allowed_editors = perms_config['allowed_editors']
                else:
                    # Final fallback: only current user
                    allowed_editors = {'users': [username], 'groups': []}
        
        # Always include current user to prevent lockout
        editor_users = list(allowed_editors.get('users', []))
        if username not in editor_users:
            editor_users.append(username)
            print(f"Auto-adding current user ({username}) to prevent lockout", file=sys.stderr)
        
        editor_groups = allowed_editors.get('groups', [])
        
        # Resolve user emails to account IDs
        resolved_users = []
        for email in editor_users:
            account_id = _resolve_user_email_to_account_id(email, confluence_url, username, api_token)
            if account_id:
                resolved_users.append({"type": "known", "accountId": account_id})
        
        if not resolved_users:
            print("Error: Could not resolve any users. Cannot lock page to prevent lockout.", file=sys.stderr)
            return False
        
        # Build group restrictions
        resolved_groups = [{"type": "group", "name": group} for group in editor_groups]
        
        # Create restrictions data
        restrictions_data = [
            {
                "operation": "update",
                "restrictions": {
                    "user": resolved_users,
                    "group": resolved_groups
                }
            }
        ]
        
        # Apply restrictions
        url = f"{confluence_url}/wiki/rest/api/content/{page_id}/restriction"
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        response = requests.put(
            url,
            headers=headers,
            data=json.dumps(restrictions_data),
            auth=(username, api_token)
        )
        
        if response.status_code in [200, 201]:
            return True
        else:
            print(f"Error locking page: {response.status_code} - {response.text}", file=sys.stderr)
            return False
            
    except Exception as e:
        print(f"Error locking Confluence page: {e}", file=sys.stderr)
        return False


def unlock_confluence_page(page_id: str, confluence_url: str, username: str, api_token: str) -> bool:
    """Unlock a Confluence page by removing all restrictions."""
    try:
        import requests
        
        # Delete all restrictions
        url = f"{confluence_url}/wiki/rest/api/content/{page_id}/restriction"
        
        response = requests.delete(
            url,
            auth=(username, api_token)
        )
        
        if response.status_code in [200, 204]:
            return True
        else:
            print(f"Error unlocking page: {response.status_code} - {response.text}", file=sys.stderr)
            return False
            
    except Exception as e:
        print(f"Error unlocking Confluence page: {e}", file=sys.stderr)
        return False


def check_confluence_lock_status(page_id: str, confluence_url: str, username: str, api_token: str):
    """Check and display the lock status of a Confluence page."""
    try:
        import requests
        
        url = f"{confluence_url}/wiki/rest/api/content/{page_id}?expand=restrictions.read.restrictions.user,restrictions.read.restrictions.group,restrictions.update.restrictions.user,restrictions.update.restrictions.group"
        
        response = requests.get(
            url,
            auth=(username, api_token)
        )
        
        if response.status_code != 200:
            print(f"Error checking lock status: {response.status_code}", file=sys.stderr)
            return
        
        data = response.json()
        restrictions = data.get('restrictions', {})
        
        update_restrictions = restrictions.get('update', {}).get('restrictions', {})
        read_restrictions = restrictions.get('read', {}).get('restrictions', {})
        
        if not update_restrictions.get('user', {}).get('results') and not update_restrictions.get('group', {}).get('results'):
            print(f"Page {page_id} is UNLOCKED (no edit restrictions)")
        else:
            print(f"Page {page_id} is LOCKED (edit restricted)")
            
            users = update_restrictions.get('user', {}).get('results', [])
            groups = update_restrictions.get('group', {}).get('results', [])
            
            if users:
                print("  Allowed editors (users):")
                for user in users:
                    print(f"    - {user.get('displayName', user.get('accountId'))}")
            
            if groups:
                print("  Allowed editors (groups):")
                for group in groups:
                    print(f"    - {group.get('name')}")
        
    except Exception as e:
        print(f"Error checking Confluence lock status: {e}", file=sys.stderr)


def _resolve_user_email_to_account_id(email: str, confluence_url: str, username: str, api_token: str) -> str:
    """Resolve a user email to Confluence account ID."""
    try:
        import requests
        
        # Try current user endpoint first
        if email == username:
            url = f"{confluence_url}/wiki/rest/api/user/current"
            response = requests.get(url, auth=(username, api_token))
            if response.status_code == 200:
                return response.json().get('accountId')
        
        # Search for user by email
        search_url = f"{confluence_url}/wiki/rest/api/search/user"
        params = {"cql": f'user="{email}"'}
        
        response = requests.get(
            search_url,
            params=params,
            auth=(username, api_token)
        )
        
        if response.status_code == 200:
            results = response.json().get("results", [])
            for user_data in results:
                user_email = user_data.get("email", user_data.get("emailAddress", ""))
                if user_email.lower() == email.lower():
                    return user_data.get("accountId")
        
        return None
        
    except Exception:
        return None


def set_confluence_labels(page_id: str, labels: list, confluence_url: str, username: str, api_token: str) -> bool:
    """Set labels on a Confluence page authoritatively (replace all existing labels).
    
    Similar to md2confluence's _set_page_labels_authoritatively.
    """
    try:
        import requests
        import json
        
        # Step 1: Get existing labels
        get_url = f"{confluence_url}/wiki/rest/api/content/{page_id}?expand=metadata.labels"
        get_response = requests.get(
            get_url,
            auth=(username, api_token)
        )
        
        existing_labels = []
        if get_response.status_code == 200:
            page_data = get_response.json()
            if 'metadata' in page_data and 'labels' in page_data['metadata']:
                existing_labels = [label['name'] for label in page_data['metadata']['labels']['results']]
        
        # Step 2: Remove all existing labels
        if existing_labels:
            for label_name in existing_labels:
                delete_url = f"{confluence_url}/wiki/rest/api/content/{page_id}/label/{label_name}"
                requests.delete(
                    delete_url,
                    auth=(username, api_token)
                )
        
        # Step 3: Add new labels
        if labels:
            labels_data = [{"name": label} for label in labels]
            
            add_url = f"{confluence_url}/wiki/rest/api/content/{page_id}/label"
            headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            }
            
            add_response = requests.post(
                add_url,
                headers=headers,
                data=json.dumps(labels_data),
                auth=(username, api_token)
            )
            
            return add_response.status_code == 200
        
        return True
        
    except Exception as e:
        print(f"Warning: Could not set labels on page {page_id}: {e}", file=sys.stderr)
        return False


def create_confluence_page(markdown_path: str, confluence, space: str, title: str, 
                           parent_id: Optional[str] = None, labels: Optional[list] = None, 
                           quiet: bool = False) -> str:
    """Create a new Confluence page from a Markdown file.
    
    Note: Labels from CLI and frontmatter are combined (CLI labels are applied first).
    """
    try:
        # Read the markdown file
        with open(markdown_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
        
        # Extract metadata from frontmatter
        frontmatter = extract_frontmatter_metadata(markdown_content)
        
        # Combine CLI labels with frontmatter labels
        all_labels = list(labels or []) + frontmatter['labels']
        
        # Resolve internal markdown links to Confluence URLs
        base_dir = os.path.dirname(os.path.abspath(markdown_path))
        resolved_content = resolve_markdown_links_to_confluence(markdown_content, base_dir)
        
        # Strip frontmatter and convert markdown to Confluence storage format
        content_for_confluence = strip_frontmatter_for_remote_sync(resolved_content)
        storage_content = markdown_to_confluence_storage(content_for_confluence)
        
        # Create the page
        new_page = confluence.create_page(
            space=space,
            title=title,
            body=storage_content,
            parent_id=parent_id,
            type='page',
            representation='storage'
        )
        
        page_id = new_page['id']
        
        # Generate Confluence URL
        # Remove /wiki from the end of confluence.url if present
        base_url = confluence.url.rstrip('/')
        if base_url.endswith('/wiki'):
            base_url = base_url[:-5]  # Remove '/wiki'
        confluence_url = f"{base_url}/wiki/spaces/{space}/pages/{page_id}"
        
        # Update frontmatter with Confluence URL
        update_frontmatter_confluence_url(markdown_path, confluence_url)
        
        # Set labels authoritatively if any
        if all_labels:
            # Get Confluence credentials for label setting
            confluence_creds = get_confluence_credentials()
            if confluence_creds:
                set_confluence_labels(
                    page_id, 
                    all_labels, 
                    confluence_creds['url'],
                    confluence_creds['username'],
                    confluence_creds['api_token']
                )
        
        if not quiet:
            print(f"✓ Created new Confluence page: {title}")
            print(f"  Page ID: {page_id}")
            print(f"  Space: {space}")
            print(f"  URL: {confluence_url}")
            if parent_id:
                print(f"  Parent ID: {parent_id}")
            if all_labels:
                print(f"  Labels: {', '.join(all_labels)}")
            print(f"  Updated frontmatter in {markdown_path}")
        
        return page_id
        
    except FileNotFoundError:
        print(f"Error: Markdown file not found: {markdown_path}", file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print(f"An error occurred: {error}", file=sys.stderr)
        sys.exit(1)
