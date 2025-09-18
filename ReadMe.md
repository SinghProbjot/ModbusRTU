# Modbus Polling + Dashboard

Uno script Python per interrogare 15 dispositivi Modbus RTU e (opzionalmente) visualizzare i dati in una dashboard web.

## Requisiti

- Python 3
- pymodbus
- flask (opzionale per dashboard)

## Installazione

```bash
git clone https://github.com/tuo-utente/modbus-project.git
cd modbus-project
pip install -r requirements.txt
python3 modbus_polling.py
