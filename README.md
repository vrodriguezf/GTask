# Tasks TUI

A simple, fast, and intuitive Terminal User Interface (TUI) for Google Tasks.

## Features

*   View your Google Tasks directly in the terminal
*   Add new tasks and lists.
*   Mark tasks as complete.
*   Hide completed tasks by default; press `v` to show or hide them for the current session.
*   Rename tasks and lists.
*   Switch between your task lists.
*   Add due dates, notes, or subtasks
*   Tasks grouped by date: Overdue, Today, Tomorrow, upcoming dates, then No date.
*   Scroll through date sections with the arrow keys or j/k; headings are not selectable.
*   Vim-style keybindings for navigation.

## Screenshots
<img width="1365" height="742" alt="image" src="https://github.com/user-attachments/assets/4c51a8ba-eac3-4a02-ab62-060d91150941" />



## Installation

1.  **Install via pip:**

    ```bash
    pip install tasks-tui-app
    ```

2.  **Clone the repository (optional, for development):**

    ```bash
    git clone https://github.com/your-username/Gtask.git
    cd Gtask
    ```

3.  **Install the dependencies (if cloning for development):**

    ```bash
    pip install -r requirements.txt
    ```

4.  **Enable the Google Tasks API [Guide](https://developers.google.com/workspace/tasks/quickstart/python)**

    *   Go to the [Google API Console](https://console.developers.google.com/).
    *   Create a new project.
    *   Enable the **Google Tasks API** for your project.
    *   Create an **OAuth 2.0 Client ID** for a **Desktop application**.
    *   Download the JSON file and rename it to `client_secrets.json`.
    *   Place the `client_secrets.json` file in the ~/.gtask.

## Usage

To run the application, use the following command:

```bash
tasks-tui
```

By default, sync fetches up to 100 tasks per list to keep startup short.
Choose a different limit for each run:

```bash
tasks-tui --max-tasks 50
tasks-tui --max-tasks 500
tasks-tui --max-tasks 0    # Fetch all tasks (slower)
```

The limit includes completed tasks and subtasks, before the visibility filter
and date sorting. Tasks beyond the limit remain in Google Tasks but are not
loaded for this run. All task lists are fetched regardless of this limit.

### Keyboard Shortcuts

| Key          | Action                                  |
| :----------- | :-------------------------------------- |
| `q`          | Quit application                        |
| `w`          | Write and Sync                          |
| `↑` / `k`    | Move selection up                       |
| `↓` / `j`    | Move selection down                     |
| `←` / `h`    | Exit selection                          |
| `→` / `l`    | Enter selection                         |
| `a`          | Add task/list                           |
| `d`          | Delete selection                        |
| `e`          | Edit title and date (or list name)                        |
| `c`          | Toggle task completion                  |
| `v`          | Show/hide completed tasks               |
| `i`          | Insert/view task note   |
| `p`          | Paste from buffer       |
| `?`          | Toggle Help                             |

### Creating and scheduling tasks

In the task panel, press `a`, type a title, and press Enter to create a task
with **No date**. To schedule it before creating it, press Tab to reach
**No date**, **Today**, **Tomorrow**, or **Choose date**, then Enter to select.
Choose **Create task** to save. Escape cancels the draft.

Press `e` on an existing task to edit its title and date in the same form.
The current values are filled in; choose **Save changes** or press Enter in
the title to save both. Escape discards all edits. In the date picker:

- `t`: today; `m`: tomorrow; `n`: no date.
- Choose **Choose date** or press Tab to enter the calendar.
- Arrow keys (or `h/j/k/l`) move by day/week.
- Page Up/Page Down (or `[` / `]`) change months.
- Enter selects; Escape cancels without changing the task or its draft title.

Dates are optional for both tasks and subtasks. New tasks remain selected,
including when they appear in the **No date** section.

Times and repeat rules must be set in the official Google Tasks app.
The [public Tasks API](https://developers.google.com/workspace/tasks/reference/rest/v1/tasks)
only stores the date and exposes no recurrence field, so GTask cannot sync
those settings.

### Task Status Symbols

| Symbol            | Meaning                                                                                  |
| :-----            | :--------------                                                                          |
| `[ ]`             | Task needs action                                                                        |
| `[X]`             | Task completed                                                                           |
| `('Task Counts')` | Count of tasks/subtasks within (subtasks of subtasks do not display in web Google Tasks) |

When you run the application for the first time, it will open a web browser and ask you to authorize the application to access your Google Tasks. After you authorize the application, it will create a `token.json` file in the `~/.gtask` directory. This file contains your access and refresh tokens, so you won't have to authorize the application every time you run it. (Occasionally your token might become expire, so just delete `token.json` from `~/.gtask` and rerun the application to reauthenticate!)

## Contributing

Contributions are welcome! If you have any ideas, suggestions, or bug reports, please open an issue or submit a pull request.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
