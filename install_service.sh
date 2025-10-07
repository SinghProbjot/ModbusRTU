#!/bin/bash

set -e

SERVICE_NAME="modbussilo"
USER_NAME="serverubuntu"
APP_DIR="/home/serverubuntu/fromPC/ModbusRTU"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "=================================================================="
echo "🛠️  INSTALLAZIONE SERVIZIO MODBUS SILO CON GUNICORN"
echo "=================================================================="
echo "Directory: $APP_DIR"
echo "Servizio: $SERVICE_NAME"
echo "=================================================================="

# Verifiche
if [ ! -d "$APP_DIR" ]; then
    echo "❌ ERRORE: Directory $APP_DIR non trovata!"
    exit 1
fi

if [ ! -f "$APP_DIR/App.py" ]; then
    echo "❌ ERRORE: app.py non trovato in $APP_DIR!"
    exit 1
fi

# Crea wsgi.py se non esiste
if [ ! -f "$APP_DIR/wsgi.py" ]; then
    echo "📄 Creazione wsgi.py..."
    cat > "$APP_DIR/wsgi.py" << 'EOF'
#!/usr/bin/env python3
"""
WSGI entry point for Modbus Silo Monitoring
Production-ready with Gunicorn
"""

import os
import sys
import time

# Aggiungi la directory del progetto al path
project_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_dir)

# Imposta timezone Europe/Rome
os.environ['TZ'] = 'Europe/Rome'
try:
    time.tzset()
except:
    pass  # Su alcuni sistemi non disponibile

from app import app, data_manager, stop_event

if __name__ == "__main__":
    # Solo per sviluppo
    app.run()
EOF
    echo "✅ wsgi.py creato"
fi

# Installa Gunicorn se non presente
if [ ! -f "$APP_DIR/venv/bin/gunicorn" ]; then
    echo "📦 Installazione Gunicorn..."
    cd "$APP_DIR"
    source venv/bin/activate
    pip install gunicorn
    deactivate
    echo "✅ Gunicorn installato"
fi

# Crea directory LOG se non esiste
mkdir -p "$APP_DIR/LOG"

# Crea file di servizio
echo "📁 Creazione servizio systemd..."
sudo tee $SERVICE_FILE > /dev/null <<EOF
[Unit]
Description=Modbus Silo Monitoring Dashboard
After=network.target
Wants=network.target

[Service]
Type=simple
User=$USER_NAME
Group=$USER_NAME
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/gunicorn \\
    --bind 0.0.0.0:5000 \\
    --workers 2 \\
    --threads 4 \\
    --worker-class gthread \\
    --timeout 60 \\
    --preload \\
    --access-logfile $APP_DIR/LOG/gunicorn_access.log \\
    --error-logfile $APP_DIR/LOG/gunicorn_error.log \\
    --capture-output \\
    --log-level info \\
    wsgi:app
Restart=always
RestartSec=10
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=$APP_DIR/LOG
Environment=PATH=$APP_DIR/venv/bin
Environment=PYTHONPATH=$APP_DIR

[Install]
WantedBy=multi-user.target
EOF

echo "✅ File servizio creato: $SERVICE_FILE"

# Imposta permessi
sudo chmod 644 $SERVICE_FILE
sudo chown root:root $SERVICE_FILE

# Ricarica systemd
echo "🔄 Ricarica systemd..."
sudo systemctl daemon-reload

# Abilita e avvia servizio
echo "⚙️  Abilitazione servizio..."
sudo systemctl enable $SERVICE_NAME

echo "🚀 Avvio servizio..."
sudo systemctl start $SERVICE_NAME

# Verifica
sleep 5
echo "=================================================================="
echo "📊 VERIFICA INSTALLAZIONE"
echo "=================================================================="

if sudo systemctl is-active --quiet $SERVICE_NAME; then
    echo "✅ SERVIZIO ATTIVO E FUNZIONANTE"
    
    # Test health check
    echo "🌐 Test health check..."
    if curl -s http://localhost:5000/health > /dev/null; then
        echo "✅ Health check OK"
    else
        echo "❌ Health check fallito"
    fi
else
    echo "❌ IL SERVIZIO NON È ATTIVO"
fi

echo ""
echo "📋 STATO SERVIZIO:"
sudo systemctl status $SERVICE_NAME --no-pager -l | head -10

echo ""
echo "=================================================================="
echo "🎉 INSTALLAZIONE COMPLETATA!"
echo "=================================================================="
echo ""
echo "📋 COMANDI UTILI:"
echo "   Stato servizio:    sudo systemctl status $SERVICE_NAME"
echo "   Log in tempo reale: sudo journalctl -u $SERVICE_NAME -f"
echo "   Riavvio graceful:  sudo systemctl reload $SERVICE_NAME"
echo "   Ferma servizio:    sudo systemctl stop $SERVICE_NAME"
echo "   Avvia servizio:    sudo systemctl start $SERVICE_NAME"
echo ""
echo "📊 LOG GUNICORN:"
echo "   Access log:        tail -f $APP_DIR/LOG/gunicorn_access.log"
echo "   Error log:         tail -f $APP_DIR/LOG/gunicorn_error.log"
echo ""
echo "🌐 TEST APPLICAZIONE:"
echo "   Health check:      curl http://localhost:5000/health"
echo "   Dashboard:         http://localhost:5000"
echo "   API dati:          curl http://localhost:5000/api/data"
echo "=================================================================="