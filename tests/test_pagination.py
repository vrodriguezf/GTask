import unittest
from unittest.mock import Mock, call, patch

from tasks_tui.task_service import TaskService


class PaginationTests(unittest.TestCase):
    def setUp(self):
        self.service = TaskService.__new__(TaskService)
        self.service.service = Mock()
        self.service.data = {'task_lists': [], 'tasks': {}}
        self.service.initial_sync_completed = False
        self.service.dirty = False
        self.service.max_tasks = 0
        self.save = patch('tasks_tui.task_service.local_storage.save_data').start()
        self.addCleanup(patch.stopall)

    def test_download_all_lists_and_tasks_and_sort_across_pages(self):
        lists = self.service.service.tasklists.return_value
        lists.list.return_value.execute.side_effect = [
            {'items': [{'id': 'first'}], 'nextPageToken': 'more-lists'},
            {'items': [{'id': 'second'}]},
        ]
        first_page = [
            {'id': str(i), 'position': f'{i:03d}', 'status': 'completed'}
            for i in range(1, 21)
        ]
        late_task = {'id': 'late', 'position': '000', 'status': 'needsAction'}
        tasks = self.service.service.tasks.return_value
        tasks.list.return_value.execute.side_effect = [
            {'items': first_page, 'nextPageToken': 'more-tasks'},
            {'items': [late_task]},
            {},
        ]

        self.service.sync_from_google()

        self.assertEqual(self.service.data['task_lists'], [{'id': 'first'}, {'id': 'second'}])
        self.assertEqual(self.service.data['tasks']['first'], [late_task] + first_page)
        self.assertEqual(self.service.data['tasks']['second'], [])
        self.assertEqual(lists.list.call_args_list, [call(maxResults=100), call(maxResults=100, pageToken='more-lists')])
        self.assertEqual(tasks.list.call_args_list, [
            call(tasklist='first', showHidden=True, maxResults=100),
            call(tasklist='first', showHidden=True, maxResults=100, pageToken='more-tasks'),
            call(tasklist='second', showHidden=True, maxResults=100),
        ])
        self.save.assert_called_once_with(self.service.data)

    def test_empty_intermediate_page_does_not_end_pagination(self):
        resource = Mock()
        resource.list.return_value.execute.side_effect = [
            {'nextPageToken': 'next'},
            {'items': [{'id': 'found'}]},
        ]
        self.assertEqual(self.service._list_all(resource), [{'id': 'found'}])

    def test_limit_stops_fetching_and_requests_only_remaining_items(self):
        resource = Mock()
        resource.list.return_value.execute.side_effect = [
            {'items': [{'id': str(i)} for i in range(100)], 'nextPageToken': 'next'},
            {'items': [{'id': str(i)} for i in range(100, 125)], 'nextPageToken': 'unused'},
        ]
        self.assertEqual(len(self.service._list_all(resource, limit=125)), 125)
        self.assertEqual(resource.list.call_args_list, [
            call(maxResults=100), call(maxResults=25, pageToken='next')])

    def test_download_applies_limit_per_list(self):
        self.service.max_tasks = 1
        self.service.service.tasklists.return_value.list.return_value.execute.return_value = {
            'items': [{'id': 'a'}, {'id': 'b'}]}
        tasks = self.service.service.tasks.return_value
        tasks.list.return_value.execute.return_value = {
            'items': [{'id': 'task'}], 'nextPageToken': 'unused'}
        self.service.sync_from_google()
        self.assertEqual(tasks.list.call_count, 2)
        self.assertEqual([len(v) for v in self.service.data['tasks'].values()], [1, 1])

    def test_upload_compares_against_lists_and_tasks_on_later_pages(self):
        self.service.dirty = True
        self.service.data = {
            'task_lists': [{'id': 'later-list', 'title': 'New list title'}],
            'tasks': {'later-list': [{'id': 'later-task', 'title': 'New task title'}]},
        }
        lists = self.service.service.tasklists.return_value
        lists.list.return_value.execute.side_effect = [
            {'items': [{'id': 'first-list'}], 'nextPageToken': 'next-list'},
            {'items': [{'id': 'later-list', 'title': 'Old list title'}]},
        ]
        tasks = self.service.service.tasks.return_value
        tasks.list.return_value.execute.side_effect = [
            {'items': [{'id': 'first-task'}], 'nextPageToken': 'next-task'},
            {'items': [{'id': 'later-task', 'title': 'Old task title'}]},
        ]

        self.service.sync_to_google()

        lists.patch.assert_called_once_with(
            tasklist='later-list', body={'title': 'New list title'})
        tasks.patch.assert_called_once_with(
            tasklist='later-list', task='later-task', body={'title': 'New task title'})
        self.assertFalse(self.service.dirty)

    def test_upload_updates_loaded_task_that_moved_beyond_limit(self):
        self.service.max_tasks = 1
        self.service.dirty = True
        self.service.data = {
            'task_lists': [{'id': 'list'}],
            'tasks': {'list': [{'id': 'moved', 'title': 'Edited'}]},
        }
        self.service.service.tasklists.return_value.list.return_value.execute.return_value = {
            'items': [{'id': 'list'}]}
        tasks = self.service.service.tasks.return_value
        tasks.list.return_value.execute.return_value = {
            'items': [{'id': 'other'}], 'nextPageToken': 'unused'}
        tasks.get.return_value.execute.return_value = {'id': 'moved', 'title': 'Original'}
        self.service.sync_to_google()
        tasks.list.assert_called_once_with(tasklist='list', showHidden=True, maxResults=1)
        tasks.get.assert_called_once_with(tasklist='list', task='moved')
        tasks.patch.assert_called_once_with(tasklist='list', task='moved', body={'title': 'Edited'})


if __name__ == '__main__':
    unittest.main()
