import sys

import yaml


def extract_frontmatter_metadata(markdown_content: str) -> dict:
    """Extract metadata from markdown frontmatter (title, labels, gdoc_url, confluence_url, batch, etc.)."""
    try:
        import frontmatter
        post = frontmatter.loads(markdown_content)
        return {
            'title': post.metadata.get('title'),
            'labels': post.metadata.get('labels', []),
            'parent': post.metadata.get('parent'),
            'gdoc_url': post.metadata.get('gdoc_url'),
            'confluence_url': post.metadata.get('confluence_url'),
            'batch': post.metadata.get('batch'),
            'gdoc_tab_id': post.metadata.get('gdoc_tab_id'),
            'gdoc_created': post.metadata.get('gdoc_created'),
            'gdoc_modified': post.metadata.get('gdoc_modified'),
            'confluence_created': post.metadata.get('confluence_created'),
            'confluence_modified': post.metadata.get('confluence_modified'),
        }
    except Exception:
        return {
            'title': None, 
            'labels': [], 
            'parent': None, 
            'gdoc_url': None,
            'confluence_url': None,
            'batch': None,
            'gdoc_tab_id': None,
            'gdoc_created': None,
            'gdoc_modified': None,
            'confluence_created': None,
            'confluence_modified': None,
        }


def update_frontmatter_metadata(content: str, metadata: dict) -> str:
    """Update frontmatter metadata in markdown content."""
    try:
        import frontmatter
        post = frontmatter.loads(content)
        
        # Update metadata
        for key, value in metadata.items():
            post.metadata[key] = value
        
        # Return updated content
        return frontmatter.dumps(post)
    except Exception:
        # If frontmatter library fails, fall back to manual YAML handling
        if not content.startswith('---'):
            # No existing frontmatter, add it
            frontmatter_yaml = yaml.dump(metadata, default_flow_style=False, sort_keys=False)
            return f"---\n{frontmatter_yaml}---\n\n{content}"
        
        try:
            # Find the end of existing frontmatter
            end_marker = content.find('---', 3)
            if end_marker == -1:
                # Malformed frontmatter, replace it
                frontmatter_yaml = yaml.dump(metadata, default_flow_style=False, sort_keys=False)
                return f"---\n{frontmatter_yaml}---\n\n{content}"
            
            # Extract content after frontmatter
            content_after_frontmatter = content[end_marker + 3:].lstrip('\n')
            
            # Create new frontmatter
            frontmatter_yaml = yaml.dump(metadata, default_flow_style=False, sort_keys=False)
            return f"---\n{frontmatter_yaml}---\n\n{content_after_frontmatter}"
            
        except Exception:
            # If anything fails, just add new frontmatter
            frontmatter_yaml = yaml.dump(metadata, default_flow_style=False, sort_keys=False)
            return f"---\n{frontmatter_yaml}---\n\n{content}"


def update_frontmatter_gdoc_url(markdown_path: str, gdoc_url: str) -> bool:
    """Update the gdoc_url and sync date in markdown frontmatter."""
    try:
        import frontmatter
        from datetime import datetime
        
        # Read current content
        with open(markdown_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse frontmatter
        post = frontmatter.loads(content)
        
        # Update gdoc_url and sync dates
        post.metadata['gdoc_url'] = gdoc_url
        
        current_time = datetime.now().isoformat()
        
        # Set created date if this is the first time we're adding a gdoc_url
        if 'gdoc_created' not in post.metadata:
            post.metadata['gdoc_created'] = current_time
        
        # Always update modified date
        post.metadata['gdoc_modified'] = current_time
        
        # Write back
        with open(markdown_path, 'w', encoding='utf-8') as f:
            f.write(frontmatter.dumps(post))
        
        return True
    except Exception as e:
        print(f"Warning: Could not update frontmatter in {markdown_path}: {e}", file=sys.stderr)
        return False


def update_frontmatter_confluence_url(markdown_path: str, confluence_url: str) -> bool:
    """Update the confluence_url and sync dates in markdown frontmatter."""
    try:
        import frontmatter
        from datetime import datetime
        
        # Read current content
        with open(markdown_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse frontmatter
        post = frontmatter.loads(content)
        
        # Update confluence_url and sync dates
        post.metadata['confluence_url'] = confluence_url
        
        current_time = datetime.now().isoformat()
        
        # Set created date if this is the first time we're adding a confluence_url
        if 'confluence_created' not in post.metadata:
            post.metadata['confluence_created'] = current_time
        
        # Always update modified date
        post.metadata['confluence_modified'] = current_time
        
        # Write back
        with open(markdown_path, 'w', encoding='utf-8') as f:
            f.write(frontmatter.dumps(post))
        
        return True
    except Exception as e:
        print(f"Warning: Could not update frontmatter in {markdown_path}: {e}", file=sys.stderr)
        return False


def strip_frontmatter_for_remote_sync(markdown_content: str) -> str:
    """Strip frontmatter from markdown content for remote platform sync (Google Docs, Confluence, etc.)."""
    # Check if content has frontmatter
    if markdown_content.startswith('---'):
        # Find the end of frontmatter
        lines = markdown_content.split('\n')
        if len(lines) > 1 and lines[0] == '---':
            for i, line in enumerate(lines[1:], 1):
                if line.strip() == '---':
                    # Found end of frontmatter, return content after it
                    return '\n'.join(lines[i+1:]).strip()
    
    # No frontmatter found, return original content
    return markdown_content
