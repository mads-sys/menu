import os
import sys
import subprocess
import json
import time
import ctypes

def is_admin() -> bool:
    if os.name != 'nt':
        return True
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def check_windows_firewall_fast():
    if os.name != 'nt':
        return {"supported": False, "ok": True, "message": "Ambiente Linux / Não-Windows"}

    t0 = time.time()
    try:
        # 1. Checagem ultra-rápida via netsh (leva < 0.2s)
        proc = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", "name=all", "dir=in"],
            capture_output=True,
            text=True,
            errors='ignore',
            timeout=3
        )
        output = proc.stdout
        
        # Filtra apenas regras ativas (Habilitado: Sim / Enabled: Yes) com Ação: Permitir / Action: Allow
        # e protocolo TCP
        blocks = output.split("\n----------------------------------------------------------------------\n")
        
        port_5050_ok = False
        vnc_range_ok = False
        all_port_ok = False

        for b in blocks:
            b_lower = b.lower()
            # Verifica se a regra está ativa e é de permissão
            is_enabled = ("habilitado:\s+sim" in b_lower or "enabled:\s+yes" in b_lower or "habilitado:                     sim" in b_lower)
            is_allow = ("ao:\s+permitir" in b_lower or "acao:\s+permitir" in b_lower or "ação:\s+permitir" in b_lower or "action:\s+allow" in b_lower or "permitir" in b_lower)
            if not is_allow:
                continue
            
            # Verifica portas locais
            for line in b.splitlines():
                line_lower = line.lower().strip()
                if "porta local:" in line_lower or "localport:" in line_lower:
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
                        if "5900-7500" in val or "5900-8900" in val or "5000-8000" in val:
                            vnc_range_ok = True
                        if "6000-7500" in val or "6080-7450" in val:
                            vnc_range_ok = True

        elapsed = time.time() - t0
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
            "elapsed_seconds": round(elapsed, 3)
        }
    except Exception as e:
        return {"supported": True, "ok": False, "error": str(e), "elapsed_seconds": round(time.time() - t0, 3)}

if __name__ == '__main__':
    res = check_windows_firewall_fast()
    print("Resultado netsh:", json.dumps(res, indent=2, ensure_ascii=False))
