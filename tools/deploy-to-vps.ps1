# Deploy infra/ to the VPS and run setup.sh there.
#   .\tools\deploy-to-vps.ps1                 copy + run setup.sh
#   .\tools\deploy-to-vps.ps1 -NoSetup        copy only
#   .\tools\deploy-to-vps.ps1 -Vps user@host  another server
# Needs SSH key login (no password prompts). Secrets and files generated on the
# VPS are excluded from the package, so the copy never overwrites them.
param(
    [string]$Vps = 'ubuntu@43.173.6.37',
    [string]$RemoteDir = 'deploy',
    [switch]$NoSetup
)
$ErrorActionPreference = 'Stop'

$Root  = Split-Path -Parent $PSScriptRoot
$Infra = Join-Path $Root 'infra'
$Dist  = Join-Path $Root 'dist'
$Pkg   = Join-Path $Dist 'infra.tar.gz'
New-Item -ItemType Directory -Force $Dist | Out-Null

# Keep in sync with infra/.gitignore
$Exclude = @(
    './local', './reports',
    '*.env', '*.env.local',
    './siem/config/wazuh_indexer_ssl_certs',
    './siem/config/wazuh_cluster/authd.pass',
    './siem/config/wazuh_indexer/internal_users.yml',
    './siem/config/wazuh_dashboard/wazuh.yml',
    './nextcloud/caddy/certs/*.pem',
    '__pycache__'
)
$tarArgs = @('-czf', $Pkg, '-C', $Infra) + ($Exclude | ForEach-Object { "--exclude=$_" }) + @('.')

Write-Host "[1/3] Packing infra/ -> dist/infra.tar.gz"
& tar.exe @tarArgs
if ($LASTEXITCODE -ne 0) { throw 'tar failed' }

Write-Host "[2/3] Copying to ${Vps}:~/$RemoteDir"
& scp -o BatchMode=yes $Pkg "${Vps}:~/infra.tar.gz"
if ($LASTEXITCODE -ne 0) { throw 'scp failed (is SSH key login set up?)' }

# Normalize line endings in the unpacked package (not in ~/deploy, which holds root-only secrets)
$remote = "set -e; rm -rf ~/infra.new; mkdir ~/infra.new; tar xzf ~/infra.tar.gz -C ~/infra.new; " +
          "find ~/infra.new -type f \( -name '*.sh' -o -name 'Caddyfile' -o -name '*.yml' -o -name '*.conf' -o -name '*.xml' -o -name '*.example' -o -name '*.template' \) -exec sed -i 's/\r$//' {} +; " +
          "chmod 755 ~/infra.new/setup.sh ~/infra.new/scripts/*.sh; " +
          "mkdir -p ~/$RemoteDir; cp -r ~/infra.new/. ~/$RemoteDir/; rm -rf ~/infra.new"
& ssh -o BatchMode=yes $Vps $remote
if ($LASTEXITCODE -ne 0) { throw 'unpacking on the VPS failed' }

if ($NoSetup) { Write-Host '[3/3] Skipped setup.sh (-NoSetup)'; exit 0 }

Write-Host '[3/3] Running setup.sh on the VPS (output also saved to ~/setup-output.txt)'
& ssh -o BatchMode=yes -o ServerAliveInterval=30 $Vps "cd ~/$RemoteDir && sudo ./setup.sh 2>&1 | tee ~/setup-output.txt"
exit $LASTEXITCODE
