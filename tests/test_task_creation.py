import copy
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tasks_tui import task_dialogs as dialogs
from tasks_tui.main import AppState, handle_input
from tasks_tui.task_dates import serialize_due, shift_month
from tasks_tui.task_service import TaskService


class TaskCreationTests(unittest.TestCase):
    def setUp(self):
        self.service = TaskService.__new__(TaskService)
        self.service.active_list_id = 'list'
        self.service.max_tasks = 0
        self.service.dirty = False
        self.service.data = {'task_lists': [{'id': 'list'}], 'tasks': {'list': []}}

    def test_undated_and_dated_subtask_creation_and_unique_ids(self):
        parent = self.service.add_task('list', 'Parent')
        self.assertNotIn('due', parent)
        child = self.service.add_task('list', 'Child', parent=parent['id'], due='2026-09-26')
        self.assertEqual(child['parent'], parent['id'])
        self.assertEqual(child['due'], '2026-09-26T00:00:00Z')
        self.assertNotEqual(child['id'], parent['id'])

    def test_date_normalization_and_invalid_edit_is_unchanged(self):
        task = self.service.add_task('list', 'Task', due='2026-09-25')
        self.service.dirty = False
        self.assertIsNone(self.service.change_date_task('list', task['id'], 'bad'))
        self.assertFalse(self.service.dirty)
        self.assertEqual(serialize_due('2026-09-25T23:30:00-04:00'), '2026-09-25T00:00:00Z')
        self.assertIsNone(serialize_due(''))

    def test_clear_date_syncs_explicit_null_for_parent_and_subtask(self):
        for parent in (None, 'parent'):
            with self.subTest(parent=parent):
                task = {'id': 'task', 'title': 'Task', 'due': '2026-09-25T00:00:00Z'}
                tasks = [task]
                if parent:
                    task['parent'] = parent
                    tasks.insert(0, {'id': parent, 'title': 'Parent'})
                remote = copy.deepcopy(tasks)
                self.service.data['tasks']['list'] = tasks
                self.service.change_date_task('list', 'task', '')
                self.service.service = Mock()
                api = self.service.service
                api.tasklists.return_value.list.return_value.execute.return_value = {'items': [{'id': 'list'}]}
                api.tasks.return_value.list.return_value.execute.return_value = {'items': remote}
                with patch('tasks_tui.task_service.local_storage.save_data'):
                    self.service.sync_to_google()
                api.tasks.return_value.patch.assert_called_once_with(tasklist='list', task='task', body={'due': None})

    def test_creation_sync_omits_date_or_sends_midnight(self):
        for due in ('', '2026-09-26'):
            with self.subTest(due=due):
                self.service.data['tasks']['list'] = []
                self.service.add_task('list', 'Task', due=due)
                api = self.service.service = Mock()
                api.tasklists.return_value.list.return_value.execute.return_value = {'items': [{'id': 'list'}]}
                api.tasks.return_value.list.return_value.execute.return_value = {}
                api.tasks.return_value.insert.return_value.execute.return_value = {'id': 'remote'}
                with patch('tasks_tui.task_service.local_storage.save_data'):
                    self.service.sync_to_google()
                body = api.tasks.return_value.insert.call_args.kwargs['body']
                if due:
                    self.assertEqual(body['due'], '2026-09-26T00:00:00Z')
                else:
                    self.assertNotIn('due', body)

    def test_controller_cancel_and_select_new_undated_task(self):
        self.service.add_task('list', 'Earlier', due='2026-09-25')
        self.service.dirty = False
        state = AppState(self.service)
        ui = SimpleNamespace(active_panel='tasks', selected_task_idx=0, task_form=Mock(return_value=None))
        with patch('tasks_tui.main.getch', return_value=ord('a')):
            handle_input(None, state, ui)
            self.assertFalse(self.service.dirty)
            ui.task_form.return_value = {'title': 'New', 'due': ''}
            handle_input(None, state, ui)
        self.assertEqual(state.tasks[ui.selected_task_idx]['title'], 'New')
        self.assertEqual(ui.selected_task_idx, 1)

    def test_edit_saves_both_fields_preserves_metadata_and_selection(self):
        for parent in (None, 'parent'):
            with self.subTest(parent=parent):
                self.service.data['tasks']['list'] = []
                self.service.add_task('list', 'Earlier', parent=parent, due='2026-01-01')
                task = self.service.add_task('list', 'Original', parent=parent, due='2026-09-25')
                task['notes'] = 'Keep these notes'
                state = AppState(self.service)
                state.current_parent_task_id = parent
                state.refresh_data()
                ui = SimpleNamespace(active_panel='tasks', selected_task_idx=1,
                                     task_form=Mock(return_value={'title': 'Edited', 'due': '2025-12-31'}))
                with patch('tasks_tui.main.getch', return_value=ord('e')):
                    handle_input(None, state, ui)
                ui.task_form.assert_called_once_with(task)
                self.assertEqual(task['title'], 'Edited')
                self.assertEqual(task['due'], '2025-12-31T00:00:00Z')
                self.assertEqual(task['notes'], 'Keep these notes')
                self.assertEqual(task.get('parent'), parent)
                self.assertEqual(state.tasks[ui.selected_task_idx]['id'], task['id'])
                self.assertEqual(ui.selected_task_idx, 0)

    def test_cancel_edit_and_unchanged_save_leave_service_clean(self):
        task = self.service.add_task('list', 'Original', due='2026-09-25')
        before = copy.deepcopy(task)
        self.service.dirty = False
        state = AppState(self.service)
        ui = SimpleNamespace(active_panel='tasks', selected_task_idx=0,
                             task_form=Mock(return_value=None))
        with patch('tasks_tui.main.getch', return_value=ord('e')):
            handle_input(None, state, ui)
            self.assertEqual(task, before)
            self.assertFalse(self.service.dirty)
            ui.task_form.return_value = {'title': 'Original', 'due': '2026-09-25'}
            handle_input(None, state, ui)
            self.assertFalse(self.service.dirty)
            ui.task_form.return_value = {'title': 'Updated', 'due': ''}
            handle_input(None, state, ui)
        self.assertEqual(task['title'], 'Updated')
        self.assertIsNone(task['due'])

    def test_empty_task_panel_edit_does_not_open_form(self):
        state = AppState(self.service)
        ui = SimpleNamespace(active_panel='tasks', selected_task_idx=0, task_form=Mock())
        with patch('tasks_tui.main.getch', return_value=ord('e')):
            handle_input(None, state, ui)
        ui.task_form.assert_not_called()


class DialogTests(unittest.TestCase):
    def setUp(self):
        @contextmanager
        def window(*args):
            yield None, True
        self.ui = SimpleNamespace()
        self.ui.pick_date = lambda initial: dialogs.pick_date(self.ui, initial)
        self.addCleanup(patch.stopall)
        patch.object(dialogs, 'dialog', window).start()
        for name in ('mvwaddstr', 'wrefresh', 'curs_set', 'wmove'):
            patch.object(dialogs, name).start()
        today = patch.object(dialogs, 'date', wraps=date).start()
        today.today.return_value = date(2026, 9, 25)

    def run_keys(self, keys, method, *args):
        with patch.object(dialogs, 'wgetch', side_effect=keys):
            return method(self.ui, *args)

    def test_fast_undated_creation_unicode_editing_and_empty_title(self):
        keys = [10] + list('Café 🚀'.encode()) + [dialogs.KEY_LEFT, dialogs.KEY_RIGHT, 10]
        self.assertEqual(self.run_keys(keys, dialogs.task_form), {'title': 'Café 🚀', 'due': ''})

    def test_today_tomorrow_no_date_and_cancel(self):
        for key, expected in [('t', '2026-09-25'), ('m', '2026-09-26'), ('n', '')]:
            self.assertEqual(self.run_keys([ord(key)], dialogs.pick_date), expected)
        self.assertIsNone(self.run_keys([27], dialogs.pick_date, '2026-09-25'))
        self.assertEqual(self.run_keys([10], dialogs.pick_date), '')

    def test_calendar_crosses_month_and_year_and_leap_day(self):
        self.assertEqual(shift_month(date(2028, 1, 31), 1), date(2028, 2, 29))
        self.assertEqual(shift_month(date(2026, 12, 31), 1), date(2027, 1, 31))
        self.assertEqual(self.run_keys([9, dialogs.KEY_RIGHT, 10], dialogs.pick_date, '2026-12-31'), '2027-01-01')
        self.assertEqual(self.run_keys([ord(']'), 10], dialogs.pick_date, '2028-01-31'), '2028-02-29')

    def test_draft_survives_calendar_cancel_and_resize(self):
        keys = list(b'Draft') + [9, 9, 9, 9, 10, 27, dialogs.KEY_RESIZE, 9, 10]
        self.assertEqual(self.run_keys(keys, dialogs.task_form), {'title': 'Draft', 'due': ''})

    def test_draft_can_pick_tomorrow_and_save(self):
        keys = list(b'New task') + [9, 9, 9, 10, 10]
        self.assertEqual(self.run_keys(keys, dialogs.task_form), {'title': 'New task', 'due': '2026-09-26'})

    def test_edit_prefills_fields_and_discards_draft_on_escape(self):
        initial = {'title': 'Original', 'due': '2026-09-25T00:00:00Z'}
        self.assertEqual(self.run_keys([10], dialogs.task_form, initial),
                         {'title': 'Original', 'due': '2026-09-25'})
        keys = list(b' edited') + [9, ord('n'), 10]
        self.assertEqual(self.run_keys(keys, dialogs.task_form, initial),
                         {'title': 'Original edited', 'due': ''})
        self.assertIsNone(self.run_keys(list(b' discarded') + [9, ord('m'), 27],
                                       dialogs.task_form, initial))
        self.assertEqual(initial, {'title': 'Original', 'due': '2026-09-25T00:00:00Z'})


if __name__ == '__main__':
    unittest.main()
