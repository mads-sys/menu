# -*- coding: utf-8 -*-
"""
schedule_service.py - Módulo de Integração com o Horário Escolar
Sincroniza horários de aula com https://educacao-tech.github.io/horario/
e executa alertas automáticos de 5 minutos, além de LIMPEZA E BLOQUEIO DE TELA ao final da aula.
"""

import os
import re
import time
import json
import logging
import sqlite3
import threading
import urllib.request
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# Horários padrão da Escola 1 (EMEB Profª Anna Bonagura de Andrade)
DEFAULT_SCHEDULE_PERIODS_ESCOLA_1 = [
    # Manhã
    {"id": "e1_ent_m", "name": "Entrada da Manhã", "type": "entrada", "shift": "Manhã", "start": "07:05", "end": "07:05"},
    {"id": "e1_m1", "name": "1ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "07:05", "end": "08:00"},
    {"id": "e1_m2", "name": "2ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "08:00", "end": "08:55"},
    {"id": "e1_m3", "name": "3ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "08:55", "end": "09:50"},
    {"id": "e1_rec1_m", "name": "1º Recreio (Manhã)", "type": "recreio", "shift": "Manhã", "start": "10:15", "end": "10:35"},
    {"id": "e1_m4", "name": "4ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "09:50", "end": "10:45"},
    {"id": "e1_rec2_m", "name": "2º Recreio (Manhã)", "type": "recreio", "shift": "Manhã", "start": "10:45", "end": "11:05"},
    {"id": "e1_m5", "name": "5ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "11:05", "end": "12:00"},
    # Tarde
    {"id": "e1_ent_t", "name": "Entrada da Tarde", "type": "entrada", "shift": "Tarde", "start": "12:35", "end": "12:35"},
    {"id": "e1_t1", "name": "1ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "12:35", "end": "13:30"},
    {"id": "e1_t2", "name": "2ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "13:30", "end": "14:25"},
    {"id": "e1_t3", "name": "3ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "14:25", "end": "15:20"},
    {"id": "e1_rec1_t", "name": "1º Recreio (Tarde)", "type": "recreio", "shift": "Tarde", "start": "14:50", "end": "15:10"},
    {"id": "e1_rec2_t", "name": "2º Recreio (Tarde)", "type": "recreio", "shift": "Tarde", "start": "15:20", "end": "15:40"},
    {"id": "e1_t4", "name": "4ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "15:40", "end": "16:35"},
    {"id": "e1_t5", "name": "5ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "16:35", "end": "17:30"}
]

# Horários padrão da Escola 2 (55 minutos por aula)
DEFAULT_SCHEDULE_PERIODS_ESCOLA_2 = [
    # Manhã
    {"id": "e2_ent_m", "name": "Entrada da Manhã", "type": "entrada", "shift": "Manhã", "start": "07:00", "end": "07:00"},
    {"id": "e2_m1", "name": "1ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "07:00", "end": "07:55"},
    {"id": "e2_m2", "name": "2ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "07:55", "end": "08:50"},
    {"id": "e2_m3", "name": "3ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "08:50", "end": "09:45"},
    {"id": "e2_rec1_m", "name": "1º Recreio (Manhã)", "type": "recreio", "shift": "Manhã", "start": "09:45", "end": "10:05"},
    {"id": "e2_rec2_m", "name": "2º Recreio (Manhã)", "type": "recreio", "shift": "Manhã", "start": "09:50", "end": "10:10"},
    {"id": "e2_m4", "name": "4ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "10:10", "end": "11:05"},
    {"id": "e2_m5", "name": "5ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "11:05", "end": "12:00"},
    # Tarde
    {"id": "e2_ent_t", "name": "Entrada da Tarde", "type": "entrada", "shift": "Tarde", "start": "12:30", "end": "12:30"},
    {"id": "e2_t1", "name": "1ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "12:30", "end": "13:25"},
    {"id": "e2_t2", "name": "2ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "13:25", "end": "14:20"},
    {"id": "e2_t3", "name": "3ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "14:20", "end": "15:15"},
    {"id": "e2_rec1_t", "name": "1º Recreio (Tarde)", "type": "recreio", "shift": "Tarde", "start": "15:15", "end": "15:35"},
    {"id": "e2_rec2_t", "name": "2º Recreio (Tarde)", "type": "recreio", "shift": "Tarde", "start": "15:20", "end": "15:40"},
    {"id": "e2_t4", "name": "4ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "15:40", "end": "16:35"},
    {"id": "e2_t5", "name": "5ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "16:35", "end": "17:30"}
]

DEFAULT_SCHEDULES: Dict[str, Any] = {
    "escola_1": {
        "name": "Escola 1 (EMEB Profª Anna Bonagura)",
        "url": "https://educacao-tech.github.io/horario/",
        "periods": DEFAULT_SCHEDULE_PERIODS_ESCOLA_1
    },
    "escola_2": {
        "name": "Escola 2 (EMEB Padre Benito)",
        "url": "",
        "periods": DEFAULT_SCHEDULE_PERIODS_ESCOLA_2
    }
}

SCHEDULE_SOURCE_URL = "https://educacao-tech.github.io/horario/"
SCHEDULE_JSON_PATH = os.path.join(os.path.dirname(__file__), "schedule_schools.json")

class ClassScheduleManager:
    def __init__(self, db_manager=None, socketio=None, batch_executor=None, end_class_executor=None):
        self.db_manager = db_manager
        self.socketio = socketio
        self.batch_executor = batch_executor
        self.end_class_executor = end_class_executor
        
        self.enabled = True
        self.minutes_before = 5
        self.custom_message = "📢 ATENÇÃO: Faltam {minutos} minutos para encerrar a aula! Por favor, salvem seus arquivos e organizem os computadores."
        self.play_sound = True
        
        # Novas propriedades de encerramento e início de aula
        self.auto_clean_screen = True
        self.auto_lock_screen = True
        self.auto_unlock_screen = True
        self.auto_unlock_minutes = 2
        self.lock_message = "🔒 AULA ENCERRADA: Por favor, aguarde orientações do professor."
        self.recreio_message = "🍎 RECREIO / INTERVALO: Aproveite o lanche e o descanso! As telas serão liberadas no retorno."
        self.entrada_message = "☀️ BEM-VINDOS: Aulas iniciadas! Computadores liberados."
        
        # Automação de Ligar (Wake-on-LAN) e Desligar por Turno Escolar
        self.auto_wol_enabled = True
        self.wol_minutes_before = 5
        self.auto_shutdown_enabled = True
        
        self.selected_school = "escola_1"
        self.schools: Dict[str, Any] = {}
        self.periods: List[Dict[str, Any]] = []
        self.fired_today = set()
        self.last_fired_date = None
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        
        self._load_config()

    def _load_config(self):
        """Carrega configurações salvas no arquivo JSON e no banco de dados SQLite."""
        # 1. Carregar escolas a partir do arquivo schedule_schools.json se disponível
        self.schools = {}
        if os.path.exists(SCHEDULE_JSON_PATH):
            try:
                with open(SCHEDULE_JSON_PATH, 'r', encoding='utf-8') as f:
                    file_data = json.load(f)
                    if isinstance(file_data, dict):
                        if 'selected_school' in file_data and file_data['selected_school']:
                            self.selected_school = file_data['selected_school']
                        if 'schools' in file_data and isinstance(file_data['schools'], dict):
                            self.schools = file_data['schools']
                        if 'auto_wol_enabled' in file_data:
                            self.auto_wol_enabled = bool(file_data['auto_wol_enabled'])
                        if 'wol_minutes_before' in file_data:
                            self.wol_minutes_before = int(file_data['wol_minutes_before'])
                        if 'auto_shutdown_enabled' in file_data:
                            self.auto_shutdown_enabled = bool(file_data['auto_shutdown_enabled'])
            except Exception as e:
                logger.warning(f"[ScheduleManager] Falha ao ler {SCHEDULE_JSON_PATH}: {e}")

        # Garantir que escolas padrão estejam presentes e atualizadas com entradas e recreios
        for s_id, s_data in DEFAULT_SCHEDULES.items():
            if s_id not in self.schools:
                self.schools[s_id] = {
                    "name": s_data["name"],
                    "url": s_data.get("url", ""),
                    "periods": list(s_data["periods"])
                }
            else:
                # Se os períodos salvos não incluem recreio ou entrada, atualiza para os novos padrões
                periods = self.schools[s_id].get("periods", [])
                if not any(p.get("type") in ("recreio", "entrada") for p in periods):
                    self.schools[s_id]["periods"] = list(s_data["periods"])

        if self.selected_school not in self.schools:
            self.selected_school = "escola_1"

        self.periods = list(self.schools[self.selected_school].get("periods", []))

        # 2. Carregar do banco SQLite (sobreposição/persistência adicional)
        try:
            if self.db_manager:
                with sqlite3.connect(self.db_manager.db_path) as conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS class_schedule_config (
                            key TEXT PRIMARY KEY,
                            value TEXT
                        )
                    """)
                    cursor = conn.execute("SELECT key, value FROM class_schedule_config")
                    rows = dict(cursor.fetchall())
                    if 'enabled' in rows:
                        self.enabled = rows['enabled'].lower() in ('true', '1', 'yes')
                    if 'minutes_before' in rows:
                        self.minutes_before = int(rows['minutes_before'])
                    if 'custom_message' in rows:
                        self.custom_message = rows['custom_message']
                    if 'play_sound' in rows:
                        self.play_sound = rows['play_sound'].lower() in ('true', '1', 'yes')
                    if 'auto_clean_screen' in rows:
                        self.auto_clean_screen = rows['auto_clean_screen'].lower() in ('true', '1', 'yes')
                    if 'auto_lock_screen' in rows:
                        self.auto_lock_screen = rows['auto_lock_screen'].lower() in ('true', '1', 'yes')
                    if 'auto_unlock_screen' in rows:
                        self.auto_unlock_screen = rows['auto_unlock_screen'].lower() in ('true', '1', 'yes')
                    if 'auto_unlock_minutes' in rows:
                        self.auto_unlock_minutes = int(rows['auto_unlock_minutes'])
                    if 'auto_wol_enabled' in rows:
                        self.auto_wol_enabled = rows['auto_wol_enabled'].lower() in ('true', '1', 'yes')
                    if 'wol_minutes_before' in rows:
                        self.wol_minutes_before = int(rows['wol_minutes_before'])
                    if 'auto_shutdown_enabled' in rows:
                        self.auto_shutdown_enabled = rows['auto_shutdown_enabled'].lower() in ('true', '1', 'yes')
                    if 'lock_message' in rows:
                        self.lock_message = rows['lock_message']
                    if 'recreio_message' in rows:
                        self.recreio_message = rows['recreio_message']
                    if 'entrada_message' in rows:
                        self.entrada_message = rows['entrada_message']
                    if 'selected_school' in rows and rows['selected_school']:
                        if rows['selected_school'] in self.schools:
                            self.selected_school = rows['selected_school']
                    if 'schools_json' in rows and rows['schools_json']:
                        try:
                            saved_schools = json.loads(rows['schools_json'])
                            if isinstance(saved_schools, dict):
                                for s_id, s_info in saved_schools.items():
                                    periods = s_info.get("periods", [])
                                    if any(p.get("type") in ("recreio", "entrada") for p in periods) or s_id not in DEFAULT_SCHEDULES:
                                        self.schools[s_id] = s_info
                                    else:
                                        if s_id in self.schools:
                                            self.schools[s_id]["name"] = s_info.get("name", self.schools[s_id].get("name"))
                                            self.schools[s_id]["url"] = s_info.get("url", self.schools[s_id].get("url"))
                        except Exception:
                            pass
                    # Retrocompatibilidade
                    if 'periods_json' in rows and rows['periods_json'] and self.selected_school == 'escola_1' and not self.schools.get('escola_1', {}).get('periods'):
                        try:
                            self.schools['escola_1']['periods'] = json.loads(rows['periods_json'])
                        except Exception:
                            pass

                    self.periods = list(self.schools[self.selected_school].get("periods", []))
        except Exception as e:
            logger.warning(f"[ScheduleManager] Falha ao carregar configs do DB, usando padrões: {e}")

    def save_config(self):
        """Salva as configurações atuais no banco SQLite e no arquivo schedule_schools.json."""
        # Atualiza a lista da escola ativa
        if self.selected_school in self.schools:
            self.schools[self.selected_school]['periods'] = self.periods

        # 1. Salvar no arquivo JSON
        try:
            file_data = {
                "selected_school": self.selected_school,
                "auto_wol_enabled": self.auto_wol_enabled,
                "wol_minutes_before": self.wol_minutes_before,
                "auto_shutdown_enabled": self.auto_shutdown_enabled,
                "schools": self.schools
            }
            with open(SCHEDULE_JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump(file_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[ScheduleManager] Erro ao salvar schedule_schools.json: {e}")

        # 2. Salvar no SQLite
        try:
            if self.db_manager:
                with sqlite3.connect(self.db_manager.db_path) as conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS class_schedule_config (
                            key TEXT PRIMARY KEY,
                            value TEXT
                        )
                    """)
                    for key, val in [
                        ('enabled', 'true' if self.enabled else 'false'),
                        ('minutes_before', str(self.minutes_before)),
                        ('custom_message', self.custom_message),
                        ('play_sound', 'true' if self.play_sound else 'false'),
                        ('auto_clean_screen', 'true' if self.auto_clean_screen else 'false'),
                        ('auto_lock_screen', 'true' if self.auto_lock_screen else 'false'),
                        ('auto_unlock_screen', 'true' if self.auto_unlock_screen else 'false'),
                        ('auto_unlock_minutes', str(self.auto_unlock_minutes)),
                        ('auto_wol_enabled', 'true' if self.auto_wol_enabled else 'false'),
                        ('wol_minutes_before', str(self.wol_minutes_before)),
                        ('auto_shutdown_enabled', 'true' if self.auto_shutdown_enabled else 'false'),
                        ('lock_message', self.lock_message),
                        ('recreio_message', self.recreio_message),
                        ('entrada_message', self.entrada_message),
                        ('selected_school', self.selected_school),
                        ('schools_json', json.dumps(self.schools, ensure_ascii=False)),
                        ('periods_json', json.dumps(self.periods, ensure_ascii=False)),
                    ]:
                        conn.execute(
                            "INSERT INTO class_schedule_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (key, val)
                        )
        except Exception as e:
            logger.error(f"[ScheduleManager] Erro ao salvar configurações no DB: {e}")

    def set_school(self, school_id: str) -> bool:
        """Altera a escola ativa e recarrega os períodos."""
        if school_id in self.schools:
            self.selected_school = school_id
            self.periods = list(self.schools[school_id].get("periods", []))
            self.fired_today.clear()
            self.save_config()
            logger.info(f"[ScheduleManager] Escola ativa alterada para: {school_id} ({self.schools[school_id].get('name')})")
            return True
        return False

    def update_school_periods(self, school_id: str, periods: List[Dict[str, Any]]) -> bool:
        """Atualiza a lista de períodos de uma escola específica."""
        if school_id in self.schools:
            self.schools[school_id]['periods'] = periods
            if self.selected_school == school_id:
                self.periods = list(periods)
                self.fired_today.clear()
            self.save_config()
            return True
        return False

    def fetch_schedule_from_web(self, school_id: Optional[str] = None) -> Dict[str, Any]:
        """Tenta raspar/sincronizar o quadro de horários diretamente da URL pública da escola."""
        target_school = school_id or self.selected_school
        school_info = self.schools.get(target_school, {})
        url = school_info.get("url") or (SCHEDULE_SOURCE_URL if target_school == "escola_1" else "")

        if not url:
            return {"success": False, "message": f"A {school_info.get('name', target_school)} não possui URL de sincronização cadastrada."}

        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode('utf-8')
            
            time_pattern = re.compile(r'(\d{1,2})h(\d{2})?\s*-\s*(\d{1,2})h(\d{2})?')
            matches = time_pattern.findall(html)
            
            parsed_periods = []
            seen = set()
            count = 1
            for m in matches:
                h1, m1, h2, m2 = m
                start_str = f"{int(h1):02d}:{int(m1 or 0):02d}"
                end_str = f"{int(h2):02d}:{int(m2 or 0):02d}"
                pair_key = f"{start_str}-{end_str}"
                
                if pair_key not in seen:
                    seen.add(pair_key)
                    shift = "Manhã" if int(h1) < 12 else "Tarde"
                    parsed_periods.append({
                        "id": f"{target_school}_{count}",
                        "name": f"Aula {count} ({shift})",
                        "shift": shift,
                        "start": start_str,
                        "end": end_str
                    })
                    count += 1
            
            if parsed_periods:
                self.schools[target_school]['periods'] = parsed_periods
                if target_school == self.selected_school:
                    self.periods = parsed_periods
                    self.fired_today.clear()
                self.save_config()
                logger.info(f"[ScheduleManager] Sincronizados {len(parsed_periods)} horários para {target_school}!")
                return {"success": True, "count": len(parsed_periods), "periods": parsed_periods, "school": target_school}
            else:
                return {"success": False, "message": "Nenhum horário válido encontrado no HTML extraído."}
        except Exception as e:
            logger.error(f"[ScheduleManager] Erro ao buscar grade da web: {e}")
            return {"success": False, "message": str(e)}

    def get_shift_schedules(self) -> List[Dict[str, Any]]:
        """Calcula dinamicamente os horários de início (WoL 5 min antes) e término (Desligamento) de cada turno."""
        shifts_dict: Dict[str, Dict[str, List[str]]] = {}
        for p in self.periods:
            shift = p.get('shift') or 'Geral'
            p_start = p.get('start')
            p_end = p.get('end') or p_start
            if not p_start:
                continue
            if shift not in shifts_dict:
                shifts_dict[shift] = {'starts': [], 'ends': []}
            shifts_dict[shift]['starts'].append(p_start)
            if p_end:
                shifts_dict[shift]['ends'].append(p_end)

        shift_schedules = []
        now = datetime.now()
        for shift, times in shifts_dict.items():
            if not times['starts']:
                continue
            min_start = min(times['starts'])
            max_end = max(times['ends']) if times['ends'] else min_start

            # Calcula horário do WoL (5 minutos antes do primeiro período)
            try:
                start_h, start_m = map(int, min_start.split(':'))
                start_dt = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
                wol_dt = start_dt - timedelta(minutes=self.wol_minutes_before)
                wol_hm = wol_dt.strftime("%H:%M")
            except Exception:
                wol_hm = min_start

            shift_schedules.append({
                'shift': shift,
                'first_start': min_start,
                'wol_time': wol_hm,
                'last_end': max_end,
                'shutdown_time': max_end
            })

        return shift_schedules

    def get_upcoming_alerts(self) -> List[Dict[str, Any]]:
        """Retorna a lista de horários com os horários calculados de aviso e encerramento."""
        now = datetime.now()
        alerts = []
        
        # 1. Alertas de Turno (Wake-on-LAN antes do 1º período e Desligamento no último período)
        shift_schedules = self.get_shift_schedules()
        for s in shift_schedules:
            shift_name = s['shift']
            wol_hm = s['wol_time']
            shutdown_hm = s['shutdown_time']
            
            # Evento WoL (Ligar Laboratório)
            try:
                wol_h, wol_m = map(int, wol_hm.split(':'))
                wol_dt = now.replace(hour=wol_h, minute=wol_m, second=0, microsecond=0)
                wol_key = f"{shift_name}_wol_{wol_hm}"
                alerts.append({
                    "id": f"shift_wol_{shift_name.lower()}",
                    "period_name": f"☀️ Ligar Laboratório (Wake-on-LAN Turno {shift_name})",
                    "shift": shift_name,
                    "type": "shift_wol",
                    "class_start": s['first_start'],
                    "class_end": s['first_start'],
                    "alert_time": wol_hm,
                    "is_future": wol_dt > now,
                    "fired_today": wol_key in self.fired_today
                })
            except Exception:
                pass

            # Evento Desligamento (Fim do Turno)
            try:
                shut_h, shut_m = map(int, shutdown_hm.split(':'))
                shut_dt = now.replace(hour=shut_h, minute=shut_m, second=0, microsecond=0)
                shut_key = f"{shift_name}_shutdown_{shutdown_hm}"
                alerts.append({
                    "id": f"shift_shut_{shift_name.lower()}",
                    "period_name": f"🌙 Desligar Laboratório (Fim do Turno {shift_name})",
                    "shift": shift_name,
                    "type": "shift_shutdown",
                    "class_start": s['last_end'],
                    "class_end": s['last_end'],
                    "alert_time": shutdown_hm,
                    "is_future": shut_dt > now,
                    "fired_today": shut_key in self.fired_today
                })
            except Exception:
                pass

        # 2. Períodos regulares (Entrada, Aulas, Recreios)
        for period in self.periods:
            try:
                p_type = period.get('type', 'aula')
                p_start = period.get('start', '')
                p_end = period.get('end', '')

                if p_type == 'entrada':
                    start_h, start_m = map(int, p_start.split(':'))
                    ent_dt = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
                    ent_key = f"{period['id']}_ent_{p_start}"
                    fired = ent_key in self.fired_today
                    alerts.append({
                        "id": period['id'],
                        "period_name": period['name'],
                        "shift": period.get('shift', 'Geral'),
                        "type": "entrada",
                        "class_start": p_start,
                        "class_end": p_end or p_start,
                        "alert_time": p_start,
                        "is_future": ent_dt > now,
                        "fired_today": fired
                    })
                elif p_type == 'recreio':
                    alerts.append({
                        "id": period['id'],
                        "period_name": period['name'],
                        "shift": period.get('shift', 'Geral'),
                        "type": "recreio",
                        "class_start": p_start,
                        "class_end": p_end,
                        "alert_time": "--:--",
                        "is_future": False,
                        "fired_today": False
                    })
                else:
                    end_h, end_m = map(int, p_end.split(':'))
                    end_dt = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
                    alert_dt = end_dt - timedelta(minutes=self.minutes_before)
                    alert_time_str = alert_dt.strftime("%H:%M")
                    
                    warn_key = f"{period['id']}_warn_{alert_time_str}"
                    end_key = f"{period['id']}_end_{p_end}"
                    
                    fired_warn = warn_key in self.fired_today
                    fired_end = end_key in self.fired_today
                    
                    alerts.append({
                        "id": period['id'],
                        "period_name": period['name'],
                        "shift": period.get('shift', 'Geral'),
                        "type": "aula",
                        "class_start": p_start,
                        "class_end": p_end,
                        "alert_time": alert_time_str,
                        "is_future": alert_dt > now,
                        "fired_today": fired_warn or fired_end
                    })
            except Exception as e:
                logger.warning(f"[ScheduleManager] Erro ao calcular alerta para período {period}: {e}")
                
        alerts.sort(key=lambda x: x['alert_time'])
        return alerts

    def get_current_period_info(self) -> Dict[str, Any]:
        """Retorna informações da aula/período e turno que está acontecendo agora no horário escolar."""
        now = datetime.now()
        now_str = now.strftime("%H:%M")
        with self._lock:
            for p in self.periods:
                p_start = p.get('start', '00:00')
                p_end = p.get('end', '23:59')
                if p_start <= now_str <= p_end:
                    return {
                        "school_id": self.selected_school,
                        "period_id": p.get("id"),
                        "period_name": p.get("name"),
                        "shift": p.get("shift", "Geral"),
                        "type": p.get("type", "aula"),
                        "start": p_start,
                        "end": p_end
                    }
        hour = now.hour
        shift = "Manhã" if hour < 12 else ("Tarde" if hour < 18 else "Noite")
        return {
            "school_id": self.selected_school,
            "period_id": "fora_horario",
            "period_name": "Fora do Horário Regular",
            "shift": shift,
            "type": "livre",
            "start": now_str,
            "end": now_str
        }

    def trigger_test_alert(self, target_ips: Optional[List[str]] = None, message_text: Optional[str] = None) -> Dict[str, Any]:
        """Dispara um alerta imediato de teste formatando adequadamente os minutos no texto."""
        msg = self.format_message(minutes=self.minutes_before, template=message_text)
        return self._send_alert_to_targets(msg, target_ips, is_test=True)

    def trigger_test_end_class(self, target_ips: Optional[List[str]] = None) -> Dict[str, Any]:
        """Dispara imediatamente o teste de Limpeza e Bloqueio de fim de aula (força Clean=True e Lock=True no teste)."""
        return self._trigger_end_class_actions({"name": "Aula de Teste", "end": "Agora"}, target_ips=target_ips, is_test=True, force_clean=True, force_lock=True)

    def format_message(self, minutes: Optional[int] = None, template: Optional[str] = None) -> str:
        mins = minutes if minutes is not None else self.minutes_before
        raw_tmpl = template if template else self.custom_message
        if not raw_tmpl:
            raw_tmpl = "📢 ATENÇÃO: Faltam {minutos} minutos para encerrar a aula! Por favor, salvem seus arquivos e organizem os computadores."

        msg = str(raw_tmpl)
        msg = msg.replace("{minutos}", str(mins)).replace("{minuto}", str(mins)).replace("{min}", str(mins)).replace("{minutes}", str(mins))
        return msg

    def _send_alert_to_targets(self, message: str, target_ips: Optional[List[str]] = None, is_test: bool = False) -> Dict[str, Any]:
        """Envia a mensagem pop-up de aviso via batch executor SSH para os computadores."""
        logger.info(f"[ScheduleManager] Disparando alerta de fim de aula (Teste={is_test}): '{message}'")
        
        if self.socketio:
            try:
                self.socketio.emit('class_end_warning_triggered', {
                    'message': message,
                    'is_test': is_test,
                    'timestamp': datetime.now().strftime("%H:%M:%S")
                })
            except Exception as e:
                logger.warning(f"[ScheduleManager] Falha ao emitir socketio event: {e}")

        if self.batch_executor:
            try:
                result = self.batch_executor(message=message, target_ips=target_ips)
                return {"success": True, "details": result}
            except Exception as e:
                logger.error(f"[ScheduleManager] Erro no executor batch de mensagem: {e}")
                return {"success": False, "message": str(e)}
        else:
            return {"success": True, "message": "Alerta gerado (sem executor batch direto anexado)."}

    def _trigger_end_class_actions(self, period: Dict[str, Any], target_ips: Optional[List[str]] = None, is_test: bool = False, force_clean: bool = False, force_lock: bool = False) -> Dict[str, Any]:
        """Executa a limpeza da área de trabalho e o bloqueio de tela no término exato da aula."""
        do_clean = True if force_clean else self.auto_clean_screen
        do_lock = True if force_lock else self.auto_lock_screen

        logger.info(f"[ScheduleManager] Executando Ações de Término de Aula para {period.get('name')}: Clean={do_clean}, Lock={do_lock}")
        
        if self.socketio:
            try:
                self.socketio.emit('class_ended_actions_triggered', {
                    'period_name': period.get('name'),
                    'clean': do_clean,
                    'lock': do_lock,
                    'lock_message': self.lock_message,
                    'is_test': is_test,
                    'timestamp': datetime.now().strftime("%H:%M:%S")
                })
            except Exception as e:
                logger.warning(f"[ScheduleManager] Falha ao emitir SocketIO de término de aula: {e}")

        if self.end_class_executor:
            try:
                res = self.end_class_executor(
                    clean_screen=do_clean,
                    lock_screen=do_lock,
                    lock_message=self.lock_message,
                    target_ips=target_ips
                )
                return {"success": True, "details": res}
            except Exception as e:
                logger.error(f"[ScheduleManager] Erro ao executar ações de término de aula: {e}")
                return {"success": False, "message": str(e)}
        return {"success": True, "message": "Ações de término acionadas (sem executor registrado)."}

    def trigger_test_unlock(self, target_ips: Optional[List[str]] = None) -> Dict[str, Any]:
        """Dispara o desbloqueio em lote imediato para os computadores para encerrar o teste de fim de aula."""
        logger.info(f"[ScheduleManager] Encerrando teste e desbloqueando telas de {target_ips or 'todos os computadores'}...")
        try:
            from ssh_service import _execute_for_each_user
            from app import _get_all_network_target_ips, SSH_USER, DEFAULT_PASSWORD, ssh_connect

            if not target_ips:
                target_ips = _get_all_network_target_ips()

            def unlock_one(target_spec):
                try:
                    if '/' in target_spec:
                        host_ip, target_user = target_spec.split('/', 1)
                    else:
                        host_ip, target_user = target_spec, None

                    with ssh_connect(host_ip, SSH_USER, DEFAULT_PASSWORD, logger) as ssh:
                        if ssh:
                            payload = {'password': DEFAULT_PASSWORD}
                            if target_user:
                                payload['target_user'] = target_user
                            _execute_for_each_user(ssh, 'desbloquear_tela_mensagem', payload, logger)
                            return target_spec, True
                except Exception as err:
                    logger.debug(f"[ScheduleTestUnlock] Host indisponível em {target_spec}: {err}")
                return target_spec, False

            results = {}
            with ThreadPoolExecutor(max_workers=min(40, max(1, len(target_ips)))) as executor:
                futures = [executor.submit(unlock_one, spec) for spec in target_ips]
                for f in as_completed(futures):
                    spec, ok = f.result()
                    if ok:
                        results[spec] = True

            return {"success": True, "delivered_count": len(results), "delivered_ips": list(results.keys())}
        except Exception as e:
            logger.error(f"[ScheduleTestUnlock] Erro ao desbloquear no teste: {e}")
            return {"success": False, "message": str(e)}

    def trigger_test_close_alert(self, target_ips: Optional[List[str]] = None) -> Dict[str, Any]:
        """Fecha o pop-up de aviso de teste enviado aos computadores."""
        logger.info(f"[ScheduleManager] Fechando pop-up de aviso em {target_ips or 'todos os computadores'}...")
        try:
            from ssh_service import _execute_for_each_user
            from app import _get_all_network_target_ips, SSH_USER, DEFAULT_PASSWORD, ssh_connect

            if not target_ips:
                target_ips = _get_all_network_target_ips()

            def close_one(target_spec):
                try:
                    if '/' in target_spec:
                        host_ip, target_user = target_spec.split('/', 1)
                    else:
                        host_ip, target_user = target_spec, None

                    with ssh_connect(host_ip, SSH_USER, DEFAULT_PASSWORD, logger) as ssh:
                        if ssh:
                            payload = {'password': DEFAULT_PASSWORD}
                            if target_user:
                                payload['target_user'] = target_user
                            _execute_for_each_user(ssh, 'fechar_mensagem', payload, logger)
                            return target_spec, True
                except Exception as err:
                    logger.debug(f"[ScheduleCloseAlert] Host indisponível em {target_spec}: {err}")
                return target_spec, False

            results = {}
            with ThreadPoolExecutor(max_workers=min(40, max(1, len(target_ips)))) as executor:
                futures = [executor.submit(close_one, spec) for spec in target_ips]
                for f in as_completed(futures):
                    spec, ok = f.result()
                    if ok:
                        results[spec] = True

            return {"success": True, "delivered_count": len(results), "delivered_ips": list(results.keys())}
        except Exception as e:
            logger.error(f"[ScheduleCloseAlert] Erro ao fechar aviso no teste: {e}")
            return {"success": False, "message": str(e)}

    def _trigger_shift_wol(self, shift_name: str, first_start: str) -> Dict[str, Any]:
        """Dispara Wake-on-LAN para ligar os computadores do laboratório 5 minutos antes do início do primeiro período."""
        logger.info(f"[ScheduleManager] ⏰ Disparando Wake-on-LAN do turno {shift_name} ({self.wol_minutes_before} min antes do início das {first_start})...")
        if self.socketio:
            try:
                self.socketio.emit('schedule_shift_wol_triggered', {
                    'shift': shift_name,
                    'first_start': first_start,
                    'wol_minutes_before': self.wol_minutes_before,
                    'timestamp': datetime.now().strftime("%H:%M:%S")
                })
            except Exception as e:
                logger.warning(f"[ScheduleManager] Falha ao emitir SocketIO WoL: {e}")

        try:
            from network_service import send_batch_wake_on_lan
            mac_list = []
            if self.db_manager:
                ip_mac_map = self.db_manager.get_known_macs()
                mac_list = list(ip_mac_map.values())

            wol_results = send_batch_wake_on_lan(mac_list, logger)
            return {"success": True, "count": len(wol_results), "shift": shift_name}
        except Exception as e:
            logger.error(f"[ScheduleManager] Erro ao disparar WoL do turno: {e}")
            return {"success": False, "message": str(e)}

    def _trigger_shift_shutdown(self, shift_name: str, last_end: str) -> Dict[str, Any]:
        """Dispara desligamento automático de todas as máquinas dos alunos no término do último período do turno."""
        logger.info(f"[ScheduleManager] ⏰ Disparando Desligamento Automático do turno {shift_name} (término às {last_end})...")
        if self.socketio:
            try:
                self.socketio.emit('schedule_shift_shutdown_triggered', {
                    'shift': shift_name,
                    'last_end': last_end,
                    'timestamp': datetime.now().strftime("%H:%M:%S")
                })
            except Exception as e:
                logger.warning(f"[ScheduleManager] Falha ao emitir SocketIO Shutdown: {e}")

        try:
            from app import _get_all_network_target_ips, SSH_USER, DEFAULT_PASSWORD, ssh_connect

            target_ips = _get_all_network_target_ips()
            if not target_ips:
                logger.warning("[ScheduleManager] Nenhuma máquina online detectada para desligamento do turno.")
                return {"success": True, "count": 0}

            def shutdown_one(target_spec):
                try:
                    host_ip = target_spec.split('/')[0].strip()
                    with ssh_connect(host_ip, SSH_USER, DEFAULT_PASSWORD, logger) as ssh:
                        if ssh:
                            ssh.exec_command("sudo shutdown -h now || sudo poweroff || shutdown -h now", timeout=4)
                            return target_spec, True
                except Exception as err:
                    logger.debug(f"[ScheduleShutdown] Host {target_spec}: {err}")
                return target_spec, False

            results = {}
            with ThreadPoolExecutor(max_workers=min(25, max(1, len(target_ips)))) as executor:
                futures = [executor.submit(shutdown_one, spec) for spec in target_ips]
                for f in as_completed(futures):
                    spec, ok = f.result()
                    if ok:
                        results[spec] = True

            logger.info(f"[ScheduleManager] Desligamento do turno {shift_name} enviado para {len(results)} máquinas.")
            return {"success": True, "count": len(results), "delivered_ips": list(results.keys())}
        except Exception as e:
            logger.error(f"[ScheduleManager] Erro ao desligar máquinas no fim do turno: {e}")
            return {"success": False, "message": str(e)}

    def trigger_test_shift_wol(self, shift_name: str = "Manhã") -> Dict[str, Any]:
        """Dispara imediatamente teste de Wake-on-LAN do turno para verificação."""
        return self._trigger_shift_wol(shift_name, "Agora")

    def trigger_test_shift_shutdown(self, shift_name: str = "Manhã") -> Dict[str, Any]:
        """Dispara imediatamente teste de Desligamento de turno para verificação."""
        return self._trigger_shift_shutdown(shift_name, "Agora")

    def start_loop(self):
        """Inicia o loop em segundo plano."""
        with self._lock:
            if not self._running:
                self._running = True
                self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="ClassScheduleDaemon")
                self._thread.start()
                logger.info("[ScheduleManager] Daemon de monitoramento do Horário Escolar iniciado.")

    def stop_loop(self):
        with self._lock:
            self._running = False

    def _monitor_loop(self):
        while self._running:
            try:
                now = datetime.now()
                today_str = now.strftime("%Y-%m-%d")
                
                if self.last_fired_date != today_str:
                    self.fired_today.clear()
                    self.last_fired_date = today_str

                if self.enabled:
                    current_hm = now.strftime("%H:%M")
                    
                    # 1. Checagem dos Turnos (Wake-on-LAN 5 min antes do 1º período e Desligamento no último período)
                    shift_schedules = self.get_shift_schedules()
                    for s in shift_schedules:
                        shift_name = s['shift']
                        wol_hm = s['wol_time']
                        shutdown_hm = s['shutdown_time']
                        
                        # 1.1 Wake-on-LAN automático do turno (5 min antes do início)
                        if self.auto_wol_enabled and wol_hm:
                            wol_key = f"{shift_name}_wol_{wol_hm}"
                            if current_hm == wol_hm and wol_key not in self.fired_today:
                                self.fired_today.add(wol_key)
                                self._trigger_shift_wol(shift_name, s['first_start'])

                        # 1.2 Desligamento automático do turno (término do último período)
                        if self.auto_shutdown_enabled and shutdown_hm:
                            shut_key = f"{shift_name}_shutdown_{shutdown_hm}"
                            if current_hm == shutdown_hm and shut_key not in self.fired_today:
                                self.fired_today.add(shut_key)
                                self._trigger_shift_shutdown(shift_name, s['last_end'])

                    # 2. Checagem dos Períodos da Grade
                    for period in self.periods:
                        try:
                            p_type = period.get('type', 'aula')
                            p_start = period.get('start', '')
                            p_end = period.get('end', '')

                            if p_type == 'entrada':
                                ent_key = f"{period['id']}_ent_{p_start}"
                                if current_hm == p_start and ent_key not in self.fired_today:
                                    self.fired_today.add(ent_key)
                                    logger.info(f"[ScheduleManager] 🚪 Horário de Entrada ({period.get('name')}) atingido. Desbloqueando computadores...")
                                    if self.auto_unlock_screen:
                                        self.trigger_test_unlock()
                                    if self.socketio:
                                        self.socketio.emit('schedule_entry_triggered', {
                                            'period_name': period.get('name'),
                                            'shift': period.get('shift'),
                                            'message': self.entrada_message
                                        })

                            elif p_type == 'recreio':
                                # Recreios / Intervalos NÃO disparam alertas nem bloqueio/limpeza de tela
                                # para evitar cortar aulas de turmas que estão no laboratório nesse horário.
                                pass

                            else:
                                # Aula regular
                                end_h, end_m = map(int, p_end.split(':'))
                                end_dt = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
                                alert_dt = end_dt - timedelta(minutes=self.minutes_before)
                                alert_hm = alert_dt.strftime("%H:%M")
                                end_hm = p_end
                                
                                warn_key = f"{period['id']}_warn_{alert_hm}"
                                end_key = f"{period['id']}_end_{end_hm}"
                                
                                # 1. Alerta de aviso prévio (ex: 5 min antes)
                                if current_hm == alert_hm and warn_key not in self.fired_today:
                                    self.fired_today.add(warn_key)
                                    msg = self.format_message(self.minutes_before)
                                    self._send_alert_to_targets(msg)

                                # 2. Ações de Encerramento (Limpeza + Bloqueio no horário exato do fim da aula)
                                if current_hm == end_hm and end_key not in self.fired_today:
                                    self.fired_today.add(end_key)
                                    if self.auto_clean_screen or self.auto_lock_screen:
                                        self._trigger_end_class_actions(period)

                                # 3. Desbloqueio Automático no início da aula (ex: 2 min após o início)
                                if self.auto_unlock_screen and p_start:
                                    try:
                                        start_h, start_m = map(int, p_start.split(':'))
                                        start_dt = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
                                        unlock_dt = start_dt + timedelta(minutes=self.auto_unlock_minutes)
                                        unlock_hm = unlock_dt.strftime("%H:%M")
                                        unlock_key = f"{period['id']}_unlock_{unlock_hm}"

                                        if current_hm == unlock_hm and unlock_key not in self.fired_today:
                                            self.fired_today.add(unlock_key)
                                            logger.info(f"[ScheduleManager] Executando Desbloqueio Automático ({self.auto_unlock_minutes} min após início da {period.get('name')})...")
                                            self.trigger_test_unlock()
                                    except Exception as u_err:
                                        logger.warning(f"[ScheduleManager] Erro ao processar desbloqueio automático: {u_err}")

                        except Exception as p_err:
                            logger.warning(f"[ScheduleManager] Erro processando período no loop: {p_err}")
            except Exception as e:
                logger.error(f"[ScheduleManager] Erro no loop de monitoramento: {e}")
                
            time.sleep(15)
