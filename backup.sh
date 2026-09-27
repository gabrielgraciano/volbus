#!/bin/bash
# Backup noturno para o Google Drive.
#   - move para o Drive o bronze com mais de 48h (libera disco no droplet)
#   - copia o resto (auditoria, CET, dias recentes)
# Cada passo roda independente: se um falhar, os outros seguem.

D=/home/gabriel/olhovivo/data
LOG=/home/gabriel/olhovivo/rclone.log
RC=/usr/bin/rclone

echo "=== $(date -u +%FT%TZ) inicio" >> "$LOG"

for sub in bronze_posicao bronze_raw; do
  if [ -d "$D/$sub" ]; then
    $RC move "$D/$sub" "gdrive:olhovivo-bronze/$sub" \
      --min-age 48h --delete-empty-src-dirs --log-file "$LOG" \
      || echo "!!! falha no move de $sub" >> "$LOG"
  fi
done

$RC copy "$D" gdrive:olhovivo-bronze --exclude 'estado_dedupe.json' --log-file "$LOG" \
  || echo "!!! falha no copy" >> "$LOG"

echo "=== $(date -u +%FT%TZ) fim" >> "$LOG"
