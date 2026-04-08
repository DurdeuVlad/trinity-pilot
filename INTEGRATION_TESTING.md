# Integration Testing Guide
**Trinity-Pilot Module Services**

---

## ✅ **PRE-REQUISITES**

1. **Environment Setup:**
   ```powershell
   # Verify .env file exists with GEMINI_API_KEY
   cat unified-app/.env
   ```
   Should contain:
   ```
   GEMINI_API_KEY=AIzaSy...
   ```

2. **Dependencies Installed:**
   ```powershell
   pip install -r unified-app/requirements.txt
   pip install -r api-accessibility-poc/requirements.txt
   pip install -r cli-automation-poc/requirements.txt
   pip install -r browser-gui-automation/requirements.txt
   playwright install chromium
   ```

3. **Pre-Integration Checks:**
   ```powershell
   cd unified-app
   python tests/run_pre_integration_checks.py
   ```
   Expected: ✅ 8/8 checks passed

---

## 🚀 **QUICK START**

### **Step 1: Start All Services**
```powershell
.\start_services.ps1
```

This will open 3 PowerShell windows:
- **Browser Service** (Port 8103)
- **Desktop Service** (Port 8101)
- **CLI Service** (Port 8102)

Wait 5-10 seconds for services to initialize.

### **Step 2: Test Health Endpoints**
```powershell
.\test_services.ps1
```

Expected output:
```
✅ Browser service is healthy
✅ Desktop service is healthy
✅ CLI service is healthy
✅ ALL SERVICES HEALTHY - Ready for testing!
```

### **Step 3: Test Direct Module Call**
```powershell
.\test_direct_call.ps1
```

This tests the CLI module with a simple task to verify Gemini function calling works.

Expected: Task completes successfully with file list.

---

## 📋 **MANUAL TESTING**

### **Test Browser Module:**
```powershell
$body = @{
    description = "Navigate to google.com and read the page title"
    context = ""
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:8103/task" -Method POST -Body $body -ContentType "application/json"
```

### **Test Desktop Module:**
```powershell
$body = @{
    description = "List all open windows"
    context = ""
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:8101/task" -Method POST -Body $body -ContentType "application/json"
```

### **Test CLI Module:**
```powershell
$body = @{
    description = "Get the current date and time"
    context = ""
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:8102/task" -Method POST -Body $body -ContentType "application/json"
```

---

## 🎯 **INTEGRATION TEST SCENARIOS**

### **Scenario 1: Simple CLI Task**
**Task:** "List files in the Documents folder"

**Expected:**
- ✅ Service calls `list_files` tool
- ✅ Returns formatted file list
- ✅ Steps taken: 1-2
- ✅ No errors

### **Scenario 2: Simple Browser Task**
**Task:** "Navigate to example.com and get the page title"

**Expected:**
- ✅ Service calls `navigate` tool
- ✅ Service calls `read_page` tool
- ✅ Returns page title
- ✅ Steps taken: 2-3
- ✅ No errors

### **Scenario 3: Simple Desktop Task**
**Task:** "Open Notepad"

**Expected:**
- ✅ Service calls `launch_app` tool
- ✅ Notepad opens
- ✅ Returns success message
- ✅ Steps taken: 1-2
- ✅ No errors

### **Scenario 4: Multi-Step Task**
**Task:** "Open Notepad, type 'Hello World', and save to Desktop as test.txt"

**Expected:**
- ✅ Service calls multiple tools in sequence
- ✅ File created on Desktop
- ✅ Returns success message
- ✅ Steps taken: 3-5
- ✅ No errors

---

## 🔍 **DEBUGGING**

### **Service Not Starting:**
1. Check if port is already in use:
   ```powershell
   netstat -ano | findstr "8101"
   netstat -ano | findstr "8102"
   netstat -ano | findstr "8103"
   ```

2. Check service window for errors

3. Verify .env file exists and has GEMINI_API_KEY

### **Task Failing:**
1. Check service logs in the PowerShell window
2. Verify GEMINI_API_KEY is valid
3. Check network connectivity
4. Try simpler task first

### **Gemini API Errors:**
- **401 Unauthorized:** Invalid API key
- **429 Too Many Requests:** Rate limit exceeded
- **500 Internal Error:** Gemini service issue

---

## 📊 **SUCCESS CRITERIA**

Before declaring "integration ready":

- ✅ All 3 services start successfully
- ✅ All health checks return OK
- ✅ Direct module call works (Gemini function calling verified)
- ✅ At least 1 successful task per module
- ✅ Multi-step task works
- ✅ Error handling works (try invalid task)
- ✅ Cost per task < $0.01

---

## 🎓 **NEXT STEPS**

After integration tests pass:

1. **Run Unified App:**
   ```powershell
   cd unified-app
   python main.py
   ```

2. **Test End-to-End:**
   - Submit task via GUI
   - Verify orchestrator routes to correct module
   - Verify task completes successfully
   - Check logs and metrics

3. **Performance Testing:**
   - Test multiple tasks in sequence
   - Measure latency and cost
   - Verify no memory leaks

4. **Production Readiness:**
   - Add error recovery
   - Add retry logic
   - Add monitoring
   - Add rate limiting

---

## 💡 **TIPS**

- **Start Simple:** Test with trivial tasks first
- **Check Logs:** Service windows show detailed logs
- **Monitor Costs:** Gemini Lite is cheap (~$0.001 per task)
- **Use Health Checks:** Verify services before testing
- **Stop Services:** Ctrl+C in each service window when done

---

## 🆘 **TROUBLESHOOTING**

### **"Module not found" errors:**
```powershell
# Verify Python path
python -c "import sys; print('\n'.join(sys.path))"

# Reinstall dependencies
pip install -r unified-app/requirements.txt --force-reinstall
```

### **"Port already in use" errors:**
```powershell
# Kill process on port 8101
$process = Get-NetTCPConnection -LocalPort 8101 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess
if ($process) { Stop-Process -Id $process -Force }
```

### **Playwright errors:**
```powershell
# Reinstall browsers
playwright install chromium --force
```

---

## ✅ **VALIDATION CHECKLIST**

Before moving to production:

- [ ] All unit tests pass (49/49)
- [ ] All component tests pass (8/8)
- [ ] All 3 services start successfully
- [ ] All health checks return OK
- [ ] Direct module call works
- [ ] Browser task works
- [ ] Desktop task works
- [ ] CLI task works
- [ ] Multi-step task works
- [ ] Error handling works
- [ ] Logs are clean
- [ ] No memory leaks
- [ ] Cost per task acceptable

---

**Ready to test!** 🚀
