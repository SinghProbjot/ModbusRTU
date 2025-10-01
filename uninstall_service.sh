#!/bin/bash

SERVICE_NAME="modbussilo"

echo "  Disinstallazione servizio Modbus Silo..."

# Ferma il servizio
sudo systemctl stop $SERVICE_NAME 2>/dev/null || true

# Disabilita il servizio
sudo systemctl disable $SERVICE_NAME 2>/dev/null || true

# Rimuovi il file di servizio
sudo rm -f /etc/systemd/system/$SERVICE_NAME.service

# Ricarica systemd
sudo systemctl daemon-reload

echo " Servizio $SERVICE_NAME disinstallato"
echo " Nota: I file dell'applicazione in /home/serverubuntu/ModbusRTU non sono stati rimossi"