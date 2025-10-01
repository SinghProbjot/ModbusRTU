import logging
import requests
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Set, Optional, Any
import os

class TelegramAlertManager:
    """Gestisce gli alert via Telegram"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config.get('alerts', {})
        self.enabled = self.config.get('enabled', False)
        self.logger = logging.getLogger(__name__)
        
        if not self.enabled:
            self.logger.info(" Sistema alert Telegram disabilitato")
            return
        
        # Carica configurazione Telegram
        telegram_config = self.config.get('telegram', {})
        self.bot_token = os.getenv(telegram_config.get('bot_token_env', 'TELEGRAM_BOT_TOKEN'))
        self.chat_id = os.getenv(telegram_config.get('chat_id_env', 'TELEGRAM_CHAT_ID'))
        
        if not self.bot_token or not self.chat_id:
            self.logger.error(" Token Telegram o Chat ID mancanti nelle variabili ambiente")
            self.enabled = False
            return
        
        self.offline_threshold = timedelta(minutes=self.config.get('offline_threshold_minutes', 5))
        self.cooldown_period = timedelta(minutes=telegram_config.get('alert_cooldown_minutes', 15))
        
        # Stato degli alert
        self.last_alerts: Dict[int, datetime] = {}  # slave_id -> ultimo alert
        self.currently_offline: Set[int] = set()
        self.lock = threading.Lock()
        
        # Test connessione iniziale
        if self._test_telegram_connection():
            self.logger.info(" Sistema alert Telegram inizializzato")
            self._send_startup_message()
        else:
            self.enabled = False
    
    def _test_telegram_connection(self) -> bool:
        """Testa la connessione con Telegram"""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                bot_info = response.json()
                if bot_info['ok']:
                    bot_name = bot_info['result']['first_name']
                    self.logger.info(f"🤖 Bot Telegram connesso: {bot_name}")
                    return True
            
            self.logger.error(f" Test Telegram fallito: {response.status_code}")
            return False
            
        except Exception as e:
            self.logger.error(f" Errore test connessione Telegram: {e}")
            return False
    
    def _send_telegram_message(self, message: str, parse_mode: str = 'HTML') -> bool:
        """Invia messaggio Telegram"""
        if not self.enabled:
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True
            }
            
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                return True
            else:
                self.logger.error(f" Errore invio Telegram: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            self.logger.error(f" Errore invio messaggio Telegram: {e}")
            return False
    
    def _send_startup_message(self):
        """Invia messaggio di avvio sistema"""
        timestamp = datetime.now(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d %H:%M:%S")
        
        message = f"""
🚀 <b>SISTEMA MONITORAGGIO SILO AVVIATO</b>

📅 <b>Timestamp:</b> {timestamp}
🛰️ <b>Sistema:</b> Modbus RTU Dashboard
📊 <b>Slaves:</b> 15 dispositivi
⚙️ <b>Stato:</b> Operativo

ℹ️ Sistema di alert attivo
        """.strip()
        
        self._send_telegram_message(message)
    
    def check_and_send_alerts(self, silo_data: Dict[int, Dict[str, Any]]):
        """Controlla stato silo e invia alert se necessario"""
        if not self.enabled:
            return
        
        current_time = datetime.now(ZoneInfo("Europe/Rome"))
        newly_offline = set()
        back_online = set()
        
        with self.lock:
            for slave_id, silo_status in silo_data.items():
                is_online = silo_status.get('online', False)
                last_ok_str = silo_status.get('last_ok')
                
                # Determina se il silo è offline da troppo tempo
                is_offline_too_long = False
                if not is_online and last_ok_str:
                    try:
                        last_ok = datetime.fromisoformat(last_ok_str.replace('Z', '+00:00'))
                        if current_time - last_ok > self.offline_threshold:
                            is_offline_too_long = True
                    except:
                        is_offline_too_long = True
                elif not is_online and not last_ok_str:
                    is_offline_too_long = True
                
                # Rileva cambiamenti di stato
                was_offline = slave_id in self.currently_offline
                
                if is_offline_too_long and not was_offline:
                    # Dispositivo appena andato offline
                    newly_offline.add(slave_id)
                    self.currently_offline.add(slave_id)
                    
                elif is_online and was_offline:
                    # Dispositivo tornato online
                    back_online.add(slave_id)
                    self.currently_offline.discard(slave_id)
                    if slave_id in self.last_alerts:
                        del self.last_alerts[slave_id]
        
        # Invia alert per dispositivi offline
        for slave_id in newly_offline:
            self._send_offline_alert(slave_id, silo_data[slave_id])
        
        # Invia alert per dispositivi tornati online
        for slave_id in back_online:
            self._send_online_alert(slave_id, silo_data[slave_id])
    
    def _send_offline_alert(self, slave_id: int, silo_status: Dict[str, Any]):
        """Invia alert per dispositivo offline"""
        current_time = datetime.now(ZoneInfo("Europe/Rome"))
        
        # Controlla cooldown
        if slave_id in self.last_alerts:
            if current_time - self.last_alerts[slave_id] < self.cooldown_period:
                return  # Ancora in cooldown
        
        timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")
        last_ok = silo_status.get('last_ok', 'Mai')
        error_msg = silo_status.get('last_error', 'Timeout comunicazione')
        
        message = f"""
🔴 <b>ALERT - DISPOSITIVO OFFLINE</b>

🆔 <b>Slave ID:</b> {slave_id}
📅 <b>Timestamp:</b> {timestamp}
⏰ <b>Ultimo OK:</b> {last_ok}
❌ <b>Errore:</b> {error_msg}

⚠️ Verificare connessione dispositivo
        """.strip()
        
        if self._send_telegram_message(message):
            self.last_alerts[slave_id] = current_time
            self.logger.info(f"📱 Alert offline inviato per Slave {slave_id}")
    
    def _send_online_alert(self, slave_id: int, silo_status: Dict[str, Any]):
        """Invia alert per dispositivo tornato online"""
        timestamp = datetime.now(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d %H:%M:%S")
        value = silo_status.get('value', 'N/A')
        percent = silo_status.get('percent', 'N/A')
        
        message = f"""
🟢 <b>RECOVERY - DISPOSITIVO ONLINE</b>

🆔 <b>Slave ID:</b> {slave_id}
📅 <b>Timestamp:</b> {timestamp}
📊 <b>Valore:</b> {value}
📈 <b>Percentuale:</b> {percent}%

✅ Comunicazione ripristinata
        """.strip()
        
        if self._send_telegram_message(message):
            self.logger.info(f"📱 Alert recovery inviato per Slave {slave_id}")
    
    def send_daily_report(self, stats: Dict[str, Any], silo_data: Dict[int, Dict[str, Any]]):
        """Invia report giornaliero"""
        if not self.enabled:
            return
        
        timestamp = datetime.now(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d %H:%M:%S")
        online_count = stats.get('online_slaves', 0)
        total_count = stats.get('total_slaves', 0)
        uptime_hours = stats.get('uptime_seconds', 0) / 3600
        
        # Lista dispositivi offline
        offline_slaves = []
        for slave_id, silo_status in silo_data.items():
            if not silo_status.get('online', False):
                offline_slaves.append(str(slave_id))
        
        offline_list = ', '.join(offline_slaves) if offline_slaves else 'Nessuno'
        
        message = f"""
📊 <b>REPORT GIORNALIERO SILO</b>

📅 <b>Data:</b> {timestamp}
⏱️ <b>Uptime:</b> {uptime_hours:.1f} ore

📈 <b>STATO DISPOSITIVI</b>
• Online: {online_count}/{total_count}
• Offline: {offline_list}

📋 <b>STATISTICHE</b>
• Letture totali: {stats.get('total_reads', 0):,}
• Errori totali: {stats.get('total_errors', 0):,}
• Database: {'✅ Attivo' if stats.get('database_enabled') else '❌ Disattivo'}

🔧 Sistema operativo
        """.strip()
        
        if self._send_telegram_message(message):
            self.logger.info("📱 Report giornaliero inviato")
    
    def send_critical_alert(self, message: str):
        """Invia alert critico"""
        if not self.enabled:
            return
        
        timestamp = datetime.now(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d %H:%M:%S")
        
        critical_msg = f"""
🚨 <b>ALERT CRITICO</b>

📅 <b>Timestamp:</b> {timestamp}
⚠️ <b>Messaggio:</b> {message}

🔧 Intervento richiesto
        """.strip()
        
        if self._send_telegram_message(critical_msg):
            self.logger.warning(f"📱 Alert critico inviato: {message}")
    
    def send_test_message(self):
        """Invia messaggio di test"""
        if not self.enabled:
            return False
        
        timestamp = datetime.now(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d %H:%M:%S")
        
        message = f"""
🧪 <b>TEST SISTEMA ALERT</b>

📅 <b>Timestamp:</b> {timestamp}
🤖 <b>Bot:</b> Funzionante
📱 <b>Chat:</b> Connessa

✅ Sistema alert operativo
        """.strip()
        
        return self._send_telegram_message(message)

# === COME CREARE UN BOT TELEGRAM ===
"""
GUIDA RAPIDA BOT TELEGRAM:

1. Apri Telegram e cerca @BotFather
2. Scrivi /newbot
3. Scegli nome e username per il bot
4. Copia il TOKEN che ricevi

5. Per ottenere CHAT_ID:
   - Aggiungi il bot a un gruppo o scrivici direttamente
   - Vai su: https://api.telegram.org/botTOKEN/getUpdates
   - Sostituisci TOKEN con il tuo token
   - Invia un messaggio al bot
   - Cerca "chat":{"id":-1234567890 nel JSON
   - Copia questo ID (con il - se c'è)

6. Aggiungi al file .env:
   TELEGRAM_BOT_TOKEN=il_tuo_token
   TELEGRAM_CHAT_ID=il_tuo_chat_id
"""