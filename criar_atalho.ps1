# Cria o atalho "Pesquisas Nave" na área de trabalho apontando para o executável gerado.
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe = Join-Path $raiz "dist\PesquisasNave\PesquisasNave.exe"
if (-not (Test-Path $exe)) {
    Write-Error "Executável não encontrado: $exe (rode construir_windows.bat primeiro)"
    exit 1
}
$destino = Join-Path ([Environment]::GetFolderPath("Desktop")) "Pesquisas Nave.lnk"
$shell = New-Object -ComObject WScript.Shell
$atalho = $shell.CreateShortcut($destino)
$atalho.TargetPath = $exe
$atalho.WorkingDirectory = Split-Path -Parent $exe
$atalho.IconLocation = "$exe,0"
$atalho.Description = "Automação das pesquisas de satisfação da Nave do Conhecimento"
$atalho.Save()
Write-Host "Atalho criado em: $destino"
