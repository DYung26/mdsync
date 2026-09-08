"""Directory/file synchronization for real Google Docs tabs."""

from pathlib import Path
import difflib

from googleapiclient.discovery import build

from .auth import get_credentials
from .directory import (
    get_document_id,
    get_tab_id,
    markdown_files,
    set_google_doc_metadata,
    set_tab_metadata,
    unique_markdown_path,
)
from .frontmatter import extract_frontmatter_metadata
from .gdocs import (
    _find_tab_by_id,
    _find_tab_by_title,
    _get_document_tabs,
    _tab_title,
    _tab_text,
    create_document_tab,
    create_tabbed_document_from_markdown,
    export_tab_to_markdown,
    _replace_tab_content,
    _sync_compare_content,
    _converted_document_body,
    apply_markdown_diff_to_tab,
)
from .urls import extract_doc_id, extract_doc_id_from_url
from .sync_state import (
    clear_conflict_state,
    load_conflict_state,
    load_sync_state,
    save_conflict_state,
    save_sync_state,
)


def _doc_id(value):
    return extract_doc_id_from_url(value) or extract_doc_id(value)


def _doc_url(doc_id):
    return f"https://docs.google.com/document/d/{doc_id}/edit"


def _doc_title(drive_service, doc_id):
    file = drive_service.files().get(fileId=doc_id, fields='name').execute()
    return file.get('name') or 'Untitled'


def _tab_files_by_id(directory):
    result = {}
    for path in markdown_files(directory):
        tab_id = get_tab_id(path)
        if tab_id:
            result[tab_id] = path
    return result


def _tab_title_for_file(path):
    content = Path(path).read_text(encoding='utf-8')
    metadata = extract_frontmatter_metadata(content)
    return metadata.get('title') or Path(path).stem


def pull_document_to_directory(doc_id, destination, creds=None, parent=False, quiet=False):
    """Pull all tabs from a Google Doc into a directory."""
    creds = creds or get_credentials()
    docs_service = build('docs', 'v1', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)
    title = _doc_title(drive_service, doc_id)
    base = Path(destination)
    directory = base / title if parent else base
    directory.mkdir(parents=True, exist_ok=True)
    set_google_doc_metadata(directory, doc_id, _doc_url(doc_id), title)
    _, tabs = _get_document_tabs(docs_service, doc_id)

    reserved = []
    for tab in tabs:
        tab_id = tab['tabProperties']['tabId']
        tab_title = _tab_title(tab) or 'Untitled'
        existing = _tab_files_by_id(directory).get(tab_id)
        if existing and existing.stem != tab_title:
            renamed = directory / f'{existing.stem}.md'
            candidate = directory / f'{tab_title}.md'
            candidate = unique_markdown_path(directory, tab_title, [existing]) if candidate.resolve() != existing.resolve() else existing
            if candidate != existing and not candidate.exists():
                existing.rename(candidate)
                existing = candidate
        path = existing or unique_markdown_path(directory, tab_title, reserved)
        content = export_tab_to_markdown(docs_service, doc_id, tab_id)
        save_sync_state(path, tab_id, content)
        metadata = {'title': tab_title, 'gdoc_tab_id': tab_id}
        from .frontmatter import update_frontmatter_metadata
        path.write_text(update_frontmatter_metadata(content, metadata), encoding='utf-8')
        reserved.append(path)
        if not quiet:
            print(f"  ✓ {tab_title} -> {path}")
    return directory


def pull_tab_to_file(doc_id, tab_id, destination, creds=None, quiet=False):
    """Pull one Google Docs tab into one Markdown file."""
    creds = creds or get_credentials()
    docs_service = build('docs', 'v1', credentials=creds)
    _, tabs = _get_document_tabs(docs_service, doc_id)
    tab = _find_tab_by_id(tabs, tab_id) or _find_tab_by_title(tabs, tab_id)
    if not tab:
        raise ValueError(f"Google Docs tab not found: {tab_id}")
    title = _tab_title(tab) or Path(destination).stem
    content = export_tab_to_markdown(docs_service, doc_id, tab['tabProperties']['tabId'])
    save_sync_state(destination, tab['tabProperties']['tabId'], content)
    from .frontmatter import update_frontmatter_metadata
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(update_frontmatter_metadata(content, {'title': title, 'gdoc_tab_id': tab['tabProperties']['tabId']}), encoding='utf-8')
    if not quiet:
        print(f"✓ Pulled tab '{title}' -> {output}")
    return output


def _write_file_to_tab(markdown_path, doc_id, tab_id, creds, quiet=False, baseline_override=None):
    content = Path(markdown_path).read_text(encoding="utf-8")
    local_remote = _remote_content(content)
    docs_service = build("docs", "v1", credentials=creds)
    _, tabs = _get_document_tabs(docs_service, doc_id)
    target = _find_tab_by_id(tabs, tab_id)
    if not target:
        raise ValueError(f"Google Docs tab not found: {tab_id}")
    baseline = baseline_override if baseline_override is not None else load_sync_state(markdown_path, tab_id)
    if baseline is None:
        remote = export_tab_to_markdown(docs_service, doc_id, tab_id)
        if remote.strip() != local_remote.strip():
            raise RuntimeError(f"No sync baseline exists for {markdown_path}; pull the tab before pushing local changes")
        save_sync_state(markdown_path, tab_id, remote)
        if not quiet:
            print(f"No changes: {markdown_path}")
        return False
    changed = apply_markdown_diff_to_tab(docs_service, doc_id, tab_id, baseline, local_remote, creds)
    if changed:
        # Store the remote canonical representation after a successful push.
        # Google Docs may normalize Markdown syntax (for example ~text~ to
        # ~~text~~), so using the pre-push local spelling as the remote baseline
        # causes a false conflict on the next push.
        pushed_remote = export_tab_to_markdown(docs_service, doc_id, tab_id)
        save_sync_state(markdown_path, tab_id, pushed_remote)
        if not quiet:
            print(f"✓ Updated tab for {markdown_path}")
    elif not quiet:
        print(f"No changes: {markdown_path}")
    return changed


def _remote_content(content):
    from .frontmatter import strip_frontmatter_for_remote_sync
    remote = strip_frontmatter_for_remote_sync(content).replace("\r\n", "\n").replace("\r", "\n").strip()
    return remote + "\n" if remote else ""



def _content_lines(content):
    return _remote_content(content).splitlines()


def _diff_hunks(base_lines, changed_lines):
    return [
        (a1, a2, changed_lines[b1:b2])
        for tag, a1, a2, b1, b2 in difflib.SequenceMatcher(None, base_lines, changed_lines).get_opcodes()
        if tag != 'equal'
    ]


def _hunks_overlap(left, right):
    a1, a2, _ = left
    b1, b2, _ = right
    if a1 == a2 and b1 == b2:
        return a1 == b1
    if a1 == a2:
        return b1 <= a1 <= b2
    if b1 == b2:
        return a1 <= b1 <= a2
    return max(a1, b1) < min(a2, b2)


def _render_hunks(base_lines, hunks, start, end):
    out = []
    cursor = start
    for a1, a2, replacement in hunks:
        if a1 < start or a1 > end:
            continue
        out.extend(base_lines[cursor:a1])
        out.extend(replacement)
        cursor = a2
    out.extend(base_lines[cursor:end])
    return out


def _three_way_merge(base, local, remote):
    """Three-way line merge. Returns (merged_text, conflicts)."""
    base_lines = _content_lines(base)
    local_lines = _content_lines(local)
    remote_lines = _content_lines(remote)
    local_hunks = _diff_hunks(base_lines, local_lines)
    remote_hunks = _diff_hunks(base_lines, remote_lines)

    if not local_hunks:
        return remote, []
    if not remote_hunks:
        return local, []

    all_hunks = [('local', h) for h in local_hunks] + [('remote', h) for h in remote_hunks]
    all_hunks.sort(key=lambda item: (item[1][0], item[1][1], 0 if item[0] == 'local' else 1))
    merged = []
    conflicts = []
    cursor = 0
    i = 0

    while i < len(all_hunks):
        _, first = all_hunks[i]
        start = first[0]
        if start > cursor:
            merged.extend(base_lines[cursor:start])

        group = [all_hunks[i]]
        end = first[1]
        i += 1
        changed = True
        while changed:
            changed = False
            j = i
            while j < len(all_hunks):
                candidate = all_hunks[j][1]
                if _hunks_overlap(first, candidate) or any(_hunks_overlap(h, candidate) for _, h in group):
                    group.append(all_hunks[j])
                    end = max(end, candidate[1])
                    all_hunks.pop(j)
                    changed = True
                else:
                    j += 1
            # Re-sort remaining isn't necessary because only later hunks are consumed.

        local_group = [h for side, h in group if side == 'local']
        remote_group = [h for side, h in group if side == 'remote']
        local_render = _render_hunks(base_lines, sorted(local_group), start, end)
        remote_render = _render_hunks(base_lines, sorted(remote_group), start, end)

        if not local_group:
            merged.extend(remote_render)
        elif not remote_group:
            merged.extend(local_render)
        elif local_render == remote_render:
            merged.extend(local_render)
        else:
            conflict_id = len(conflicts) + 1
            merged.extend([
                f'<<<<<<< LOCAL (conflict {conflict_id})',
                *local_render,
                '=======',
                *remote_render,
                '>>>>>>> GOOGLE-DOCS',
            ])
            conflicts.append(conflict_id)
        cursor = end

    merged.extend(base_lines[cursor:])
    return '\n'.join(merged) + ('\n' if merged else ''), conflicts


def _has_conflict_markers(content):
    return any(line.startswith(('<<<<<<< ', '=======', '>>>>>>> ')) for line in content.splitlines())


def sync_file(markdown_path, creds=None, quiet=False):
    """Three-way synchronize one directory-backed Markdown tab."""
    creds = creds or get_credentials()
    path = Path(markdown_path)
    from .directory import load_directory_metadata
    metadata = load_directory_metadata(path.parent)
    doc_id = get_document_id(metadata)
    tab_id = get_tab_id(path)
    if not doc_id or not tab_id:
        raise ValueError(f"{path} is not associated with a directory-backed Google Docs tab")

    local_full = path.read_text(encoding='utf-8')
    conflict_state = load_conflict_state(path, tab_id)
    if conflict_state is not None:
        if _has_conflict_markers(_remote_content(local_full)):
            raise ValueError(f"Unresolved sync conflicts remain in {path}; resolve them, then run mdsync resolve {path}")
        raise ValueError(f"Conflicts were previously recorded for {path}; after resolving the file, run mdsync resolve {path} to confirm the final content for Google Docs")
    if _has_conflict_markers(_remote_content(local_full)):
        raise ValueError(f"Unresolved sync conflicts remain in {path}; resolve the conflict markers before syncing again")

    baseline = load_sync_state(path, tab_id)
    if baseline is None:
        raise ValueError(f"No sync baseline exists for {path}; pull the tab before syncing")

    docs_service = build('docs', 'v1', credentials=creds)
    _, tabs = _get_document_tabs(docs_service, doc_id)
    if not _find_tab_by_id(tabs, tab_id):
        raise ValueError(f"Google Docs tab not found: {tab_id}")
    remote = export_tab_to_markdown(docs_service, doc_id, tab_id)
    local = _remote_content(local_full)
    base = _remote_content(baseline)

    local_changed = _sync_compare_content(local) != _sync_compare_content(base)
    remote_changed = _sync_compare_content(remote) != _sync_compare_content(base)

    if not local_changed and not remote_changed:
        if not quiet:
            print(f"No local or Google Docs changes detected; nothing to sync.")
        return False
    if remote_changed and not local_changed:
        from .frontmatter import update_frontmatter_metadata
        title = extract_frontmatter_metadata(local_full).get('title') or path.stem
        path.write_text(update_frontmatter_metadata(remote, {'title': title, 'gdoc_tab_id': tab_id}), encoding='utf-8')
        save_sync_state(path, tab_id, remote)
        if not quiet:
            print(f"Google Docs changes detected; pulling remote changes into the local file.")
            print(f"✓ Pulled remote changes into {path}")
        return True
    if local_changed and not remote_changed:
        if not quiet:
            print(f"Local changes detected; pushing local changes to Google Docs.")
        return _write_file_to_tab(path, doc_id, tab_id, creds, quiet)

    merged, conflicts = _three_way_merge(base, local, remote)
    if conflicts:
        from .frontmatter import update_frontmatter_metadata
        title = extract_frontmatter_metadata(local_full).get('title') or path.stem
        path.write_text(update_frontmatter_metadata(merged, {'title': title, 'gdoc_tab_id': tab_id}), encoding='utf-8')
        save_conflict_state(path, tab_id, base, remote)
        if not quiet:
            print(f"⚠ Conflicts written to {path}; resolve them, then run mdsync resolve {path} to confirm the final content.")
        return False

    from .frontmatter import update_frontmatter_metadata
    title = extract_frontmatter_metadata(local_full).get('title') or path.stem
    path.write_text(update_frontmatter_metadata(merged, {'title': title, 'gdoc_tab_id': tab_id}), encoding='utf-8')
    if not quiet:
        print(f"Local and Google Docs changes detected; changes do not conflict, merging and pushing.")
    # The merged document already incorporates the current remote state. Use
    # that remote representation as the push baseline; using the older stored
    # baseline would make the targeted push reject its own merge as a remote
    # change.
    return _write_file_to_tab(path, doc_id, tab_id, creds, quiet, baseline_override=remote)


def resolve_file(markdown_path, creds=None, quiet=False):
    """Confirm a manually resolved conflict and push it safely."""
    creds = creds or get_credentials()
    path = Path(markdown_path)
    from .directory import load_directory_metadata
    metadata = load_directory_metadata(path.parent)
    doc_id = get_document_id(metadata)
    tab_id = get_tab_id(path)
    if not doc_id or not tab_id:
        raise ValueError(f"{path} is not associated with a directory-backed Google Docs tab")

    state = load_conflict_state(path, tab_id)
    if state is None:
        raise ValueError(f"No pending conflict exists for {path}")

    content = path.read_text(encoding='utf-8')
    if _has_conflict_markers(_remote_content(content)):
        raise ValueError(f"Unresolved sync conflicts remain in {path}; remove all conflict markers before confirming")

    docs_service = build('docs', 'v1', credentials=creds)
    _, tabs = _get_document_tabs(docs_service, doc_id)
    if not _find_tab_by_id(tabs, tab_id):
        raise ValueError(f"Google Docs tab not found: {tab_id}")
    remote = export_tab_to_markdown(docs_service, doc_id, tab_id)
    if _sync_compare_content(remote) != _sync_compare_content(state['remote']):
        raise ValueError(f"Google Docs changed after the conflict was created; refusing to overwrite remote changes. Pull/sync again to create a new conflict.")

    changed = _write_file_to_tab(path, doc_id, tab_id, creds, quiet, baseline_override=state['remote'])
    clear_conflict_state(path, tab_id)
    if not quiet:
        print(f"✓ Conflict resolution confirmed and pushed for {path}")
    return changed

def push_file(markdown_path, creds=None, quiet=False):
    """Push one Markdown file, using directory metadata for tab-backed files."""
    creds = creds or get_credentials()
    path = Path(markdown_path)
    directory = path.parent
    from .directory import load_directory_metadata
    metadata = load_directory_metadata(directory)
    doc_id = get_document_id(metadata)
    tab_id = get_tab_id(path)
    if doc_id:
        docs_service = build('docs', 'v1', credentials=creds)
        if not tab_id:
            tab_id = create_document_tab(docs_service, doc_id, _tab_title_for_file(path))
            set_tab_metadata(path, tab_id, _tab_title_for_file(path))
        elif not _find_tab_by_id(_get_document_tabs(docs_service, doc_id)[1], tab_id):
            tab_id = create_document_tab(docs_service, doc_id, _tab_title_for_file(path))
            set_tab_metadata(path, tab_id, _tab_title_for_file(path))
        return _write_file_to_tab(path, doc_id, tab_id, creds, quiet)
    # Preserve the legacy one-file -> whole-document mode.
    from .gdocs import import_markdown_to_gdoc
    content = path.read_text(encoding='utf-8')
    fm = extract_frontmatter_metadata(content)
    remote = fm.get('gdoc_url')
    if not remote:
        raise ValueError(f"No gdoc_url in {path} and no directory tab metadata found")
    return import_markdown_to_gdoc(str(path), _doc_id(remote), creds, quiet=quiet)


def push_directory(directory, creds=None, quiet=False):
    """Push all local tab files in a directory to their corresponding tabs."""
    creds = creds or get_credentials()
    from .directory import load_directory_metadata
    metadata = load_directory_metadata(directory)
    doc_id = get_document_id(metadata)
    if not doc_id:
        raise ValueError(f"{directory} has no {'.mdsync.yaml'} Google Doc metadata")
    return [(path, push_file(path, creds, quiet)) for path in markdown_files(directory)]


def sync_directory(directory, creds=None, quiet=False):
    """Reconcile a local tab directory with its Google Doc."""
    creds = creds or get_credentials()
    from .directory import load_directory_metadata
    metadata = load_directory_metadata(directory)
    doc_id = get_document_id(metadata)
    if not doc_id:
        raise ValueError(f"{directory} has no Google Doc metadata")
    docs_service = build('docs', 'v1', credentials=creds)
    _, tabs = _get_document_tabs(docs_service, doc_id)
    local_by_id = _tab_files_by_id(directory)
    remote_ids = set()
    for tab in tabs:
        tab_id = tab['tabProperties']['tabId']
        remote_ids.add(tab_id)
        if tab_id not in local_by_id:
            title = _tab_title(tab) or 'Untitled'
            path = unique_markdown_path(directory, title)
            from .frontmatter import update_frontmatter_metadata
            content = export_tab_to_markdown(docs_service, doc_id, tab_id)
            path.write_text(update_frontmatter_metadata(content, {'title': title, 'gdoc_tab_id': tab_id}), encoding='utf-8')
            if not quiet:
                print(f"  ✓ Created local tab file: {path}")
    for tab_id, path in local_by_id.items():
        if tab_id not in remote_ids:
            # A local tab with a stale ID is safely recreated remotely.
            title = _tab_title_for_file(path)
            new_tab_id = create_document_tab(docs_service, doc_id, title)
            set_tab_metadata(path, new_tab_id, title)
            _write_file_to_tab(path, doc_id, new_tab_id, creds, quiet)
            if not quiet:
                print(f"  ✓ Created remote tab: {title}")
    return [(path, sync_file(path, creds, quiet)) for path in markdown_files(directory)]


def create_directory_document(markdown_files_list, parent, title=None, creds=None, quiet=False):
    """Create a local directory-backed Google Doc with one real tab per Markdown file."""
    creds = creds or get_credentials()
    files = [Path(p) for p in markdown_files_list]
    if not files:
        raise ValueError('At least one Markdown file is required')
    title = title or files[0].stem
    directory = Path(parent) / title
    directory.mkdir(parents=True, exist_ok=True)

    local_files = []
    for source in files:
        target = directory / source.name
        if source.resolve() != target.resolve():
            target.write_text(source.read_text(encoding='utf-8'), encoding='utf-8')
        local_files.append(target)

    doc_id = create_tabbed_document_from_markdown(local_files, title, creds, quiet)
    set_google_doc_metadata(directory, doc_id, _doc_url(doc_id), title)
    return directory
