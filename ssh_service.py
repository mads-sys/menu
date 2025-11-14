# services/ssh_service.py

import posixpath
import subprocess
import stat
import re
import shlex
import base64
import binascii
from contextlib import contextmanager
from typing import List, Dict, Tuple, Optional, Any, Generator

import paramiko
from command_builder import _get_command_builder, _build_gsettings_visibility_command, _parse_system_info, CommandExecutionError
COMMANDS = {} # Adicionado para evitar erro de importação circular se não for usado

def _fix_host_key(ip: str, logger) -> bool:
    """Executa 'ssh-keygen -R <ip>' para remover uma chave de host antiga."""
    try:
        command = ["ssh-keygen", "-R", ip]
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
        if result.returncode == 0:
            logger.info(f"Chave SSH para {ip} removida automaticamente com sucesso.")
            return True
        else:
            logger.error(f"Falha ao remover automaticamente a chave SSH para {ip}: {result.stderr.strip()}")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        logger.error(f"Exceção ao tentar remover a chave SSH para {ip}: {e}")
        return False

@contextmanager
def ssh_connect(ip: str, username: str, password: str, logger, auto_fix_key: bool = True) -> Generator[paramiko.SSHClient, None, None]:
    """
    Gerencia uma conexão SSH com tratamento de exceções e fechamento automático.
    Inclui lógica para corrigir automaticamente chaves de host inválidas e tentar novamente.
    """
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(ip, username=username, password=password, timeout=10)
        yield ssh
    except paramiko.SSHException as e:
        # Verifica se é um erro de chave de host e se a correção automática está habilitada.
        error_str = str(e).lower()
        is_key_error = "host key for server" in error_str and "does not match" in error_str

        if is_key_error and auto_fix_key:
            logger.warning(f"Chave de host para {ip} inválida. Tentando corrigir automaticamente...")
            if _fix_host_key(ip, logger):
                # Tenta reconectar após a correção.
                logger.info(f"Tentando reconectar a {ip} após a correção da chave...")
                ssh.connect(ip, username=username, password=password, timeout=10)
                yield ssh # Se a reconexão for bem-sucedida, continua.
            else:
                raise e # Se a correção falhar, relança a exceção original.
        else:
            raise e # Relança para outros erros de SSH ou se a correção automática estiver desabilitada.
    finally:
        ssh.close()

def _handle_ssh_exception(e: Exception, ip: str, action: str, logger) -> Tuple[Dict[str, Any], int]:
    """Analisa exceções de SSH e retorna uma resposta JSON padronizada."""
    error_str = str(e).lower()
    logger.error(f"Erro de SSH na ação '{action}' em {ip}: {error_str}")

    if isinstance(e, paramiko.AuthenticationException) or "authentication failed" in error_str:
        return {"success": False, "message": "Falha na autenticação. Verifique a senha."}, 401

    if "timed out" in error_str or "timeout" in error_str or "connection timed out" in error_str:
        message = "A conexão SSH expirou (timeout)."
        details = "O dispositivo remoto não respondeu a tempo. Verifique se o serviço SSH está ativo e se não há um firewall bloqueando a porta 22."
        return {"success": False, "message": message, "details": details}, 504

    if "host key for server" in error_str and "does not match" in error_str:
        message = "Alerta de segurança: A chave do host mudou."
        details = (f"A chave do host para {ip} é diferente da que está salva em 'known_hosts'. "
                   "A correção automática falhou. Isso pode significar que o sistema operacional foi reinstalado ou, em casos raros, que há um ataque 'man-in-the-middle'.\n\n"
                   f"Para resolver manualmente, execute no terminal do servidor: ssh-keygen -R {ip}")
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
        # Para scripts multi-linha (como o de atualização) ou comandos simples,
        # esta abordagem é a mais robusta. O sudo eleva o bash, que então executa o comando.
        # A flag -H garante que o $HOME seja o do root, evitando problemas de permissão.
        final_command = f"sudo -S -H -p '' bash -c {shlex.quote(command)}"

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

def _stream_shell_command(ssh: paramiko.SSHClient, command: str, password: str, timeout: int = 300) -> Generator[str, None, int]:
    """
    Executa um comando shell via SSH e transmite a saída (stdout e stderr) em tempo real.
    Retorna o código de saída do comando.
    """
    # Se o comando for um script multi-linha (como o de atualização), ele já será
    # complexo. Se for um comando simples, garantimos que 'sudo -S' seja adicionado.
    if '\n' in command or "sudo -S" in command:
        # Para scripts multi-linha ou que já contêm sudo, o sudo deve envolver o bash.
        # A flag -H é importante para definir a variável de ambiente HOME para o usuário root.
        # Usamos 'bash -c' para executar o script, e o sudo eleva o bash.
        final_command = f"sudo -S -H -p '' bash -c {shlex.quote(command)}" 
    else:
        # Para comandos simples que não precisam de um shell complexo.
        final_command = f"sudo -S -p '' {command}" 

    channel = ssh.get_transport().open_session()
    channel.set_combine_stderr(True)  # Combina stdout e stderr em um único fluxo.
    channel.get_pty() # Solicita um pseudo-terminal, necessário para algumas interações.
    
    try:
        channel.exec_command(final_command)

        # Envia a senha para o prompt do sudo.
        if "sudo -S" in final_command:
            channel.sendall(password + '\n')

        # Lê a saída linha por linha enquanto o comando estiver em execução.
        while not channel.exit_status_ready():
            # Verifica se há dados para ler para evitar bloqueio.
            if channel.recv_ready():
                line = channel.recv(1024).decode('utf-8', errors='ignore')
                # Remove o prompt de senha da saída para não exibi-lo no frontend.
                cleaned_line = re.sub(r'\[sudo\].*?password for.*?:', '', line, flags=re.IGNORECASE).strip()
                if cleaned_line:
                    yield cleaned_line + '\n' # Adiciona nova linha para o streaming
        
        # Retorna o código de saída final.
        return channel.recv_exit_status()
    finally:
        channel.close()

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

def _handle_sftp_action(ssh: paramiko.SSHClient, username: str, action: str, data: Dict[str, Any], backup_root_dir: str) -> Dict[str, Any]:
    """Lida com ações que usam o protocolo SFTP (desativar/ativar atalhos)."""
    if action == 'desativar':
        message, errors = sftp_disable_shortcuts(ssh, username, backup_root_dir)
        success = not errors
        return {"success": success, "message": message, "details": errors}

    elif action == 'ativar':
        backup_files = data.get('backup_files', [])
        if not backup_files:
            return {"success": False, "message": "Nenhum atalho selecionado para restauração."}

        message, errors, warnings = sftp_restore_shortcuts(ssh, username, backup_files, backup_root_dir)
        
        success = not errors
        details = []
        if warnings: details.append(f"Avisos: {warnings}")
        if errors: details.append(f"Erros: {errors}")

        return {"success": success, "message": message, "details": "\n".join(details) if details else None}

    return {"success": False, "message": "Ação SFTP interna desconhecida."}

def _handle_set_wallpaper_for_user(ssh: paramiko.SSHClient, username: str, password: str, remote_image_path: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Define o papel de parede para um usuário específico usando um arquivo já existente na máquina remota."""
    from command_builder import GSETTINGS_ENV_SETUP
    
    safe_uri = shlex.quote(f"file://{remote_image_path}")
    set_wallpaper_script = f"""
        if gsettings list-schemas | grep -q 'org.cinnamon.desktop.background'; then
            gsettings set org.cinnamon.desktop.background picture-uri {safe_uri}
            echo "Papel de parede definido com sucesso (Cinnamon)."
        elif gsettings list-schemas | grep -q 'org.gnome.desktop.background'; then
            gsettings set org.gnome.desktop.background picture-uri {safe_uri}
            echo "Papel de parede definido com sucesso (GNOME Fallback)."
        else
            echo "Erro: Nenhum schema de papel de parede compatível (Cinnamon ou GNOME) foi encontrado." >&2
            exit 1
        fi
    """
    command = GSETTINGS_ENV_SETUP + set_wallpaper_script
    return _execute_shell_command(ssh, command, password, username=username)

def _handle_cleanup_wallpaper(ssh: paramiko.SSHClient, data: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[str]]:
    """Remove o arquivo de papel de parede temporário da máquina remota usando um comando simples."""
    wallpaper_filename = data.get('wallpaper_filename')
    if not wallpaper_filename:
        raise CommandExecutionError("Nome do arquivo de papel de parede não fornecido para limpeza.")

    remote_temp_path = posixpath.join("/tmp", wallpaper_filename)
    command = f"rm -f {shlex.quote(remote_temp_path)}"

    # Executa um comando simples de remoção que não requer sudo.
    _, _, stderr = ssh.exec_command(command)
    error_output = stderr.read().decode('utf-8', errors='ignore').strip()

    return "Limpeza concluída.", None, error_output if error_output else None

def _execute_for_each_user(ssh: paramiko.SSHClient, action: str, data: Dict[str, Any], logger) -> Tuple[Dict[str, Any], int]:
    """Encontra e executa uma ação para cada usuário na máquina remota."""
    list_users_cmd = r"getent passwd | awk -F: '$6 ~ /^\/home\// && $7 !~ /nologin|false/ {print $1}'"
    _, stdout, stderr = ssh.exec_command(list_users_cmd)
    users = stdout.read().decode().strip().splitlines()
    err = stderr.read().decode().strip()

    if err and not users:
        return {"success": False, "message": "Não foi possível encontrar usuários na máquina remota.", "details": err}, 500

    results = {}
    sftp_shortcut_actions = ['desativar', 'ativar']
    backup_root_dir = data.get('backup_root_dir', 'atalhos_desativados')
    
    # --- Lógica Refatorada para Papel de Parede ---
    # 1. Faz o upload do arquivo UMA VEZ para um local temporário.
    if action == 'definir_papel_de_parede':
        wallpaper_data_url = data.get('wallpaper_data')
        wallpaper_filename = data.get('wallpaper_filename')
        if not all([wallpaper_data_url, wallpaper_filename]):
            return {"success": False, "message": "Dados da imagem ou nome do arquivo ausentes."}, 400
        
        try:
            encoded_data = wallpaper_data_url.split(",", 1)[1]
            decoded_data = base64.b64decode(encoded_data)
        except (IndexError, binascii.Error) as e:
            return {"success": False, "message": f"Formato de Data URL ou Base64 inválido: {e}"}, 400

        # Usa /tmp para o arquivo, que é um local compartilhado e geralmente limpo no reboot.
        remote_temp_path = posixpath.join("/tmp", wallpaper_filename)
        try:
            with ssh.open_sftp() as sftp:
                with sftp.open(remote_temp_path, 'wb') as f:
                    f.write(decoded_data)
                # Garante que o arquivo seja legível por todos os usuários para que o gsettings funcione.
                # O SFTP não tem chmod, então usamos exec_command.
                ssh.exec_command(f"chmod 644 {shlex.quote(remote_temp_path)}")
        except Exception as e:
            return {"success": False, "message": f"Falha no upload do papel de parede via SFTP: {e}"}, 500

    for user in users:
        try:
            if action == 'definir_papel_de_parede':
                # 2. Executa a definição para cada usuário usando o arquivo já enviado.
                message, warnings, errors = _handle_set_wallpaper_for_user(
                    ssh, 
                    user, 
                    data['password'], 
                    remote_temp_path
                )
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
            # Captura exceções mais amplas, como falhas de conexão ou erros inesperados no serviço.
            logger.error(f"Exceção inesperada na ação '{action}' para o usuário '{user}': {e}")
            results[user] = {"success": False, "message": "Ocorreu uma exceção inesperada no servidor.", "details": str(e)}

    # --- Lógica de Relatório Aprimorada ---
    # Verifica se a operação foi um sucesso para todos os usuários.
    all_success = all(r.get('success', False) for r in results.values())
    # Conta quantos usuários tiveram sucesso.
    success_count = sum(1 for r in results.values() if r.get('success', False))

    # Cria uma mensagem de resumo mais informativa.
    summary_message = f"Ação '{action}' concluída para {success_count} de {len(users)} usuário(s)."

    # O payload de resposta agora inclui a mensagem de resumo e um dicionário
    # detalhado com o resultado para cada usuário.
    response_payload = {
        "success": all_success,
        "message": summary_message,
        "user_results": results  # Estrutura detalhada com os resultados por usuário.
    }

    return response_payload, 200 if all_success else 207 # 207 Multi-Status é ideal para resultados mistos