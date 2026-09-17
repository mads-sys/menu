#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
firewall_service.py - Verificação e Correção Automática do Windows Firewall
Garante que as portas do Menu Admin e VNC estejam acessíveis por outros computadores na rede local.
  - Porta 5050 (TCP): Painel Web do Menu Admin / API
  - Faixa 5900-7500 (TCP): Streaming VNC / Websockify
"""

import os
import sys
import time
import ctypes
import logging
import subprocess
import threading
from typing import Dict, Any, List

logger = logging.getLogger("firewall_service")


def is_admin() -> bool:
    """Verifica se o processo atual possui privilégios de Administrador no Windows."""
    if os.name != 'nt':
        return True
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def check_firewall_status() -> Dict[str, Any]:
    """
    Verifica se as portas necessárias estão liberadas para tráfego de entrada (Inbound) no Firewall do Windows.
    Execução ultra-rápida via netsh (geralmente < 0.4s).
    """
    if os.name != 'nt':
        return {
            "supported": False,
            "ok": True,
            "message": "Sistema não é Windows (Linux/macOS gerenciado via iptables/ufw)",
            "port_5050": True,
            "vnc_range": True,
            "missing": [],
            "is_admin": True
        }

    try:
        proc = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", "name=all", "dir=in"],
            capture_output=True,
            text=True,
            errors='ignore',
            timeout=4
        )
        output = proc.stdout

        blocks = output.split("\n----------------------------------------------------------------------\n")
        port_5050_ok = False
        vnc_range_ok = False
        all_port_ok = False

        for b in blocks:
            b_lower = b.lower()
            # Valida regras ativas (Habilitado / Permitir)
            is_allow = (
                "ao: permitir" in b_lower or 
                "acao: permitir" in b_lower or 
                "ação: permitir" in b_lower or 
                "action: allow" in b_lower or 
                "permitir" in b_lower
            )
            if not is_allow:
                continue

            for line in b.splitlines():
                line_clean = line.lower().strip()
                if line_clean.startswith("porta local:") or line_clean.startswith("localport:"):
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        val = parts[1].strip()
                        if val.lower() in ("qualquer", "any"):
                            port_5050_ok = True
                            vnc_range_ok = True
                            all_port_ok = True
                            break
                        if "5050" in val:
                            port_5050_ok = True
                        if any(r in val for r in ("5900-7500", "5900-8900", "5000-8000", "6000-7500", "6080-7450")):
                            vnc_range_ok = True

        all_ok = (port_5050_ok and vnc_range_ok) or all_port_ok
        missing = []
        if not port_5050_ok and not all_port_ok:
            missing.append("5050 (Painel Web)")
        if not vnc_range_ok and not all_port_ok:
            missing.append("5900-7500 (VNC / Websockify)")

        return {
            "supported": True,
            "ok": all_ok,
            "port_5050": port_5050_ok or all_port_ok,
            "vnc_range": vnc_range_ok or all_port_ok,
            "missing": missing,
            "is_admin": is_admin(),
            "message": "Todas as portas necessárias estão liberadas no Firewall." if all_ok else f"Portas bloqueadas: {', '.join(missing)}"
        }
    except Exception as e:
        logger.warning(f"Erro ao verificar regras do Firewall do Windows: {e}")
        return {
            "supported": True,
            "ok": False,
            "error": str(e),
            "missing": ["5050", "5900-7500"],
            "is_admin": is_admin(),
            "message": f"Falha na checagem: {e}"
        }


def fix_firewall_rules(elevate_if_needed: bool = True) -> Dict[str, Any]:
    """
    Adiciona as regras necessárias no Firewall do Windows:
      - 'Menu Servidor 5050' (TCP 5050)
      - 'Menu VNC Websockify 5900-7500' (TCP 5900-7500)
    Se o processo não for Admin e elevate_if_needed for True, solicita UAC ao usuário via PowerShell.
    """
    if os.name != 'nt':
        return {"success": True, "message": "Ambiente Linux / Não-Windows"}

    if is_admin():
        try:
            cmd1 = ["netsh", "advfirewall", "firewall", "add", "rule", "name=Menu Servidor 5050", "dir=in", "action=allow", "protocol=TCP", "localport=5050"]
            cmd2 = ["netsh", "advfirewall", "firewall", "add", "rule", "name=Menu VNC Websockify 5900-7500", "dir=in", "action=allow", "protocol=TCP", "localport=5900-7500"]
            
            subprocess.run(cmd1, capture_output=True, check=True)
            subprocess.run(cmd2, capture_output=True, check=True)
            logger.info("Regras do Firewall do Windows (5050 e 5900-7500) aplicadas com sucesso!")
            return {"success": True, "message": "Regras do Firewall aplicadas com sucesso!"}
        except Exception as e:
            logger.error(f"Erro ao aplicar regras de Firewall via netsh: {e}")
            return {"success": False, "message": f"Erro: {e}"}

    if elevate_if_needed:
        try:
            ps_script = (
                "Start-Process powershell -Verb RunAs -ArgumentList "
                "'-NoProfile -Command netsh advfirewall firewall add rule name=\"\"Menu Servidor 5050\"\" dir=in action=allow protocol=TCP localport=5050; "
                "netsh advfirewall firewall add rule name=\"\"Menu VNC Websockify 5900-7500\"\" dir=in action=allow protocol=TCP localport=5900-7500'"
            )
            subprocess.Popen(["powershell.exe", "-NoProfile", "-Command", ps_script])
            return {"success": True, "message": "Solicitação de permissão de Administrador enviada (UAC)."}
        except Exception as e:
            return {"success": False, "message": f"Falha ao solicitar elevação UAC: {e}"}

    return {"success": False, "message": "Requer privilégios de Administrador."}


def auto_verify_firewall_on_startup(app_logger: logging.Logger = None):
    """
    Função executada de forma assíncrona na inicialização do backend.
    Verifica o status e tenta auto-corrigir se for Admin ou registra aviso detalhado nos logs.
    """
    active_logger = app_logger or logger

    def _worker():
        time.sleep(1.0) # Espera o boot principal terminar
        status = check_firewall_status()
        if not status.get("supported"):
            return

        if status.get("ok"):
            active_logger.info("🛡️ [FIREWALL] Verificação concluída: Portas 5050 e VNC (5900-7500) liberadas no Firewall do Windows.")
        else:
            missing_str = ", ".join(status.get("missing", []))
            active_logger.warning(
                f"⚠️ [FIREWALL AVISO] Portas não liberadas no Firewall do Windows: {missing_str}. "
                "Outros computadores da rede podem não conseguir acessar o painel ou o Grid VNC."
            )
            if status.get("is_admin"):
                active_logger.info("🛡️ [FIREWALL] Permissão de Administrador detectada. Liberando portas automaticamente...")
                fix_res = fix_firewall_rules(elevate_if_needed=False)
                if fix_res.get("success"):
                    active_logger.info("🛡️ [FIREWALL] Portas liberadas automaticamente com sucesso!")
            else:
                active_logger.info("💡 [FIREWALL DICA] Execute o script 'scratch/allow_firewall.ps1' como Administrador ou use a opção na bandeja do sistema para liberar as portas.")

    t = threading.Thread(target=_worker, daemon=True, name="FirewallCheckWorker")
    t.start()
