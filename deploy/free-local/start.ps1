$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
try {
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop을 먼저 실행하고 준비될 때까지 기다려 주세요.' }
    docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose가 포함된 최신 Docker Desktop이 필요합니다.' }
    Remove-Item 'public-url.txt' -ErrorAction SilentlyContinue
    if (-not (Test-Path '.env')) {
        $secure = Read-Host '로그인 비밀번호를 정하세요 (영문/숫자 12자 이상)' -AsSecureString
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
        if ($password -notmatch '^[A-Za-z0-9]{12,}$') { throw '비밀번호는 영문/숫자로 12자 이상 입력해 주세요.' }
        [IO.File]::WriteAllText((Join-Path $PSScriptRoot '.env'), "STUDIO_PASSWORD=$password`n", (New-Object Text.UTF8Encoding($false)))
        $password = $null
    }
    Write-Host '앱과 한국어 모델을 준비합니다. 첫 설치는 수 분 이상 걸릴 수 있습니다.'
    docker compose --env-file .env -f compose.yaml up -d --build
    if ($LASTEXITCODE -ne 0) { throw '시작 실패. Docker 상태와 인터넷 연결을 확인하세요. 모델 오류는 docker compose logs studio로 확인할 수 있습니다.' }
    Write-Host '무료 임시 공개 주소를 확인합니다. PC와 Docker가 켜져 있어야 접속됩니다.'
    $deadline = (Get-Date).AddMinutes(2)
    do {
        $logs = (docker compose --env-file .env -f compose.yaml logs --no-color --tail 80 tunnel 2>&1 | Out-String)
        if ($logs -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
            $url = $Matches[0]
            try {
                $reply = Invoke-WebRequest -UseBasicParsing -Uri "$url/api/health" -TimeoutSec 10
                $reply.RawContentStream.Position = 0
                $reader = New-Object IO.StreamReader($reply.RawContentStream, [Text.Encoding]::UTF8)
                try { $health = $reader.ReadToEnd() | ConvertFrom-Json }
                finally { $reader.Dispose() }
                if ($health.status -eq 'ok' -and $health.app -eq '신상집착 컷 스튜디오') {
                    [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'public-url.txt'), $url, (New-Object Text.UTF8Encoding($false)))
                    Write-Host "접속 확인 완료: $url"
                    Write-Host '방금 정한 비밀번호로 로그인하세요. 종료는 stop.cmd를 실행하세요.'
                    Start-Process $url
                    exit 0
                }
            } catch { }
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw '공개 연결을 확인하지 못했습니다. 회사·학교 네트워크라면 개인 인터넷에서 다시 시도하세요. public-url.txt의 이전 주소는 유효하지 않을 수 있습니다.'
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
