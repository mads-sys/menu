# -*- coding: utf-8 -*-
"""
Script para testar e validar os alertas de ruído e semáforo em computadores multiseat.
Uso:
  python scratch/test_noise_multiseat.py --ip 192.168.0.101 --action silencio
  python scratch/test_noise_multiseat.py --ip 192.168.0.101 --action warn1
  python scratch/test_noise_multiseat.py --ip 192.168.0.101 --action warn2
  python scratch/test_noise_multiseat.py --ip 192.168.0.101 --action lock60
  python scratch/test_noise_multiseat.py --ip 192.168.0.101 --action unlock
  python scratch/test_noise_multiseat.py --ip 192.168.0.101 --action tf_green
  python scratch/test_noise_multiseat.py --ip 192.168.0.101 --action tf_yellow
  python scratch/test_noise_multiseat.py --ip 192.168.0.101 --action tf_red
  python scratch/test_noise_multiseat.py --ip 192.168.0.101 --action tf_off
"""

import sys
import os
import argparse
import paramiko

# Garante que o diretório raiz do projeto esteja no sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ssh_service import _execute_for_each_user, ssh_connect
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("NoiseTest")

def run_test(target_ip, action_name, password="qwe123", **kwargs):
    logger.info(f"===> Iniciando teste '{action_name}' no host {target_ip}...")
    
    with ssh_connect(target_ip, "aluno", password, logger) as ssh:
        if not ssh:
            logger.error(f"Não foi possível conectar via SSH a {target_ip}")
            return False
            
        if action_name == "silencio":
            payload = {
                'message': kwargs.get('message', "🤫 ATENÇÃO: O professor solicitou silêncio imediato na sala de aula."),
                'password': password
            }
            res = _execute_for_each_user(ssh, 'pedir_silencio', payload, logger)
            logger.info(f"Resultado 'pedir_silencio': {res}")

        elif action_name == "warn1":
            payload = {
                'message': "📢 1º AVISO DE RUÍDO: O limite de barulho (75 dB) foi excedido!\nPor favor, mantenham o silêncio na sala de aula.",
                'password': password
            }
            res = _execute_for_each_user(ssh, 'enviar_mensagem', payload, logger)
            logger.info(f"Resultado '1º Aviso': {res}")

        elif action_name == "warn2":
            payload = {
                'message': "⚠️ 2º AVISO DE RUÍDO: Limite ultrapassado pela 2ª vez!\nNo próximo excesso, os computadores serão bloqueados por 30 segundos.",
                'password': password
            }
            res = _execute_for_each_user(ssh, 'enviar_mensagem', payload, logger)
            logger.info(f"Resultado '2º Aviso': {res}")

        elif action_name in ("lock30", "lock", "lock45", "lock60"):
            sec = 30
            infraction = 3
            if action_name == "lock45":
                sec = 45
                infraction = 4
            elif action_name == "lock60":
                sec = 60
                infraction = 5
            payload = {
                'message': f"🔒 COMPUTADORES BLOQUEADOS POR {sec} SEGUNDOS ({infraction}º Excesso de Ruído)!\nAguarde o término da contagem para o desbloqueio automático.",
                'lock_message': f"🔒 COMPUTADORES BLOQUEADOS POR {sec} SEGUNDOS ({infraction}º Excesso de Ruído)!",
                'unlock_seconds': sec,
                'require_silence': False,
                'password': password
            }
            res = _execute_for_each_user(ssh, 'bloquear_tela_mensagem', payload, logger)
            logger.info(f"Resultado 'Bloqueio {sec}s': {res}")

        elif action_name == "unlock":
            payload = {'password': password}
            res = _execute_for_each_user(ssh, 'desbloquear_tela_mensagem', payload, logger)
            logger.info(f"Resultado 'Desbloquear': {res}")

        elif action_name.startswith("tf_"):
            level = action_name.split("_")[1] # green, yellow, red, off
            db_map = {'green': 45.0, 'yellow': 68.0, 'red': 82.0, 'off': 0.0}
            payload = {
                'level': level,
                'db': db_map.get(level, 60.0),
                'threshold': 75,
                'password': password
            }
            res = _execute_for_each_user(ssh, 'semaforo_ruido', payload, logger)
            logger.info(f"Resultado 'Semáforo {level}': {res}")

        elif action_name == "celeb":
            payload = {
                'stars': 3,
                'period_name': 'Aula de Informática',
                'message': 'Parabéns a toda a turma pela excelente disciplina e foco!',
                'password': password
            }
            res = _execute_for_each_user(ssh, 'celebrar_turma_nota_10', payload, logger)
            logger.info(f"Resultado 'Celebração': {res}")

        else:
            logger.error(f"Ação desconhecida: {action_name}")
            return False

    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Teste de Alertas e Semáforo Multiseat")
    parser.add_argument("--ip", type=str, required=True, help="IP do computador alvo (ex: 192.168.0.101)")
    parser.add_argument("--action", type=str, required=True, choices=["silencio", "warn1", "warn2", "lock60", "unlock", "tf_green", "tf_yellow", "tf_red", "tf_off", "celeb"], help="Ação a ser executada")
    parser.add_argument("--password", type=str, default="qwe123", help="Senha SSH")
    
    args = parser.parse_args()
    run_test(args.ip, args.action, args.password)
