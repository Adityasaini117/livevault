# build.ps1 - Package LifeVault MCP Server for AWS Lambda (ap-southeast-2)
# Runtime: Python 3.13 (python3.13, x86_64)

[CmdletBinding()]
param(
    [string]$PythonVersion = "3.13",
    [string]$Platform = "manylinux2014_x86_64",
    [switch]$KeepBuildDir = $false
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path "$ScriptDir\..").Path
$DeployDir = Join-Path $RepoRoot "deploy"
$ServerDir = Join-Path $RepoRoot "server"
$BuildDir = Join-Path $DeployDir ".build"
$ZipPath = Join-Path $DeployDir "package.zip"

Write-Host "============================================================"
Write-Host "LifeVault AWS Lambda Packaging"
Write-Host "Selected Lambda Runtime: Python $PythonVersion (x86_64)"
Write-Host "Platform Target        : $Platform"
Write-Host "Pip Resolution Flags   : --platform $Platform --only-binary=:all: --python-version $PythonVersion"
Write-Host "============================================================"

# Resolve python interpreter
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
}

# 1. Clean previous build artifacts
if (Test-Path $BuildDir) {
    Write-Host "Cleaning existing build directory: $BuildDir"
    Remove-Item -Recurse -Force $BuildDir
}
New-Item -ItemType Directory -Path $BuildDir | Out-Null

if (Test-Path $ZipPath) {
    Remove-Item -Force $ZipPath
}

# 2. Install dependencies for Linux target
Write-Host "`nResolving and installing Python dependencies into build directory..."
$ReqFile = Join-Path $ServerDir "requirements.txt"

# When executing on Windows hosts targeting manylinux, standard pip evaluates
# host sys_platform == 'win32' markers (e.g. pywin32 in mcp SDK) against the host
# rather than target platform. We patch packaging.markers.default_environment in-memory
# so pip strictly resolves Linux markers without silent fallback or host contamination.
$PipRunnerScript = @"
import os
import sys
import pip._vendor.packaging.markers as m

orig_env = m.default_environment
def linux_env():
    env = orig_env()
    env['sys_platform'] = 'linux'
    env['platform_system'] = 'Linux'
    env['os_name'] = 'posix'
    return env
m.default_environment = linux_env

import pip._internal.cli.main
req_file = r'$ReqFile'
target_dir = r'$BuildDir'

args = [
    'install',
    '--target', target_dir,
    '--platform', '$Platform',
    '--only-binary=:all:',
    '--python-version', '$PythonVersion',
    '-r', req_file,
]
exit_code = pip._internal.cli.main.main(args)
sys.exit(exit_code)
"@

$RunnerFile = Join-Path $env:TEMP "pip_lambda_runner.py"
$PipLogFile = Join-Path $env:TEMP "pip_lambda_build.log"
Set-Content -Path $RunnerFile -Value $PipRunnerScript -Encoding UTF8

try {
    & {
        $ErrorActionPreference = "Continue"
        & $PythonExe $RunnerFile
    }
    $pipExitCode = $LASTEXITCODE
    if ($pipExitCode -ne 0) {
        throw "Build failed: pip was unable to resolve a manylinux wheel for a required package (exit code $pipExitCode)."
    }
} finally {
    if (Test-Path $RunnerFile) { Remove-Item -Force $RunnerFile }
}

# 3. Strip AWS runtime-provided libraries (boto3, botocore, s3transfer) and package test directories
Write-Host "`nExcluding AWS Lambda runtime-provided libraries (boto3, botocore, s3transfer) and tests..."
$ExcludePrefixes = @("boto3", "botocore", "s3transfer")
Get-ChildItem -Path $BuildDir | Where-Object {
    $name = $_.Name
    foreach ($prefix in $ExcludePrefixes) {
        if ($name -like "$prefix*") { return $true }
    }
    return $false
} | ForEach-Object {
    Remove-Item -Recurse -Force $_.FullName
}

# Remove package tests directories
Get-ChildItem -Path $BuildDir -Recurse -Directory | Where-Object {
    $_.Name -eq "tests" -or $_.Name -eq "_tests" -or $_.Name -eq "test"
} | ForEach-Object {
    Remove-Item -Recurse -Force $_.FullName
}

# Also remove any stray benchmark/test files
Get-ChildItem -Path $BuildDir -Recurse -File | Where-Object {
    $_.Name -like "*test_*" -or $_.Name -like "*_test.py"
} | ForEach-Object {
    Remove-Item -Force $_.FullName
}

# 4. Copy server application code
Write-Host "`nCopying /server code into package..."
$ServerFiles = @("server.py", "storage.py", "storage_dynamodb.py", "ai.py", "create_table.py", "requirements.txt")
foreach ($file in $ServerFiles) {
    $src = Join-Path $ServerDir $file
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination $BuildDir -Force
    }
}

# Copy lambda_handler.py to build root (for lambda_handler.lambda_handler)
$HandlerSrc = Join-Path $DeployDir "lambda_handler.py"
Copy-Item -Path $HandlerSrc -Destination $BuildDir -Force

# Also preserve deploy/lambda_handler.py inside package so both handler paths work
$DeploySubDir = Join-Path $BuildDir "deploy"
New-Item -ItemType Directory -Path $DeploySubDir -Force | Out-Null
Copy-Item -Path $HandlerSrc -Destination $DeploySubDir -Force

# 5. Strict security and contamination inspection
Write-Host "`nPerforming security and exclusion inspection..."
$Violations = @()

Get-ChildItem -Path $BuildDir -Recurse -File | ForEach-Object {
    $fileName = $_.Name
    $filePath = $_.FullName
    if ($fileName -like "*.db" -or $fileName -like ".env*" -or $fileName -like "*test_*" -or $fileName -like "*_test.py") {
        $Violations += $filePath
    }
}
Get-ChildItem -Path $BuildDir -Recurse -Directory | Where-Object {
    $_.Name -eq "tests" -or $_.Name -eq "_tests"
} | ForEach-Object {
    $Violations += $_.FullName
}

if ($Violations.Count -gt 0) {
    Write-Error "SECURITY VIOLATION: Forbidden or secret files detected in build output:`n$($Violations -join "`n")"
    exit 1
}

# 6. Archive to deploy/package.zip
Write-Host "`nArchiving package to $ZipPath..."
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }

# Use Python's zipfile for consistent compression and clean path formatting
$ZipScript = @"
import os
import zipfile

build_dir = r'$BuildDir'
zip_path = r'$ZipPath'

with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(build_dir):
        # Exclude pycache directories
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for f in sorted(files):
            if f.endswith('.pyc') or f.endswith('.pyo'):
                continue
            full_path = os.path.join(root, f)
            arc_name = os.path.relpath(full_path, build_dir).replace('\\', '/')
            zf.write(full_path, arc_name)
"@
& $PythonExe -c $ZipScript

# 7. Verification and Size Reporting
$ZipItem = Get-Item $ZipPath
$ZipSizeMB = [math]::Round($ZipItem.Length / 1MB, 2)

Write-Host "`n============================================================"
Write-Host "PACKAGE VERIFICATION SUMMARY"
Write-Host "============================================================"
Write-Host "Package Path : $ZipPath"
Write-Host "Package Size : $ZipSizeMB MB"

# Verify size threshold
if ($ZipSizeMB -gt 50.0) {
    Write-Error "ERROR: Package size ($ZipSizeMB MB) exceeds AWS Lambda direct-upload limit of 50 MB! Trim dependencies before deploying."
    exit 1
} else {
    Write-Host "Status       : PASS (Under 50 MB direct-upload threshold)"
}

# Print top-level package listing
Write-Host "`nTop-level entries in zip package:"
& $PythonExe -c "
import zipfile
with zipfile.ZipFile(r'$ZipPath') as z:
    top = sorted(set(n.split('/')[0] for n in z.namelist()))
    for item in top:
        print(f' - {item}')
    total_files = len(z.namelist())
    print(f'\nTotal files in zip: {total_files}')
"

# 8. Cleanup build directory unless -KeepBuildDir was requested
if (-not $KeepBuildDir) {
    Write-Host "`nCleaning temporary build directory..."
    Remove-Item -Recurse -Force $BuildDir
}

Write-Host "`nBuild complete successfully! deploy/package.zip is ready for deployment."
