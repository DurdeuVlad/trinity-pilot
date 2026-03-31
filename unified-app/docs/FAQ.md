# FAQ

## Do I need an API key?
No for basic fallback planning. Yes for Gemini-generated plans.

## Why are there no screenshots?
Screenshots depend on backend execution writing files to `_runtime/screenshots`.

## Where is history stored?
SQLite database at `_runtime/orchestrator_history.db`.

## Where are settings stored?
JSON file at `_runtime/orchestrator_settings.json`.

## How do I reset state?
Delete the two files above and restart the app.
