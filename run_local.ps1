# run_local.ps1 - TrustPositif REAL-TIME checker for Windows (NO Python needed).
# Runs on any Indonesian Windows machine/RDP using built-in PowerShell.
# Double-click start-windows.bat to run it.

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'
$UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# Emojis built from code points (PS mishandles surrogate literals / [char]+[char]).
$EMO_SHIELD = [System.Char]::ConvertFromUtf32(0x1F6E1)
$EMO_RED    = [System.Char]::ConvertFromUtf32(0x1F534)
$EMO_GREEN  = [System.Char]::ConvertFromUtf32(0x1F7E2)
$EMO_BELL   = [System.Char]::ConvertFromUtf32(0x1F514)

# ---------------------------------------------------------------------------
# Load .env (KEY=VALUE lines)
# ---------------------------------------------------------------------------
$cfg = @{}
$envFile = Join-Path $PSScriptRoot ".env"
if (Test-Path $envFile) {
  foreach ($line in Get-Content $envFile) {
    $l = $line.Trim()
    if ($l -and -not $l.StartsWith("#") -and $l.Contains("=")) {
      $parts = $l.Split("=", 2)
      $cfg[$parts[0].Trim()] = $parts[1].Trim()
    }
  }
}
function Cfg($k, $d) { if ($cfg.ContainsKey($k) -and $cfg[$k]) { $cfg[$k] } else { $d } }

$BOT_TOKEN   = Cfg "BOT_TOKEN" ""
$CHANNEL_ID  = Cfg "CHANNEL_ID" ""
$GH_OWNER    = Cfg "GH_OWNER" "rexlads"
$GH_REPO     = Cfg "GH_REPO" "trustpositif-bot"
$GH_BRANCH   = Cfg "GH_BRANCH" "main"
$INTERVAL    = [int](Cfg "INTERVAL_MINUTES" "10")
$ONLY_BLOCKED = (Cfg "ONLY_BLOCKED" "0") -eq "1"

$KNOWN_BLOCKED = @("pornhub.com", "xnxx.com", "xvideos.com", "bet365.com")
$KNOWN_SAFE = "google.com"
$OFFICIAL = @(
  "https://trustpositif.komdigi.go.id/api/cek?url={0}",
  "https://trustpositif.komdigi.go.id/Rest_server/getRecordDomain?domain={0}"
)
$custom = Cfg "OFFICIAL_CHECK_URL" ""
if ($custom) { $OFFICIAL = @($custom.Replace("{domain}", "{0}")) + $OFFICIAL }

# Official Komdigi blocklist MIRROR (Skiddle), used only if real-time fails.
$MIRROR = "https://raw.githubusercontent.com/Skiddle-ID/blocklist/main/domains_{0:D3}.txt"

$BLOCK_MARKERS = @("internetpositif", "internet positif", "trustpositif",
                   "trust positif", "aduankonten", "diblokir", "terblokir")

# ---------------------------------------------------------------------------
# Detection: returns $true (blocked) / $false (safe) / $null (unknown)
# ---------------------------------------------------------------------------
function Interpret([string]$body) {
  $t = $body.ToLower()
  try {
    $j = $body | ConvertFrom-Json -ErrorAction Stop
    foreach ($k in @("blocked", "isblocked", "is_blocked", "block", "status")) {
      if ($j.PSObject.Properties.Name -contains $k) {
        $v = $j.$k
        if ($v -is [bool]) { return $v }
        $s = ("$v").ToLower().Trim()
        if ($s -in @("ada", "blocked", "true", "1", "diblokir")) { return $true }
        if ($s -in @("tidak ada", "not blocked", "false", "0", "aman")) { return $false }
      }
    }
  } catch {}
  if ($t.Contains("tidak ada") -or $t.Contains("tidak diblokir") -or $t -match '"blocked"\s*:\s*false') { return $false }
  foreach ($m in $BLOCK_MARKERS) { if ($t.Contains($m)) { return $true } }
  if ($t.Length -lt 400 -and $t -match '\bada\b') { return $true }
  return $null
}

function Check-Official([string]$tmpl, [string]$domain) {
  try {
    $u = [string]::Format($tmpl, [uri]::EscapeDataString($domain))
    $r = Invoke-WebRequest -Uri $u -Headers @{ "User-Agent" = $UA } -TimeoutSec 20 -UseBasicParsing
    if ($r.StatusCode -ne 200) { return $null }
    return (Interpret ([string]$r.Content))
  } catch { return $null }
}

function Check-BlockPage([string]$domain) {
  try {
    $r = Invoke-WebRequest -Uri ("http://" + $domain + "/") -Headers @{ "User-Agent" = $UA } `
         -TimeoutSec 15 -MaximumRedirection 5 -UseBasicParsing
    $blob = (($r.BaseResponse.ResponseUri.AbsoluteUri) + " " + ([string]$r.Content)).ToLower()
    foreach ($m in $BLOCK_MARKERS) { if ($blob.Contains($m)) { return $true } }
    return $false
  } catch { return $null }
}

function Calibrate() {
  foreach ($tmpl in $OFFICIAL) {
    if ($false -eq (Check-Official $tmpl $KNOWN_SAFE)) {
      foreach ($kb in $KNOWN_BLOCKED) {
        if ($true -eq (Check-Official $tmpl $kb)) { return @{ Type = "official"; Url = $tmpl } }
      }
    }
  }
  if ($false -eq (Check-BlockPage $KNOWN_SAFE)) {
    foreach ($kb in $KNOWN_BLOCKED) {
      if ($true -eq (Check-BlockPage $kb)) { return @{ Type = "blockpage" } }
    }
  }
  return $null
}

# ---------------------------------------------------------------------------
# Mirror fallback - exact membership over the Skiddle shards (streamed)
# ---------------------------------------------------------------------------
function Get-MirrorHits([string[]]$targets) {
  $want = [System.Collections.Generic.HashSet[string]]::new()
  foreach ($t in $targets) { [void]$want.Add($t.ToLower()) }
  $hits = [System.Collections.Generic.HashSet[string]]::new()
  for ($i = 1; $i -le 20; $i++) {
    $url = [string]::Format($MIRROR, $i)
    $tmp = Join-Path $env:TEMP ("tp_shard_{0}.txt" -f $i)
    try { Invoke-WebRequest -Uri $url -OutFile $tmp -TimeoutSec 120 -UseBasicParsing } catch { break }
    try {
      $reader = [System.IO.StreamReader]::new($tmp)
      while ($null -ne ($line = $reader.ReadLine())) {
        $d = $line.Trim().ToLower()
        if ($want.Contains($d)) { [void]$hits.Add($d) }
      }
      $reader.Close()
    } catch {}
    Remove-Item $tmp -ErrorAction SilentlyContinue
    if ($hits.Count -ge $want.Count) { break }
  }
  return $hits
}

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
function Esc([string]$s) { $s.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;") }

function Send-Telegram([string]$msg) {
  try {
    Invoke-RestMethod -Uri "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" -Method Post -Body @{
      chat_id = $CHANNEL_ID; text = $msg; parse_mode = "HTML"; disable_web_page_preview = "true"
    } | Out-Null
  } catch { Write-Host "[telegram] $($_.Exception.Message)" }
}

function Mentions-For($mObj, [string]$group) {
  $handles = @()
  $lists = @()
  if ($mObj) {
    if ($mObj.PSObject.Properties.Name -contains $group -and $mObj.$group) { $lists += , @($mObj.$group) }
    if ($mObj.PSObject.Properties.Name -contains "_all" -and $mObj._all) { $lists += , @($mObj._all) }
  }
  foreach ($lst in $lists) {
    foreach ($u in $lst) {
      $h = "@" + ("$u").Trim().TrimStart("@")
      if ($h -ne "@" -and ($handles -notcontains $h)) { $handles += $h }
    }
  }
  $handles -join " "
}

function Build-Msg([string]$group, $results, [string]$mention) {
  $lines = @("<b>$EMO_SHIELD TrustPositif - $(Esc $group)</b>", "")
  $blk = 0; $safe = 0
  foreach ($r in $results) {
    if ($r.blocked) { $icon = $EMO_RED; $det = "Diblokir ($($r.src))"; $blk++ }
    else { $icon = $EMO_GREEN; $det = "Tidak diblokir ($($r.src))"; $safe++ }
    $lines += "$icon <code>$(Esc $r.domain)</code> - $det"
  }
  $lines += ""
  $lines += "$EMO_RED $blk  $EMO_GREEN $safe"
  if ($blk -gt 0 -and $mention) { $lines += "$EMO_BELL $mention" }
  $lines += '<a href="https://trustpositif.komdigi.go.id/">Verifikasi manual</a>'
  $lines -join "`n"
}

# ---------------------------------------------------------------------------
function Get-Json([string]$fname) {
  $url = ("https://raw.githubusercontent.com/{0}/{1}/{2}/{3}?_={4}" -f `
          $GH_OWNER, $GH_REPO, $GH_BRANCH, $fname, [DateTimeOffset]::UtcNow.ToUnixTimeSeconds())
  try { return ((Invoke-WebRequest -Uri $url -TimeoutSec 30 -UseBasicParsing).Content | ConvertFrom-Json) }
  catch { return $null }
}

function Ordered-Groups($obj) {
  $groups = [ordered]@{}
  foreach ($g in @("Ary", "AS", "BD", "SV")) {
    if ($obj -and ($obj.PSObject.Properties.Name -contains $g) -and $obj.$g) { $groups[$g] = @($obj.$g) }
  }
  if ($obj) {
    foreach ($p in $obj.PSObject.Properties) {
      if (@("Ary", "AS", "BD", "SV") -notcontains $p.Name -and $p.Value) { $groups[$p.Name] = @($p.Value) }
    }
  }
  $groups
}

function Run-Once() {
  $domainsObj = Get-Json "domains.json"
  $mentionsObj = Get-Json "mentions.json"
  $groups = Ordered-Groups $domainsObj
  $total = 0; foreach ($k in $groups.Keys) { $total += $groups[$k].Count }
  if ($total -eq 0) { Write-Host "Belum ada domain (atur lewat panel)."; return }

  $method = Calibrate
  if ($method) { Write-Host "Sumber: REAL-TIME ($($method.Type))" }
  else { Write-Host "Sumber: MIRROR (metode real-time tak jalan dari mesin ini)" }

  $pending = [ordered]@{}
  $noneTargets = New-Object System.Collections.Generic.List[string]
  foreach ($g in $groups.Keys) {
    $res = @()
    foreach ($d in $groups[$g]) {
      $v = $null
      if ($method) {
        if ($method.Type -eq "official") { $v = Check-Official $method.Url $d } else { $v = Check-BlockPage $d }
      }
      if ($null -eq $v) { $noneTargets.Add($d.ToLower()); $res += @{ domain = $d; blocked = $null; src = "?" } }
      else { $res += @{ domain = $d; blocked = [bool]$v; src = "resmi" } }
      if ($method) { Start-Sleep -Milliseconds 700 }
    }
    $pending[$g] = $res
  }

  if ($noneTargets.Count -gt 0) {
    Write-Host "  ($($noneTargets.Count) domain tak pasti dari resmi -> cek mirror)"
    $hits = Get-MirrorHits ($noneTargets.ToArray())
    foreach ($g in $pending.Keys) {
      foreach ($r in $pending[$g]) {
        if ($null -eq $r.blocked) { $r.blocked = $hits.Contains($r.domain.ToLower()); $r.src = "mirror" }
      }
    }
  }

  foreach ($g in $groups.Keys) {
    $results = $pending[$g]
    foreach ($r in $results) { Write-Host ("  [{0}] {1} {2}" -f $g, $(if ($r.blocked) { "BLOCKED" } else { "safe   " }), $r.domain) }
    if ($ONLY_BLOCKED) {
      $results = @($results | Where-Object { $_.blocked })
      if ($results.Count -eq 0) { Send-Telegram "<b>$EMO_SHIELD TrustPositif - $g</b>`n$EMO_GREEN Semua aman."; Start-Sleep 1; continue }
    }
    Send-Telegram (Build-Msg $g $results (Mentions-For $mentionsObj $g))
    Start-Sleep 1
  }
}

function Self-Test() {
  Write-Host "Kalibrasi dari IP mesin ini (harus IP Indonesia)...`n"
  foreach ($t in $OFFICIAL) {
    $s = Check-Official $t $KNOWN_SAFE; $b = Check-Official $t $KNOWN_BLOCKED[0]
    Write-Host "[official] $t`n   safe(google)=$s  blocked(pornhub)=$b"
  }
  $s = Check-BlockPage $KNOWN_SAFE; $b = Check-BlockPage $KNOWN_BLOCKED[0]
  Write-Host "[blockpage] safe(google)=$s  blocked(pornhub)=$b"
  $m = Calibrate
  if ($m) { Write-Host "`n==> Metode terpilih: $($m.Type) $($m.Url)" }
  else { Write-Host "`n==> Tidak ada metode real-time; akan pakai MIRROR." }
}

# ---------------------------------------------------------------------------
if (-not $BOT_TOKEN -or -not $CHANNEL_ID) {
  Write-Host "Isi BOT_TOKEN dan CHANNEL_ID di file .env dulu." -ForegroundColor Red
  exit 1
}
if ($args -contains "--test") { Self-Test; exit 0 }

Write-Host "TrustPositif real-time runner. Interval $INTERVAL menit. Tutup jendela untuk berhenti."
while ($true) {
  try { Run-Once } catch { Write-Host "[cycle error] $($_.Exception.Message)" }
  Write-Host "--- tidur $INTERVAL menit ---"
  Start-Sleep -Seconds ($INTERVAL * 60)
}
