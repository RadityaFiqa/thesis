# LOCAL TEST of the Phase 1 stack on Docker Desktop (Windows).
# Started by run-local.cmd. Uses nextcloud.localhost / wazuh.localhost on port 8443,
# its own secrets (*.env.local) and its own Docker volumes. Does not touch the VPS.
$ErrorActionPreference = 'Continue'
$Deploy = Split-Path -Parent $PSScriptRoot
$NC     = Join-Path $Deploy 'nextcloud'
$SIEM   = Join-Path $Deploy 'siem'
$Out    = Join-Path $PSScriptRoot 'local-test-output.txt'
Start-Transcript -Path $Out -Force | Out-Null

$script:P = 0; $script:F = 0; $script:W = 0
function Step($m) { Write-Host ''; Write-Host "==> $m" -ForegroundColor Cyan }
function Pass($m) { $script:P++; Write-Host "  [PASS] $m" -ForegroundColor Green }
function Fail($m) { $script:F++; Write-Host "  [FAIL] $m" -ForegroundColor Red }
function Warn($m) { $script:W++; Write-Host "  [WARN] $m" -ForegroundColor Yellow }

# Run a native command, echo its output (stdout+stderr) into the transcript, return exit code
function Run {
    param([string]$Dir, [string[]]$Cmd)
    if ($Dir) { Push-Location $Dir }
    try {
        & $Cmd[0] $Cmd[1..($Cmd.Length - 1)] 2>&1 | ForEach-Object { Write-Host "    $_" }
        return $LASTEXITCODE
    } finally { if ($Dir) { Pop-Location } }
}
# docker compose with the local env file, output captured (stderr dropped)
function Dc {
    param([string]$Dir, [string[]]$A)
    Push-Location $Dir
    try { & docker compose --env-file .env.local @A 2>$null } finally { Pop-Location }
}
function EnvLocal($dir, $key) {
    $line = Get-Content (Join-Path $dir '.env.local') | Where-Object { $_ -match "^$key=" } | Select-Object -Last 1
    if ($line) { return $line.Substring($key.Length + 1) } else { return '' }
}
function Finish {
    Write-Host ''
    Write-Host ("Summary: {0} pass, {1} fail, {2} warn" -f $script:P, $script:F, $script:W)
    Write-Host "Output saved to $Out"
    Stop-Transcript | Out-Null
    exit $script:F
}

Write-Host "Local test of the Phase 1 stack  -  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

# ---------------------------------------------------------------- Docker
Step 'Docker Desktop'
$mem = & docker info --format '{{.MemTotal}}' 2>$null
if ($LASTEXITCODE -ne 0 -or -not $mem) {
    Fail 'Docker is not running. Install/start Docker Desktop (https://www.docker.com/products/docker-desktop/), wait until it says "Engine running", then run this again.'
    Finish
}
$memGB = [math]::Round([double]$mem / 1GB, 1)
Write-Host "  docker $(& docker version --format '{{.Server.Version}}' 2>$null), memory available to Docker: $memGB GB"
if ($memGB -lt 5.5) { Warn "Docker has only $memGB GB. Wazuh + Nextcloud need about 6 GB: Docker Desktop > Settings > Resources (or .wslconfig memory=8GB)." }
else { Pass "Docker running with $memGB GB" }

Step 'Kernel setting for the Wazuh indexer'
if ((Run '' @('docker','run','--rm','--privileged','busybox:1.37.0','sysctl','-w','vm.max_map_count=262144')) -eq 0) { Pass 'vm.max_map_count=262144' }
else { Warn 'could not set vm.max_map_count; the indexer may fail to start' }

# ---------------------------------------------------------------- config
Step 'Generate local secrets and config (only if missing)'
$rc = Run '' @('docker','run','--rm','-v',"${Deploy}:/work",'python:3.13-alpine','sh','-c',
    'pip install -q --disable-pip-version-check --root-user-action=ignore bcrypt && python /work/local/gen_local.py')
if ($rc -ne 0) { Fail 'config generation failed'; Finish }

Step 'Wazuh certificates'
if (Test-Path (Join-Path $SIEM 'config\wazuh_indexer_ssl_certs\root-ca-manager.pem')) { Write-Host '  certificates exist' }
else {
    $rc = Run $SIEM @('docker','compose','-f','generate-indexer-certs.yml','run','--rm','generator')
    if ($rc -ne 0) { Fail 'certificate generation failed'; Finish }
}

$IPW = EnvLocal $SIEM 'INDEXER_PASSWORD'
function IndexerCode { & curl.exe -sk -o NUL -w '%{http_code}' -u "admin:$IPW" 'https://127.0.0.1:9200/_cluster/health' 2>$null }

# ---------------------------------------------------------------- start
Step 'Start SIEM project'
if ((Run $SIEM @('docker','compose','--env-file','.env.local','up','-d')) -ne 0) { Fail 'siem: docker compose up failed'; Finish }
Write-Host -NoNewline '  waiting for the indexer'
$ok = $false; $inited = $false
for ($i = 1; $i -le 72; $i++) {
    if ((IndexerCode) -eq '200') { $ok = $true; break }
    if ($i -ge 24 -and -not $inited) {
        $body = & curl.exe -sk 'https://127.0.0.1:9200/' 2>$null
        if ("$body" -match 'not (yet )?initialized') {
            Write-Host ''; Warn 'security index not initialized; running securityadmin'
            Run $SIEM @('docker','compose','--env-file','.env.local','exec','-T','wazuh.indexer','bash','-c',
              'D=/usr/share/wazuh-indexer; export JAVA_HOME=$D/jdk; bash $D/plugins/opensearch-security/tools/securityadmin.sh -cd $D/config/opensearch-security/ -icl -nhnv -h localhost -p 9200 -cacert $D/config/certs/root-ca.pem -cert $D/config/certs/admin.pem -key $D/config/certs/admin-key.pem') | Out-Null
            $inited = $true
        }
    }
    Write-Host -NoNewline '.'; Start-Sleep 5
}
Write-Host ''
if ($ok) { Pass 'indexer up, admin password accepted' }
else {
    Fail 'indexer not ready after 6 minutes. Last indexer log lines:'
    Run $SIEM @('docker','compose','--env-file','.env.local','logs','--tail','40','wazuh.indexer') | Out-Null
    Finish
}

Step 'Start Nextcloud project'
if ((Run $NC @('docker','compose','--env-file','.env.local','up','-d')) -ne 0) { Fail 'nextcloud: docker compose up failed'; Finish }
Write-Host -NoNewline '  waiting for Nextcloud to install (first run: several minutes)'
$healthy = $false
for ($i = 1; $i -le 120; $i++) {
    $id = Dc $NC @('ps','-q','app')
    if ($id) { $h = & docker inspect -f '{{.State.Health.Status}}' $id 2>$null; if ($h -eq 'healthy') { $healthy = $true; break } }
    Write-Host -NoNewline '.'; Start-Sleep 5
}
Write-Host ''
if ($healthy) { Pass 'Nextcloud healthy' }
else {
    Fail 'Nextcloud not healthy after 10 minutes. Last app log lines:'
    Run $NC @('docker','compose','--env-file','.env.local','logs','--tail','60','app') | Out-Null
    Finish
}

# ---------------------------------------------------------------- checks
Step 'Services'
foreach ($pair in @(@($NC, @('db','redis','app','cron','caddy','wazuh-agent')), @($SIEM, @('wazuh.manager','wazuh.indexer','wazuh.dashboard')))) {
    $lines = Dc $pair[0] @('ps','--format','{{.Service}}|{{.State}}|{{.Health}}')
    foreach ($s in $pair[1]) {
        $l = $lines | Where-Object { $_ -like "$s|*" } | Select-Object -First 1
        if ($l -and $l.Split('|')[1] -eq 'running' -and $l.Split('|')[2] -ne 'unhealthy') { Pass "$s running" } else { Fail "$s : '$l'" }
    }
}

Step 'Project isolation (INF-01)'
function Nets($proj) { (& docker ps --filter "label=com.docker.compose.project=$proj" --format '{{.Networks}}') -join ',' -split ',' | Where-Object { $_ } | Sort-Object -Unique }
$n1 = Nets 'nextcloud'; $n2 = Nets 'siem'
$shared = $n1 | Where-Object { $n2 -contains $_ }
if ($n1 -and $n2 -and -not $shared) { Pass "no shared network (nextcloud: $($n1 -join ' '); siem: $($n2 -join ' '))" } else { Fail "shared networks: $shared" }

$NCU = 'https://nextcloud.localhost:8443'
$RES = @('--resolve','nextcloud.localhost:8443:127.0.0.1','--resolve','wazuh.localhost:8443:127.0.0.1')
Step 'HTTPS through the proxy (INF-03)'
$st = & curl.exe -sk @RES "$NCU/status.php" 2>$null
if ("$st" -match '"installed":true') { Pass "status.php: $st" } else { Fail "status.php returned: $st" }
$wc = & curl.exe -sk @RES -o NUL -w '%{http_code}' 'https://wazuh.localhost:8443/' 2>$null
if ($wc -match '^(200|302)$') { Pass "Wazuh dashboard through the proxy (HTTP $wc)" } else { Fail "Wazuh dashboard through the proxy: HTTP $wc" }

Step 'Logging, audit, cron (INF-09, INF-10)'
function Occ([string[]]$a) { Dc $NC (@('exec','-T','-u','www-data','app','php','occ') + $a) }
foreach ($kv in @(@('log_type','file'), @('logfile','/var/log/nextcloud/nextcloud.log'), @('logfile_audit','/var/log/nextcloud/audit.log'), @('overwritehost','nextcloud.localhost:8443'))) {
    $v = (Occ @('config:system:get', $kv[0])) -join ' '
    if ($v -eq $kv[1]) { Pass "$($kv[0]) = $v" } else { Fail "$($kv[0]) = '$v' (expected $($kv[1]))" }
}
if ((Occ @('app:list','--enabled')) -match 'admin_audit') { Pass 'admin_audit enabled' } else { Fail 'admin_audit not enabled' }
$mode = (Occ @('config:app:get','core','backgroundjobs_mode')) -join ''
if ($mode -eq 'cron') { Pass 'background jobs = cron' } else { Fail "background jobs = '$mode'" }

Step 'Test account and WebDAV transfer (INF-02)'
$user = 'thesis-check'; $credFile = Join-Path $PSScriptRoot '.thesis-check.pass'
if (-not (Test-Path $credFile)) { -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ }) | Set-Content -NoNewline $credFile }
$cpw = (Get-Content $credFile -Raw).Trim()
Dc $NC @('exec','-T','-u','www-data','-e',"OC_PASS=$cpw",'app','php','occ','user:add','--password-from-env',$user) | Out-Null
Occ @('user:info',$user) | Out-Null
if ($LASTEXITCODE -eq 0) { Pass "account $user exists" } else { Fail "could not create $user" }
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'; $file = "phase1-local-$ts.txt"
$tmp = Join-Path $env:TEMP $file; "local test $ts $([guid]::NewGuid())" | Set-Content -NoNewline $tmp
$up = & curl.exe -sk @RES -o NUL -w '%{http_code}' -u "${user}:$cpw" -T $tmp "$NCU/remote.php/dav/files/$user/$file" 2>$null
if ($up -match '^(201|204)$') { Pass "upload $file (HTTP $up)" } else { Fail "upload HTTP $up" }
$dl = "$tmp.dl"; & curl.exe -sk @RES -u "${user}:$cpw" -o $dl "$NCU/remote.php/dav/files/$user/$file" 2>$null
if ((Test-Path $dl) -and ((Get-FileHash $tmp).Hash -eq (Get-FileHash $dl).Hash)) { Pass 'download identical to upload' } else { Fail 'download differs' }

Step 'Logs readable by the agent (INF-06)'
Start-Sleep 3
foreach ($f in @('/var/log/nextcloud/audit.log','/var/log/nextcloud/nextcloud.log','/var/log/caddy/access.log')) {
    Dc $NC @('exec','-T','wazuh-agent','test','-s',$f) | Out-Null
    if ($LASTEXITCODE -eq 0) { Pass "agent reads $f" } else { Fail "agent cannot read $f" }
}
Dc $NC @('exec','-T','wazuh-agent','touch','/var/log/nextcloud/.rw') | Out-Null
if ($LASTEXITCODE -ne 0) { Pass 'log mount is read-only' } else { Fail 'log mount is writable' }
$audit = Dc $NC @('exec','-T','wazuh-agent','grep','-F',$file,'/var/log/nextcloud/audit.log')
if ($audit) { Pass 'audit log recorded the upload' } else { Fail 'upload not in audit.log' }

Step 'Agent enrollment (INF-07)'
$agentName = EnvLocal $NC 'WAZUH_AGENT_NAME'
$found = $false
for ($i = 1; $i -le 12; $i++) {
    $al = Dc $SIEM @('exec','-T','wazuh.manager','/var/ossec/bin/agent_control','-l')
    $line = $al | Where-Object { $_ -match "Name: $agentName," } | Select-Object -First 1
    if ($line -match 'Active') { $found = $true; break }
    Start-Sleep 5
}
if ($found) { Pass "agent active: $($line.Trim())" } else { Fail "agent not active: $line" }

Step 'Indexed and searchable (INF-05)'
$q = Join-Path $env:TEMP 'thesis-q.json'
('{"query":{"query_string":{"query":"rule.id:100100 AND full_log:\"' + $file + '\""}}}') | Set-Content -NoNewline -Encoding Ascii $q
$hit = $false
Write-Host -NoNewline '  waiting for the upload to be indexed'
for ($i = 1; $i -le 36; $i++) {
    $r = & curl.exe -sk -u "admin:$IPW" -H 'Content-Type: application/json' -d "@$q" 'https://127.0.0.1:9200/wazuh-alerts-*/_count' 2>$null
    try { if (($r | ConvertFrom-Json).count -gt 0) { $hit = $true; break } } catch {}
    Write-Host -NoNewline '.'; Start-Sleep 5
}
Write-Host ''
if ($hit) { Pass 'test upload searchable in wazuh-alerts-*' } else { Fail "test upload not indexed after 3 min (last response: $r)" }

Write-Host ''
Write-Host 'Open in your browser (accept the self-signed certificate warning):'
Write-Host "  Nextcloud  $NCU            user: admin  password: NEXTCLOUD_ADMIN_PASSWORD in nextcloud\.env.local"
Write-Host '  Wazuh      https://wazuh.localhost:8443   user: admin  password: INDEXER_PASSWORD in siem\.env.local'
Write-Host 'Stop (keeps data):   run stop-local.cmd'
Finish
