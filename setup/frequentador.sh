#!/usr/bin/env bash
# Cria na área de trabalho o atalho "SAN - Pesquisa" (abre o site da pesquisa de satisfação no
# navegador padrão, para o frequentador responder sozinho) e já abre o site. Uso: ./setup/frequentador.sh [--sem-abrir]
URL="https://pesquisas.navedoconhecimento.rio/"
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"

DESKTOP="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
if [ -z "$DESKTOP" ] || [ ! -d "$DESKTOP" ]; then
    for nome in "Área de trabalho" "Desktop"; do
        [ -d "$HOME/$nome" ] && DESKTOP="$HOME/$nome" && break
    done
fi
[ -n "$DESKTOP" ] || DESKTOP="$HOME/Desktop"
mkdir -p "$DESKTOP"

ATALHO="$DESKTOP/san-pesquisa.desktop"
cat > "$ATALHO" <<EOF
[Desktop Entry]
Type=Application
Name=SAN - Pesquisa
Comment=Responder a pesquisa de satisfação da Nave do Conhecimento
Exec=xdg-open $URL
Icon=$RAIZ/web/nave.png
Terminal=false
Categories=Education;
EOF
chmod +x "$ATALHO"
command -v gio >/dev/null 2>&1 && gio set "$ATALHO" metadata::trusted true 2>/dev/null
echo "Atalho criado: $ATALHO"

[ "$1" = "--sem-abrir" ] && exit 0
xdg-open "$URL" >/dev/null 2>&1 &
exit 0
