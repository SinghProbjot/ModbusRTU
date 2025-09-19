
## INSTALLA PRIMA :
# pip install cryptography


# encrypt_password.py
from cryptography.fernet import Fernet

# 1. Genera una chiave e salvala da qualche parte sicura
key = Fernet.generate_key()
with open("secret.key", "wb") as key_file:
    key_file.write(key)

# 2. Usa la chiave per cifrare la password
fernet = Fernet(key)
password = "laTuaPasswordQui"
encrypted = fernet.encrypt(password.encode())

print("Encrypted password:", encrypted.decode())
