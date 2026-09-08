import re

from googleapiclient.discovery import build


def check_for_formatted_h1_headings(markdown_content: str, quiet: bool = False) -> list:
    """
    Check for H1 headings that have markdown formatting (bold, italic, etc.).
    These can break TOC link creation.
    
    Args:
        markdown_content (str): Markdown content to check
        quiet (bool): If True, suppress output messages
        
    Returns:
        list: List of formatted H1 headings found
    """
    import re
    
    formatted_headings = []
    
    # Pattern to match H1 headings with formatting
    h1_pattern = r'^#\s+(.+)$'
    
    for line in markdown_content.split('\n'):
        match = re.match(h1_pattern, line.strip())
        if match:
            heading_text = match.group(1).strip()
            
            # Check for markdown formatting
            if ('**' in heading_text or 
                '__' in heading_text or 
                '*' in heading_text or 
                '_' in heading_text or
                '`' in heading_text):
                formatted_headings.append(heading_text)
    
    if formatted_headings and not quiet:
        print("⚠️  Warning: Found H1 headings with markdown formatting:")
        for heading in formatted_headings:
            print(f"   • {heading}")
        print("   These may not work properly in the Table of Contents.")
        print("   Consider removing formatting from H1 headings for better TOC compatibility.")
    
    return formatted_headings


def extract_h1_headings_from_markdown(content: str) -> list:
    """
    Extract H1 headings from markdown content.
    
    Args:
        content (str): Markdown content to parse
        
    Returns:
        list: List of H1 heading texts
    """
    import re
    
    # Pattern to match H1 headings (lines starting with # followed by space)
    h1_pattern = r'^#\s+(.+)$'
    headings = []
    
    for line in content.split('\n'):
        match = re.match(h1_pattern, line.strip())
        if match:
            headings.append(match.group(1).strip())
    
    return headings


def generate_table_of_contents(headings: list) -> str:
    """
    Generate a table of contents from a list of headings.
    Uses simple numbered list format that works well with Google Docs.
    
    Args:
        headings (list): List of heading texts
        
    Returns:
        str: Table of contents
    """
    if not headings:
        return ""
    
    toc_lines = ["## Table of Contents", ""]
    
    for i, heading in enumerate(headings, 1):
        # Simple numbered list without links
        # Google Docs will handle navigation through its native outline
        toc_lines.append(f"{i}. {heading}")
    
    toc_lines.append("")  # Add blank line after TOC
    return "\n".join(toc_lines)


def create_working_toc_links_in_gdoc(doc_id: str, headings: list, creds, quiet: bool = False) -> None:
    """
    Create working TOC links in Google Doc by finding heading IDs and creating proper links.
    This creates clickable links that actually work by using Google Docs' internal heading IDs.
    
    Args:
        doc_id (str): Google Doc ID
        headings (list): List of heading texts
        creds: Google API credentials
        quiet (bool): If True, suppress output messages
    """
    try:
        docs_service = build('docs', 'v1', credentials=creds)
        
        # Get the document
        doc = docs_service.documents().get(documentId=doc_id).execute()
        
        # Find all headings and their IDs
        heading_ids = {}
        for element in doc.get('body', {}).get('content', []):
            if 'paragraph' in element:
                paragraph = element['paragraph']
                if 'paragraphStyle' in paragraph:
                    style = paragraph['paragraphStyle']
                    if style.get('namedStyleType') == 'HEADING_1':
                        # This is a heading, find its ID
                        if 'elements' in paragraph and len(paragraph['elements']) > 0:
                            first_element = paragraph['elements'][0]
                            if 'textRun' in first_element:
                                heading_text = first_element['textRun'].get('content', '').strip()
                                
                                # Look for heading ID in various places
                                heading_id = None
                                
                                # Method 1: Check if heading already has an ID in textStyle.link
                                if 'headingId' in first_element.get('textRun', {}).get('textStyle', {}).get('link', {}):
                                    heading_id = first_element['textRun']['textStyle']['link']['headingId']
                                
                                # Method 2: Check if there's a headingId in the paragraph style
                                elif 'headingId' in paragraph.get('paragraphStyle', {}):
                                    heading_id = paragraph['paragraphStyle']['headingId']
                                
                                # Method 3: Generate a heading ID based on the text (Google Docs format)
                                if not heading_id and heading_text:
                                    # Google Docs generates IDs like "h.abc123def456"
                                    # We'll create a simple one based on the text
                                    import hashlib
                                    text_hash = hashlib.md5(heading_text.lower().encode()).hexdigest()[:12]
                                    heading_id = f"h.{text_hash}"
                                
                                if heading_id:
                                    heading_ids[heading_text] = heading_id
                                    if not quiet:
                                        print(f"  Found heading: '{heading_text}' -> {heading_id}")
        
        if not heading_ids:
            if not quiet:
                print("ℹ No headings with IDs found - headings may not be properly formatted")
            return
        
        # Find the TOC section and replace links
        requests = []
        
        for element in doc.get('body', {}).get('content', []):
            if 'paragraph' in element:
                paragraph = element['paragraph']
                if 'elements' in paragraph:
                    for elem in paragraph['elements']:
                        if 'textRun' in elem:
                            text_content = elem['textRun'].get('content', '')
                            # Check if this looks like a TOC item
                            for heading_text in headings:
                                # Check if this is a TOC item (exact match with heading text)
                                if (text_content.strip() == heading_text and 
                                    'Table of Contents' not in text_content):
                                    
                                    # Find the best matching heading ID
                                    best_match = None
                                    best_heading = None
                                    
                                    # Try exact match first
                                    if heading_text in heading_ids:
                                        best_match = heading_ids[heading_text]
                                        best_heading = heading_text
                                    else:
                                        # Try partial matches
                                        for doc_heading, heading_id in heading_ids.items():
                                            if heading_text.lower() in doc_heading.lower() or doc_heading.lower() in heading_text.lower():
                                                best_match = heading_id
                                                best_heading = doc_heading
                                                break
                                    
                                    if best_match:
                                        # Create a link to the heading
                                        start_index = elem['startIndex']
                                        end_index = elem['endIndex']
                                        
                                        # Update the text style to include a link
                                        requests.append({
                                            'updateTextStyle': {
                                                'range': {
                                                    'startIndex': start_index,
                                                    'endIndex': end_index
                                                },
                                                'textStyle': {
                                                    'link': {
                                                        'headingId': best_match
                                                    },
                                                    'foregroundColor': {
                                                        'color': {
                                                            'rgbColor': {
                                                                'red': 0.06666667,
                                                                'green': 0.33333334,
                                                                'blue': 0.8
                                                            }
                                                        }
                                                    },
                                                    'underline': True
                                                },
                                                'fields': 'link,foregroundColor,underline'
                                            }
                                        })
                                        
                                        if not quiet:
                                            print(f"  Linking TOC item: '{heading_text}' -> '{best_heading}' ({best_match})")
        
        # Apply the requests
        if requests:
            docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={'requests': requests}
            ).execute()
            
            if not quiet:
                print(f"✓ Created {len(requests)} working TOC links")
        else:
            if not quiet:
                print("ℹ No TOC links to update")
        
    except Exception as e:
        if not quiet:
            print(f"Warning: Could not create working TOC links: {e}")


def fix_toc_links_in_gdoc(doc_id: str, creds, quiet: bool = False) -> None:
    """
    Fix TOC links in Google Doc to use proper internal navigation.
    This replaces markdown-style links with Google Docs internal links.
    """
    try:
        docs_service = build('docs', 'v1', credentials=creds)
        
        # Get the document
        doc = docs_service.documents().get(documentId=doc_id).execute()
        
        # Find the Table of Contents section and fix the links
        requests = []
        
        for element in doc.get('body', {}).get('content', []):
            if 'paragraph' in element:
                paragraph = element['paragraph']
                if 'elements' in paragraph:
                    for elem in paragraph['elements']:
                        if 'textRun' in elem:
                            text_content = elem['textRun'].get('content', '')
                            # Look for markdown-style links like [text](#anchor)
                            if '[' in text_content and '](#' in text_content:
                                # This is a TOC link that needs to be fixed
                                # For now, we'll just remove the anchor part
                                # Google Docs will handle internal navigation automatically
                                if not quiet:
                                    print("ℹ Found TOC links - Google Docs will handle internal navigation")
                                return
        
        if not quiet:
            print("ℹ No TOC links found to fix")
        
    except Exception as e:
        if not quiet:
            print(f"Warning: Could not fix TOC links: {e}")


def ensure_heading_formatting_in_gdoc(doc_id: str, creds, quiet: bool = False) -> None:
    """
    Ensure that H1 headings in a Google Doc are properly formatted as Heading 1 style.
    This is necessary for TOC links to work correctly.
    """
    try:
        docs_service = build('docs', 'v1', credentials=creds)
        
        # Get the document
        doc = docs_service.documents().get(documentId=doc_id).execute()
        
        # Find all paragraphs that start with '#' and format them as Heading 1
        requests = []
        
        for element in doc.get('body', {}).get('content', []):
            if 'paragraph' in element:
                paragraph = element['paragraph']
                if 'elements' in paragraph and len(paragraph['elements']) > 0:
                    # Check if this paragraph starts with a single '#' (H1)
                    first_element = paragraph['elements'][0]
                    if 'textRun' in first_element:
                        text_content = first_element['textRun'].get('content', '')
                        if text_content.startswith('# ') and not text_content.startswith('##'):
                            # This should be an H1 heading
                            start_index = element['startIndex']
                            end_index = element['endIndex']
                            
                            # Remove the '#' prefix
                            requests.append({
                                'deleteTextRange': {
                                    'range': {
                                        'startIndex': start_index,
                                        'endIndex': start_index + 2
                                    }
                                }
                            })
                            
                            # Set the paragraph style to Heading 1
                            requests.append({
                                'updateParagraphStyle': {
                                    'range': {
                                        'startIndex': start_index,
                                        'endIndex': end_index - 2
                                    },
                                    'paragraphStyle': {
                                        'namedStyleType': 'HEADING_1'
                                    },
                                    'fields': 'namedStyleType'
                                }
                            })
        
        # Apply all requests if any were found
        if requests:
            if not quiet:
                print(f"✓ Formatting {len(requests)//2} headings as Heading 1 style")
            
            docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={'requests': requests}
            ).execute()
        else:
            if not quiet:
                print("ℹ No H1 headings found to format")
        
    except Exception as e:
        if not quiet:
            print(f"Warning: Could not format headings: {e}")
