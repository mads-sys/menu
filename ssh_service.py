# services/ssh_service.py

import posixpath
import stat
import re
import shlex
from contextlib import contextmanager
from typing import List, Dict, Tuple, Optional, Any, Generator

import paramiko
from command_builder import _get_command_builder, _build_gsettings_visibility_command, _parse_system_info, CommandExecutionError


@contextmanager
def ssh_connect(ip: str, username: str, password: Optional[str] = None) -> Generator[paramiko.SSHClient, None, None]:
    """
    Gerencia uma conexão SSH com tratamento de exceções e fechamento automático.
    """
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(ip, username=username, password=password, timeout=10)
        yield ssh
    finally:
        ssh.close()

def _handle_ssh_exception(e: Exception, ip: str, action: str, logger) -> Tuple[Dict[str, Any], int]:
    """Analisa exceções de SSH e retorna uma resposta JSON padronizada."""
    error_str = str(e).lower()
    logger.error(f"Erro de SSH na ação '{action}' em {ip}: {error_str}")

    if isinstance(e, paramiko.AuthenticationException):
        return {"success": False, "message": "Falha na autenticação. Verifique a senha."}, 401

    if "timed out" in error_str or "timeout" in error_str or "connection timed out" in error_str:
        message = "A conexão SSH expirou (timeout)."
        details = "O dispositivo remoto não respondeu a tempo. Verifique se o serviço SSH está ativo e se não há um firewall bloqueando a porta 22."
        return {"success": False, "message": message, "details": details}, 504

    if "host key for server" in error_str and "does not match" in error_str:
        message = "Alerta de segurança: A chave do host mudou."
        details = (f"A chave do host para {ip} é diferente da que está salva em 'known_hosts'. "
                   "Isso pode significar que o sistema operacional foi reinstalado ou, em casos raros, que há um ataque 'man-in-the-middle'.\n\n"
                   f"Para resolver, remova a chave antiga executando no terminal onde o backend está rodando:\nssh-keygen -R {ip}")
        return {"success": False, "message": message, "details": details}, 409

    if "server not found in known_hosts" in error_str:
        message = "Host desconhecido. A chave do servidor não foi encontrada."
        details = f"Por segurança, a conexão foi rejeitada. Para confiar neste host, execute o seguinte comando no terminal onde o backend está rodando e tente novamente:\nssh-keyscan -H {ip} >> ~/.ssh/known_hosts"
        return {"success": False, "message": message, "details": details}, 409

    # Para outros erros de SSH ou exceções genéricas
    logger.error(f"Erro inesperado na ação '{action}' em {ip}: {e}")
    return {"success": False, "message": "Ocorreu um erro interno no servidor.", "details": str(e)}, 500

def _execute_shell_command(ssh: paramiko.SSHClient, command: str, password: str, timeout: int = 20, username: Optional[str] = None) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Executa um comando shell via SSH, tratando sudo e separando warnings de erros.
    """
    if username:
        final_command = f"sudo -S -u {username} bash -c {shlex.quote(command)}"
    else:
        base_cmd = command if command.strip().startswith("sudo -S") else f"sudo -S {command}"
        final_command = f"bash -c {shlex.quote(base_cmd)}"

    stdin, stdout, stderr = ssh.exec_command(final_command, timeout=timeout)

    if "sudo -S" in final_command:
        stdin.write(password + '\n')
        stdin.flush()

    exit_status = stdout.channel.recv_exit_status()
    output = stdout.read().decode('utf-8', errors='ignore').strip()
    error_output = stderr.read().decode('utf-8', errors='ignore').strip()

    sudo_prompt_regex = r'\[sudo\] (senha|password) para .*:'
    cleaned_error_output = re.sub(sudo_prompt_regex, '', error_output).strip()

    all_error_lines = cleaned_error_output.splitlines()
    warnings = [line for line in all_error_lines if line.strip().startswith('W:')]
    errors = [line for line in all_error_lines if not line.strip().startswith('W:') and line.strip()]

    if exit_status != 0:
        error_details = "\n".join(errors) if errors else cleaned_error_output
        raise CommandExecutionError(
            message=f"O comando falhou com o código de saída {exit_status}.",
            details=error_details,
            warnings="\n".join(warnings) if warnings else None
        )

    return output, "\n".join(warnings) if warnings else None, None

def _get_remote_desktop_path(ssh: paramiko.SSHClient, sftp: paramiko.SFTPClient, username: str) -> Optional[str]:
    """Descobre o caminho da Área de Trabalho na máquina remota."""
    _, stdout, _ = ssh.exec_command(f"sudo -u {username} xdg-user-dir DESKTOP")
    desktop_path = stdout.read().decode(errors='ignore').strip()
    if desktop_path and not desktop_path.startswith('/'):
        home_dir = sftp.normalize('.')
        desktop_path = posixpath.join(home_dir, desktop_path)

    if not desktop_path:
        home_dir = sftp.normalize('.')
        possible_dirs = ["Área de Trabalho", "Desktop", "Área de trabalho", "Escritorio"]
        for p_dir in possible_dirs:
            full_path = posixpath.join(home_dir, p_dir)
            try:
                sftp.stat(full_path)
                desktop_path = full_path
                break
            except FileNotFoundError:
                continue
    return desktop_path

def _normalize_shortcut_name(filename: str) -> str:
    """Normaliza o nome de um atalho removendo dígitos para permitir correspondência flexível."""
    if not filename.endswith('.desktop'):
        return filename
    name_part = filename[:-len('.desktop')]
    normalized_name_part = re.sub(r'[-_]?\d+$', '', name_part)
    if not normalized_name_part.strip(' -_'):
        return filename
    return normalized_name_part + ".desktop"

def sftp_disable_shortcuts(ssh: paramiko.SSHClient, username: str, backup_root_dir: str) -> Tuple[str, Optional[str]]:
    """Desativa atalhos usando SFTP para mover os arquivos."""
    with ssh.open_sftp() as sftp:
        desktop_path = _get_remote_desktop_path(ssh, sftp, username)
        if not desktop_path:
            return "ERRO: Nenhum diretório de Área de Trabalho válido foi encontrado.", None

        home_dir = sftp.normalize('.')
        backup_root = posixpath.join(home_dir, backup_root_dir)
        desktop_basename = posixpath.basename(desktop_path)
        backup_subdir = posixpath.join(backup_root, desktop_basename)

        try: sftp.mkdir(backup_root)
        except IOError: pass
        try: sftp.mkdir(backup_subdir)
        except IOError: pass

        files_moved = 0
        for filename in sftp.listdir(desktop_path):
            if filename.endswith('.desktop'):
                source = posixpath.join(desktop_path, filename)
                destination = posixpath.join(backup_subdir, filename)
                sftp.rename(source, destination)
                files_moved += 1

    return f"Operação de desativação concluída. {files_moved} atalhos movidos para backup.", None

def sftp_restore_shortcuts(ssh: paramiko.SSHClient, username: str, backup_files_to_match: List[str], backup_root_dir: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Restaura atalhos selecionados usando SFTP com correspondência flexível."""
    with ssh.open_sftp() as sftp:
        desktop_path = _get_remote_desktop_path(ssh, sftp, username)
        if not desktop_path:
            return "ERRO: Nenhum diretório de Área de Trabalho válido foi encontrado para restauração.", None, None

        home_dir = sftp.normalize('.')
        backup_root = posixpath.join(home_dir, backup_root_dir)
        files_restored, errors, warnings = 0, [], []

        available_backups_map = {}
        try:
            for directory_name in sftp.listdir(backup_root):
                backup_dir_path = posixpath.join(backup_root, directory_name)
                if not stat.S_ISDIR(sftp.lstat(backup_dir_path).st_mode): continue
                for filename in sftp.listdir(backup_dir_path):
                    if filename.endswith('.desktop'):
                        normalized_name = _normalize_shortcut_name(filename)
                        normalized_path = posixpath.join(directory_name, normalized_name)
                        real_path = posixpath.join(directory_name, filename)
                        available_backups_map[normalized_path] = real_path
        except FileNotFoundError:
            return f"ERRO: Diretório de backup '{backup_root_dir}' não encontrado.", None, None

        for path_from_request in backup_files_to_match:
            dir_name = posixpath.dirname(path_from_request)
            file_name = posixpath.basename(path_from_request)
            normalized_file_name = _normalize_shortcut_name(file_name)
            lookup_key = posixpath.join(dir_name, normalized_file_name)
            real_path_to_restore = available_backups_map.get(lookup_key)

            if real_path_to_restore:
                filename_to_restore = posixpath.basename(real_path_to_restore)
                source = posixpath.join(backup_root, real_path_to_restore)
                destination = posixpath.join(desktop_path, filename_to_restore)
                try:
                    sftp.rename(source, destination)
                    files_restored += 1
                except IOError as e:
                    errors.append(f"Falha ao restaurar {filename_to_restore}: {e}")
            else:
                warnings.append(f"Atalho '{file_name}' não encontrado no backup desta máquina.")

    message = f"Restauração concluída. {files_restored} atalhos restaurados."
    return message, "\n".join(errors) if errors else None, "\n".join(warnings) if warnings else None

def list_sftp_backups(ssh: paramiko.SSHClient, backup_root_dir: str) -> Dict[str, List[str]]:
    """Lista os backups de atalhos disponíveis via SFTP."""
    with ssh.open_sftp() as sftp:
        home_dir = sftp.normalize('.')
        backup_root = posixpath.join(home_dir, backup_root_dir)
        try:
            sftp.stat(backup_root)
        except FileNotFoundError:
            return {}

        backup_dirs = [d for d in sftp.listdir(backup_root) if stat.S_ISDIR(sftp.stat(posixpath.join(backup_root, d)).st_mode)]
        backups_by_dir = {}
        for directory in backup_dirs:
            dir_path = posixpath.join(backup_root, directory)
            files = [f for f in sftp.listdir(dir_path) if f.endswith('.desktop')]
            if files:
                backups_by_dir[directory] = files
        return backups_by_dir

def _handle_sftp_action(ssh: paramiko.SSHClient, username: str, action: str, data: Dict[str, Any], backup_root_dir: str):
    """Lida com ações que usam o protocolo SFTP (desativar/ativar atalhos)."""
    password = data.get('password')
    
    if action == 'desativar':
        sftp_message, sftp_details = sftp_disable_shortcuts(ssh, username, backup_root_dir)
        if "ERRO:" in sftp_message:
            return {"success": False, "message": sftp_message, "details": sftp_details}

        hide_icons_command = _build_gsettings_visibility_command(False)
        gsettings_output, gsettings_warnings, gsettings_errors = _execute_shell_command(ssh, hide_icons_command, password, username=username)

        final_messages = [sftp_message]
        all_details, success = [], True
        if gsettings_errors:
            success = False
            final_messages.append("Falha ao ocultar ícones do sistema.")
            all_details.append(f"Erros (ícones do sistema): {gsettings_errors}")
        else:
            final_messages.append(gsettings_output)
        if sftp_details: all_details.append(f"Detalhes (atalhos): {sftp_details}")
        if gsettings_warnings: all_details.append(f"Avisos (ícones do sistema): {gsettings_warnings}")

        return {"success": success, "message": " ".join(final_messages), "details": "\n".join(all_details) if all_details else None}

    elif action == 'ativar':
        backup_files = data.get('backup_files', [])
        if not backup_files:
            return {"success": False, "message": "Nenhum atalho selecionado para restauração."}

        # Passo 1: Restaurar atalhos da área de trabalho via SFTP.
        sftp_message, sftp_errors, sftp_warnings = sftp_restore_shortcuts(ssh, username, backup_files, backup_root_dir)
        
        # Passo 2 (Removido): A reativação dos ícones do sistema foi removida para atender à solicitação.
        # Agora, esta ação restaura apenas os atalhos selecionados.

        # Passo 3: Combinar os resultados da operação.
        all_details, success = [], True
        if sftp_errors or "ERRO:" in sftp_message:
            success = False

        if sftp_warnings: all_details.append(f"Avisos (restauração): {sftp_warnings}")
        if sftp_errors: all_details.append(f"Erros (restauração): {sftp_errors}")

        return {"success": success, "message": sftp_message, "details": "\n".join(all_details) if all_details else None}

    return {"success": False, "message": "Ação SFTP interna desconhecida."}

def _handle_set_wallpaper(ssh: paramiko.SSHClient, username: str, data: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[str]]:
    """Faz o upload de uma imagem e a define como papel de parede."""
    from command_builder import GSETTINGS_ENV_SETUP # Importação local para evitar ciclo
    wallpaper_data_url = data.get('wallpaper_data')
    wallpaper_filename = data.get('wallpaper_filename')
    password = data.get('password')

    if not all([wallpaper_data_url, wallpaper_filename, password]):
        raise CommandExecutionError("Dados da imagem, nome do arquivo e senha são necessários.")

    try:
        encoded_data = wallpaper_data_url.split(",", 1)[1]
    except IndexError:
        raise CommandExecutionError("Formato de Data URL inválido.")

    safe_b64_data = shlex.quote(encoded_data)
    safe_filename = shlex.quote(wallpaper_filename)
    upload_and_set_script = f"""
        mkdir -p "$HOME/Imagens"
        FILENAME={safe_filename}
        REMOTE_PATH="$HOME/Imagens/$FILENAME"
        echo {safe_b64_data} | base64 --decode > "$REMOTE_PATH"
        URI="file://$REMOTE_PATH"
        SAFE_URI_ARG=$(printf %q "$URI")
        if gsettings list-schemas | grep -q 'org.cinnamon.desktop.background'; then
            gsettings set org.cinnamon.desktop.background picture-uri "$SAFE_URI_ARG"
            echo "Papel de parede definido com sucesso (Cinnamon)."
        elif gsettings list-schemas | grep -q 'org.gnome.desktop.background'; then
            gsettings set org.gnome.desktop.background picture-uri "$SAFE_URI_ARG"
            echo "Papel de parede definido com sucesso (GNOME Fallback)."
        else
            echo "Erro: Nenhum schema de papel de parede compatível (Cinnamon ou GNOME) foi encontrado." >&2
            exit 1
        fi
    """
    command = GSETTINGS_ENV_SETUP + upload_and_set_script
    return _execute_shell_command(ssh, command, password, username=username)

def _execute_for_each_user(ssh: paramiko.SSHClient, action: str, data: Dict[str, Any], logger) -> Tuple[Dict[str, Any], int]:
    """Encontra e executa uma ação para cada usuário na máquina remota."""
    list_users_cmd = r"getent passwd | awk -F: '$6 ~ /^\/home\// && $7 !~ /nologin|false/ {print $1}'"
    _, stdout, stderr = ssh.exec_command(list_users_cmd)
    users = stdout.read().decode().strip().splitlines()
    err = stderr.read().decode().strip()

    if err or not users:
        return {"success": False, "message": "Não foi possível encontrar usuários na máquina remota.", "details": err}, 500

    results = {}
    sftp_shortcut_actions = ['desativar', 'ativar']
    backup_root_dir = data.get('backup_root_dir', 'atalhos_desativados')

    for user in users:
        try:
            if action == 'definir_papel_de_parede':
                message, warnings, errors = _handle_set_wallpaper(ssh, user, data)
                success = not errors
                details = []
                if warnings: details.append(f"Warnings: {warnings}")
                if errors: details.append(f"Errors: {errors}")
                result = {"success": success, "message": message, "details": "\n".join(details) if details else None}
            elif action in sftp_shortcut_actions:
                result = _handle_sftp_action(ssh, user, action, data, backup_root_dir)
            else:
                # A função de manipulação é passada no dicionário 'data' para evitar
                # uma dependência de importação circular com o app.py.
                result = data['shell_action_handler'](ssh, user, action, data)
            results[user] = result
        except CommandExecutionError as e:
            logger.error(f"Erro na ação '{action}' para o usuário '{user}': {e.details}")
            details = []
            if e.warnings: details.append(f"Avisos: {e.warnings}")
            if e.details: details.append(f"Erros: {e.details}")
            results[user] = {"success": False, "message": "Ocorreu um erro no dispositivo remoto.", "details": "\n".join(details)}
        except Exception as e:
            logger.error(f"Erro inesperado na ação '{action}' para o usuário '{user}': {e}")
            results[user] = {"success": False, "message": "Erro inesperado no servidor.", "details": str(e)}

    final_success = all(r.get('success', False) for r in results.values())
    final_message = f"Ação '{action}' executada para {len(users)} usuário(s)."
    details_list = [f"Usuário '{u}': {r.get('message')} {r.get('details') or ''}".strip() for u, r in results.items()]
    final_details = "\n".join(details_list)

    return {"success": final_success, "message": final_message, "details": final_details}, 200 if final_success else 500