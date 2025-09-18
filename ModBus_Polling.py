## Testing Polling on modbus


from pymodbus.client import ModbusSerialClient
import time

client = ModbusSerialClient(
    port='COM5',  
    baudrate=115200,
    bytesize=8,
    parity='E',
    stopbits=1,
    timeout=1
)

if not client.connect():
    print("Errore: impossibile connettersi alla porta COM")
    exit(1)

for slave_id in range(1, 16):
    print(f"📡 Polling slave {slave_id}...")

    response = client.read_holding_registers(9, 1, unit=slave_id)

    if response.isError():
        print(f"❌ Errore lettura slave {slave_id}")
    else:
        print(f"✅ Slave {slave_id} → Registro 10: {response.registers[0]}")
    
    time.sleep(0.2)

client.close()
