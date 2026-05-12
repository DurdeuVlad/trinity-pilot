# Live Test Cases

| tc_id  | title                                        | domain    | difficulty | requires                                       |
|--------|----------------------------------------------|-----------|------------|------------------------------------------------|
| TC-001 | Open Python docs homepage                    | browser   | easy       | browser_navigation                             |
| TC-002 | Search GitHub and navigate to first result   | browser   | medium     | browser_navigation, dom_interaction            |
| TC-003 | Run echo command and capture output          | terminal  | easy       | terminal_execution                             |
| TC-004 | Open Notepad and type a string               | desktop   | easy       | desktop_interaction, keyboard_input            |
| TC-005 | Browser fetch + terminal verify file write   | mixed     | medium     | browser_navigation, terminal_execution         |

## Usage

Submit a test case via the CLI:

```
python app_control_cli.py submit-case docs/live-test-cases/TC-001-browser-easy.md
```

Stream events until the task completes:

```
python app_control_cli.py stream-events <task_id> --until-terminal
```

Retrieve the full artifact bundle:

```
python app_control_cli.py get-artifact-bundle <task_id>
```
