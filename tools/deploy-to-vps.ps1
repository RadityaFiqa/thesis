# Update the VPS to what is pushed on GitHub and run setup.sh there.
#   .\tools\deploy-to-vps.ps1                 git pull + run setup.sh
#   .\tools\deploy-to-vps.ps1 -NoSetup        git pull only
#   .\tools\deploy-to-vps.ps1 -Vps user@host  another server
# The VPS runs from a clone at ~/thesis (stack in ~/thesis/infra). Secrets and
# generated files there are git-ignored, so a pull never touches them.
# Push your commits first: the VPS only sees what is on origin/main.
param(
    [string]$Vps = 'ubuntu@43.173.6.37',
    [string]$RemoteDir = 'thesis',
    [switch]$NoSetup
)
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$local = (& git -C $Root rev-parse HEAD).Trim()
$ahead = (& git -C $Root rev-list --count '@{u}..HEAD' 2>$null)
if ($ahead -and [int]$ahead -gt 0) { Write-Warning "$ahead local commit(s) not pushed; the VPS won't get them" }
if (& git -C $Root status --porcelain) { Write-Warning 'uncommitted local changes; the VPS won''t get them' }

Write-Host "[1/2] git pull on ${Vps}:~/$RemoteDir"
& ssh -o BatchMode=yes $Vps "cd ~/$RemoteDir && git pull --ff-only && git log --oneline -1"
if ($LASTEXITCODE -ne 0) { throw 'git pull on the VPS failed (local changes there? run git status on the VPS)' }

if ($NoSetup) { Write-Host '[2/2] Skipped setup.sh (-NoSetup)'; exit 0 }

Write-Host '[2/2] Running setup.sh on the VPS (output also saved to ~/setup-output.txt)'
& ssh -o BatchMode=yes -o ServerAliveInterval=30 $Vps "cd ~/$RemoteDir/infra && sudo ./setup.sh 2>&1 | tee ~/setup-output.txt"
exit $LASTEXITCODE
