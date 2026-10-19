# ECOSAFR Daily Auto Test & Fix
# Runs at 09:00 daily via Windows Task Scheduler
# Tests 10 questions, stops if quota hit, an AI agent fixes failures

$CHATBOT_DIR   = "D:\New version\ECOSAFR_CHATBOT"
# Command-line AI agent used to fix failures. Set both before scheduling the task:
#   $env:AGENT_EXE  = full path of the agent executable
#   $env:AGENT_ARGS = extra arguments it needs (e.g. non-interactive / permission flags)
$AGENT_EXE     = $env:AGENT_EXE
$AGENT_ARGS    = @($env:AGENT_ARGS -split " " | Where-Object { $_ })
$PYTHON_EXE    = "C:\Users\legion\AppData\Local\Programs\Python\Python312\python.exe"
$LOG_FILE      = "$CHATBOT_DIR\daily_auto_log.txt"
$PROGRESS_FILE = "$CHATBOT_DIR\daily_progress.json"

function Write-Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $msg" | Tee-Object -FilePath $LOG_FILE -Append
}

Write-Log "=== Daily Auto Run Started ==="

# ── 1. Check progress ──────────────────────────────────────────────
$progress = Get-Content $PROGRESS_FILE | ConvertFrom-Json
if ($progress.all_done) {
    Write-Log "All 50 questions done! Nothing to do."
    exit 0
}

$batch = $progress.current_batch
Write-Log "Batch $($batch+1)/5 — Q$($batch*10+1) to Q$($batch*10+10)"

# ── 2. Start ECOSAFR server if not running ─────────────────────────
$serverUp = $false
try {
    $r = Invoke-WebRequest -Uri "http://localhost:8002/chat/" -Method POST `
         -ContentType "application/json" `
         -Body '{"question":"ping","user_id":"health","company_code":"1"}' `
         -TimeoutSec 5 -ErrorAction SilentlyContinue
    $serverUp = ($r.StatusCode -eq 200)
} catch { }

if (-not $serverUp) {
    Write-Log "Server not running — starting it..."
    Start-Process -FilePath $PYTHON_EXE `
        -ArgumentList "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002" `
        -WorkingDirectory $CHATBOT_DIR -WindowStyle Hidden
    Start-Sleep -Seconds 15

    # Verify it started
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8002/chat/" -Method POST `
             -ContentType "application/json" `
             -Body '{"question":"ping","user_id":"health","company_code":"1"}' `
             -TimeoutSec 10 -ErrorAction SilentlyContinue
        $serverUp = ($r.StatusCode -eq 200)
    } catch { }

    if (-not $serverUp) {
        Write-Log "ERROR: Could not start server. Aborting."
        exit 1
    }
    Write-Log "Server started OK"
} else {
    Write-Log "Server already running OK"
}

# ── 3. Run the batch test ──────────────────────────────────────────
Write-Log "Running batch test..."
& $PYTHON_EXE "$CHATBOT_DIR\daily_batch_test.py" $batch 2>&1 | Tee-Object -FilePath $LOG_FILE -Append

# ── 4. Read results ────────────────────────────────────────────────
$resultsFile = "$CHATBOT_DIR\daily_results_latest.json"
if (-not (Test-Path $resultsFile)) {
    Write-Log "ERROR: No results file found."
    exit 1
}

$results = Get-Content $resultsFile | ConvertFrom-Json
$failures = $results.results | Where-Object { $_.status -eq "fail" }
$quotaHit = $results.quota_hit

Write-Log "Results: $($results.summary), quota_hit=$quotaHit"

# ── 5. If quota hit → stop for today ──────────────────────────────
if ($quotaHit) {
    Write-Log "Quota hit — stopping. Will retry tomorrow."
    exit 0
}

# ── 6. If failures exist → ask the AI agent to fix them ─────────────────
if ($failures -and $failures.Count -gt 0) {
    Write-Log "Calling the AI agent to fix $($failures.Count) failure(s)..."

    $failureSummary = ($failures | ForEach-Object {
        "Q$($_.num) [$($_.label)]: question='$($_.question)' method=$($_.method) answer='$($_.answer.Substring(0,[Math]::Min(100,$_.answer.Length)))'"
    }) -join "`n"

    $agentPrompt = @"
You are fixing the ECOSAFR CRM chatbot located at D:\New version\ECOSAFR_CHATBOT.

Today's batch test found these failures:
$failureSummary

The chatbot runs at localhost:8002. It uses:
- query_templates.py: SQL templates matched by sub_intent
- intent_classifier.py: Arabic NLP classifier
- pipeline.py: main pipeline with semantic gate

Rules:
1. DB credentials stay in .env - never expose them
2. Do NOT save question patterns in justclick_comments.sql
3. Analyze each failure and add the minimum fix needed (add template, fix regex pattern, etc.)
4. After fixing, save all files

Read the current files, diagnose each failure, apply targeted fixes, and save.
Restart the server after fixing: python -m uvicorn app:app --host 0.0.0.0 --port 8002 (background)
"@

    # Write prompt to temp file to avoid shell escaping issues
    $promptFile = "$env:TEMP\daily_agent_prompt.txt"
    $agentPrompt | Out-File -FilePath $promptFile -Encoding utf8

    Push-Location $CHATBOT_DIR
    & $AGENT_EXE -p (Get-Content $promptFile -Raw) @AGENT_ARGS `
        2>&1 | Tee-Object -FilePath $LOG_FILE -Append
    Pop-Location

    Write-Log "Agent fix attempt complete."
} else {
    Write-Log "All questions in batch passed!"
}

# ── 7. Reload progress and check if batch is done ─────────────────
$progress = Get-Content $PROGRESS_FILE | ConvertFrom-Json
if ($progress.all_done) {
    Write-Log "=== All 50 questions complete! ==="
} else {
    Write-Log "Next batch: $($progress.current_batch+1)/5 — scheduled for tomorrow."
}

Write-Log "=== Daily Auto Run Done ==="
