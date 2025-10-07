from flask import Flask, render_template, jsonify, request
from pymodbus.client.serial import ModbusSerialClient
import threading
import time
import logging
from logging.handlers import RotatingFileHandler
from threading import Lock, Event
import os
import gc
import signal
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import deque
from dataclasses import dataclass, asdict
from typing import Dict, Optional, List, Any

# Carica variabili ambiente
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print(" python-dotenv non installato, usando variabili di sistema")

# Import moduli personalizzati
from database_manager import DatabaseManager, ConfigManager
from telegram_alerts import TelegramAlertManager

# === CARICAMENTO CONFIGURAZIONE ===
try:
    config = ConfigManager.load_config('config.json')
except Exception as e:
    print(f" Errore caricamento configurazione: {e}")
    sys.exit(1)

# === BANNER DI AVVIO ===
print(f"""
==============================================================================================
MODBUS RTU SILO MONITORING DASHBOARD
==============================================================================================
Author      : Probjot Singh
Version     : 3.1.0
Description : Flask app that polls Modbus RTU slave devices and serves a live dashboard via web interface.
Start Time  : {datetime.now(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d %H:%M:%S")}
Port        : {config['modbus']['serial_port']} @ {config['modbus']['baudrate']} baud
Polling     : Every {config['polling']['interval_seconds']}s
Web UI      : http://localhost:{config['flask']['port']}
Database    : {' Enabled' if config.get('database', {}).get('enabled') else ' Disabled'}
Telegram    : {' Enabled' if config.get('alerts', {}).get('enabled') else ' Disabled'}
==============================================================================================
""")

# === CONFIGURAZIONE LOGGING ===
def setup_logging():
    """Configura il sistema di logging"""
    log_config = config.get('logging', {})
    os.makedirs(log_config.get('log_dir', 'LOG'), exist_ok=True)
    log_file = os.path.join(log_config.get('log_dir', 'LOG'), log_config.get('log_file', 'modbus_polling.log'))
    
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_config.get('level', 'INFO')))
    
    # Rimuovi handler esistenti
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # File log rotante
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=log_config.get('max_bytes', 5 * 1024 * 1024),
        backupCount=log_config.get('backup_count', 5)
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
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
    
    return logger

logger = setup_logging()

# === STRUTTURE DATI ===
@dataclass
class SiloStatus:
    """Struttura dati per un singolo silo"""
    value: Optional[int] = None
    percent: Optional[int] = None
    online: bool = False
    last_ok: Optional[str] = None
    last_error: Optional[str] = None
    error_count: int = 0
    total_reads: int = 0
    
    @property
    def success_rate(self) -> float:
        """Percentuale di successo delle letture"""
        if self.total_reads == 0:
            return 0.0
        return ((self.total_reads - self.error_count) / self.total_reads) * 100

class SiloDataManager:
    """Gestisce i dati dei silo con storico e database"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.slaves = config['polling'].get('slaves', list(range(1, 16)))
        self.silo_data: Dict[int, SiloStatus] = {
            slave_id: SiloStatus() for slave_id in self.slaves
        }
        self.history: Dict[int, deque] = {
            slave_id: deque(maxlen=config.get('history_max_points', 100))
            for slave_id in self.slaves
        }
        self.lock = Lock()
        self.stats = {
            'total_polls': 0,
            'successful_polls': 0,
            'start_time': datetime.now(ZoneInfo("Europe/Rome")).isoformat(),
            'last_poll': None
        }
        
        # Inizializza database manager
        self.db_manager = DatabaseManager(config) if config.get('database', {}).get('enabled') else None
        
        # Inizializza alert manager
        self.alert_manager = TelegramAlertManager(config)
    
    def update_slave(self, slave_id: int, value: Optional[int], error: Optional[str] = None):
        """Aggiorna i dati di un singolo slave"""
        with self.lock:
            silo = self.silo_data[slave_id]
            silo.total_reads += 1
            
            validation = self.config['validation']
            min_val = validation['min_value']
            max_val = validation['max_value']
            
            if error:
                silo.online = False
                silo.last_error = error
                silo.error_count += 1
                logger.warning(f"Slave {slave_id} errore: {error}")
            else:
                if min_val <= value <= max_val:
                    silo.value = value
                    silo.percent = int((value / max_val) * 100)
                    silo.online = True
                    silo.last_ok = datetime.now(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d %H:%M:%S")
                    silo.last_error = None
                    
                    # Aggiungi al storico
                    self.history[slave_id].append({
                        'timestamp': time.time(),
                        'value': value,
                        'percent': silo.percent
                    })
                    
                    logger.info(f"Slave {slave_id} → Valore: {value}, Percentuale: {silo.percent}%")
                else:
                    silo.online = False
                    silo.last_error = f"Valore fuori range: {value} (range: {min_val}-{max_val})"
                    silo.error_count += 1
                    logger.warning(f"Slave {slave_id} valore fuori range: {value}")
            
            # Scrivi nel database se abilitato
            if self.db_manager:
                self.db_manager.queue_data(slave_id, asdict(silo))
    
    def get_current_data(self) -> Dict[int, Dict[str, Any]]:
        """Restituisce i dati attuali in formato serializzabile"""
        with self.lock:
            return {
                slave_id: asdict(silo)
                for slave_id, silo in self.silo_data.items()
            }
    
    def get_history(self, slave_id: int, points: int = None) -> List[Dict]:
        """Restituisce lo storico di un slave"""
        with self.lock:
            history = list(self.history[slave_id])
            if points:
                history = history[-points:]
            return history
    
    def get_stats(self) -> Dict[str, Any]:
        """Restituisce statistiche globali"""
        with self.lock:
            online_count = sum(1 for silo in self.silo_data.values() if silo.online)
            total_errors = sum(silo.error_count for silo in self.silo_data.values())
            total_reads = sum(silo.total_reads for silo in self.silo_data.values())
            
            return {
                **self.stats,
                'online_slaves': online_count,
                'total_slaves': len(self.silo_data),
                'total_errors': total_errors,
                'total_reads': total_reads,
                'uptime_seconds': (datetime.now(ZoneInfo("Europe/Rome")) - 
                                 datetime.fromisoformat(self.stats['start_time'])).total_seconds(),
                'database_enabled': self.db_manager is not None,
                'alerts_enabled': self.alert_manager.enabled
            }
    
    def close(self):
        """Chiude connessioni e thread"""
        if self.db_manager:
            self.db_manager.close()

# === ISTANZE GLOBALI ===
data_manager = SiloDataManager(config)
app = Flask(__name__)
stop_event = Event()

# === CLASSE MODBUS POLLER ===
class ModbusPoller:
    """Gestisce il polling Modbus con reconnessione automatica"""
    
    def __init__(self, config: Dict[str, Any], data_manager: SiloDataManager):
        self.config = config
        self.data_manager = data_manager
        self.client = None
        self.is_connected = False
        self.client_lock = Lock()
        self.last_connection_attempt = 0
        self.connection_timeout = 2  # Riduci il timeout tra i tentativi

    def ensure_connection(self) -> bool:
        """Garantisce che la connessione sia attiva"""
        with self.client_lock:
            current_time = time.time()
            
            # Controlla se già connesso e funzionante
            if self.is_connected and self.client and self.client.is_socket_open():
                return True
            
            # Rate limiting solo per errori consecutivi
            time_since_last_attempt = current_time - self.last_connection_attempt
            if time_since_last_attempt < self.connection_timeout:
                logger.debug(f" Rate limiting connessione, riprova tra {self.connection_timeout - time_since_last_attempt:.1f}s")
                return False
                
            self.last_connection_attempt = current_time
            
            try:
                # Chiudi connessione esistente se presente
                if self.client:
                    try:
                        self.client.close()
                    except:
                        pass
                
                # Crea nuova connessione
                modbus_config = self.config['modbus']
                logger.info(f"🔌 Tentativo connessione a {modbus_config['serial_port']}...")
                
                self.client = ModbusSerialClient(
                    port=modbus_config['serial_port'],
                    baudrate=modbus_config['baudrate'],
                    bytesize=modbus_config['bytesize'],
                    parity=modbus_config['parity'],
                    stopbits=modbus_config['stopbits'],
                    timeout=modbus_config['timeout']
                )
                
                if self.client.connect():
                    self.is_connected = True
                    logger.info(f" Connesso a {modbus_config['serial_port']}")
                    return True
                else:
                    self.is_connected = False
                    logger.error(f" Connessione fallita a {modbus_config['serial_port']}")
                    return False
                    
            except Exception as e:
                self.is_connected = False
                logger.error(f" Errore connessione Modbus: {e}")
                return False

    def read_slave(self, slave_id: int) -> tuple[Optional[int], Optional[str]]:
        """Legge un singolo slave con gestione semplificata"""
        max_retries = self.config['polling'].get('max_retries', 3)
        
        # DEBUG: Log dell'inizio lettura
        logger.debug(f" Iniziando lettura slave {slave_id}")
        
        for attempt in range(max_retries):
            try:
                # Prova a riconnetterti se necessario (solo al primo tentativo)
                if attempt == 0 and not self.ensure_connection():
                    # Se non riesce a connettersi, aspetta un po' e riprova
                    time.sleep(0.5)
                    if not self.ensure_connection():
                        return None, "Connessione non disponibile"
                
                with self.client_lock:
                    if not self.is_connected or not self.client:
                        return None, "Connessione persa durante la lettura"
                    
                    # Leggi i registri
                    response = self.client.read_holding_registers(
                        address=10,
                        count=1,
                        device_id=slave_id
                    )
                
                # Controlla se è una risposta di errore
                if hasattr(response, 'isError') and response.isError():
                    error_msg = f"Errore Modbus: {response}"
                    logger.warning(f" Slave {slave_id} - {error_msg} (tentativo {attempt+1}/{max_retries})")
                    
                    if attempt == max_retries - 1:
                        # All'ultimo tentativo, marca come disconnesso
                        with self.client_lock:
                            self.is_connected = False
                        return None, error_msg
                    continue
                
                # Controlla se la risposta è valida
                if hasattr(response, 'registers') and response.registers:
                    value = response.registers[0]
                    logger.info(f" Slave {slave_id} - Valore letto: {value}")
                    return value, None
                else:
                    error_msg = f"Risposta vuota o non valida (tentativo {attempt+1}/{max_retries})"
                    logger.warning(f" Slave {slave_id} - {error_msg}")
                    
            except Exception as e:
                error_msg = f"Eccezione durante lettura: {str(e)} (tentativo {attempt+1}/{max_retries})"
                logger.warning(f" Slave {slave_id} - {error_msg}")
                
                # Per errori di I/O, marca come disconnesso
                if any(keyword in str(e).lower() for keyword in ['input/output', 'lock', 'timeout', 'serial']):
                    with self.client_lock:
                        self.is_connected = False
            
            # Breve pausa prima del prossimo tentativo
            if attempt < max_retries - 1:
                time.sleep(0.2)
        
        return None, f"Tentativi esauriti dopo {max_retries} tentativi"

    def polling_loop(self):
        """Loop principale di polling"""
        polling_config = self.config['polling']
        poll_interval = polling_config.get('interval_seconds', 30)
        slave_delay = polling_config.get('slave_delay_seconds', 0.1)  # Aumenta il delay
        slaves = polling_config.get('slaves', list(range(1, 16)))
        
        logger.info(f" Avviato polling Modbus ogni {poll_interval} secondi per {len(slaves)} slave")
        
        # Connessione iniziale
        logger.info("🔌 Tentativo connessione iniziale...")
        if self.ensure_connection():
            logger.info(" Connessione iniziale riuscita!")
        else:
            logger.warning(" Connessione iniziale fallita, riproverà nel ciclo...")
        
        try:
            while not stop_event.is_set():
                cycle_start = time.time()
                successful_reads = 0
                
                # Aggiorna stats
                self.data_manager.stats['total_polls'] += 1
                self.data_manager.stats['last_poll'] = datetime.now(ZoneInfo("Europe/Rome")).isoformat()
                
                # Polling di tutti gli slave
                for slave_id in slaves:
                    if stop_event.is_set():
                        break
                    
                    logger.debug(f" Lettura slave {slave_id}...")
                    value, error = self.read_slave(slave_id)
                    self.data_manager.update_slave(slave_id, value, error)
                    
                    if not error:
                        successful_reads += 1
                    
                    # Delay tra un slave e l'altro
                    time.sleep(slave_delay)
                
                # Aggiorna statistiche
                self.data_manager.stats['successful_polls'] += successful_reads
                
                logger.info(f" Ciclo completato: {successful_reads}/{len(slaves)} slave letti con successo")
                
                # Controlla alert Telegram
                if self.data_manager.alert_manager.enabled:
                    current_data = self.data_manager.get_current_data()
                    self.data_manager.alert_manager.check_and_send_alerts(current_data)
                
                # Calcola tempo per il prossimo ciclo
                cycle_time = time.time() - cycle_start
                sleep_time = max(1, poll_interval - cycle_time)  # Minimo 1 secondo
                
                logger.debug(f" Ciclo durato {cycle_time:.2f}s, pausa per {sleep_time:.2f}s")
                
                # Attesa per il prossimo ciclo
                stop_event.wait(sleep_time)
                
        except Exception as e:
            logger.error(f" Errore nel loop di polling: {e}")
            # Invia alert critico
            if self.data_manager.alert_manager.enabled:
                self.data_manager.alert_manager.send_critical_alert(f"Loop polling crashato: {str(e)}")
        finally:
            self.disconnect()

    def disconnect(self):
        """Chiude connessione Modbus"""
        with self.client_lock:
            if self.client:
                try:
                    self.client.close()
                except:
                    pass
            self.is_connected = False
            logger.info("🔌 Connessione Modbus chiusa")

# === ROUTES FLASK ===
@app.route("/")
def index():
    """Dashboard principale"""
    current_data = data_manager.get_current_data()
    stats = data_manager.get_stats()
    return render_template("dashboard.html", silo_data=current_data, stats=stats)

@app.route("/api/data")
def api_data():
    """API per dati in tempo reale"""
    return jsonify(data_manager.get_current_data())

@app.route("/api/stats")
def api_stats():
    """API per statistiche sistema"""
    return jsonify(data_manager.get_stats())

@app.route("/api/history/<int:slave_id>")
def api_history(slave_id):
    """API per storico dati di un slave"""
    if slave_id not in data_manager.slaves:
        return jsonify({"error": "Slave ID non valido"}), 400
    
    points = request.args.get('points', type=int, default=100)
    hours = request.args.get('hours', type=int, default=24)
    
    try:
        # Se il database è abilitato, leggi da lì
        if data_manager.db_manager:
            history_data = data_manager.db_manager.get_recent_data(slave_id, hours, points)
        else:
            # Fallback allo storico in memoria
            history_data = data_manager.get_history(slave_id, points)
        
        return jsonify(history_data)
        
    except Exception as e:
        logger.error(f" Errore API history per slave {slave_id}: {e}")
        return jsonify({"error": "Errore interno del server"}), 500

@app.route("/api/database")
def api_database():
    """API per dati dal database"""
    if not data_manager.db_manager:
        return jsonify({"error": "Database disabilitato"}), 400
    slave_id = request.args.get('slave_id', type=int)
    data = data_manager.db_manager.get_recent_data(slave_id)
    return jsonify(data)

@app.route("/api/test_telegram")
def api_test_telegram():
    """API per testare alert Telegram"""
    if not data_manager.alert_manager.enabled:
        return jsonify({"error": "Alert Telegram disabilitati"}), 400
    success = data_manager.alert_manager.send_test_message()
    return jsonify({"success": success, "message": "Test alert inviato" if success else "Errore invio test"})

@app.route("/health")
def health():
    """Health check endpoint"""
    stats = data_manager.get_stats()
    return jsonify({
        "status": "healthy",
        "online_slaves": stats['online_slaves'],
        "total_slaves": stats['total_slaves'],
        "uptime": stats['uptime_seconds'],
        "database": stats['database_enabled'],
        "alerts": stats['alerts_enabled']
    })

# === GESTIONE SEGNALI ===
def signal_handler(signum, frame):
    """Gestisce la terminazione graceful"""
    logger.info(" Ricevuto segnale di terminazione...")
    stop_event.set()
    
    # Invia messaggio di shutdown
    if data_manager.alert_manager.enabled:
        data_manager.alert_manager.send_critical_alert("Sistema in shutdown")
    
    data_manager.close()
    time.sleep(1)
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# === FUNZIONE MAIN ===
def main():
    """Funzione principale di avvio"""
    try:
        # Avvia thread di polling
        poller = ModbusPoller(config, data_manager)
        polling_thread = threading.Thread(target=poller.polling_loop, daemon=True)
        polling_thread.start()
        
        logger.info(f" Dashboard disponibile su http://localhost:{config['flask']['port']}")
        
        # Avvia Flask
        flask_config = config.get('flask', {})
        app.run(
            host=flask_config.get('host', '0.0.0.0'),
            port=flask_config.get('port', 5000),
            debug=flask_config.get('debug', False),
            threaded=True,
            use_reloader=False  # Evita problemi con threading
        )
        
    except Exception as e:
        logger.error(f" Errore avvio applicazione: {e}")
        sys.exit(1)

# === AVVIO APPLICAZIONE ===
if __name__ == "__main__":
    main()