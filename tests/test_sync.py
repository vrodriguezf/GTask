import copy
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from googleapiclient.errors import HttpError
from httplib2 import Response

from tasks_tui.main import AppState, handle_input, main_loop
from tasks_tui.task_service import TaskService


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            'task_lists': [{'id': 'list', 'title': 'List'}],
            'tasks': {'list': [
                {'id': 'first', 'title': 'First', 'status': 'needsAction'},
                {'id': 'second', 'title': 'Second', 'status': 'needsAction'},
            ]},
        }
        self.remote = copy.deepcopy(self.data)
        self.api = Mock()
        self.api.tasklists.return_value.list.return_value.execute.side_effect = (
            lambda: {'items': copy.deepcopy(self.remote['task_lists'])})
        self.api.tasks.return_value.list.side_effect = lambda tasklist, **kwargs: Mock(
            execute=lambda: {'items': copy.deepcopy(self.remote['tasks'].get(tasklist, []))})

        def patch_task(tasklist, task, body):
            def execute():
                remote_task = next(item for item in self.remote['tasks'][tasklist] if item['id'] == task)
                remote_task.update(body)
                return copy.deepcopy(remote_task)
            return Mock(execute=execute)

        self.api.tasks.return_value.patch.side_effect = patch_task
        self.addCleanup(patch.stopall)
        self.save = patch('tasks_tui.task_service.local_storage.save_data').start()
        patch('tasks_tui.task_service.local_storage.load_data', return_value=copy.deepcopy(self.data)).start()
        patch('tasks_tui.task_service.get_credentials').start()
        patch('tasks_tui.task_service.build', return_value=self.api).start()
        self.service = TaskService()
        self.service.sync_from_google()
        self.save.reset_mock()

    def make_ui(self):
        return SimpleNamespace(active_panel='tasks', selected_list_idx=0, selected_task_idx=1,
                               task_scroll_offset=0, start_sync_animation=Mock(),
                               stop_sync_animation=Mock(), show_temporary_message=Mock())

    def press(self, key, state, ui):
        with patch('tasks_tui.main.getch', return_value=ord(key)):
            return handle_input(None, state, ui)

    def run_loop(self, keys, ui):
        ui.draw_layout = Mock()
        with ExitStack() as stack:
            stack.enter_context(patch('tasks_tui.main.TaskService', return_value=self.service))
            stack.enter_context(patch('tasks_tui.main.UIManager', return_value=ui))
            stack.enter_context(patch('tasks_tui.main.getch', side_effect=(ord(key) for key in keys)))
            for name in ('curs_set', 'noecho', 'cbreak', 'keypad'):
                stack.enter_context(patch('tasks_tui.main.' + name))
            main_loop(None)

    def test_edit_and_completion_upload_before_next_key_without_fetching_cloud_changes(self):
        ui = self.make_ui()
        ui.task_form = Mock(return_value={'title': 'Auto saved', 'due': '2026-10-01'})
        self.remote['tasks']['list'][0]['title'] = 'Changed on phone'

        def keys():
            yield 'e'
            self.assertEqual(self.remote['tasks']['list'][1]['title'], 'Auto saved')
            self.assertEqual(self.remote['tasks']['list'][1]['due'], '2026-10-01T00:00:00Z')
            self.assertFalse(self.service.dirty)
            self.assertEqual(self.service.get_task('list', 'first')['title'], 'First')
            self.assertEqual(ui.selected_task_idx, 0)
            yield 'c'
            self.assertEqual(self.remote['tasks']['list'][1]['status'], 'completed')
            self.assertFalse(self.service.dirty)
            yield 'q'

        with patch.object(self.service, 'sync_from_google', wraps=self.service.sync_from_google) as download:
            self.run_loop(keys(), ui)
            download.assert_not_called()
        self.assertEqual(self.api.tasks.return_value.patch.call_count, 2)

    def test_create_paste_delete_and_note_edit_upload_automatically(self):
        ui = self.make_ui()
        ui.task_form = Mock(return_value={'title': 'New task', 'due': ''})

        def insert_task(tasklist, body, parent=None):
            def execute():
                created = dict(body, id='created-' + str(len(self.remote['tasks'][tasklist])))
                self.remote['tasks'][tasklist].append(created)
                return copy.deepcopy(created)
            return Mock(execute=execute)

        def delete_task(tasklist, task):
            def execute():
                self.remote['tasks'][tasklist] = [item for item in self.remote['tasks'][tasklist]
                                                 if item['id'] != task]
            return Mock(execute=execute)

        self.api.tasks.return_value.insert.side_effect = insert_task
        self.api.tasks.return_value.delete.side_effect = delete_task

        def edit_notes(screen, state, manager):
            task = state.tasks[manager.selected_task_idx]
            self.service.change_detail_task(state.active_list_id, task['id'], 'Saved note')
            state.refresh_data()

        def keys():
            yield 'a'
            self.assertEqual(self.remote['tasks']['list'][-1]['title'], 'New task')
            self.assertFalse(self.service.dirty)
            self.assertEqual(ui.selected_task_idx, 2)
            yield 'i'
            self.assertEqual(self.remote['tasks']['list'][-1]['notes'], 'Saved note')
            yield 'd'
            self.assertEqual(len(self.remote['tasks']['list']), 2)
            yield 'p'
            self.assertEqual(len(self.remote['tasks']['list']), 3)
            self.assertEqual(self.remote['tasks']['list'][-1]['notes'], 'Saved note')
            self.assertFalse(self.service.dirty)
            yield 'q'

        with patch('tasks_tui.main.open_editor_for_task_notes', side_effect=edit_notes):
            self.run_loop(keys(), ui)
        self.assertEqual(self.api.tasks.return_value.insert.call_count, 2)

    def test_list_creation_rename_and_deletion_upload_automatically(self):
        ui = self.make_ui()
        ui.active_panel = 'lists'
        ui.get_user_input = Mock(side_effect=['Added list', 'Renamed list', 'y', 'y'])

        def insert_list(body):
            def execute():
                result = dict(body, id='created-list')
                self.remote['task_lists'].append(result)
                self.remote['tasks'][result['id']] = []
                return copy.deepcopy(result)
            return Mock(execute=execute)

        def rename_list(tasklist, body):
            def execute():
                item = next(item for item in self.remote['task_lists'] if item['id'] == tasklist)
                item.update(body)
                return copy.deepcopy(item)
            return Mock(execute=execute)

        def delete_list(tasklist):
            def execute():
                self.remote['task_lists'] = [item for item in self.remote['task_lists'] if item['id'] != tasklist]
                del self.remote['tasks'][tasklist]
            return Mock(execute=execute)

        self.api.tasklists.return_value.insert.side_effect = insert_list
        self.api.tasklists.return_value.patch.side_effect = rename_list
        self.api.tasklists.return_value.delete.side_effect = delete_list

        def keys():
            yield 'a'
            self.assertEqual(len(self.remote['task_lists']), 2)
            yield 'e'
            self.assertEqual(self.remote['task_lists'][0]['title'], 'Renamed list')
            yield 'd'
            self.assertEqual(self.service.active_list_id, 'created-list')
            self.assertEqual(len(self.remote['task_lists']), 1)
            yield 'd'
            self.assertIsNone(self.service.active_list_id)
            self.assertEqual(self.remote['task_lists'], [])
            self.assertFalse(self.service.dirty)
            yield 'q'

        self.run_loop(keys(), ui)

    def test_failed_automatic_upload_retries_on_next_edit_but_not_navigation_or_cancel(self):
        ui = self.make_ui()
        ui.task_form = Mock(side_effect=[{'title': 'Pending', 'due': ''}, None,
                                        {'title': 'Pending', 'due': ''}, {'title': 'Retry edit', 'due': ''}])
        ui.update_task_selection = Mock()
        patch_task = self.api.tasks.return_value.patch.side_effect
        self.api.tasks.return_value.patch.side_effect = OSError('Offline')

        def keys():
            yield 'e'
            self.assertTrue(self.service.dirty)
            self.assertEqual(self.service.get_task('list', 'second')['title'], 'Pending')
            self.assertEqual(self.remote['tasks']['list'][1]['title'], 'Second')
            yield 'j'
            yield 'a'  # Cancel creation.
            yield 'e'  # Save without changing anything.
            self.assertEqual(self.api.tasks.return_value.patch.call_count, 1)
            self.api.tasks.return_value.patch.side_effect = patch_task
            yield 'e'
            self.assertEqual(self.remote['tasks']['list'][1]['title'], 'Retry edit')
            self.assertFalse(self.service.dirty)
            yield 'q'

        self.run_loop(keys(), ui)
        self.assertEqual(self.api.tasks.return_value.patch.call_count, 2)
        ui.show_temporary_message.assert_called_once()

    def test_repeated_sync_fetches_additions_updates_and_deletions(self):
        for title in ('Phone edit', 'Another phone edit'):
            self.remote['tasks']['list'] = [{'id': 'remote', 'title': title}]
            self.service.sync()
            self.assertEqual(self.service.data, self.remote)
            self.assertFalse(self.service.dirty)
        self.api.tasks.return_value.patch.assert_not_called()

    def test_local_title_edit_preserves_remote_fields_other_tasks_and_list_title(self):
        self.service.rename_task('list', 'first', 'Local title')
        self.remote['tasks']['list'][0].update(title='Remote title', notes='Phone notes', status='completed')
        self.remote['tasks']['list'][1]['title'] = 'Changed elsewhere'
        self.remote['task_lists'][0]['title'] = 'Phone list'
        self.service.sync()
        self.api.tasks.return_value.patch.assert_called_once_with(
            tasklist='list', task='first', body={'title': 'Local title'})
        self.api.tasklists.return_value.patch.assert_not_called()
        self.assertEqual(self.service.data, self.remote)
        self.assertEqual(self.service.get_task('list', 'first')['notes'], 'Phone notes')

    def test_failed_download_keeps_complete_previous_cache_and_can_retry(self):
        self.remote['task_lists'].append({'id': 'new', 'title': 'New list'})
        good_request = self.api.tasks.return_value.list.side_effect

        def fail_second_list(tasklist, **kwargs):
            if tasklist == 'new':
                raise OSError('Offline')
            return good_request(tasklist, **kwargs)

        self.api.tasks.return_value.list.side_effect = fail_second_list
        with self.assertRaisesRegex(OSError, 'Offline'):
            self.service.sync()
        self.assertEqual(self.service.data, self.data)
        self.save.assert_not_called()
        self.api.tasks.return_value.list.side_effect = good_request
        self.service.sync()
        self.assertEqual(len(self.service.get_task_lists()), 2)

    def test_failed_upload_keeps_edits_and_does_not_download(self):
        self.service.rename_task('list', 'first', 'Pending title')
        self.api.tasks.return_value.patch.side_effect = OSError('Offline')
        with patch.object(self.service, 'sync_from_google') as download:
            with self.assertRaisesRegex(OSError, 'Offline'):
                self.service.sync()
            download.assert_not_called()
        self.assertTrue(self.service.dirty)
        self.assertEqual(self.service.get_task('list', 'first')['title'], 'Pending title')
        self.save.assert_not_called()

    def test_direct_download_refuses_to_discard_pending_edits(self):
        self.service.rename_task('list', 'first', 'Pending')
        with self.assertRaisesRegex(RuntimeError, 'pending changes'):
            self.service.sync_from_google()
        self.assertTrue(self.service.dirty)

    def test_remote_deletions_do_not_block_unrelated_local_edit(self):
        self.remote['tasks']['list'].pop(1)
        self.service.rename_task('list', 'first', 'Keep')
        self.service.sync()
        self.assertIsNone(self.service.get_task('list', 'second'))
        self.api.tasks.return_value.get.assert_not_called()

    def test_delete_failure_is_reported_and_retry_keeps_tombstone(self):
        self.service.delete_task('list', 'first')
        self.api.tasks.return_value.delete.return_value.execute.side_effect = HttpError(
            Response({'status': '503'}), b'{"error": {"message": "Unavailable"}}')
        with self.assertRaises(HttpError):
            self.service.sync()
        self.assertTrue(self.service.dirty)
        self.assertTrue(self.service.get_task('list', 'first')['deleted'])
        self.api.tasks.return_value.delete.return_value.execute.side_effect = HttpError(
            Response({'status': '404'}), b'{}')
        self.remote['tasks']['list'].pop(0)
        self.service.sync()
        self.assertFalse(self.service.dirty)
        self.assertIsNone(self.service.get_task('list', 'first'))

    def test_deleted_unsynced_task_is_never_created_remotely(self):
        task = self.service.add_task('list', 'Discard')
        self.service.delete_task('list', task['id'])
        self.service.sync()
        self.api.tasks.return_value.insert.assert_not_called()
        self.api.tasks.return_value.delete.assert_not_called()

    def test_list_delete_failure_keeps_pending_deletion_until_retry(self):
        self.service.delete_list('list')
        self.api.tasklists.return_value.delete.return_value.execute.side_effect = OSError('Offline')
        with self.assertRaisesRegex(OSError, 'Offline'):
            self.service.sync()
        self.assertTrue(self.service.dirty)
        self.assertTrue(self.service.data['task_lists'][0]['deleted'])
        self.api.tasklists.return_value.delete.return_value.execute.side_effect = None
        self.remote = {'task_lists': [], 'tasks': {}}
        self.service.sync()
        self.assertEqual(self.service.data, self.remote)
        self.assertIsNone(self.service.active_list_id)

    def test_remote_list_deletion_preserves_pending_task_and_list_edits(self):
        self.remote = {'task_lists': [], 'tasks': {}}
        self.service.rename_task('list', 'first', 'Unsaved edit')
        with self.assertRaisesRegex(RuntimeError, 'pending edits was deleted'):
            self.service.sync()
        self.assertTrue(self.service.dirty)
        self.assertEqual(self.service.get_task('list', 'first')['title'], 'Unsaved edit')
        self.service.rename_list('list', 'Unsaved list')
        with self.assertRaisesRegex(RuntimeError, 'edited list was deleted'):
            self.service.sync()
        self.assertEqual(self.service.get_task_lists()[0]['title'], 'Unsaved list')

    def test_shortcuts_fetch_cloud_edits_and_preserve_selection_and_filter(self):
        state = AppState(self.service)
        ui = self.make_ui()
        state.show_completed = True
        for key in ('r', 'w'):
            self.remote['tasks']['list'][1]['due'] = '2026-01-01'
            self.remote['tasks']['list'][1]['title'] = key
            self.assertTrue(self.press(key, state, ui))
            self.assertEqual(state.tasks[ui.selected_task_idx]['id'], 'second')
            self.assertEqual(state.tasks[ui.selected_task_idx]['title'], key)
            self.assertTrue(state.show_completed)
            self.assertEqual(ui.active_panel, 'tasks')
        self.assertEqual(ui.start_sync_animation.call_count, 2)
        self.assertEqual(ui.stop_sync_animation.call_count, 2)

    def test_active_list_removed_remotely_falls_back_and_empty_lists_are_safe(self):
        state = AppState(self.service)
        ui = self.make_ui()
        self.remote = {'task_lists': [{'id': 'new', 'title': 'New'}], 'tasks': {'new': []}}
        self.press('r', state, ui)
        self.assertEqual(state.active_list_id, 'new')
        self.assertEqual(state.task_counts, {'new': 0})
        self.assertEqual(ui.selected_task_idx, 0)
        self.remote = {'task_lists': [], 'tasks': {}}
        self.press('r', state, ui)
        self.assertIsNone(state.active_list_id)
        self.assertEqual(state.tasks, [])
        self.assertEqual(state.task_counts, {})
        ui.active_panel = 'lists'
        self.assertTrue(self.press('l', state, ui))

    def test_deleted_parent_returns_to_top_level(self):
        state = AppState(self.service)
        ui = self.make_ui()
        state.current_parent_task_id = 'second'
        state.parent_task_id_stack = [None]
        state.parent_task_idx_stack = [1]
        state.refresh_data()
        self.remote['tasks']['list'].pop(1)
        self.press('r', state, ui)
        self.assertIsNone(state.current_parent_task_id)
        self.assertEqual(state.parent_task_id_stack, [])
        self.assertEqual(state.parent_task_idx_stack, [])
        self.assertEqual(state.tasks[ui.selected_task_idx]['id'], 'first')

    def test_sync_failure_stops_spinner_and_keeps_app_open_including_on_quit(self):
        self.service.rename_task('list', 'first', 'Pending')
        state = AppState(self.service)
        ui = self.make_ui()
        self.api.tasks.return_value.patch.side_effect = OSError('Offline')
        for key in ('r', 'q'):
            self.assertTrue(self.press(key, state, ui))
            self.assertIn('Sync failed:', ui.show_temporary_message.call_args.args[0])
            self.assertTrue(self.service.dirty)
            self.assertEqual(self.service.get_task('list', 'first')['title'], 'Pending')
        self.assertEqual(ui.start_sync_animation.call_count, 2)
        self.assertEqual(ui.stop_sync_animation.call_count, 2)

    def test_new_list_parent_and_child_ids_preserve_open_subtask_view_after_retry(self):
        new_list = self.service.add_list('New list')
        self.service.set_active_list(new_list['id'])
        parent = self.service.add_task(new_list['id'], 'Parent')
        child = self.service.add_task(new_list['id'], 'Child', parent=parent['id'])
        state = AppState(self.service)
        state.current_parent_task_id = parent['id']
        state.parent_task_id_stack = [None]
        state.parent_task_idx_stack = [0]
        state.refresh_data()
        ui = self.make_ui()
        ui.selected_list_idx = 1
        ui.selected_task_idx = 0

        def insert_list(body):
            def execute():
                result = dict(body, id='created-list')
                self.remote['task_lists'].append(result)
                self.remote['tasks'][result['id']] = []
                return copy.deepcopy(result)
            return Mock(execute=execute)

        fail_child_once = [True]

        def insert_task(tasklist, body, parent=None):
            def execute():
                if body['title'] == 'Child' and fail_child_once[0]:
                    fail_child_once[0] = False
                    raise OSError('Offline after creating parent')
                result = dict(body, id='created-' + body['title'].lower())
                if parent:
                    result['parent'] = parent
                self.remote['tasks'][tasklist].append(result)
                return copy.deepcopy(result)
            return Mock(execute=execute)

        self.api.tasklists.return_value.insert.side_effect = insert_list
        self.api.tasks.return_value.insert.side_effect = insert_task
        self.press('r', state, ui)
        self.assertTrue(self.service.dirty)
        self.assertEqual(state.active_list_id, 'created-list')
        self.assertEqual(state.current_parent_task_id, 'created-parent')
        self.assertEqual(state.tasks[0]['parent'], 'created-parent')
        self.press('r', state, ui)
        self.assertEqual(state.active_list_id, 'created-list')
        self.assertEqual(state.current_parent_task_id, 'created-parent')
        self.assertEqual(state.tasks[ui.selected_task_idx]['id'], 'created-child')
        self.assertEqual(state.tasks[0]['parent'], 'created-parent')
        self.assertEqual(state.task_lists[ui.selected_list_idx]['id'], 'created-list')
        self.assertEqual(child['id'], 'created-child')
        self.assertFalse(self.service.dirty)
        self.assertEqual(self.api.tasks.return_value.insert.call_count, 3)
        self.api.tasklists.return_value.insert.assert_called_once()


if __name__ == '__main__':
    unittest.main()
