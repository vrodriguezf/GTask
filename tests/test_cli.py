import unittest
from unittest.mock import patch

from tasks_tui.main import cli


class CliTests(unittest.TestCase):
    def test_limit_reaches_main_loop(self):
        for argv, expected in [([], 100), (['--max-tasks', '50'], 50), (['--max-tasks', '0'], 0)]:
            with self.subTest(argv=argv), patch('tasks_tui.main.wrapper') as wrapper, patch('tasks_tui.main.main_loop') as main:
                cli(argv)
                wrapper.call_args.args[0]('screen')
                main.assert_called_once_with('screen', max_tasks=expected)

    def test_invalid_limit_rejected_before_launch(self):
        for value in ['-1', 'abc']:
            with self.subTest(value=value), patch('sys.stderr'), patch('tasks_tui.main.wrapper') as wrapper:
                with self.assertRaises(SystemExit) as error:
                    cli(['--max-tasks', value])
                self.assertEqual(error.exception.code, 2)
                wrapper.assert_not_called()
