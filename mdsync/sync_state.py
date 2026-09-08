from pathlib import Path
import hashlib
import json

STATE_DIRNAME = '.mdsync-state'


def _state_path(markdown_path, tab_id):
    path = Path(markdown_path)
    state_dir = path.parent / STATE_DIRNAME
    state_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(tab_id.encode('utf-8')).hexdigest()[:16]
    return state_dir / f'{digest}.md'


def save_sync_state(markdown_path, tab_id, content):
    _state_path(markdown_path, tab_id).write_text(content, encoding='utf-8')


def load_sync_state(markdown_path, tab_id):
    path = _state_path(markdown_path, tab_id)
    if not path.exists():
        return None
    return path.read_text(encoding='utf-8')


def _conflict_path(markdown_path, tab_id):
    path = Path(markdown_path)
    state_dir = path.parent / STATE_DIRNAME
    state_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(tab_id.encode('utf-8')).hexdigest()[:16]
    return state_dir / f'{digest}.conflict.json'


def save_conflict_state(markdown_path, tab_id, baseline, remote):
    _conflict_path(markdown_path, tab_id).write_text(
        json.dumps({'baseline': baseline, 'remote': remote}, ensure_ascii=False),
        encoding='utf-8',
    )


def load_conflict_state(markdown_path, tab_id):
    path = _conflict_path(markdown_path, tab_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding='utf-8'))


def clear_conflict_state(markdown_path, tab_id):
    path = _conflict_path(markdown_path, tab_id)
    if path.exists():
        path.unlink()
