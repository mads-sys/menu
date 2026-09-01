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

# Horários padrão de término das aulas (EMEB Profª Anna Bonagura de Andrade)
DEFAULT_SCHEDULE_PERIODS = [
    # Manhã
    {"id": "m1", "name": "1ª Aula (Manhã)", "shift": "Manhã", "start": "07:05", "end": "08:00"},
    {"id": "m2", "name": "2ª Aula (Manhã)", "shift": "Manhã", "start": "08:00", "end": "08:55"},
    {"id": "m3", "name": "3ª Aula (Manhã)", "shift": "Manhã", "start": "08:55", "end": "09:50"},
    {"id": "m4", "name": "4ª Aula (Manhã)", "shift": "Manhã", "start": "09:50", "end": "10:45"},
    {"id": "m5", "name": "5ª Aula (Manhã)", "shift": "Manhã", "start": "11:05", "end": "12:00"},
    # Tarde
    {"id": "t1", "name": "1ª Aula (Tarde)", "shift": "Tarde", "start": "12:35", "end": "13:30"},
    {"id": "t2", "name": "2ª Aula (Tarde)", "shift": "Tarde", "start": "13:30", "end": "14:25"},
    {"id": "t3", "name": "3ª Aula (Tarde)", "shift": "Tarde", "start": "14:25", "end": "15:20"},
    {"id": "t4", "name": "4ª Aula (Tarde)", "shift": "Tarde", "start": "15:40", "end": "16:35"},
    {"id": "t5", "name": "5ª Aula (Tarde)", "shift": "Tarde", "start": "16:35", "end": "17:30"},
]

SCHEDULE_SOURCE_URL = "https://educacao-tech.github.io/horario/"

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
        
        # Gestão de Energia e Sessão estilo Veyon
        self.auto_wol_before_shift = True
        self.wol_minutes_before = 10
        self.auto_logoff_on_class_end = False
        self.auto_shutdown_on_shift_end = True

        self.periods = list(DEFAULT_SCHEDULE_PERIODS)
        self.fired_today = set()
        self.last_fired_date = None
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        
        self._load_config()

    def _load_config(self):
        """Carrega configurações salvas no banco de dados SQLite ou arquivo de config."""
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
                    if 'lock_message' in rows:
                        self.lock_message = rows['lock_message']
                    if 'auto_wol_before_shift' in rows:
                        self.auto_wol_before_shift = rows['auto_wol_before_shift'].lower() in ('true', '1', 'yes')
                    if 'wol_minutes_before' in rows:
                        self.wol_minutes_before = int(rows['wol_minutes_before'])
                    if 'auto_logoff_on_class_end' in rows:
                        self.auto_logoff_on_class_end = rows['auto_logoff_on_class_end'].lower() in ('true', '1', 'yes')
                    if 'auto_shutdown_on_shift_end' in rows:
                        self.auto_shutdown_on_shift_end = rows['auto_shutdown_on_shift_end'].lower() in ('true', '1', 'yes')
                    if 'periods_json' in rows and rows['periods_json']:
                        self.periods = json.loads(rows['periods_json'])
        except Exception as e:
            logger.warning(f"[ScheduleManager] Falha ao carregar configs do DB, usando padrões: {e}")

    def save_config(self):
        """Salva as configurações atuais no banco SQLite."""
        try:
            if self.db_manager:
                with sqlite3.connect(self.db_manager.db_path) as conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS class_schedule_config (
                            key TEXT PRIMARY KEY,
                            value TEXT
                        )
                    """)
                    conn.execute("INSERT INTO class_schedule_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                 ('enabled', 'true' if self.enabled else 'false'))
                    conn.execute("INSERT INTO class_schedule_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                 ('minutes_before', str(self.minutes_before)))
                    conn.execute("INSERT INTO class_schedule_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                 ('custom_message', self.custom_message))
                    conn.execute("INSERT INTO class_schedule_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                 ('play_sound', 'true' if self.play_sound else 'false'))
                    conn.execute("INSERT INTO class_schedule_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                 ('auto_clean_screen', 'true' if self.auto_clean_screen else 'false'))
                    conn.execute("INSERT INTO class_schedule_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                 ('auto_lock_screen', 'true' if self.auto_lock_screen else 'false'))
                    conn.execute("INSERT INTO class_schedule_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                 ('auto_unlock_screen', 'true' if self.auto_unlock_screen else 'false'))
                    conn.execute("INSERT INTO class_schedule_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                 ('auto_unlock_minutes', str(self.auto_unlock_minutes)))
                    conn.execute("INSERT INTO class_schedule_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                 ('lock_message', self.lock_message))
                    conn.execute("INSERT INTO class_schedule_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                 ('auto_wol_before_shift', 'true' if self.auto_wol_before_shift else 'false'))
                    conn.execute("INSERT INTO class_schedule_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                 ('wol_minutes_before', str(self.wol_minutes_before)))
                    conn.execute("INSERT INTO class_schedule_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                 ('auto_logoff_on_class_end', 'true' if self.auto_logoff_on_class_end else 'false'))
                    conn.execute("INSERT INTO class_schedule_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                 ('auto_shutdown_on_shift_end', 'true' if self.auto_shutdown_on_shift_end else 'false'))
                    conn.execute("INSERT INTO class_schedule_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                 ('periods_json', json.dumps(self.periods)))
        except Exception as e:
            logger.error(f"[ScheduleManager] Erro ao salvar configurações no DB: {e}")

    def fetch_schedule_from_web(self) -> Dict[str, Any]:
        """Tenta raspar/sincronizar o quadro de horários diretamente da URL pública."""
        try:
            req = urllib.request.Request(SCHEDULE_SOURCE_URL, headers={'User-Agent': 'Mozilla/5.0'})
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
                        "id": f"web_{count}",
                        "name": f"Aula {count} ({shift})",
                        "shift": shift,
                        "start": start_str,
                        "end": end_str
                    })
                    count += 1
            
            if parsed_periods:
                self.periods = parsed_periods
                self.save_config()
                logger.info(f"[ScheduleManager] Sincronizados {len(parsed_periods)} horários da web!")
                return {"success": True, "count": len(parsed_periods), "periods": parsed_periods}
            else:
                return {"success": False, "message": "Nenhum horário válido encontrado no HTML extraído."}
        except Exception as e:
            logger.error(f"[ScheduleManager] Erro ao buscar grade da web: {e}")
            return {"success": False, "message": str(e)}

    def get_upcoming_alerts(self) -> List[Dict[str, Any]]:
        """Retorna a lista de horários com os horários calculados de aviso e encerramento."""
        now = datetime.now()
        alerts = []
        
        for period in self.periods:
            try:
                end_h, end_m = map(int, period['end'].split(':'))
                end_dt = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
                alert_dt = end_dt - timedelta(minutes=self.minutes_before)
                alert_time_str = alert_dt.strftime("%H:%M")
                
                warn_key = f"{period['id']}_warn_{alert_time_str}"
                end_key = f"{period['id']}_end_{period['end']}"
                
                fired_warn = warn_key in self.fired_today
                fired_end = end_key in self.fired_today
                
                alerts.append({
                    "id": period['id'],
                    "period_name": period['name'],
                    "shift": period.get('shift', 'Geral'),
                    "class_end": period['end'],
                    "alert_time": alert_time_str,
                    "is_future": alert_dt > now,
                    "fired_today": fired_warn or fired_end
                })
            except Exception as e:
                logger.warning(f"[ScheduleManager] Erro ao calcular alerta para período {period}: {e}")
                
        alerts.sort(key=lambda x: x['alert_time'])
        return alerts

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

    def trigger_batch_wol(self) -> Dict[str, Any]:
        """Envia pacote mágico Wake-on-LAN para todos os MACs cadastrados/conhecidos da rede."""
        logger.info("[ScheduleManager] Executando Ligar Máquinas em Massa (Wake-on-LAN)...")
        try:
            from network_service import send_batch_wake_on_lan
            from app import _get_known_macs
            macs = list(_get_known_macs().values())
            if macs:
                res = send_batch_wake_on_lan(macs, logger)
                return {"success": True, "count": len(macs), "results": res}
            return {"success": False, "message": "Nenhum endereço MAC cadastrado para envio de WoL."}
        except Exception as e:
            logger.error(f"[ScheduleManager] Erro ao disparar WoL em lote: {e}")
            return {"success": False, "message": str(e)}

    def trigger_batch_logoff(self, target_ips: Optional[List[str]] = None) -> Dict[str, Any]:
        """Encerra todas as sessões ativas de usuários (Logoff em massa)."""
        logger.info("[ScheduleManager] Executando Encerramento de Sessões (Logoff em massa)...")
        try:
            from app import _get_all_network_target_ips, _execute_command_internal
            if not target_ips:
                target_ips = _get_all_network_target_ips()
            return _execute_command_internal('deslogar_todos', {}, target_ips)
        except Exception as e:
            logger.error(f"[ScheduleManager] Erro ao disparar logoff em massa: {e}")
            return {"success": False, "message": str(e)}

    def trigger_batch_shutdown(self, target_ips: Optional[List[str]] = None) -> Dict[str, Any]:
        """Desliga todas as máquinas do laboratório (Shutdown em massa)."""
        logger.info("[ScheduleManager] Executando Desligamento do Laboratório (Shutdown em massa)...")
        try:
            from app import _get_all_network_target_ips, _execute_command_internal
            if not target_ips:
                target_ips = _get_all_network_target_ips()
            return _execute_command_internal('desligar', {}, target_ips)
        except Exception as e:
            logger.error(f"[ScheduleManager] Erro ao disparar desligamento em massa: {e}")
            return {"success": False, "message": str(e)}

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
                    
                    for period in self.periods:
                        try:
                            end_h, end_m = map(int, period['end'].split(':'))
                            end_dt = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
                            alert_dt = end_dt - timedelta(minutes=self.minutes_before)
                            alert_hm = alert_dt.strftime("%H:%M")
                            end_hm = period['end']
                            
                            warn_key = f"{period['id']}_warn_{alert_hm}"
                            end_key = f"{period['id']}_end_{end_hm}"
                            
                            # 1. Alerta de aviso prévio (ex: 5 min antes do fim da aula)
                            if current_hm == alert_hm and warn_key not in self.fired_today:
                                self.fired_today.add(warn_key)
                                msg = self.format_message(self.minutes_before)
                                self._send_alert_to_targets(msg)

                            # 2. Ações de Encerramento de Aula (Limpeza + Bloqueio + Logoff se configurado)
                            if current_hm == end_hm and end_key not in self.fired_today:
                                self.fired_today.add(end_key)
                                if self.auto_clean_screen or self.auto_lock_screen:
                                    self._trigger_end_class_actions(period)
                                if self.auto_logoff_on_class_end:
                                    logger.info(f"[ScheduleManager] Logoff Automático ativado ao término da aula {period.get('name')}...")
                                    self.trigger_batch_logoff()

                            # 3. Desbloqueio Automático no início da aula (ex: 2 min após o início)
                            if self.auto_unlock_screen and period.get('start'):
                                try:
                                    start_h, start_m = map(int, period['start'].split(':'))
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

                            # 4. Wake-on-LAN Pré-Turno/Pré-Aula (Ligar computadores N min antes do início)
                            if self.auto_wol_before_shift and period.get('start'):
                                try:
                                    start_h, start_m = map(int, period['start'].split(':'))
                                    start_dt = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
                                    wol_dt = start_dt - timedelta(minutes=self.wol_minutes_before)
                                    wol_hm = wol_dt.strftime("%H:%M")
                                    wol_key = f"{period['id']}_wol_{wol_hm}"

                                    if current_hm == wol_hm and wol_key not in self.fired_today:
                                        self.fired_today.add(wol_key)
                                        logger.info(f"[ScheduleManager] Executando Ligar Máquinas (WoL) {self.wol_minutes_before} min antes do início de {period.get('name')}...")
                                        self.trigger_batch_wol()
                                except Exception as wol_err:
                                    logger.warning(f"[ScheduleManager] Erro ao processar WoL automático: {wol_err}")

                            # 5. Desligamento Automático no Final do Turno (12:00 e 17:30 / Últimas Aulas)
                            if self.auto_shutdown_on_shift_end and period.get('id') in ('m5', 't5', 'web_5', 'web_10'):
                                shutdown_key = f"{period['id']}_shutdown_{end_hm}"
                                if current_hm == end_hm and shutdown_key not in self.fired_today:
                                    self.fired_today.add(shutdown_key)
                                    logger.info(f"[ScheduleManager] Desligamento Automático do Laboratório ao final do turno ({period.get('name')})...")
                                    self.trigger_batch_shutdown()

                        except Exception as p_err:
                            logger.warning(f"[ScheduleManager] Erro processando período no loop: {p_err}")
            except Exception as e:
                logger.error(f"[ScheduleManager] Erro no loop de monitoramento: {e}")
                
            time.sleep(15)
