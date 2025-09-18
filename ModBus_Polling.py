## Testing Polling on modbus
from pymodbus.client.serial import ModbusSerialClient
import time

# Configurazione del client
client = ModbusSerialClient(
    port='/dev/ttyUSB0',
    baudrate=115200,
    bytesize=8,
    parity='E',
    stopbits=1,
    timeout=1
)

# Connessione
if not client.connect():
    print("❌ Errore: impossibile connettersi alla porta seriale.")
    exit(1)

print("🔁 Inizio polling Modbus RTU...")

try:
    for slave_id in range(1, 16): 
        print(f"\n📡 Leggo da slave ID {slave_id}...")

        try:
            response = client.read_holding_registers(
                address=10,
                count=1,
                device_id=slave_id
            )


            if hasattr(response, 'registers'):
                value = response.registers[0]
                print(f"✅ Slave {slave_id} → Registro 10: {value}")
            else:
                print(f"⚠️  Slave {slave_id}: risposta ricevuta, ma senza dati leggibili.")

        except Exception as e:
            print(f"❌ Slave {slave_id}: nessuna risposta o errore → {e}")

        time.sleep(0.2)  # pausa minima tra richieste

finally:
    client.close()
    print("\n🔌 Connessione Modbus chiusa.")
