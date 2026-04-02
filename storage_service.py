import json
import os
import threading
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class StorageManager:
    """Gerencia a persistência de dados de forma segura para threads."""
    def __init__(self, root_path):
        self.root = Path(root_path)
        self.files = {
            'macs': self.root / 'known_macs.json',
            'blocklist': self.root / 'ip_blocklist.json',
            'aliases': self.root / 'device_aliases.json'
        }
        self.lock = threading.Lock()
        self.data = {'macs': {}, 'blocklist': set(), 'aliases': {}}
        self.load_all()

    def load_all(self):
        try:
            if self.files['macs'].exists():
                with open(self.files['macs'], 'r') as f: self.data['macs'] = json.load(f)
            if self.files['blocklist'].exists():
                with open(self.files['blocklist'], 'r') as f: self.data['blocklist'] = set(json.load(f))
            if self.files['aliases'].exists():
                with open(self.files['aliases'], 'r') as f: self.data['aliases'] = json.load(f)
        except Exception as e:
            logger.error(f"Erro ao carregar dados persistentes: {e}")

    def save(self, key):
        with self.lock:
            file_path = self.files[key]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            temp_data = self.data[key]
            if key == 'blocklist': temp_data = list(temp_data)
            
            temp_file = str(file_path) + ".tmp"
            with open(temp_file, 'w') as f:
                json.dump(temp_data, f, indent=4, sort_keys=True)
            
            os.replace(temp_file, str(file_path))

    @property
    def known_macs(self): return self.data['macs']
    
    @property
    def ip_blocklist(self): return self.data['blocklist']
    
    @property
    def device_aliases(self): return self.data['aliases']