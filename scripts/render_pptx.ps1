<#
F07 — Renderiza LOCALMENTE um PPTX EXPORTADO (dados sintéticos) para PNG com o PowerPoint instalado (COM) e registra
diagnósticos estruturais do próprio PowerPoint: abertura sem reparo, fontes incorporadas reconhecidas e nº de linhas de
cada caixa de texto/célula (para comparar as quebras com o HTML).

- Arquivo aberto SOMENTE LEITURA, sem janela; nada é salvo. Se o PowerPoint já estava aberto, ele NÃO é encerrado.
- Saída deve ficar fora do Git (output/, private/ ou fora do repositório). Não usar com apresentações reais fora da
  máquina local; nada é enviado a serviços externos.

Uso:  powershell -ExecutionPolicy Bypass -File scripts/render_pptx.ps1 -Pptx output\export-fidelity\deck.pptx -OutDir output\export-fidelity\pptx
#>
param(
    [Parameter(Mandatory = $true)][string]$Pptx,
    [Parameter(Mandatory = $true)][string]$OutDir,
    [int]$Width = 1920,
    [int]$Height = 1080,
    # Opcional: pasta com .ttf (fontes OFL do tema, geradas por scripts/export_fonts.py) registradas SÓ nesta sessão
    # durante a renderização (AddFontResource) e removidas no fim — o PowerPoint local não aplica fontes incorporadas.
    [string]$FontsDir = ''
)
$ErrorActionPreference = 'Stop'
$sessionFonts = @()
if ($FontsDir) {
    Add-Type -Namespace AfrikaF07 -Name Gdi -MemberDefinition '[DllImport("gdi32.dll", CharSet=CharSet.Unicode)] public static extern int AddFontResourceW(string f); [DllImport("gdi32.dll", CharSet=CharSet.Unicode)] public static extern bool RemoveFontResourceW(string f);'
    foreach ($f in Get-ChildItem -LiteralPath $FontsDir -Filter '*.ttf') { if ([AfrikaF07.Gdi]::AddFontResourceW($f.FullName) -gt 0) { $sessionFonts += $f.FullName } }
}
$full = (Resolve-Path -LiteralPath $Pptx).Path
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
$alreadyRunning = @(Get-Process -Name POWERPNT -ErrorAction SilentlyContinue).Count -gt 0
$app = New-Object -ComObject PowerPoint.Application
$report = [ordered]@{ file = (Split-Path $full -Leaf); opened = $false; slides = 0; fonts = @(); text = @() }
try {
    # Open(FileName, ReadOnly=msoTrue, Untitled=msoFalse, WithWindow=msoFalse)
    $pres = $app.Presentations.Open($full, -1, 0, 0)
    $report.opened = $true
    try {
        $report.slides = $pres.Slides.Count
        $report.slide_size = @($pres.PageSetup.SlideWidth, $pres.PageSetup.SlideHeight)
        for ($f = 1; $f -le $pres.Fonts.Count; $f++) {
            $font = $pres.Fonts.Item($f)
            $report.fonts += [ordered]@{ name = $font.Name; embedded = [bool]$font.Embedded; embeddable = [bool]$font.Embeddable }
        }
        for ($i = 1; $i -le $pres.Slides.Count; $i++) {
            $slide = $pres.Slides.Item($i)
            $slide.Export((Join-Path $outFull ('slide{0:D2}.png' -f $i)), 'PNG', $Width, $Height)
            foreach ($shape in $slide.Shapes) {
                if ($shape.HasTextFrame -and $shape.TextFrame.HasText) {
                    $report.text += [ordered]@{ slide = $i; key = $shape.Name; lines = $shape.TextFrame.TextRange.Lines(1, 10000).Count }
                }
                elseif ($shape.HasTable) {
                    $t = $shape.Table
                    for ($r = 1; $r -le $t.Rows.Count; $r++) {
                        for ($c = 1; $c -le $t.Columns.Count; $c++) {
                            $tf = $t.Cell($r, $c).Shape.TextFrame
                            if ($tf.HasText) { $report.text += [ordered]@{ slide = $i; key = "$($shape.Name)[$r,$c]"; lines = $tf.TextRange.Lines(1, 10000).Count } }
                        }
                    }
                }
            }
        }
    }
    finally { $pres.Close() }
}
finally {
    if (-not $alreadyRunning) { $app.Quit() }
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null
    foreach ($f in $sessionFonts) { [void][AfrikaF07.Gdi]::RemoveFontResourceW($f) }  # nada fica instalado
}
$report.session_fonts = $sessionFonts.Count
$after = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash
if ($before -ne $after) { throw 'O arquivo mudou durante a renderização (não deveria).' }
$report | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $outFull 'powerpoint.json')
"slides: $($report.slides); fontes: $(($report.fonts | ForEach-Object { "$($_.name)=$($_.embedded)" }) -join ', ')"
