# How to Test: testing/gemini_mock

## Focused Module Tests

```bash
PYTHONPATH=. pytest testing/gemini_mock/tests -q
```

## Cross-Module Validation

```bash
PYTHONPATH=. python testing/gemini_mock/validate_cross_module.py
```

## Repo Regression

```bash
PYTHONPATH=. pytest unified-app/tests/ -q
python ai-quality-checker/check_code.py
python ai-quality-checker/check_docs.py
python .ai/scripts/validate.py
```
