param([Parameter(Mandatory=$true)][string]$PdfPath,[Parameter(Mandatory=$true)][string]$Url,[Parameter(Mandatory=$true)][switch]$DedicatedTestEnvironment)
if (-not $DedicatedTestEnvironment) { throw "Dedicated environment confirmation required" }
python "$PSScriptRoot/check_api.py" e2e --url $Url --pdf $PdfPath --dedicated-test-environment
if ($LASTEXITCODE -ne 0) { throw "E2E failed" }
