<#
F06B — Renderiza LOCALMENTE os slides de um PowerPoint de referência para PNG (comparação visual).

- Usa o PowerPoint instalado na máquina via COM: arquivo aberto SOMENTE LEITURA, sem janela; nada é salvo.
- Saída deve ficar fora do Git (padrão: private/reference-render/, ignorado). Os PNGs contêm o conteúdo real do
  arquivo: não versionar, não publicar, não enviar a serviços externos.
- O hash SHA-256 do arquivo é conferido antes e depois (falha se o original mudar).
- Se o PowerPoint já estava aberto pelo usuário, ele NÃO é encerrado.

Uso:  powershell -ExecutionPolicy Bypass -File scripts/render_reference.ps1 -Pptx references\ARQUIVO.pptx
#>
param(
    [Parameter(Mandatory = $true)][string]$Pptx,
    [string]$OutDir = 'private/reference-render',
    [int]$Width = 1920,
    [int]$Height = 1080
)
$ErrorActionPreference = 'Stop'
$full = (Resolve-Path -LiteralPath $Pptx).Path
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$outFull = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $OutDir))
if ($outFull.StartsWith($repo, [System.StringComparison]::OrdinalIgnoreCase)) {
    $rel = $outFull.Substring($repo.Length).TrimStart('\', '/')
    $first = ($rel -split '[\\/]')[0]
    if (@('private', 'output', 'data') -notcontains $first) {
        throw "Saída dentro do repositório e versionável ($rel). Use private/, output/ ou data/ (ignorados) ou fora do repo."
    }
}
New-Item -ItemType Directory -Force -Path $outFull | Out-Null
$before = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash
$alreadyRunning = @(Get-Process -Name POWERPNT -ErrorAction SilentlyContinue).Count -gt 0
$app = New-Object -ComObject PowerPoint.Application
$count = 0
try {
    # Open(FileName, ReadOnly=msoTrue, Untitled=msoFalse, WithWindow=msoFalse)
    $pres = $app.Presentations.Open($full, -1, 0, 0)
    try {
        $count = $pres.Slides.Count
        for ($i = 1; $i -le $count; $i++) {
            $target = Join-Path $outFull ('slide{0:D2}.png' -f $i)
            $pres.Slides.Item($i).Export($target, 'PNG', $Width, $Height)
        }
    }
    finally {
        $pres.Saved = -1   # marca como salvo para nunca perguntar/gravar
        $pres.Close()
    }
}
finally {
    if (-not $alreadyRunning -and $app.Presentations.Count -eq 0) { $app.Quit() }
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
}
$after = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash
if ($before -ne $after) { throw 'ERRO: o arquivo de referência foi alterado durante a renderização.' }
Write-Output ("Renderizados {0} slide(s) em {1} ({2}x{3}); arquivo original intacto (SHA-256 conferido)." -f $count, $OutDir, $Width, $Height)
