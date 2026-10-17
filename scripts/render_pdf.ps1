<#
F07 — Rasteriza LOCALMENTE um PDF exportado (dados sintéticos) para PNG com a API nativa do Windows (Windows.Data.Pdf),
sem instalar nada e sem enviar o arquivo a serviços externos. Usado na medição de fidelidade HTML × PDF.

- Saída fora do Git (output/, private/ ou fora do repositório). O arquivo de entrada não é alterado (SHA-256 conferido).

Uso:  powershell -ExecutionPolicy Bypass -File scripts/render_pdf.ps1 -Pdf output\export-fidelity\caso\deck.pdf -OutDir output\export-fidelity\caso\pdf
#>
param(
    [Parameter(Mandatory = $true)][string]$Pdf,
    [Parameter(Mandatory = $true)][string]$OutDir,
    [int]$Width = 1920
)
$ErrorActionPreference = 'Stop'
$full = (Resolve-Path -LiteralPath $Pdf).Path
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$outFull = if ([System.IO.Path]::IsPathRooted($OutDir)) { [System.IO.Path]::GetFullPath($OutDir) } else { [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $OutDir)) }
if ($outFull.StartsWith($repo, [System.StringComparison]::OrdinalIgnoreCase)) {
    $rel = $outFull.Substring($repo.Length).TrimStart('\', '/')
    $first = ($rel -split '[\\/]')[0]
    if (@('private', 'output', 'data') -notcontains $first) {
        throw "Saída dentro do repositório e versionável ($rel). Use private/, output/ ou data/ (ignorados) ou fora do repo."
    }
}
New-Item -ItemType Directory -Force -Path $outFull | Out-Null
$before = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
$asTaskAction = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
function AwaitAction($op) { $task = $asTaskAction.Invoke($null, @($op)); $task.Wait(-1) | Out-Null }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($full)) ([Windows.Storage.StorageFile])
$doc = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
for ($i = 0; $i -lt $doc.PageCount; $i++) {
    $page = $doc.GetPage($i)
    $opts = New-Object Windows.Data.Pdf.PdfPageRenderOptions
    $opts.DestinationWidth = $Width
    $opts.DestinationHeight = [uint32][math]::Round($Width * $page.Size.Height / $page.Size.Width)
    $opts.BitmapEncoderId = [Windows.Graphics.Imaging.BitmapEncoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]::PngEncoderId
    $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
    AwaitAction ($page.RenderToStreamAsync($stream, $opts))
    $net = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream.GetInputStreamAt(0))
    $target = Join-Path $outFull ('page{0:D2}.png' -f ($i + 1))
    $fs = [System.IO.File]::Create($target)
    $net.CopyTo($fs); $fs.Close(); $net.Close(); $page.Dispose()
}
$after = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash
if ($before -ne $after) { throw 'O arquivo mudou durante a renderização (não deveria).' }
"páginas: $($doc.PageCount)"
