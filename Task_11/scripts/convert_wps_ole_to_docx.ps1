param(
    [Parameter(Mandatory = $true)][string]$SourcePath,
    [Parameter(Mandatory = $true)][string]$OutputPath
)

$ErrorActionPreference = 'Stop'

if (Test-Path -LiteralPath $OutputPath) {
    $existing = [System.IO.File]::ReadAllBytes($OutputPath)
    if ($existing.Length -ge 4 -and $existing[0] -eq 0x50 -and $existing[1] -eq 0x4B) {
        Write-Output $OutputPath
        exit 0
    }
}

$parent = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Path $parent -Force | Out-Null

$app = $null
$doc = $null
try {
    $app = New-Object -ComObject 'kwps.Application'
    $app.Visible = $false
    $doc = $app.Documents.Open($SourcePath, $false, $true)
    # 16 = Word 默认 OOXML 文档格式（.docx）。
    $doc.SaveAs2($OutputPath, 16)
    Write-Output $OutputPath
}
finally {
    if ($doc) { $doc.Close($false) }
    if ($app) { $app.Quit() }
    [System.GC]::Collect()
    [System.GC]::WaitForPendingFinalizers()
}
