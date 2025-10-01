## Testing Polling on modbus
import logging
from pymodbus.client.serial import ModbusSerialClient
import time
from datetime import datetime

# === LOGGING CONFIG ===
LOG_FILE = "modbus_polling.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# === MODBUS CLIENT CONFIG ===
client = ModbusSerialClient(
    port='/dev/ttyUSB0',
    baudrate=115200,
    bytesize=8,
    parity='E',
    stopbits=1,
    timeout=1
)

# === AVVIO CONNESSIONE ===
if not client.connect():
    logging.error(" Impossibile connettersi a /dev/ttyUSB0. Verifica collegamento e permessi.")
    exit(1)

logging.info(" Inizio polling Modbus RTU da slave 1 a 16.")

try:
    for slave_id in range(1, 16):
        logging.info(f" Polling slave ID {slave_id}...")

        try:
            response = client.read_holding_registers(
                address=10,
                count=1,
                device_id=slave_id
            )

            if hasattr(response, 'registers'):
                value = response.registers[0]
                logging.info(f" Slave {slave_id} → Registro 10 = {value}")
            else:
                logging.warning(f"  Slave {slave_id} ha risposto ma senza registri.")

        except Exception as e:
            logging.error(f" Slave {slave_id} → Errore o timeout: {e}")

        time.sleep(0.1)  # evita di saturare il bus

finally:
    client.close()
    logging.info("🔌 Connessione Modbus chiusa.")
