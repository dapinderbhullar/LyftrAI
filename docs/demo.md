# Voice demo

Record one 2–3 minute take with your microphone on. Set the terminal and browser side by side, enlarge terminal text, and keep hosting settings and credentials off screen.

### Before recording

Open the public frontend. In PowerShell 7, set the API URL once and define these helpers. Choose a unique first prompt to ensure the first request misses the cache.

```powershell
$api = Read-Host 'Public HTTPS backend URL'
$tag = [guid]::NewGuid().ToString('N').Substring(0, 8)
$prompt = "I'm naming my demo notebook Atlas-$tag. Please acknowledge."
function Send-Chat($id, $message, $failure = '') {
    $headers = @{}
    if ($failure) { $headers['X-Simulate-Failure'] = $failure }
    $body = @{ session_id = $id; message = $message } | ConvertTo-Json -Compress
    $response = Invoke-WebRequest "$api/chat" -Method Post -ContentType 'application/json' -Body $body -Headers $headers -SkipHttpErrorCheck
    "HTTP $([int]$response.StatusCode)"
    $response.Content | ConvertFrom-Json | ConvertTo-Json -Depth 8
}
$prompt
```

### Recording timeline

- **0:00–0:45** — Open the public frontend and send the printed prompt. Point out LIVE_INFERENCE, the model, latency and both token counts. Ask “What did I name my notebook?” and show that the assistant recalls the name.
- **0:45–1:10** — Reload the page and send the exact initial prompt again. Show LLM_CACHE, the identical answer, the stored token counts and the measured latency.
- **1:10–2:15** — Switch to PowerShell. Show health, the successful fallback to key_2 with one failed attempt, and stored history. Then show HTTP 503 followed by a 404 for the failed session.

```powershell
Invoke-RestMethod "$api/health" | ConvertTo-Json
Send-Chat "fallback-$tag" 'Give me one reason to write tests.' 'key_1=429'
Invoke-RestMethod "$api/sessions/fallback-$tag/messages" | ConvertTo-Json -Depth 8
Send-Chat "failed-$tag" 'Hello' '*=429'
$failed = Invoke-WebRequest "$api/sessions/failed-$tag/messages" -SkipHttpErrorCheck
"HTTP $([int]$failed.StatusCode)"
$failed.Content
```

- **2:15–2:40** — Explain that React sends the latest message, FastAPI fetches the SQLite conversation, and LiteLLM caches responses by model and conversation. Explain that the backend attempts the keys in order and stores history on a persistent disk.

Export the recording, upload it with public link access, and test the link in a private browser window. Add the verified link to the README and include it with the two public service URLs and GitHub URL in the assignment submission.
