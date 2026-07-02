param(
    [Parameter(Mandatory=$true)][string]$Token,
    [string]$Repo = "mdrumondn-creator/clinica-whatsapp-bot",
    [string]$Branch = "main"
)

$BaseUrl = "https://api.github.com/repos/$Repo"
$Headers = @{
    "Authorization" = "token $Token"
    "Accept"        = "application/vnd.github.v3+json"
    "Content-Type"  = "application/json"
    "User-Agent"    = "PowerShell-PatchScript"
}

function Get-FileSha($path) {
    try {
        $r = Invoke-RestMethod -Uri "$BaseUrl/contents/$path" -Headers $Headers -Method GET
        return $r.sha
    } catch { return $null }
}

function Update-File($path, $content, $message, $sha=$null) {
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($content))
    $body = @{ message=$message; content=$encoded; branch=$Branch }
    if ($sha) { $body["sha"] = $sha }
    $json = $body | ConvertTo-Json
    try {
        $r = Invoke-RestMethod -Uri "$BaseUrl/contents/$path" `
            -Headers $Headers -Method PUT -Body $json
        Write-Host "[OK] $path" -ForegroundColor Green
        return $true
    } catch {
        Write-Host "[FAIL] $path : $_" -ForegroundColor Red
        return $false
    }
}

function Delete-File($path, $message) {
    $sha = Get-FileSha $path
    if (-not $sha) { Write-Host "[SKIP] $path nao encontrado" -ForegroundColor Yellow; return }
    $body = @{ message=$message; sha=$sha; branch=$Branch } | ConvertTo-Json
    try {
        Invoke-RestMethod -Uri "$BaseUrl/contents/$path" `
            -Headers $Headers -Method DELETE -Body $body | Out-Null
        Write-Host "[DEL] $path" -ForegroundColor Cyan
    } catch {
        Write-Host "[FAIL-DEL] $path : $_" -ForegroundColor Red
    }
}

Write-Host "`n=== INICIANDO PATCHES DE SEGURANÇA ===" -ForegroundColor Magenta
Write-Host "Repo: $Repo | Branch: $Branch`n"

# === DELETAR ARQUIVOS LIXO ===
Write-Host "-- Deletando arquivos desnecessarios --" -ForegroundColor Yellow
$filesToDelete = @(
    "fix_enum.py",
    "fix_modal.py",
    "replace_emojis.py",
    "swap_icons.py",
    "inject_users.py",
    "update_pass.sql",
    "create_admin.sql",
    "ANTIGRAVITY_SYNC.md"
)
foreach ($f in $filesToDelete) {
    Delete-File $f "security: remove dev/one-shot script $f"
}

# === ATUALIZAR ARQUIVOS ===
Write-Host "`n-- Atualizando arquivos modificados --" -ForegroundColor Yellow

# requirements.txt
$req = Get-Content "requirements.txt" -Raw
$sha = Get-FileSha "requirements.txt"
Update-File "requirements.txt" $req "security: add bcrypt dependency" $sha

# .gitignore
$gi = Get-Content ".gitignore" -Raw
$sha = Get-FileSha ".gitignore"
Update-File ".gitignore" $gi "security: expand gitignore (cache, .env, aider history)" $sha

# .env.example
$env = Get-Content ".env.example" -Raw
$sha = Get-FileSha ".env.example"
Update-File ".env.example" $env "security: document JWT_SECRET requirement in .env.example" $sha

# docker-compose.yml
$dc = Get-Content "docker-compose.yml" -Raw
$sha = Get-FileSha "docker-compose.yml"
Update-File "docker-compose.yml" $dc "security: remove exposed 5432 port, DANGEROUS_FUNCTIONS=false, remove hardcoded IP" $sha

# create_admin.py
$ca = Get-Content "create_admin.py" -Raw -Encoding UTF8
$sha = Get-FileSha "create_admin.py"
Update-File "create_admin.py" $ca "security: migrate create_admin.py to bcrypt with password validation" $sha

# main.py
$mp = Get-Content "main.py" -Raw -Encoding UTF8
$sha = Get-FileSha "main.py"
Update-File "main.py" $mp "security: bcrypt login+migration, JWT fail-fast, CORS fix, remove dead code, password policy" $sha

Write-Host "`n=== PATCHES CONCLUIDOS ===" -ForegroundColor Magenta
Write-Host "Verifique o repositorio em: https://github.com/$Repo" -ForegroundColor Cyan
