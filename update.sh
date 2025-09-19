#!/bin/bash

echo "🔄 Reset del repository alle condizioni del remoto..."

# Reset forzato dei file modificati
git reset --hard HEAD
echo "Elimino le modifiche locali..."
# Rimuove file e cartelle non tracciate
git clean -fd
echo "Rimuovo file e cartelle non tracciate..."
# Pull degli ultimi aggiornamenti dal repository remoto
git pull

echo "✅ Codice aggiornato!"
