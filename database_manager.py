import logging
import threading
import time
import queue
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import json

# Database connector - SQL Server
# pip install pyodbc

@dataclass
class DatabaseRecord:
    """Struttura record per database"""
    slave_id: int
    timestamp: datetime
    value: Optional[int]
    percent: Optional[int]
    online: bool
    error_message: Optional[str] = None

class DatabaseManager:
    """Gestisce la scrittura dati nel database SQL Server"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config['database']
        self.connection = None
        self.write_queue = queue.Queue(maxsize=1000)
        self.logger = logging.getLogger(__name__)
        self.stop_event = threading.Event()
        
        if self.config.get('enabled', False):
            self._init_database()
            self._start_writer_thread()
    
    def _init_database(self):
        """Inizializza connessione database SQL Server"""
        try:
            self._init_sqlserver()
            self._create_tables()
            self.logger.info(f" Database SQL Server inizializzato correttamente")
            
        except Exception as e:
            self.logger.error(f" Errore inizializzazione database: {e}")
            raise
    
    def _init_sqlserver(self):
        """Inizializza connessione SQL Server"""
        try:
            import pyodbc
            
            # Ottieni credenziali da variabili ambiente
            username_env = self.config.get('username_env', 'SQLSERVER_USERNAME')
            password_env = self.config.get('password_env', 'SQLSERVER_PASSWORD')
            
            username = os.getenv(username_env)
            password = os.getenv(password_env)
            
            if not username:
                raise ValueError(f"Username SQL Server non trovato nella variabile ambiente: {username_env}")
            if not password:
                raise ValueError(f"Password SQL Server non trovata nella variabile ambiente: {password_env}")
            
            # Costruisci connection string
            host = self.config['host']
            port = self.config.get('port', 1433)
            database = self.config['database']
            instance = self.config.get('instance', '')
            driver = self.config.get('driver', 'ODBC Driver 18 for SQL Server')
            
            # Server name con istanza se specificata
            if instance:
                server = f"{host}\\{instance}"
            else:
                server = f"{host},{port}"
            
            connection_string = (
                f"DRIVER={{{driver}}};"
                f"SERVER={server};"
                f"DATABASE={database};"
                f"UID={username};"
                f"PWD={password};"
                f"Encrypt=optional;"
                f"TrustServerCertificate=yes;"
                f"Connection Timeout=10;"
            )
            
            # Test connessione
            self.connection = pyodbc.connect(connection_string)
            self.connection.autocommit = False
            
            self.logger.info(f" Connesso a SQL Server: {server}/{database}")
            
        except ImportError:
            raise ImportError("pyodbc non installato. Esegui: pip install pyodbc")
        except Exception as e:
            self.logger.error(f" Errore connessione SQL Server: {e}")
            raise

    def _map_slave_to_erp_code(self, slave_id: int) -> str:
        """Mappa ID numerico slave a codice ERP"""
        erp_mapping = {
            1: "S01", 2: "S02", 3: "S03", 4: "S04", 5: "S05",
            6: "S06", 7: "S07", 8: "S08", 9: "S09", 10: "S10",
            11: "S11", 12: "S12", 13: "S13", 14: "S14", 15: "S15"
        }
        return erp_mapping.get(slave_id, f"S{slave_id:02d}")
    
    def _create_tables(self):
        """Crea tabelle se non esistono - SOLO VERIFICA"""
        table_name = self.config.get('table_name', 'silo_monitoring')
        
        # Solo verifica che la tabella esista (non la crea)
        check_sql = f"""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='{table_name}' AND xtype='U')
        BEGIN
            RAISERROR('Tabella {table_name} non trovata! Creala manualmente con SSMS.', 16, 1)
        END
        """
        
        try:
            cursor = self.connection.cursor()
            cursor.execute(check_sql)
            cursor.close()
            self.logger.info(f" Tabella {table_name} verificata")
        except Exception as e:
            self.logger.error(f" Tabella non trovata: {e}")
            self.logger.error(" Crea manualmente la tabella con SSMS usando lo schema fornito")
            raise
    
    def _get_connection(self):
        """Ottiene connessione database"""
        if not self.connection or not self._test_connection():
            self.logger.warning(" Connessione persa, riconnessione...")
            self._init_sqlserver()
        return self.connection
    
    def _test_connection(self) -> bool:
        """Testa se la connessione è ancora valida"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return True
        except:
            return False
    
    def _start_writer_thread(self):
        """Avvia thread per scrittura batch"""
        self.writer_thread = threading.Thread(target=self._batch_writer, daemon=True)
        self.writer_thread.start()
        self.logger.info(" Thread scrittura database avviato")
    
    def _batch_writer(self):
        """Thread che scrive dati in batch"""
        records_buffer = []
        write_interval = self.config.get('write_interval_seconds', 60)
        batch_size = self.config.get('batch_size', 50)
        
        while not self.stop_event.is_set():
            try:
                # Accumula record per batch
                timeout_start = time.time()
                while (len(records_buffer) < batch_size and 
                       time.time() - timeout_start < write_interval):
                    
                    try:
                        record = self.write_queue.get(timeout=1.0)
                        records_buffer.append(record)
                        self.write_queue.task_done()
                    except queue.Empty:
                        continue
                
                # Scrivi batch se ci sono record
                if records_buffer:
                    self._write_batch(records_buffer)
                    records_buffer.clear()
                    
            except Exception as e:
                self.logger.error(f" Errore nel writer thread: {e}")
                time.sleep(5)  # Pausa prima di riprovare
    
    def _write_batch(self, records: List[DatabaseRecord]):
        """Scrive un batch di record nel database (sempre INSERT)"""
        if not records:
            return
        
        table_name = self.config.get('table_name', 'silo_monitoring')
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # SQL: INSERT con codici ERP
            insert_sql = f"""
            INSERT INTO {table_name} 
                (Cd_xMGSilo, Qta, ultimo_aggiornamento) 
            VALUES (?, ?, ?)
            """
            
            successful_writes = 0
            for record in records:
                try:
                    # Scrivi SOLO se il silo è online e ha un valore valido
                    if record.online and record.value is not None:
                        # Converti ID numerico in codice ERP
                        erp_code = self._map_slave_to_erp_code(record.slave_id)
                        
                        cursor.execute(insert_sql, (
                            erp_code,           # Cd_xMGSilo (S01, S02, ecc.)
                            record.value,       # Qta  
                            record.timestamp.strftime('%Y-%m-%d %H:%M:%S')  # ultimo_aggiornamento
                        ))
                        successful_writes += 1
                    
                except Exception as e:
                    self.logger.error(f" Errore scrittura record slave {record.slave_id}: {e}")
            
            conn.commit()
            cursor.close()
            
            if successful_writes > 0:
                self.logger.info(f" Inseriti {successful_writes} record nel database (codici ERP)")
            
        except Exception as e:
            self.logger.error(f" Errore scrittura batch database: {e}")
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
    
    def queue_data(self, slave_id: int, silo_status: Dict[str, Any]):
        """Accoda dati per scrittura nel database"""
        if not self.config.get('enabled', False):
            return
        
        try:
            record = DatabaseRecord(
                slave_id=slave_id,
                timestamp=datetime.now(ZoneInfo("Europe/Rome")),
                value=silo_status.get('value'),
                percent=silo_status.get('percent'),
                online=silo_status.get('online', False),
                error_message=silo_status.get('last_error')
            )
            
            self.write_queue.put_nowait(record)
            
        except queue.Full:
            self.logger.warning(" Coda database piena, record perso")
        except Exception as e:
            self.logger.error(f" Errore accodamento dati: {e}")
    
    def get_recent_data(self, slave_id: int = None, hours: int = 24, limit: int = 1000) -> List[Dict]:
        """Recupera dati recenti dal database per grafici"""
        if not self.config.get('enabled', False):
            return []
        
        table_name = self.config.get('table_name', 'silo_monitoring')
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            if slave_id:
                # Converti ID numerico in codice ERP per la query
                erp_code = self._map_slave_to_erp_code(slave_id)
                sql = f"""
                SELECT Cd_xMGSilo, Qta, ultimo_aggiornamento 
                FROM {table_name} 
                WHERE Cd_xMGSilo = ? AND ultimo_aggiornamento >= DATEADD(HOUR, -?, GETDATE())
                ORDER BY ultimo_aggiornamento DESC
                """
                cursor.execute(sql, (erp_code, hours))
            else:
                sql = f"""
                SELECT Cd_xMGSilo, Qta, ultimo_aggiornamento 
                FROM {table_name} 
                WHERE ultimo_aggiornamento >= DATEADD(HOUR, -?, GETDATE())
                ORDER BY ultimo_aggiornamento DESC, Cd_xMGSilo
                """
                cursor.execute(sql, (hours,))
            
            results = cursor.fetchmany(limit)
            cursor.close()
            
            # Converte in lista di dict
            return [
                {
                    'id_silo': row[0],           # Cd_xMGSilo (S01, S02, ecc.)
                    'quantita': row[1],          # Qta
                    'ultimo_aggiornamento': row[2].strftime('%Y-%m-%d %H:%M:%S') if row[2] else None
                }
                for row in results
            ]
            
        except Exception as e:
            self.logger.error(f" Errore lettura dati database: {e}")
            return []
    
    def close(self):
        """Chiude connessioni database"""
        self.logger.info(" Chiusura database manager...")
        self.stop_event.set()
        
        if hasattr(self, 'writer_thread'):
            self.writer_thread.join(timeout=5)
        
        if self.connection:
            try:
                self.connection.close()
            except:
                pass
        
        self.logger.info(" Database chiuso correttamente")

# === CLASSE PER CARICAMENTO CONFIGURAZIONE ===
class ConfigManager:
    """Gestisce caricamento e validazione configurazione"""
    
    @staticmethod
    def load_config(config_file: str = 'config.json') -> Dict[str, Any]:
        """Carica configurazione da file JSON"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Validazione base
            ConfigManager._validate_config(config)
            
            logging.info(f" Configurazione caricata da {config_file}")
            return config
            
        except FileNotFoundError:
            logging.error(f" File configurazione {config_file} non trovato")
            # Crea file di esempio
            ConfigManager._create_example_config(config_file)
            raise
        except json.JSONDecodeError as e:
            logging.error(f" Errore parsing JSON in {config_file}: {e}")
            raise
        except Exception as e:
            logging.error(f" Errore caricamento configurazione: {e}")
            raise
    
    @staticmethod
    def _validate_config(config: Dict[str, Any]):
        """Validazione configurazione"""
        required_sections = ['modbus', 'polling', 'flask']
        
        for section in required_sections:
            if section not in config:
                raise ValueError(f"Sezione '{section}' mancante nella configurazione")
        
        # Validazione specifica
        modbus = config['modbus']
        if not modbus.get('serial_port'):
            raise ValueError("serial_port è obbligatorio nella sezione modbus")
        
        if modbus.get('baudrate', 0) <= 0:
            raise ValueError("baudrate deve essere > 0")
    
    @staticmethod
    def _create_example_config(filename: str):
        """Crea file di configurazione di esempio"""
        example_config = {
            "modbus": {
                "serial_port": "/dev/ttyUSB0",
                "baudrate": 115200,
                "bytesize": 8,
                "parity": "E",
                "stopbits": 1,
                "timeout": 1.0
            },
            "polling": {
                "interval_seconds": 30,
                "slave_delay_seconds": 0.05,
                "max_retries": 3,
                "slaves": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
            },
            "database": {
                "enabled": true,
                "type": "sqlserver",
                "host": "10.1.8.252",
                "port": 1433,
                "database": "MIP_IMPEXP",
                "instance": "SQL2022",
                "username_env": "SQLSERVER_USERNAME",
                "password_env": "SQLSERVER_PASSWORD",
                "table_name": "silo_monitoring",
                "driver": "ODBC Driver 17 for SQL Server"
            },
            "flask": {
                "host": "0.0.0.0",
                "port": 5000,
                "debug": false
            }
        }
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(example_config, f, indent=2, ensure_ascii=False)
            
            logging.info(f" Creato file di esempio: {filename}")
            logging.info("  Modifica il file con i tuoi parametri e riavvia l'applicazione")
            
        except Exception as e:
            logging.error(f" Errore creazione file esempio: {e}")