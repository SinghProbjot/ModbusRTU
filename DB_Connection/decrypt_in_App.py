import json
from cryptography.fernet import Fernet

# Carica config
with open("config.json", "r") as f:
    config = json.load(f)

# Carica chiave segreta
with open("secret.key", "rb") as f:
    key = f.read()

# Decifra password
fernet = Fernet(key)
decrypted_password = fernet.decrypt(config["db_password_encrypted"].encode()).decode()

# Ora puoi usarla per connetterti al database
print("Connecting to DB at", config["db_host"])
