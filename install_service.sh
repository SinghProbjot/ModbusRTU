#!/bin/bash

# Script di installazione automatica per Modbus Silo Service
# Configurato per: utente=serverubuntu, cartella=ModbusRTU

set -e  # Exit on error

# Configurazioni
SERVICE_NAME="modbussilo"
USER_NAME="serverubuntu"
APP_DIR="/home/$USER_NAME/ModbusRTU"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
VENV_PATH="$APP_DIR/venv"

echo "=================================================================="
echo "  INSTALLAZIONE AUTOMATICA MODBUS SILO SERVICE"
echo "=================================================================="
echo "Utente: $USER_NAME"
echo "Directory: $APP_DIR"
echo "Servizio: $SERVICE_NAME"
echo "=================================================================="

# Verifica che l'utente esista
if ! id "$USER_NAME" &>/dev/null; then
    echo " ERRORE: Utente $USER_NAME non trovato!"
    exit 1
fi

# Verifica che la directory esista
if [ ! -d "$APP_DIR" ]; then
    echo " ERRORE: Directory $APP_DIR non trovata!"
    echo "   Assicurati che il progetto sia in $APP_DIR"
    exit 1
fi

# Verifica che app.py esista
if [ ! -f "$APP_DIR/App.py" ]; then
    echo " ERRORE: App.py non trovato in $APP_DIR!"
    exit 1
fi

# Verifica che il virtual environment esista
if [ ! -f "$VENV_PATH/bin/activate" ]; then
    echo " ERRORE: Virtual environment non trovato in $VENV_PATH!"
    echo "   Crea il virtual environment con: python3 -m venv venv"
    exit 1
fi

# Verifica che .env esista
if [ ! -f "$APP_DIR/.env" ]; then
    echo "  AVVISO: File .env non trovato, assicurati di crearlo"
fi

echo " Configurazione verificata con successo"

# Crea il file di servizio systemd
echo " Creazione file servizio systemd..."
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

# Carica le variabili ambiente dal file .env
EnvironmentFile=$APP_DIR/.env

# Script che attiva il venv e lancia l'app
ExecStart=/bin/bash -c 'source $VENV_PATH/bin/activate && exec python3 $APP_DIR/App.py'

# Politica di restart
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$SERVICE_NAME

# Sicurezza
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=$APP_DIR/LOG
ReadWritePaths=$APP_DIR

# Ambiente
Environment=PATH=$VENV_PATH/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin
Environment=PYTHONPATH=$APP_DIR

[Install]
WantedBy=multi-user.target
EOF

echo " File servizio creato: $SERVICE_FILE"

# Imposta i permessi corretti
echo " Impostazione permessi..."
sudo chmod 644 $SERVICE_FILE
sudo chown root:root $SERVICE_FILE

# Ricarica systemd
echo " Ricarica configurazione systemd..."
sudo systemctl daemon-reload

# Abilita il servizio
echo "  Abilitazione servizio..."
sudo systemctl enable $SERVICE_NAME

# Avvia il servizio
echo " Avvio servizio..."
sudo systemctl start $SERVICE_NAME

# Aspetta un attimo e verifica lo stato
sleep 3

echo "=================================================================="
echo " VERIFICA INSTALLAZIONE"
echo "=================================================================="

# Verifica lo stato del servizio
if sudo systemctl is-active --quiet $SERVICE_NAME; then
    echo " SERVIZIO ATTIVO E FUNZIONANTE"
else
    echo " IL SERVIZIO NON È ATTIVO"
    echo "   Controlla i log con: sudo journalctl -u $SERVICE_NAME"
fi

# Mostra lo stato
echo ""
echo " STATO SERVIZIO:"
sudo systemctl status $SERVICE_NAME --no-pager -l

echo ""
echo "=================================================================="
echo " INSTALLAZIONE COMPLETATA!"
echo "=================================================================="
echo ""
echo " COMANDI UTILI:"
echo "   Stato servizio:    sudo systemctl status $SERVICE_NAME"
echo "   Ferma servizio:    sudo systemctl stop $SERVICE_NAME"
echo "   Avvia servizio:    sudo systemctl start $SERVICE_NAME"
echo "   Riavvia servizio:  sudo systemctl restart $SERVICE_NAME"
echo "   Log in tempo reale: sudo journalctl -u $SERVICE_NAME -f"
echo "   Ultimi 100 log:    sudo journalctl -u $SERVICE_NAME -n 100"
echo ""
echo " VERIFICHE POST-INSTALLAZIONE:"
echo "   1. Il servizio si avvia al boot: sudo systemctl is-enabled $SERVICE_NAME"
echo "   2. Controlla i log per errori: sudo journalctl -u $SERVICE_NAME --since '1 hour ago'"
echo "   3. Testa il riavvio: sudo systemctl restart $SERVICE_NAME && sleep 5 && sudo systemctl status $SERVICE_NAME"
echo ""