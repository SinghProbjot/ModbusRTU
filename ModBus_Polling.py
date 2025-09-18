## Testing Polling on modbus

from pymodbus.client.serial import ModbusSerialClient
import time

client = ModbusSerialClient(
    port='/dev/ttyUSB0',
    baudrate=9600,
    bytesize=8,
    parity='E',
    stopbits=1,
    timeout=1,
    # questo aiuta su alcuni sistemi
    exclusive=False
)

if not client.connect():
    print("❌ Connessione Modbus fallita")
    exit(1)

try:
    for slave_id in range(1, 16):
        print(f"📡 Leggo da slave {slave_id}...")
        response = client.read_holding_registers(10, count=1, device_id=slave_id)

        if response.is_error:
            print(f"⚠️ Errore da slave {slave_id}")
        else:
            print(f"✅ Slave {slave_id} → Valore: {response.registers[0]}")

        time.sleep(0.2)  # pausa tra un polling e l’altro

finally:
    client.close()
    print("🔌 Connessione chiusa correttamente")
