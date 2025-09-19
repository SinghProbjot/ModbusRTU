from flask import Flask, render_template
from pymodbus.client.serial import ModbusSerialClient
import threading
import time
import logging
from logging.handlers import RotatingFileHandler
from threading import Lock
import os
import gc

# === CONFIGURAZIONE CARTELLA LOG ===
LOG_DIR = "LOG"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "modbus_polling.log")

# === CONFIGURAZIONE LOGGER ===
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# File log rotante
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
))
logger.addHandler(file_handler)

# Console log
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S"
))
logger.addHandler(console_handler)

# === CREAZIONE APP FLASK ===
app = Flask(__name__)

# === DATI DEGLI SLAVE ===
silo_data = {
    slave_id: {
        "value": None,
        "percent": None,
        "online": False,
        "last_ok": None
    }
    for slave_id in range(1, 16)
}

# Lock per accesso sicuro ai dati
data_lock = Lock()

# === FUNZIONE DI POLLING ===
def modbus_polling_loop():
    client = ModbusSerialClient(
        port='/dev/ttyUSB0',
        baudrate=115200,
        bytesize=8,
        parity='E',
        stopbits=1,
        timeout=1
    )

    if not client.connect():
        logging.error("❌ Impossibile connettersi a /dev/ttyUSB0")
        return

    logging.info("🔁 Avviato polling Modbus RTU ogni 30 secondi.")

    try:
        while True:
            for slave_id in range(1, 16):
                try:
                    response = client.read_holding_registers(
                        address=10,
                        count=1,
                        device_id=slave_id
                    )

                    if hasattr(response, 'registers'):
                        value = response.registers[0]

                        if 0 <= value <= 28000:
                            percent = int((value / 28000) * 100)

                            with data_lock:
                                silo_data[slave_id]["value"] = value
                                silo_data[slave_id]["percent"] = percent
                                silo_data[slave_id]["online"] = True
                                silo_data[slave_id]["last_ok"] = time.strftime("%Y-%m-%d %H:%M:%S")

                            logging.info(f"✅ Slave {slave_id} → Valore: {value}, Percentuale: {percent}%")
                        else:
                            with data_lock:
                                silo_data[slave_id]["online"] = False
                            logging.warning(f"⚠️  Slave {slave_id} ha restituito un valore fuori range: {value}")
                    else:
                        with data_lock:
                            silo_data[slave_id]["online"] = False
                        logging.warning(f"⚠️  Slave {slave_id} ha risposto ma senza dati validi")

                except Exception as e:
                    with data_lock:
                        silo_data[slave_id]["online"] = False
                    logging.error(f"❌ Slave {slave_id} → Errore: {e}")

                time.sleep(0.05)  # Breve pausa tra le richieste

            # Optional: raccolta garbage
            #gc.collect()
            time.sleep(30)  # Attesa tra un ciclo e l'altro

    finally:
        client.close()
        logging.info("🔌 Connessione Modbus chiusa.")


# === ROUTE PRINCIPALE ===
@app.route("/")
def index():
    with data_lock:
        current_data = dict(silo_data)  # Copia sicura per il rendering
    return render_template("dashboard.html", silo_data=current_data)


# === AVVIO THREAD DI POLLING ===
polling_thread = threading.Thread(target=modbus_polling_loop, daemon=True)
polling_thread.start()

# === AVVIO FLASK ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
