# Smoke tests

End-to-end smoke tests that launch the full Trinity Pilot app, drive the UI, and verify deliverables.

## easy-desktop

Submits a desktop task (write a spring poem to a file), waits for completion, verifies the file, then closes everything.

```bash
# Run directly
python tests/smoke/test_easy_desktop.py

# Run via pytest
pytest tests/smoke/test_easy_desktop.py -s -v --no-header
```

Requirements: `.env` with `GEMINI_API_KEY` set.
