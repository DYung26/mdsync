"""Directory-backed Google Docs tab synchronization."""

from pathlib import Path
import re

import yaml

from .frontmatter import extract_frontmatter_metadata, update_frontmatter_metadata

METADATA_FILENAME = '.mdsync.yaml'
TAB_ID_KEY = 'gdoc_tab_id'


def metadata_path(directory):
    return Path(directory) / METADATA_FILENAME


def load_directory_metadata(directory):
    path = metadata_path(directory)
    if not path.exists():
        return {}
    with path.open('r', encoding='utf-8') as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid {METADATA_FILENAME}: expected a YAML mapping")
    return data


def save_directory_metadata(directory, metadata):
    path = metadata_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as handle:
        yaml.safe_dump(metadata, handle, default_flow_style=False, sort_keys=False)
    return path


def get_document_id(metadata):
    document = metadata.get('gdoc')
    return document.get('doc_id') if isinstance(document, dict) else None


def get_document_url(metadata):
    document = metadata.get('gdoc')
    return document.get('url') if isinstance(document, dict) else None


def set_google_doc_metadata(directory, doc_id, url, title):
    metadata = load_directory_metadata(directory)
    metadata['gdoc'] = {'doc_id': doc_id, 'url': url, 'title': title}
    return save_directory_metadata(directory, metadata)


def get_tab_id(markdown_path):
    """Return the remote Google Docs tab ID stored in a tab file."""
    path = Path(markdown_path)
    content = path.read_text(encoding='utf-8')
    metadata = extract_frontmatter_metadata(content)
    return metadata.get(TAB_ID_KEY)


def set_tab_metadata(markdown_path, tab_id, tab_title=None):
    """Store a tab's immutable remote ID in its Markdown frontmatter."""
    path = Path(markdown_path)
    content = path.read_text(encoding='utf-8')
    values = {TAB_ID_KEY: tab_id}
    if tab_title:
        values['title'] = tab_title
    path.write_text(update_frontmatter_metadata(content, values), encoding='utf-8')


def clear_legacy_batch_metadata(markdown_path):
    """Remove legacy batch metadata when migrating a tab file."""
    path = Path(markdown_path)
    content = path.read_text(encoding='utf-8')
    metadata = extract_frontmatter_metadata(content)
    if not metadata.get('batch'):
        return
    try:
        import frontmatter
        post = frontmatter.loads(content)
        post.metadata.pop('batch', None)
        path.write_text(frontmatter.dumps(post), encoding='utf-8')
    except Exception:
        pass


def safe_filename(name):
    """Turn a Google Docs tab title into a safe Markdown filename stem."""
    name = re.sub(r'[\\/:*?"<>|]', '-', name).strip().rstrip('.')
    name = re.sub(r'\s+', ' ', name)
    return name or 'Untitled'


def unique_markdown_path(directory, title, reserved=None):
    """Return a deterministic, non-colliding Markdown path for a tab title."""
    reserved = {str(Path(p).resolve()) for p in (reserved or [])}
    stem = safe_filename(title)
    candidate = Path(directory) / f'{stem}.md'
    index = 2
    while str(candidate.resolve()) in reserved or candidate.exists():
        candidate = Path(directory) / f'{stem} ({index}).md'
        index += 1
    return candidate


def markdown_files(directory):
    """Return Markdown tab files directly contained by a sync directory."""
    path = Path(directory)
    return sorted(p for p in path.glob('*.md') if p.is_file())
