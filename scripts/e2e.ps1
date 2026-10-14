param(
    [Parameter(Mandatory=$true)][string]$PdfPath,
    [string]$Url = "https://api.universidad.localhost/process"
)

$first = & curl.exe -k -sS -X POST -H "Content-Type: application/pdf" --data-binary "@$PdfPath" $Url
if ($LASTEXITCODE -ne 0) { throw "Falló curl en la primera llamada." }
$firstResult = $first | ConvertFrom-Json
if (-not $firstResult.document_id -or -not $firstResult.checksum -or $firstResult.source -notin @("existing", "extracted")) { throw "Respuesta inesperada: $first" }
if ($firstResult.source -ne "extracted") { throw "La primera llamada debía ser extracted (respuesta: $($firstResult.source))." }

$second = & curl.exe -k -sS -X POST -H "Content-Type: application/pdf" --data-binary "@$PdfPath" $Url
if ($LASTEXITCODE -ne 0) { throw "Falló curl en la segunda llamada." }
$secondResult = $second | ConvertFrom-Json
if ($secondResult.source -ne "existing") { throw "La segunda llamada debía ser existing: $second" }
Write-Host "E2E OK: checksum $($firstResult.checksum); segunda llamada existing."
