// --- Constantes para Ações ---
export const ACTIONS = {
    // Atalhos
    DISABLE_SHORTCUTS: 'desativar',
    ENABLE_SHORTCUTS: 'ativar',
    // Ícones do Sistema
    SHOW_SYSTEM_ICONS: 'mostrar_sistema',
    HIDE_SYSTEM_ICONS: 'ocultar_sistema',
    // Controle de Energia
    SHUTDOWN: 'desligar',
    REBOOT: 'reiniciar',
    WAKE_ON_LAN: 'wake_on_lan',
    // Mensagens
    SEND_MESSAGE: 'enviar_mensagem',
    // Processos
    KILL_PROCESS: 'kill_process',
    // Papel de Parede
    SET_WALLPAPER: 'definir_papel_de_parede',
    // Barra de Tarefas
    LOCK_TASKBAR: 'bloquear_barra_tarefas',
    UNLOCK_TASKBAR: 'desbloquear_barra_tarefas',
    // Periféricos
    DISABLE_PERIPHERALS: 'desativar_perifericos',
    ENABLE_PERIPHERALS: 'ativar_perifericos',
    DISABLE_RIGHT_CLICK: 'desativar_botao_direito',
    ENABLE_RIGHT_CLICK: 'ativar_botao_direito',
    // Sistema
    UPDATE_SYSTEM: 'atualizar_sistema',
    SYNC_TIME: 'sync_time',
    // Multiseat
    SCAN_MULTISEAT: 'scan_multiseat',
    ATTACH_SEAT_DEVICE: 'anexar_dispositivo_seat',
    // Navegadores
    SET_FIREFOX_DEFAULT: 'definir_firefox_padrao',
    SET_CHROME_DEFAULT: 'definir_chrome_padrao',
    // Rede
    BLOCK_NETWORK_SETTINGS: 'bloquear_config_rede',
    UNBLOCK_NETWORK_SETTINGS: 'desbloquear_config_rede',
    ENABLE_FAMILY_DNS: 'ativar_dns_familia',
    DISABLE_FAMILY_DNS: 'desativar_dns_familia',
    ENABLE_WHITELIST_SITES: 'ativar_whitelist_sites',
    DISABLE_WHITELIST_SITES: 'desativar_whitelist_sites',
    BLOCK_SITES: 'bloquear_sites',
    UNBLOCK_SITES: 'desbloquear_sites',
    LIST_BLOCKED_SITES: 'listar_sites_bloqueados',
    INCLUDE_WHITELIST: 'incluir_whitelist',
    REMOVE_WHITELIST: 'remover_whitelist',
    VERIFY_FAMILY_DNS: 'verificar_dns_familia',
    GET_WHITELIST_RAW: 'obter_whitelist_raw',
    SET_BANDWIDTH_LIMIT: 'definir_limite_banda',
    REMOVE_BANDWIDTH_LIMIT: 'remover_limite_banda',
    MONITOR_NETWORK: 'monitorar_rede',
    SPEEDTEST: 'testar_velocidade',
    // Deep Lock
    ACTIVATE_DEEP_LOCK: 'ativar_deep_lock',
    DEACTIVATE_DEEP_LOCK: 'desativar_deep_lock',
    // Terminal
    BLOCK_TERMINAL: 'bloquear_terminal',
    UNBLOCK_TERMINAL: 'desbloquear_terminal',
    // Dconf
    BLOCK_DCONF: 'bloquear_dconf',
    UNBLOCK_DCONF: 'desbloquear_dconf',
    // Outros
    LOGOUT_ALL_USERS: 'deslogar_todos',
    REMOVE_ALL_BLOCKS: 'remover_todos_bloqueios',
    CLEANUP_IMAGES: 'limpar_imagens',
    SHUTDOWN_SERVER: 'shutdown_server',
    BACKUP_APLICACAO: 'backup_aplicacao',
    RESTAURAR_BACKUP_APLICACAO: 'restaurar_backup_aplicacao',
    ENABLE_TCP_FORWARDING: 'enable_tcp_forwarding',
    GET_SYSTEM_INFO: 'get_system_info',
    CHECK_SSH_CONFIG: 'check_ssh_config',
    DISABLE_SLEEP_BUTTON: 'disable_sleep_button',
    ENABLE_SLEEP_BUTTON: 'enable_sleep_button',
    RESET_MULTISEAT: 'resetar_multiseat',
    STATUS_MULTISEAT: 'status_multiseat',
};

// --- Ações Conflitantes (se uma é selecionada, a outra é desmarcada) ---
export const CONFLICTING_ACTIONS = {
    [ACTIONS.DISABLE_SHORTCUTS]: ACTIONS.ENABLE_SHORTCUTS,
    [ACTIONS.ENABLE_SHORTCUTS]: ACTIONS.DISABLE_SHORTCUTS,
    [ACTIONS.SHOW_SYSTEM_ICONS]: ACTIONS.HIDE_SYSTEM_ICONS,
    [ACTIONS.HIDE_SYSTEM_ICONS]: ACTIONS.SHOW_SYSTEM_ICONS,
    [ACTIONS.LOCK_TASKBAR]: ACTIONS.UNLOCK_TASKBAR,
    [ACTIONS.UNLOCK_TASKBAR]: ACTIONS.LOCK_TASKBAR,
    [ACTIONS.DISABLE_PERIPHERALS]: ACTIONS.ENABLE_PERIPHERALS,
    [ACTIONS.ENABLE_PERIPHERALS]: ACTIONS.DISABLE_PERIPHERALS,
    [ACTIONS.DISABLE_RIGHT_CLICK]: ACTIONS.ENABLE_RIGHT_CLICK,
    [ACTIONS.ENABLE_RIGHT_CLICK]: ACTIONS.DISABLE_RIGHT_CLICK,
    [ACTIONS.ENABLE_FAMILY_DNS]: ACTIONS.DISABLE_FAMILY_DNS,
    [ACTIONS.DISABLE_FAMILY_DNS]: ACTIONS.ENABLE_FAMILY_DNS,
    [ACTIONS.ENABLE_WHITELIST_SITES]: ACTIONS.DISABLE_WHITELIST_SITES,
    [ACTIONS.DISABLE_WHITELIST_SITES]: ACTIONS.ENABLE_WHITELIST_SITES,
    [ACTIONS.BLOCK_SITES]: ACTIONS.UNBLOCK_SITES,
    [ACTIONS.UNBLOCK_SITES]: ACTIONS.BLOCK_SITES,
    [ACTIONS.BLOCK_NETWORK_SETTINGS]: ACTIONS.UNBLOCK_NETWORK_SETTINGS,
    [ACTIONS.UNBLOCK_NETWORK_SETTINGS]: ACTIONS.BLOCK_NETWORK_SETTINGS,
    [ACTIONS.ACTIVATE_DEEP_LOCK]: ACTIONS.DEACTIVATE_DEEP_LOCK,
    [ACTIONS.DEACTIVATE_DEEP_LOCK]: ACTIONS.ACTIVATE_DEEP_LOCK,
    [ACTIONS.BLOCK_TERMINAL]: ACTIONS.UNBLOCK_TERMINAL,
    [ACTIONS.UNBLOCK_TERMINAL]: ACTIONS.BLOCK_TERMINAL,
    [ACTIONS.BLOCK_DCONF]: ACTIONS.UNBLOCK_DCONF,
    [ACTIONS.UNBLOCK_DCONF]: ACTIONS.BLOCK_DCONF,
    [ACTIONS.SET_BANDWIDTH_LIMIT]: ACTIONS.REMOVE_BANDWIDTH_LIMIT,
    [ACTIONS.REMOVE_BANDWIDTH_LIMIT]: ACTIONS.SET_BANDWIDTH_LIMIT,
    [ACTIONS.DISABLE_SLEEP_BUTTON]: ACTIONS.ENABLE_SLEEP_BUTTON,
    [ACTIONS.ENABLE_SLEEP_BUTTON]: ACTIONS.DISABLE_SLEEP_BUTTON,
    'bloquear_total_ia': 'desbloquear_total_ia',
    'desbloquear_total_ia': 'bloquear_total_ia',
};

// --- Ações que são executadas localmente no servidor (não requerem SSH) ---
export const LOCAL_ACTIONS = new Set([
    ACTIONS.WAKE_ON_LAN,
    ACTIONS.SHUTDOWN_SERVER,
    ACTIONS.BACKUP_APLICACAO,
    ACTIONS.RESTAURAR_BACKUP_APLICACAO,
]);

// --- Ações que não requerem senha SSH ---
export const NO_PASSWORD_ACTIONS = new Set([
    ACTIONS.WAKE_ON_LAN,
    ACTIONS.SHUTDOWN_SERVER,
    ACTIONS.BACKUP_APLICACAO,
    ACTIONS.RESTAURAR_BACKUP_APLICACAO,
    ACTIONS.GET_SYSTEM_INFO, // Pode ser executado sem senha se o SSH estiver configurado para isso
    ACTIONS.CHECK_SSH_CONFIG,
    ACTIONS.SCAN_MULTISEAT,
    ACTIONS.STATUS_MULTISEAT,
]);

// --- Categorias de Sites para Sugestão de Bloqueio ---
export const SITE_CATEGORIES = {
    'redes_sociais': {
        label: 'Redes Sociais',
        icon: 'users',
        domains: [
            'facebook.com', 'instagram.com', 'twitter.com', 'x.com', 'tiktok.com',
            'linkedin.com', 'pinterest.com', 'snapchat.com', 'reddit.com', 'vk.com'
        ]
    },
    'jogos_populares': {
        label: 'Jogos Populares',
        icon: 'gamepad',
        domains: [
            'roblox.com', 'minecraft.net', 'fortnite.com', 'steamcommunity.com',
            'leagueoflegends.com', 'valorant.com', 'twitch.tv'
        ]
    },
    'chatbots_ia': {
        label: 'Chatbots de IA',
        icon: 'cpu',
        domains: [
            "openai.com", "chat.openai.com", "bard.google.com", "gemini.google.com",
            "perplexity.ai", "claude.ai", "copilot.microsoft.com", "bing.com",
            "you.com", "phind.com", "huggingface.co", "poe.com", "character.ai",
            "writesonic.com", "jasper.ai", "rytr.me", "copy.ai", "midjourney.com",
            "stable-diffusion-web.com", "dall-e.com", "chatgpt.com", "coze.com",
            "pi.ai", "elicit.org", "semantic-scholar.org", "scispace.com",
            "researchrabbit.ai", "connectedpapers.com", "consensus.app", "genei.io",
            "trinka.ai", "grammarly.com", "quillbot.com", "wordtune.com", "deepL.com",
            "smodin.me", "writesonic.com", "rytr.me", "copy.ai", "anyword.com",
            "surferseo.com", "frase.io", "closerscopy.com", "peppertype.ai", "longshot.ai"
        ]
    },
    'noticias_falsas': {
        label: 'Sites de Notícias Falsas',
        icon: 'alert-triangle',
        domains: [
            "examplefakenews.com", "hoaxwebsite.net", "misinformation.org",
            // Adicione aqui outros domínios de notícias falsas que deseja bloquear
        ]
    }
};