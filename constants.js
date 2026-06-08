// constants.js

// Define as chaves das ações para evitar erros de digitação e centralizar a gestão.
export const ACTIONS = {
    DISABLE_SHORTCUTS: 'desativar',
    ENABLE_SHORTCUTS: 'ativar',
    SHOW_SYSTEM_ICONS: 'mostrar_sistema',
    HIDE_SYSTEM_ICONS: 'ocultar_sistema',
    SHUTDOWN: 'desligar',
    REBOOT: 'reiniciar',
    WAKE_ON_LAN: 'wake_on_lan',
    SEND_MESSAGE: 'enviar_mensagem',
    KILL_PROCESS: 'kill_process',
    SET_WALLPAPER: 'definir_papel_de_parede',
    LOCK_TASKBAR: 'bloquear_barra_tarefas',
    UNLOCK_TASKBAR: 'desbloquear_barra_tarefas',
    DISABLE_PERIPHERALS: 'desativar_perifericos',
    ENABLE_PERIPHERALS: 'ativar_perifericos',
    UPDATE_SYSTEM: 'atualizar_sistema',
    INSTALL_MONITOR_TOOLS: 'instalar_monitor_tools', // Exemplo, ajuste conforme seu command_builder.py
    BACKUP_APLICACAO: 'backup_aplicacao',
    SCAN_MULTISEAT: 'scan_multiseat',
    ATTACH_SEAT_DEVICE: 'anexar_dispositivo_seat',
    SET_FIREFOX_DEFAULT: 'definir_firefox_padrao',
    SET_CHROME_DEFAULT: 'definir_chrome_padrao',
    DISABLE_RIGHT_CLICK: 'desativar_botao_direito',
    ENABLE_RIGHT_CLICK: 'ativar_botao_direito',
    UNINSTALL_CALCULATOR: 'desinstalar_calculadora', // Exemplo, ajuste conforme seu command_builder.py
    INSTALL_CALCULATOR: 'instalar_calculadora', // Exemplo, ajuste conforme seu command_builder.py
    SHUTDOWN_SERVER: 'shutdown_server',
    RESTAURAR_BACKUP_APLICACAO: 'restaurar_backup_aplicacao',
};

// Define ações que não podem ser selecionadas simultaneamente.
export const CONFLICTING_ACTIONS = {
    [ACTIONS.WAKE_ON_LAN]: ACTIONS.SHUTDOWN,
    [ACTIONS.SHUTDOWN]: ACTIONS.WAKE_ON_LAN,
    // Adicione outros pares de ações conflitantes aqui, se houver.
};

// Define ações que são executadas localmente no backend e não requerem IPs selecionados.
export const LOCAL_ACTIONS = new Set([
    ACTIONS.BACKUP_APLICACAO,
    ACTIONS.SHUTDOWN_SERVER,
    ACTIONS.RESTAURAR_BACKUP_APLICACAO,
]);

// Define ações que não requerem senha (ex: Wake-on-LAN, que usa MAC).
export const NO_PASSWORD_ACTIONS = new Set([
    ACTIONS.WAKE_ON_LAN,
]);