param([string]$Python = 'python')

$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $PSScriptRoot
$buildRoot = Join-Path $appRoot 'build'
$distRoot = Join-Path $appRoot 'dist'
$portableRoot = Join-Path $distRoot 'optical-distortion-evaluator-v6'

& $Python (Join-Path $PSScriptRoot 'make_startup_image.py')
if ($LASTEXITCODE -ne 0) { throw '启动图生成失败。' }
& $Python -m unittest discover -s $PSScriptRoot -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw '单元测试失败。' }
& $Python -m PyInstaller --noconfirm --distpath $distRoot --workpath $buildRoot (Join-Path $PSScriptRoot 'portable.spec')
if ($LASTEXITCODE -ne 0) { throw '打包失败。' }
Copy-Item -LiteralPath (Join-Path $appRoot 'README.md') -Destination $portableRoot
Copy-Item -LiteralPath (Join-Path $appRoot 'third-party') -Destination $portableRoot -Recurse
& $Python (Join-Path $PSScriptRoot 'collect_runtime_licenses.py') (Join-Path $portableRoot 'third-party\runtime-licenses')
if ($LASTEXITCODE -ne 0) { throw '运行时许可文件收集失败。' }
$report = Join-Path $buildRoot 'portable_smoke.json'
$exe = Join-Path $portableRoot '光机镜头畸变评估工具V6.exe'
if (Test-Path -LiteralPath $report) { Remove-Item -LiteralPath $report }
$process = Start-Process -FilePath $exe -ArgumentList @('--smoke-test', ('"' + $report + '"'), '--startup-self-test') -Wait -PassThru -WindowStyle Hidden
if ($process.ExitCode -ne 0) { throw '打包后界面自检失败。' }
$result = Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $result.ok) { throw $result.error }

$native = Join-Path $buildRoot 'native_runtime.json'
if (Test-Path -LiteralPath $native) { Remove-Item -LiteralPath $native }
$process = Start-Process -FilePath $exe -ArgumentList @('--native-runtime-check', ('"' + $native + '"')) -Wait -PassThru -WindowStyle Hidden
if ($process.ExitCode -ne 0) { throw 'Windows Qt 平台检查失败。' }
$result = Get-Content -LiteralPath $native -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $result.ok) { throw 'Windows Qt 平台检查失败。' }
Write-Output $portableRoot
