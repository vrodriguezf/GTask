"""Keyboard-driven task drafts and calendar selection, without API writes."""

import calendar
import codecs
from contextlib import contextmanager
from datetime import date, timedelta
import unicodedata

from unicurses import *

from .task_dates import due_date, shift_month


ENTER = (10, 13, KEY_ENTER)


def display_width(text):
    return sum(0 if unicodedata.combining(c) else
               2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1
               for c in text)


def fit(text, width):
    result = ''
    for char in text:
        if display_width(result + char) > width:
            break
        result += char
    return result


@contextmanager
def dialog(ui, height, width, title):
    h, w = getmaxyx(ui.stdscr)
    win = newwin(min(height, h), min(width, w), max(0, (h-height)//2), max(0, (w-width)//2))
    keypad(win, True)
    noecho()
    try:
        werase(win)
        if h >= height and w >= width:
            ui._draw_border(win, title)
        yield win, h >= height and w >= width
    finally:
        curs_set(0)
        werase(win)
        wrefresh(win)
        delwin(win)
        touchwin(ui.stdscr)


def small_screen(win):
    h, w = getmaxyx(win)
    mvwaddstr(win, 0, 0, 'Enlarge terminal or Esc to cancel'[:max(0, w-1)])
    wrefresh(win)
    return wgetch(win)


def pick_date(ui, initial=None):
    """Return ISO date, '' for no date, or None on cancellation."""
    selected = due_date({'due': initial}) or date.today()
    focused = 3 if initial else 0
    in_calendar = False
    while True:
        with dialog(ui, 19, 50, 'Choose date') as (win, fits):
            if not fits:
                if small_screen(win) == 27:
                    return None
                continue
            curs_set(0)
            options = ['No date', 'Today', 'Tomorrow', 'Choose date...']
            for row, label in enumerate(options, 2):
                attr = A_REVERSE if not in_calendar and row-2 == focused else A_NORMAL
                mvwaddstr(win, row, 3, label, attr)
            mvwaddstr(win, 7, 3, f'<  {selected:%B %Y}  >', A_BOLD)
            mvwaddstr(win, 8, 3, ' Su  Mo  Tu  We  Th  Fr  Sa', A_DIM)
            weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(selected.year, selected.month)
            for row, week in enumerate(weeks, 9):
                for col, day in enumerate(week):
                    if not day:
                        continue
                    attr = A_REVERSE if day == selected.day and in_calendar else A_NORMAL
                    if date(selected.year, selected.month, day) == date.today():
                        attr |= A_BOLD
                    mvwaddstr(win, row, 3 + col*4, f'{day:3d}', attr)
            mvwaddstr(win, 15, 3, 't Today   m Tomorrow   n No date', A_DIM)
            mvwaddstr(win, 16, 3, 'Arrows move; PgUp/PgDn or [/] month', A_DIM)
            mvwaddstr(win, 17, 3, 'Enter select   Tab switch   Esc cancel', A_DIM)
            wrefresh(win)
            key = wgetch(win)
        if key == 27:
            return None
        if key == KEY_RESIZE:
            continue
        if key == ord('n'):
            return ''
        if key in (ord('t'), ord('m')):
            return (date.today() + timedelta(days=key == ord('m'))).isoformat()
        if key in (9, KEY_BTAB):
            in_calendar = not in_calendar
        elif key in ENTER:
            if in_calendar:
                return selected.isoformat()
            if focused == 0:
                return ''
            if focused in (1, 2):
                return (date.today() + timedelta(days=focused-1)).isoformat()
            in_calendar = True
        elif key in (KEY_PPAGE, ord('['), KEY_NPAGE, ord(']')):
            selected = shift_month(selected, -1 if key in (KEY_PPAGE, ord('[')) else 1)
            in_calendar = True
        elif key in (KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT, ord('h'), ord('j'), ord('k'), ord('l')):
            if in_calendar:
                days = {KEY_UP: -7, KEY_DOWN: 7, KEY_LEFT: -1, KEY_RIGHT: 1,
                        ord('h'): -1, ord('j'): 7, ord('k'): -7, ord('l'): 1}[key]
                selected = date.fromordinal(max(date.min.toordinal(), min(date.max.toordinal(), selected.toordinal()+days)))
            else:
                focused = (focused + (-1 if key in (KEY_UP, KEY_LEFT, ord('k'), ord('h')) else 1)) % 4


def task_form(ui, initial=None):
    """Keep the title and schedule in a draft until explicitly saved."""
    editing = initial is not None
    initial = initial or {}
    title = initial.get('title', '')
    day = due_date(initial)
    scheduled = day.isoformat() if day else ''
    cursor, focus = len(title), 0
    error = ''
    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
    while True:
        open_picker = False
        with dialog(ui, 13, 60, 'Edit task' if editing else 'New task') as (win, fits):
            if not fits:
                if small_screen(win) == 27:
                    return None
                continue
            mvwaddstr(win, 2, 3, 'Title', A_BOLD)
            start = 0
            while display_width(title[start:cursor]) > 51:
                start += 1
            mvwaddstr(win, 3, 3, fit(title[start:], 53).ljust(53), A_REVERSE if focus == 0 else A_NORMAL)
            label = scheduled or 'No date'
            mvwaddstr(win, 5, 3, f'Date: {label}', A_BOLD)
            for i, (col, text) in enumerate([(3, 'No date'), (15, 'Today'), (25, 'Tomorrow'), (39, 'Choose date')], 1):
                mvwaddstr(win, 6, col, text, A_REVERSE if focus == i else A_NORMAL)
            mvwaddstr(win, 8, 3, 'Save changes' if editing else 'Create task', A_REVERSE if focus == 5 else A_BOLD)
            mvwaddstr(win, 9, 3, error, A_BOLD)
            mvwaddstr(win, 10, 3, 'Tab / Shift-Tab move   Enter select   Esc cancel', A_DIM)
            mvwaddstr(win, 11, 3, 'Enter in title saves; date is optional.', A_DIM)
            curs_set(1 if focus == 0 else 0)
            if focus == 0:
                wmove(win, 3, 3 + display_width(title[start:cursor]))
            wrefresh(win)
            key = wgetch(win)
        if key == 27:
            return None
        if key == KEY_RESIZE:
            continue
        if key in (9, KEY_BTAB):
            decoder.reset()
            focus = (focus + (1 if key == 9 else -1)) % 6
        elif key in ENTER:
            if focus in (0, 5):
                if title.strip():
                    return {'title': title.strip(), 'due': scheduled}
                error, focus = 'Enter a task title.', 0
            elif focus == 1:
                scheduled = ''
                focus = 5
            elif focus in (2, 3):
                scheduled = (date.today() + timedelta(days=focus-2)).isoformat()
                focus = 5
            elif focus == 4:
                open_picker = True
        elif focus == 0:
            if key in (KEY_BACKSPACE, 127, 8):
                title = title[:max(0, cursor-1)] + title[cursor:]
                cursor = max(0, cursor-1)
            elif key == KEY_DC:
                title = title[:cursor] + title[cursor+1:]
            elif key == KEY_LEFT:
                cursor = max(0, cursor-1)
            elif key == KEY_RIGHT:
                cursor = min(len(title), cursor+1)
            elif key in (KEY_HOME, 1):
                cursor = 0
            elif key in (KEY_END, 5):
                cursor = len(title)
            elif 32 <= key <= 255:
                text = decoder.decode(bytes([key]))
                if len(title) + len(text) <= 1024:
                    title = title[:cursor] + text + title[cursor:]
                    cursor += len(text)
                    error = ''
        elif key in (KEY_LEFT, KEY_UP):
            focus = (focus-1) % 6
        elif key in (KEY_RIGHT, KEY_DOWN):
            focus = (focus+1) % 6
        elif key in (ord('t'), ord('m'), ord('n')):
            scheduled = '' if key == ord('n') else (date.today() + timedelta(days=key == ord('m'))).isoformat()
            focus = 5
        elif key == ord('d'):
            open_picker = True
        if open_picker:
            picked = ui.pick_date(scheduled)
            if picked is not None:
                scheduled, focus = picked, 5
