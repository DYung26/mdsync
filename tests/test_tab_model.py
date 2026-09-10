import tempfile
import unittest
from pathlib import Path

from mdsync.directory import (
    get_document_id,
    get_tab_id,
    load_directory_metadata,
    safe_filename,
    save_directory_metadata,
    set_tab_metadata,
    markdown_files,
)
from mdsync.gdocs import (
    _is_horizontal_rule_element,
    _paragraph_to_markdown,
    create_document_tab,
)
from mdsync.frontmatter import extract_frontmatter_metadata


class FakeBatchUpdate:
    def __init__(self):
        self.body = None

    def execute(self):
        return {'replies': [{'addDocumentTab': {'tabProperties': {'tabId': 't.new'}}}]}


class FakeDocuments:
    def batchUpdate(self, **kwargs):
        self.body = kwargs['body']
        return FakeBatchUpdate()


class FakeDocsService:
    def __init__(self):
        self.documents_obj = FakeDocuments()

    def documents(self):
        return self.documents_obj


class TabModelTests(unittest.TestCase):
    def test_directory_metadata_and_tab_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'Project'
            directory.mkdir()
            save_directory_metadata(directory, {'gdoc': {'doc_id': 'doc1', 'url': 'u', 'title': 'Project'}})
            file = directory / 'Overview.md'
            file.write_text('# Overview\n\nhello\n', encoding='utf-8')
            set_tab_metadata(file, 'tab1', 'Overview')
            self.assertEqual(get_document_id(load_directory_metadata(directory)), 'doc1')
            self.assertEqual(get_tab_id(file), 'tab1')
            self.assertEqual(extract_frontmatter_metadata(file.read_text())['title'], 'Overview')

    def test_safe_filename(self):
        self.assertEqual(safe_filename('A/B:C?'), 'A-B-C-')

    def test_create_tab_request(self):
        service = FakeDocsService()
        self.assertEqual(create_document_tab(service, 'doc1', 'Overview'), 't.new')
        self.assertEqual(service.documents_obj.body['requests'][0]['addDocumentTab']['tabProperties']['title'], 'Overview')

    def test_create_child_tab_request(self):
        service = FakeDocsService()
        self.assertEqual(create_document_tab(service, 'doc1', 'Web', 't.parent'), 't.new')
        properties = service.documents_obj.body['requests'][0]['addDocumentTab']['tabProperties']
        self.assertEqual(properties['title'], 'Web')
        self.assertEqual(properties['parentTabId'], 't.parent')

    def test_markdown_files_are_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'sandbox').mkdir()
            (root / 'sandbox' / 'web').mkdir()
            paths = [root / 'sandbox.md', root / 'sandbox' / 'web.md', root / 'sandbox' / 'web' / 'api.md']
            for path in paths:
                path.write_text('', encoding='utf-8')
            self.assertEqual(markdown_files(root), sorted(paths))

    def test_docs_paragraph_to_markdown(self):
        paragraph = {
            'paragraphStyle': {'namedStyleType': 'HEADING_2'},
            'elements': [{'textRun': {'content': 'Hello\n', 'textStyle': {}}}],
        }
        self.assertEqual(_paragraph_to_markdown(paragraph), '## Hello')

    def test_docs_bullet_to_markdown_preserves_checklist_syntax(self):
        paragraph = {
            'elements': [{'textRun': {'content': 'item\n', 'textStyle': {}}}],
            'bullet': {'listId': 'list1'},
        }
        self.assertEqual(_paragraph_to_markdown(paragraph), '- [ ] item')

    def test_source_text_omits_terminal_structural_paragraph(self):
        from mdsync.gdocs import _source_text
        source = {
            'documentTab': {'body': {'content': [
                {'paragraph': {'elements': [{'textRun': {'content': 'one\n'}}]}},
                {'paragraph': {'elements': [{'textRun': {'content': 'two\n'}}]}},
                {'paragraph': {'elements': [{'textRun': {'content': '\n'}}]}},
            ]}}
        }
        self.assertEqual(_source_text(source), 'one\ntwo\n')

    def test_html_comment_is_non_rendering_markdown(self):
        from mdsync.gdocs import _is_html_comment
        self.assertTrue(_is_html_comment('<!-- hidden implementation note -->'))
        self.assertTrue(_is_html_comment('<!-- multi-word comment -->\n'))
        self.assertFalse(_is_html_comment('<!-- incomplete'))
        self.assertFalse(_is_html_comment('visible text'))

    def test_docs_horizontal_rule_paragraph_to_markdown(self):
        paragraph = {
            'paragraphStyle': {
                'borderBottom': {
                    'width': {'magnitude': 1, 'unit': 'PT'},
                },
            },
            'elements': [{'textRun': {'content': '\n', 'textStyle': {}}}],
        }
        self.assertEqual(_paragraph_to_markdown(paragraph), '---')

    def test_docs_horizontal_rule_element_to_markdown(self):
        element = {'horizontalRule': {}}
        self.assertTrue(_is_horizontal_rule_element(element))
        self.assertFalse(_is_horizontal_rule_element({'textRun': {}}))
        paragraph = {'elements': [element]}
        self.assertEqual(_paragraph_to_markdown(paragraph), '---')

    def test_thematic_break_is_accepted_as_structural_markdown(self):
        from mdsync.gdocs import _is_thematic_break
        self.assertTrue(_is_thematic_break('---'))
        self.assertTrue(_is_thematic_break('***'))
        self.assertTrue(_is_thematic_break('_ _ _'))
        self.assertFalse(_is_thematic_break('--'))
        self.assertFalse(_is_thematic_break('not a rule'))

    def test_empty_markdown_has_no_phantom_terminal_line(self):
        from mdsync.gdocs import _markdown_lines
        self.assertEqual(_markdown_lines("\n"), [])
        self.assertEqual(_markdown_lines("   \n"), [])
        self.assertEqual(_markdown_lines("one\n"), ["one\n"])

    def test_docs_inline_style_keeps_leading_and_trailing_spaces_unstyled(self):
        paragraph = {
            'elements': [
                {'textRun': {'content': 'title', 'textStyle': {}}},
                {'textRun': {'content': ' ::: id=abc ', 'textStyle': {'bold': True}}},
                {'textRun': {'content': 'next', 'textStyle': {}}},
            ],
        }
        self.assertEqual(
            _paragraph_to_markdown(paragraph),
            'title **::: id=abc** next',
        )

    def test_docs_strikethrough_run_to_markdown(self):
        paragraph = {
            'elements': [
                {'textRun': {'content': 'before ', 'textStyle': {}}},
                {'textRun': {'content': 'struck', 'textStyle': {'strikethrough': True}}},
                {'textRun': {'content': ' after\n', 'textStyle': {}}},
            ],
        }
        self.assertEqual(
            _paragraph_to_markdown(paragraph),
            'before ~~struck~~ after',
        )

    def test_docs_inline_styles_all_keep_surrounding_spaces_unstyled(self):
        paragraph = {
            'elements': [
                {'textRun': {'content': ' bold ', 'textStyle': {'bold': True}}},
                {'textRun': {'content': ' italic ', 'textStyle': {'italic': True}}},
                {'textRun': {'content': ' under ', 'textStyle': {'underline': True}}},
            ],
        }
        self.assertEqual(
            _paragraph_to_markdown(paragraph),
            ' **bold**  *italic*  <u>under</u> ',
        )

    def test_docs_bold_run_is_closed_before_paragraph_newline(self):
        paragraph = {
            'elements': [
                {'textRun': {'content': 'TASKS ::: id; estimate', 'textStyle': {'bold': True}}},
                {'textRun': {'content': '\n', 'textStyle': {}}},
            ],
        }
        self.assertEqual(
            _paragraph_to_markdown(paragraph),
            '**TASKS ::: id; estimate**',
        )


if __name__ == '__main__':
    unittest.main()

class ThreeWayMergeTests(unittest.TestCase):
    def test_clean_non_overlapping_merge(self):
        from mdsync.tab_sync import _three_way_merge
        base = 'A\nB\nC\nD\n'
        local = 'A\nB-local\nC\nD\n'
        remote = 'A\nB\nC\nD-remote\n'
        merged, conflicts = _three_way_merge(base, local, remote)
        self.assertEqual(merged, 'A\nB-local\nC\nD-remote\n')
        self.assertEqual(conflicts, [])

    def test_conflict_writes_markers(self):
        from mdsync.tab_sync import _three_way_merge
        base = 'A\nB\nC\n'
        local = 'A\nB-local\nC\n'
        remote = 'A\nB-remote\nC\n'
        merged, conflicts = _three_way_merge(base, local, remote)
        self.assertEqual(conflicts, [1])
        self.assertIn('<<<<<<< LOCAL (conflict 1)', merged)
        self.assertIn('B-local', merged)
        self.assertIn('=======', merged)
        self.assertIn('B-remote', merged)
        self.assertIn('>>>>>>> GOOGLE-DOCS', merged)

    def test_identical_changes_merge_without_conflict(self):
        from mdsync.tab_sync import _three_way_merge
        base = 'A\nB\n'
        local = 'A\nchanged\n'
        remote = 'A\nchanged\n'
        merged, conflicts = _three_way_merge(base, local, remote)
        self.assertEqual(merged, 'A\nchanged\n')
        self.assertEqual(conflicts, [])

    def test_remote_only_change_returns_remote(self):
        from mdsync.tab_sync import _three_way_merge
        base = 'A\nB\n'
        local = base
        remote = 'A\nB-remote\n'
        merged, conflicts = _three_way_merge(base, local, remote)
        self.assertEqual(merged, remote)
        self.assertEqual(conflicts, [])

class ConflictStateTests(unittest.TestCase):
    def test_conflict_state_round_trip(self):
        from mdsync.sync_state import clear_conflict_state, load_conflict_state, save_conflict_state
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'todo.md'
            path.write_text('resolved\n', encoding='utf-8')
            save_conflict_state(path, 'tab1', 'base\n', 'remote\n', '42')
            self.assertEqual(load_conflict_state(path, 'tab1'), {'baseline': 'base\n', 'remote': 'remote\n', 'remote_version': '42'})
            clear_conflict_state(path, 'tab1')
            self.assertIsNone(load_conflict_state(path, 'tab1'))

class SyncMessageTests(unittest.TestCase):
    def test_sync_message_strings_exist(self):
        from pathlib import Path
        source = Path(__file__).parents[1] / 'mdsync' / 'tab_sync.py'
        text = source.read_text(encoding='utf-8')
        self.assertIn('Local changes detected; pushing local changes to Google Docs.', text)
        self.assertIn('Google Docs changes detected; pulling remote changes into the local file.', text)
        self.assertIn('Local and Google Docs changes detected; changes do not conflict, merging and pushing.', text)
        self.assertIn('No local or Google Docs changes detected; nothing to sync.', text)
