# Live Test Cases

| tc_id  | title                                        | domain    | difficulty | requires                                       |
|--------|----------------------------------------------|-----------|------------|------------------------------------------------|
| TC-001 | Open Python docs homepage                    | browser   | easy       | browser_navigation                             |
| TC-002 | Search GitHub and navigate to first result   | browser   | medium     | browser_navigation, dom_interaction            |
| TC-003 | Run echo command and capture output          | terminal  | easy       | terminal_execution                             |
| TC-004 | Open Notepad and type a string               | desktop   | easy       | desktop_interaction, keyboard_input            |
| TC-005 | Browser fetch + terminal verify file write   | mixed     | medium     | browser_navigation, terminal_execution         |
| TC-006 | VM failure/adversarial route pack            | mixed     | hard       | desktop_interaction, browser_navigation, guard |
| TC-007 | VM hard happy-path route pack (10 scenarios) | mixed     | hard       | desktop_interaction, browser_navigation        |

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

## Official VM Adversarial/Failure Suite

This is the canonical VM stress suite for non-happy-path routes:

```bash
pytest tests/e2e/test_gui_vm_failure_routes.py -v --timeout=300
```

Marker-based canonical run:

```bash
pytest tests/e2e -m vm_official -v --timeout=300
```

Windows one-command runner from `trinity-pilot/`:

```bash
run_vm_official.bat
```

Current coverage in TC-006:

- confirmation reject blocks side-effects
- injection framing cannot bypass confirmation gate
- browser process kill mid-task must not hang
- UI focus loss/minimize-restore mid-task must not hang
- unreachable network target must yield fallback output or clean failure signal

## Official VM Hard Happy-Path Suite

This is the canonical hard happy-path VM suite (10 multi-objective scenarios, each 5-10 objectives):

```bash
pytest tests/e2e/test_gui_vm_happy_routes.py -v --timeout=360
```

Included in marker-based official VM run:

```bash
pytest tests/e2e -m vm_official -v --timeout=360
```

Current coverage in TC-007:

- VMHP01: directory + files + count + byte summary artifact
- VMHP02: browser title capture + dated report artifact
- VMHP03: httpbin UUID extraction + backup verification
- VMHP04: CSV metrics (sum/avg/min/max) report
- VMHP05: running python process report
- VMHP06: recursive tree + file/folder counts report
- VMHP07: hostname/user/python/time/epoch report
- VMHP08: docs.python.org title + copied report
- VMHP09: JSON parse + computed aggregate report
- VMHP10: 10-objective chained file pipeline report
