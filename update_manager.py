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
    """Imprime mensagens formatadas para o stdout ou stderr, com base no nível."""
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

def update_apt(env: dict) -> bool:
    """Lógica de atualização para sistemas baseados em APT (Debian/Ubuntu/Linux Mint)."""
    log("Gerenciador de pacotes 'apt' detectado. Iniciando atualização...", "INFO")

    # Verifica se uma reinicialização é necessária antes de começar.
    if os.path.exists("/var/run/reboot-required"):
        log("O sistema tem uma reinicialização pendente. É recomendado reiniciar antes de aplicar novas atualizações.", "WARN")

    # Verifica se o apt está em uso por outro processo.
    if not wait_for_lock("/var/lib/dpkg/lock-frontend", env, timeout=60):
        log("ERRO: O gerenciador de pacotes (apt) está bloqueado por muito tempo. Abortando.", "ERROR")
        return False

    log("Passo 1/6: Corrigindo instalações interrompidas (dpkg)...")
    dpkg_result = run_command(["dpkg", "--configure", "-a"], env)
    if not dpkg_result or dpkg_result.returncode != 0:
        log(f"AVISO: Falha ao executar 'dpkg --configure -a'. Detalhes: {dpkg_result.stderr.strip() if dpkg_result else 'Comando não encontrado'}", "WARN")

    log("Passo 2/6: Atualizando lista de pacotes...")
    update_result = run_command(["apt-get", "update", "-y"], env)
    if not update_result or update_result.returncode != 0:
        log(f"ERRO: Falha ao executar 'apt-get update'. Detalhes: {update_result.stderr.strip() if update_result else 'Comando não encontrado'}", "ERROR")
        return False

    log("Passo 3/6: Corrigindo dependências quebradas...")
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

    log("Passo 4/6: Aplicando atualizações de pacotes (upgrade)...")
    upgrade_cmd = [
        "apt-get", "upgrade", "-y",
        "-o", "APT::Get::Always-Include-Phased-Updates=true",
        "-o", "Dpkg::Options::=--force-confdef",
        "-o", "Dpkg::Options::=--force-confold"
    ]
    run_command(upgrade_cmd, env)

    log("Passo 5/6: Atualizando pacotes do sistema e firmware (dist-upgrade)...")
    dist_cmd = [
        "apt-get", "dist-upgrade", "-y",
        "-o", "APT::Get::Always-Include-Phased-Updates=true",
        "-o", "Dpkg::Options::=--force-confdef",
        "-o", "Dpkg::Options::=--force-confold"
    ]
    dist_result = run_command(dist_cmd, env)
    if not dist_result or dist_result.returncode != 0:
        log(f"ERRO: Falha ao executar 'apt-get dist-upgrade'. Detalhes: {dist_result.stderr.strip() if dist_result else 'Comando não entrecontrado'}", "ERROR")
        return False

    # Passo 5.1: Força a atualização de linux-firmware que possa ter ficado pendente
    log("Passo 5.1/6: Garantindo atualização do linux-firmware e drivers retidos...")
    firmware_cmd = [
        "apt-get", "install", "-y",
        "-o", "APT::Get::Always-Include-Phased-Updates=true",
        "-o", "Dpkg::Options::=--force-confdef",
        "-o", "Dpkg::Options::=--force-confold",
        "linux-firmware"
    ]
    run_command(firmware_cmd, env)

    log("Passo 6/6: Removendo pacotes desnecessários...")
    autoremove_result = run_command(["apt-get", "autoremove", "--purge", "-y"], env)
    if not autoremove_result or autoremove_result.returncode != 0:
        log(f"Falha ao executar 'apt-get autoremove'. Detalhes: {autoremove_result.stderr.strip() if autoremove_result else 'Comando não encontrado'}", "WARN")

    run_command(["apt-get", "autoclean"], env)
    log("Pacotes APT atualizados com sucesso.", "INFO")
    return True

def update_flatpak(env: dict):
    """Atualiza aplicativos e runtimes Flatpak se o suporte a Flatpak estiver instalado."""
    if shutil.which("flatpak"):
        log("Gerenciador 'flatpak' detectado. Atualizando aplicativos Flatpak...", "INFO")
        res = run_command(["flatpak", "update", "-y"], env)
        if not res or res.returncode != 0:
            log(f"AVISO: Falha ao atualizar pacotes Flatpak. Detalhes: {res.stderr.strip() if res else ''}", "WARN")
        else:
            log("Aplicativos Flatpak atualizados com sucesso.", "INFO")

        # Remove runtimes e dependências não utilizadas do Flatpak
        run_command(["flatpak", "uninstall", "--unused", "-y"], env)

def update_snap(env: dict):
    """Atualiza aplicativos Snap se o suporte a Snap estiver instalado."""
    if shutil.which("snap"):
        log("Gerenciador 'snap' detectado. Atualizando pacotes Snap...", "INFO")
        res = run_command(["snap", "refresh"], env)
        if not res or res.returncode != 0:
            log(f"AVISO: Falha ao atualizar pacotes Snap. Detalhes: {res.stderr.strip() if res else ''}", "WARN")
        else:
            log("Pacotes Snap atualizados com sucesso.", "INFO")

def update_mintupdate(env: dict):
    """Atualiza pacotes via CLI do Linux Mint Update Manager e sincroniza o cache da GUI."""
    if shutil.which("mintupdate-cli"):
        log("Gerenciador 'mintupdate-cli' detectado. Sincronizando com o Gerenciador de Atualizações do Mint...", "INFO")
        res = run_command(["mintupdate-cli", "upgrade", "-y", "-r"], env)
        if not res or res.returncode != 0:
            run_command(["mintupdate-cli", "upgrade", "-y"], env)
        log("Gerenciador de Atualizações do Mint sincronizado com sucesso.", "INFO")

def update_firmware(env: dict):
    """Verifica atualizações de firmware do sistema via fwupdmgr."""
    if shutil.which("fwupdmgr"):
        log("Verificando atualizações de firmware do sistema (fwupdmgr)...", "INFO")
        run_command(["fwupdmgr", "refresh"], env)
        res = run_command(["fwupdmgr", "update", "-y"], env)
        if res and res.returncode == 0:
            log("Firmware de dispositivos atualizado com sucesso.", "INFO")

def update_dnf() -> bool:
    """Lógica de atualização para sistemas baseados em DNF (Fedora/CentOS 8+)."""
    log("Gerenciador de pacotes 'dnf' detectado.")
    result = run_command(["dnf", "upgrade", "-y"])
    if not result or result.returncode != 0:
        log(f"ERRO: Falha ao executar 'dnf upgrade'. Detalhes: {result.stderr.strip() if result else 'Comando não encontrado'}", "ERROR")
        return False
    log("Sistema (DNF) atualizado com sucesso.")
    return True

def update_yum() -> bool:
    """Lógica de atualização para sistemas baseados em YUM (CentOS 7)."""
    log("Gerenciador de pacotes 'yum' detectado.")
    result = run_command(["yum", "update", "-y"])
    if not result or result.returncode != 0:
        log(f"ERRO: Falha ao executar 'yum update'. Detalhes: {result.stderr.strip() if result else 'Comando não encontrado'}", "ERROR")
        return False
    log("Sistema (YUM) atualizado com sucesso.")
    return True

def update_pacman() -> bool:
    """Lógica de atualização para sistemas baseados em Pacman (Arch Linux)."""
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
    """Detecta o gerenciador de pacotes e executa a atualização completa do sistema."""
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"

    success = False
    if shutil.which("apt-get"):
        success = update_apt(env)
    elif shutil.which("dnf"):
        success = update_dnf()
    elif shutil.which("yum"):
        success = update_yum()
    elif shutil.which("pacman"):
        success = update_pacman()
    else:
        log("ERRO: Nenhum gerenciador de pacotes suportado (apt, dnf, yum, pacman) foi encontrado.", "ERROR")
        sys.exit(1)

    if not success:
        sys.exit(1)

    # Atualiza ecossistemas adicionais (Flatpak, Snap, Linux Mint Update Manager, Firmware)
    update_mintupdate(env)
    update_flatpak(env)
    update_snap(env)
    update_firmware(env)

    log("Processo de atualização do sistema concluído com sucesso!")

if __name__ == "__main__":
    main()