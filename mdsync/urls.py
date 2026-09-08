import re


def extract_doc_id(url_or_id: str) -> str:
    """Extract document ID from a Google Docs URL or return the ID if already provided."""
    # If it's already just an ID (no slashes or dots), return it
    if '/' not in url_or_id and '.' not in url_or_id:
        return url_or_id
    
    # Try to extract from URL
    match = re.search(r'/document/d/([a-zA-Z0-9-_]+)', url_or_id)
    if match:
        return match.group(1)
    
    # If no match, assume it's already an ID
    return url_or_id


def extract_doc_id_from_url(url: str) -> str:
    """Extract Google Doc ID from various URL formats."""
    import re
    
    # Handle different Google Docs URL formats
    patterns = [
        r'/document/d/([a-zA-Z0-9-_]+)',  # Standard format
        r'id=([a-zA-Z0-9-_]+)',          # Alternative format
        r'^([a-zA-Z0-9-_]+)$'            # Just the ID
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return None


def is_google_doc(path: str) -> bool:
    """Check if the path is a Google Docs URL or ID."""
    if not path:
        return False
    return ('docs.google.com' in path or 
            ('/' not in path and '.' not in path and len(path) > 20))


def is_confluence_page(path: str) -> bool:
    """Check if the path is a Confluence page URL or ID."""
    if not path:
        return False
    return ('atlassian.net/wiki' in path or 
            path.startswith('confluence:') or
            (path.isdigit() and len(path) < 20))  # Confluence page IDs are numeric
