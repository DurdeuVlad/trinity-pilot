# Repository Instructions

`trinity-pilot/` is the real project, not the AI workspace.

- Keep this repo clean and human-looking.
- Do not add AI planning files, memory files, handoff notes, `.agents/`, or generated scaffolding here.
- Put AI-only artifacts in `../.ai/`.
- Keep comments minimal and only where they clarify something non-obvious.
- Favor edits to real project files over adding new structure.

## AI changelog rule

- Every AI assistant working on this repo must maintain a progress changelog in `../.ai/changelog/`.
- Use one dated Markdown file per work topic/session: `YYYY-MM-DD-short-title.md`.
- Initialize entries from `../.ai/changelog/ENTRY_TEMPLATE.md`.
- For each meaningful action (analysis, file edits, command runs, verification, decisions), append concise updates in that session file.
