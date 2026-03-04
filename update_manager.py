#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import sys
import os
import shutil
import re
import time
from typing import Optional

def log(message: str, level: str = "INFO"):
    """Imprime mensagens para o stdout ou stderr."""
    # Avisos (warnings) são enviados para stderr para serem capturados como 'details'.
    if level == "WARN":
        print(f"W: {message}", file=sys.stderr)
    # Erros fatais também vão para stderr e devem levar à saída do script.
    elif level == "ERROR":
        print(f"{message}", file=sys.stderr)
    # Mensagens de sucesso/info vão para stdout para serem capturadas como a mensagem principal.
    else:
        print(message)

def run_command(command: list, env: dict = None) -> Optional[subprocess.CompletedProcess]:
    """Executa um comando e retorna o objeto de resultado."""
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace', # Evita crash se a saída tiver caracteres inválidos
            env=env,
            check=False
        )
        return result
    except Exception as e:
        log(f"Erro na execução do comando '{command[0]}': {e}", "ERROR")
        # Retorna None para indicar que o comando nem sequer foi encontrado.
        return None

def wait_for_lock(lock_path: str, env: dict, timeout: int = 60) -> bool:
    """Aguarda a liberação de um arquivo de bloqueio (lock file)."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        # fuser retorna 0 se o arquivo estiver em uso, 1 se estiver livre.
        fuser_result = run_command(["fuser", lock_path], env)
        
        # Se fuser falhar (comando não encontrado) ou retornar != 0 (arquivo livre), prossegue.
        if not fuser_result or fuser_result.returncode != 0:
            return True
            
        log(f"Aguardando liberação do bloqueio {lock_path}...", "INFO")
        time.sleep(5)
    
    return False

def update_apt():
    """Lógica de atualização para sistemas baseados em APT (Debian/Ubuntu)."""
    log("Gerenciador de pacotes 'apt' detectado. Iniciando atualização...", "INFO")

    # Verifica se uma reinicialização é necessária antes de começar.
    if os.path.exists("/var/run/reboot-required"):
        log("O sistema tem uma reinicialização pendente. É recomendado reiniciar antes de aplicar novas atualizações.", "WARN")

    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"

    # Verifica se o apt está em uso por outro processo.
    # Usar 'fuser' é mais portável que 'flock' em alguns sistemas mínimos.
    # fuser retorna 0 (sucesso) se o arquivo estiver em uso.
    fuser_result = run_command(["fuser", "/var/lib/dpkg/lock-frontend"], env)
    if fuser_result and fuser_result.returncode == 0:
        log("ERRO: O gerenciador de pacotes (apt) está bloqueado, possivelmente em uso por outro processo.", "ERROR")
    if not wait_for_lock("/var/lib/dpkg/lock-frontend", env, timeout=60):
        log("ERRO: O gerenciador de pacotes (apt) está bloqueado por muito tempo. Abortando.", "ERROR")
        return False

    log("Passo 1/5: Corrigindo instalações interrompidas (dpkg)...")
    dpkg_result = run_command(["dpkg", "--configure", "-a"], env)
    if not dpkg_result or dpkg_result.returncode != 0:
        log(f"AVISO: Falha ao executar 'dpkg --configure -a'. Detalhes: {dpkg_result.stderr.strip() if dpkg_result else 'Comando não encontrado'}", "WARN")

    log("Passo 2/5: Atualizando lista de pacotes...")
    update_result = run_command(["apt-get", "update", "-y"], env)
    if not update_result or update_result.returncode != 0:
        log(f"ERRO: Falha ao executar 'apt-get update'. Detalhes: {update_result.stderr.strip() if update_result else 'Comando não encontrado'}", "ERROR")
        return False

    log("Passo 3/5: Corrigindo dependências quebradas...")
    fix_cmd = [
        "apt-get", "--fix-broken", "install", "-y",
        "-o", "Dpkg::Options::=--force-confdef",
        "-o", "Dpkg::Options::=--force-confold"
    ]
    fix_result = run_command(fix_cmd, env)
    if not fix_result or fix_result.returncode != 0:
        stderr_output = fix_result.stderr.strip() if fix_result else "Comando não encontrado"
        
        # Procura pelo erro específico de pacote que precisa ser reinstalado mas não é encontrado.
        match = re.search(r"O pacote (.*?) precisa ser reinstalado, mas não foi possível encontrar um arquivo para o mesmo.", stderr_output)

        if match:
            # Extrai apenas o nome do pacote, ignorando informações de versão, etc.
            broken_package = match.group(1).strip().split()[0]
            log(f"AVISO: Detectado pacote quebrado '{broken_package}' que não pode ser reinstalado. Tentando remover forçadamente...", "WARN")
            
            # Usa dpkg para forçar a remoção, que é mais robusto para este tipo de erro.
            remove_cmd = ["dpkg", "--remove", "--force-remove-reinstreq", broken_package]
            remove_result = run_command(remove_cmd, env)

            if remove_result and remove_result.returncode == 0:
                log(f"Pacote '{broken_package}' removido com sucesso. Tentando corrigir dependências novamente.", "INFO")
                # Tenta executar o --fix-broken install novamente.
                fix_result_retry = run_command(fix_cmd, env)
                if not fix_result_retry or fix_result_retry.returncode != 0:
                    log(f"ERRO: Falha ao corrigir dependências mesmo após remover '{broken_package}'. Detalhes: {fix_result_retry.stderr.strip() if fix_result_retry else 'Comando não encontrado'}", "ERROR")
                    return False
                log("Dependências corrigidas com sucesso após remoção do pacote quebrado.", "INFO")
            else:
                log(f"ERRO: Falha ao remover o pacote quebrado '{broken_package}'. Detalhes: {remove_result.stderr.strip() if remove_result else 'Comando não encontrado'}", "ERROR")
                return False
        else:
            log(f"ERRO: Falha ao executar 'apt-get --fix-broken install'. Detalhes: {stderr_output}", "ERROR")
            return False

    log("Passo 4/5: Atualizando pacotes do sistema...")
    # Usa 'dist-upgrade' em vez de 'upgrade' para uma atualização mais completa.
    # 'dist-upgrade' pode instalar ou remover pacotes para resolver dependências complexas.
    upgrade_cmd = [
        "apt-get", "dist-upgrade", "-y",
        "-o", "Dpkg::Options::=--force-confdef",
        "-o", "Dpkg::Options::=--force-confold"
    ]
    upgrade_result = run_command(upgrade_cmd, env)
    if not upgrade_result or upgrade_result.returncode != 0:
        log(f"ERRO: Falha ao executar 'apt-get upgrade'. Detalhes: {upgrade_result.stderr.strip() if upgrade_result else 'Comando não encontrado'}", "ERROR")
        return False

    log("Passo 5/5: Removendo pacotes desnecessários...")
    autoremove_result = run_command(["apt-get", "autoremove", "--purge", "-y"], env)
    if not autoremove_result or autoremove_result.returncode != 0:
        # Um aviso é mais apropriado aqui, pois a falha no autoremove não é crítica.
        log(f"Falha ao executar 'apt-get autoremove'. Detalhes: {autoremove_result.stderr.strip() if autoremove_result else 'Comando não encontrado'}", "WARN")
        return False

    log("Sistema atualizado com sucesso.")
    return True

def update_dnf():
    """Lógica de atualização para sistemas baseados em DNF (Fedora/CentOS 8+)."""
    # Envia a detecção para stdout.
    log("Gerenciador de pacotes 'dnf' detectado.")
    result = run_command(["dnf", "upgrade", "-y"])
    if not result or result.returncode != 0:
        log(f"ERRO: Falha ao executar 'dnf upgrade'. Detalhes: {result.stderr.strip() if result else 'Comando não encontrado'}", "ERROR")
        return False
    log("Sistema (DNF) atualizado com sucesso.")
    return True

def update_yum():
    """Lógica de atualização para sistemas baseados em YUM (CentOS 7)."""
    # Envia a detecção para stdout.
    log("Gerenciador de pacotes 'yum' detectado.")
    result = run_command(["yum", "update", "-y"])
    if not result or result.returncode != 0:
        log(f"ERRO: Falha ao executar 'yum update'. Detalhes: {result.stderr.strip() if result else 'Comando não encontrado'}", "ERROR")
        return False
    log("Sistema (YUM) atualizado com sucesso.")
    return True

def update_pacman():
    """Lógica de atualização para sistemas baseados em Pacman (Arch Linux)."""
    # Envia a detecção para stdout.
    log("Gerenciador de pacotes 'pacman' detectado.")
    if os.path.exists("/var/lib/pacman/db.lck"):
        log("ERRO: Lock do Pacman ('db.lck') encontrado. Outro processo pode estar em execução.", "ERROR")
        return False
    result = run_command(["pacman", "-Syu", "--noconfirm"])
    if not result or result.returncode != 0:
        log(f"ERRO: Falha ao executar 'pacman -Syu'. Detalhes: {result.stderr.strip() if result else 'Comando não encontrado'}", "ERROR")
        return False
    log("Sistema (Pacman) atualizado com sucesso.")
    return True

def main():
    """Detecta o gerenciador de pacotes e executa a atualização."""
    if shutil.which("apt-get"): # Usa shutil.which para uma detecção mais robusta.
        if not update_apt(): sys.exit(1)
    elif shutil.which("dnf"):
        if not update_dnf(): sys.exit(1)
    elif shutil.which("yum"):
        if not update_yum(): sys.exit(1)
    elif shutil.which("pacman"):
        if not update_pacman(): sys.exit(1)
    else:
        log("ERRO: Nenhum gerenciador de pacotes suportado (apt, dnf, yum, pacman) foi encontrado.", "ERROR")
        sys.exit(1)

if __name__ == "__main__":
    main()