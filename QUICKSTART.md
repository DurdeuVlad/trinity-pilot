# TrinityPilot - Quick Start Guide

Get up and running in 5 minutes.

## Prerequisites

- Windows 10/11
- Python 3.10 or higher
- Git

## Installation

### 1. Clone the repository

```powershell
git clone https://github.com/your-username/trinity-pilot.git
cd trinity-pilot
```

### 2. Install dependencies

```powershell
# Install all Python dependencies
pip install -r unified-app/requirements.txt
pip install -r api-accessibility-poc/requirements.txt
pip install -r cli-automation-poc/requirements.txt
pip install -r browser-gui-automation/requirements.txt

# Install Playwright browser
playwright install chromium
```

### 3. Configure API key

```powershell
# Copy the example config to unified-app
cp .env.example unified-app/.env

# Edit unified-app/.env and add your Gemini API key
notepad unified-app\.env
```

Get a free Gemini API key at: https://aistudio.google.com/apikey

Your `.env` file should look like:
```
GEMINI_API_KEY=AIzaSy...your_actual_key_here
```

### 4. Run the app

```powershell
cd unified-app
python main.py
```

The GUI will open maximized.

## First Tasks to Try

### CLI Task
Type: `list all files in the current directory`

Expected: CLI backend executes PowerShell commands and shows results

### Desktop Task
Type: `open Notepad and type hello world`

Expected: Windows UIA opens Notepad, types text, captures screenshots

### Browser Task
Type: `navigate to example.com`

Expected: Chromium launches, navigates to the site, shows status

## Troubleshooting

### "No API key found"
- Ensure `unified-app/.env` exists (not just `.env.example`)
- Verify the file contains `GEMINI_API_KEY=your_key`
- Check the key is valid at https://aistudio.google.com/apikey

### "GUI doesn't open"
```powershell
# Verify Python version
python --version  # Should be 3.10+

# Check PyQt6 is installed
pip list | findstr PyQt6

# If missing, install it
pip install PyQt6
```

### "Browser automation failed"
```powershell
# Install Playwright browsers
playwright install chromium

# Verify installation
playwright --version
```

### "Desktop automation not working"
- Windows 10/11 required (uses UIA)
- Try running as administrator for system apps
- Some apps may require accessibility permissions

## Next Steps

- Check the **History** tab to see past executions
- Configure settings in the **Settings** tab
- View execution screenshots in the glass box panel
- Try cross-domain tasks like: `search google for python and paste the first result into notepad`

## Running Tests

```powershell
# Run all tests
pytest unified-app/tests -v

# Run with coverage
pytest unified-app/tests --cov=unified-app/orchestrator --cov=unified-app/ui
```

## Need Help?

- Full documentation: See `README.md`
- Architecture details: See `unified-app/README.md`
- Report issues: [GitHub Issues](https://github.com/your-username/trinity-pilot/issues)
