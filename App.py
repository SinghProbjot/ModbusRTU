from flask import Flask, render_template, jsonify
from pymodbus.client import ModbusSerialClient
import threading
import time

app = Flask(__name__)

# Dati letti da Modbus
silos_data = [{'percent': 0, 'quantity': 0} for _ in range(15)]

# Modbus client
client = ModbusSerialClient(
    method='rtu',
    port='COM5',  # ⚠️ Cambia con la tua COM
    baudrate=9600,
    bytesize=8,
    parity='N',
    stopbits=1,
    timeout=1
)

def poll_modbus():
    while True:
        if not client.connect():
            print("❌ Connessione Modbus fallita")
            time.sleep(5)
            continue

        for i in range(15):  # Slave 1 → 15
            slave_id = i + 1
            response = client.read_holding_registers(10, 1, unit=slave_id)
            if not response.isError():
                value = response.registers[0]  # es: quantità in kg
                max_capacity = 1000  # capacità massima del silo
                percent = min(100, int((value / max_capacity) * 100))
                silos_data[i]['quantity'] = value
                silos_data[i]['percent'] = percent
            else:
                silos_data[i]['quantity'] = 0
                silos_data[i]['percent'] = 0

        client.close()
        time.sleep(5)  # intervallo polling

# API per la dashboard
@app.route("/api/data")
def api_data():
    return jsonify(silos_data)

# Dashboard principale
@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    threading.Thread(target=poll_modbus, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=True)
