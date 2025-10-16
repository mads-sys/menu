#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import sys
import os
import shutil

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

def run_command(command: list, env: dict = None) -> subprocess.CompletedProcess | None:
    """Executa um comando e retorna o objeto de resultado."""
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            env=env,
            check=False
        )
        return result
    except (FileNotFoundError, OSError):
        log(f"Comando '{command[0]}' não encontrado.", "ERROR")
        # Retorna None para indicar que o comando nem sequer foi encontrado.
        return None

def update_apt():
    """Lógica de atualização para sistemas baseados em APT (Debian/Ubuntu)."""
    # Envia a detecção para stdout para que não seja confundida com um aviso ou erro.
    log("Gerenciador de pacotes 'apt' detectado. Iniciando atualização...")
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"

    # Verifica se o apt está em uso por outro processo.
    # Usar 'fuser' é mais portável que 'flock' em alguns sistemas mínimos.
    # fuser retorna 0 (sucesso) se o arquivo estiver em uso.
    fuser_result = run_command(["fuser", "/var/lib/dpkg/lock-frontend"], env)
    if fuser_result and fuser_result.returncode == 0:
        log("ERRO: O gerenciador de pacotes (apt) está bloqueado, possivelmente em uso por outro processo.", "ERROR")
        return False

    log("Passo 1/4: Atualizando lista de pacotes...")
    update_result = run_command(["apt-get", "update"], env)
    if not update_result or update_result.returncode != 0:
        log(f"ERRO: Falha ao executar 'apt-get update'. Detalhes: {update_result.stderr.strip() if update_result else 'Comando não encontrado'}", "ERROR")
        return False

    log("Passo 2/4: Corrigindo dependências quebradas...")
    fix_result = run_command(["apt-get", "--fix-broken", "install", "-y"], env)
    if not fix_result or fix_result.returncode != 0:
        log(f"ERRO: Falha ao executar 'apt-get --fix-broken install'. Detalhes: {fix_result.stderr.strip() if fix_result else 'Comando não encontrado'}", "ERROR")
        return False

    log("Passo 3/4: Atualizando pacotes do sistema...")
    upgrade_cmd = [
        "apt-get", "upgrade", "-y",
        "-o", "Dpkg::Options::=--force-confdef",
        "-o", "Dpkg::Options::=--force-confold"
    ]
    upgrade_result = run_command(upgrade_cmd, env)
    if not upgrade_result or upgrade_result.returncode != 0:
        log(f"ERRO: Falha ao executar 'apt-get upgrade'. Detalhes: {upgrade_result.stderr.strip() if upgrade_result else 'Comando não encontrado'}", "ERROR")
        return False

    log("Passo 4/4: Removendo pacotes desnecessários...")
    autoremove_result = run_command(["apt-get", "autoremove", "-y"], env)
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
    # Usa shutil.which para uma detecção mais robusta do executável no PATH.
    if shutil.which("apt-get"):
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