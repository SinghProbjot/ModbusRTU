from flask import Flask, render_template
from pymodbus.client.serial import ModbusSerialClient
import threading
import time
import logging

# === CONFIGURAZIONE LOG ===
LOG_FILE = "modbus_polling.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# === CREAZIONE APP FLASK ===
app = Flask(__name__)

# === DATI DEGLI SLAVE ===
silo_data = {
    slave_id: {
        "value": None,
        "percent": None,
        "online": False,  # Stato di connessione
        "last_ok": None   # Timestamp ultimo valore valido
    }
    for slave_id in range(1, 17)
}

# === FUNZIONE DI POLLING IN BACKGROUND ===
def modbus_polling_loop():
    client = ModbusSerialClient(
        port='/dev/ttyUSB0',
        baudrate=9600,
        bytesize=8,
        parity='E',
        stopbits=1,
        timeout=1,
        exclusive=False
    )

    if not client.connect():
        logging.error("❌ Impossibile connettersi a /dev/ttyUSB0")
        return

    logging.info("🔁 Avviato polling Modbus RTU ogni 5 secondi.")

    try:
        while True:
            for slave_id in range(1, 17):
                try:
                    response = client.read_holding_registers(
                        address=10,
                        count=1,
                        device_id=slave_id
                    )

                    if hasattr(response, 'registers'):
                        value = response.registers[0]
                        percent = min(100, max(0, int((value / 28000) * 100)))
                        #percent = int((value / 2000) * 100)
                        #percent = max(0, min(100, percent))


                        # Aggiorna lo stato
                        silo_data[slave_id]["value"] = value
                        silo_data[slave_id]["percent"] = percent
                        silo_data[slave_id]["online"] = True
                        silo_data[slave_id]["last_ok"] = time.strftime("%Y-%m-%d %H:%M:%S")

                        logging.info(f"✅ Slave {slave_id} → Valore: {value}, Percentuale: {percent}%")

                    else:
                        # Risposta ricevuta ma non valida
                        silo_data[slave_id]["online"] = False
                        logging.warning(f"⚠️  Slave {slave_id} ha risposto ma senza dati validi")

                except Exception as e:
                    # Timeout o errore
                    silo_data[slave_id]["online"] = False
                    logging.error(f"❌ Slave {slave_id} → Errore: {e}")

                time.sleep(0.05)  # Pausa tra richieste

            time.sleep(5)  # Pausa tra cicli completi

    finally:
        client.close()
        logging.info("🔌 Connessione Modbus chiusa.")


# === ROUTE PRINCIPALE ===
@app.route("/")
def index():
    return render_template("dashboard.html", silo_data=silo_data)

# === AVVIA IL THREAD DI POLLING ===
polling_thread = threading.Thread(target=modbus_polling_loop, daemon=True)
polling_thread.start()

# === AVVIA FLASK ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
