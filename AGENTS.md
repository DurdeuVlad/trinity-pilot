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

## Bachelor's degree research documentation rule

- **CRITICAL**: All work on this repository must be documented in `../DesktopAI_Research/Arhitecture_History/` for bachelor's degree research.
- Document **every mistake, decision, architectural change, bug fix, and implementation detail**.
- Place documentation in:
  - An existing dated folder under `Arhitecture_History/` if the topic fits and the folder is recent (within 2 weeks).
  - A new dated folder named `YYYY-MM-DD-topic-name/` if starting a new architectural topic or analysis.
- Use descriptive Markdown files with clear titles that explain what was done, why, what failed, and what succeeded.
- This documentation is for academic research purposes and must capture the full development journey, including failures and pivots.
