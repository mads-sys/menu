document.addEventListener('DOMContentLoaded', () => {
    // --- Constantes de Configuração ---
    const ACTIONS = Object.freeze({
        DISABLE_SHORTCUTS: 'desativar',
        SHOW_SYSTEM_ICONS: 'mostrar_sistema',
        HIDE_SYSTEM_ICONS: 'ocultar_sistema',
        CLEAR_IMAGES: 'limpar_imagens',
        DISABLE_TASKBAR: 'desativar_barra_tarefas',
        ENABLE_TASKBAR: 'ativar_barra_tarefas',
        LOCK_TASKBAR: 'bloquear_barra_tarefas',
        UNLOCK_TASKBAR: 'desbloquear_barra_tarefas',
        DISABLE_PERIPHERALS: 'desativar_perifericos',
        ENABLE_PERIPHERALS: 'ativar_perifericos',
        DISABLE_RIGHT_CLICK: 'desativar_botao_direito',
        ENABLE_RIGHT_CLICK: 'ativar_botao_direito',
        SEND_MESSAGE: 'enviar_mensagem',
        REBOOT: 'reiniciar',
        ENABLE_SHORTCUTS: 'ativar',
        SHUTDOWN: 'desligar',
        WAKE_ON_LAN: 'ligar',
        SET_FIREFOX_DEFAULT: 'definir_firefox_padrao',
        SET_CHROME_DEFAULT: 'definir_chrome_padrao',
        SET_WALLPAPER: 'definir_papel_de_parede',
        KILL_PROCESS: 'kill_process',
        REMOVE_NEMO: 'remover_nemo',
        INSTALL_NEMO: 'instalar_nemo',
        DISABLE_SLEEP_BUTTON: 'disable_sleep_button',
        UPDATE_SYSTEM: 'atualizar_sistema',
        ENABLE_DEEP_LOCK: 'ativar_deep_lock',
        ENABLE_SLEEP_BUTTON: 'enable_sleep_button',
        DISABLE_DEEP_LOCK: 'desativar_deep_lock',
        INSTALL_MONITOR_TOOLS: 'instalar_monitor_tools',
        UNINSTALL_SCRATCHJR: 'desinstalar_scratchjr',
        INSTALL_SCRATCHJR: 'instalar_scratchjr',
        UNINSTALL_GCOMPRIS: 'desinstalar_gcompris',
        INSTALL_GCOMPRIS: 'instalar_gcompris',
        UNINSTALL_TUXPAINT: 'desinstalar_tuxpaint',
        INSTALL_TUXPAINT: 'instalar_tuxpaint',
        UNINSTALL_LIBREOFFICE: 'desinstalar_libreoffice',
        INSTALL_LIBREOFFICE: 'instalar_libreoffice',
        GET_SYSTEM_INFO: 'get_system_info',
        BACKUP_APLICACAO: 'backup_aplicacao',
        RESTAURAR_BACKUP_APLICACAO: 'restaurar_backup_aplicacao',
        SHUTDOWN_SERVER: 'shutdown_server',
    });

    // Mapa de ações conflitantes. A chave é uma ação, e o valor é a ação que conflita com ela.
    const CONFLICTING_ACTIONS = Object.freeze({
        [ACTIONS.DISABLE_SHORTCUTS]: ACTIONS.ENABLE_SHORTCUTS, [ACTIONS.ENABLE_SHORTCUTS]: ACTIONS.DISABLE_SHORTCUTS,
        [ACTIONS.SHOW_SYSTEM_ICONS]: ACTIONS.HIDE_SYSTEM_ICONS, [ACTIONS.HIDE_SYSTEM_ICONS]: ACTIONS.SHOW_SYSTEM_ICONS,
        [ACTIONS.DISABLE_TASKBAR]: ACTIONS.ENABLE_TASKBAR, [ACTIONS.ENABLE_TASKBAR]: ACTIONS.DISABLE_TASKBAR,
        [ACTIONS.LOCK_TASKBAR]: ACTIONS.UNLOCK_TASKBAR, [ACTIONS.UNLOCK_TASKBAR]: ACTIONS.LOCK_TASKBAR,
        [ACTIONS.DISABLE_PERIPHERALS]: ACTIONS.ENABLE_PERIPHERALS, [ACTIONS.ENABLE_PERIPHERALS]: ACTIONS.DISABLE_PERIPHERALS,
        [ACTIONS.DISABLE_RIGHT_CLICK]: ACTIONS.ENABLE_RIGHT_CLICK, [ACTIONS.ENABLE_RIGHT_CLICK]: ACTIONS.DISABLE_RIGHT_CLICK,
        [ACTIONS.SET_FIREFOX_DEFAULT]: ACTIONS.SET_CHROME_DEFAULT, [ACTIONS.SET_CHROME_DEFAULT]: ACTIONS.SET_FIREFOX_DEFAULT,
        [ACTIONS.REMOVE_NEMO]: ACTIONS.INSTALL_NEMO, [ACTIONS.INSTALL_NEMO]: ACTIONS.REMOVE_NEMO,
        [ACTIONS.DISABLE_SLEEP_BUTTON]: ACTIONS.ENABLE_SLEEP_BUTTON, [ACTIONS.ENABLE_SLEEP_BUTTON]: ACTIONS.DISABLE_SLEEP_BUTTON,
        [ACTIONS.ENABLE_DEEP_LOCK]: ACTIONS.DISABLE_DEEP_LOCK, [ACTIONS.DISABLE_DEEP_LOCK]: ACTIONS.ENABLE_DEEP_LOCK,
        [ACTIONS.UNINSTALL_SCRATCHJR]: ACTIONS.INSTALL_SCRATCHJR, [ACTIONS.INSTALL_SCRATCHJR]: ACTIONS.UNINSTALL_SCRATCHJR,
        [ACTIONS.UNINSTALL_GCOMPRIS]: ACTIONS.INSTALL_GCOMPRIS, [ACTIONS.INSTALL_GCOMPRIS]: ACTIONS.UNINSTALL_GCOMPRIS,
        [ACTIONS.UNINSTALL_TUXPAINT]: ACTIONS.INSTALL_TUXPAINT, [ACTIONS.INSTALL_TUXPAINT]: ACTIONS.UNINSTALL_TUXPAINT,
        [ACTIONS.UNINSTALL_LIBREOFFICE]: ACTIONS.INSTALL_LIBREOFFICE, [ACTIONS.INSTALL_LIBREOFFICE]: ACTIONS.UNINSTALL_LIBREOFFICE,
        [ACTIONS.REBOOT]: ACTIONS.SHUTDOWN, [ACTIONS.SHUTDOWN]: ACTIONS.REBOOT,
        [ACTIONS.BACKUP_APLICACAO]: ACTIONS.RESTAURAR_BACKUP_APLICACAO, [ACTIONS.RESTAURAR_BACKUP_APLICACAO]: ACTIONS.BACKUP_APLICACAO,
    });

    // Ações que são executadas localmente no servidor e não requerem seleção de IP.
    const LOCAL_ACTIONS = Object.freeze(new Set([
        ACTIONS.BACKUP_APLICACAO,
        ACTIONS.RESTAURAR_BACKUP_APLICACAO,
        ACTIONS.SHUTDOWN_SERVER,
    ]));

    // Ações que devem usar a rota de streaming para feedback em tempo real.
    const STREAMING_ACTIONS = Object.freeze([
        ACTIONS.UPDATE_SYSTEM,
        ACTIONS.INSTALL_MONITOR_TOOLS,
        ACTIONS.INSTALL_GCOMPRIS,
        ACTIONS.UNINSTALL_GCOMPRIS,
        ACTIONS.INSTALL_TUXPAINT,
        ACTIONS.UNINSTALL_TUXPAINT,
        ACTIONS.INSTALL_LIBREOFFICE,
        ACTIONS.UNINSTALL_LIBREOFFICE,
    ]);

    const AUTO_REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutos

    // Define quais ações são consideradas perigosas e exigirão confirmação.
    const DANGEROUS_ACTIONS = Object.freeze([
        // A confirmação para ações perigosas foi desativada para agilizar o uso em ambiente de laboratório.
        ACTIONS.SHUTDOWN_SERVER,
        // Para reativar, adicione as ações desejadas aqui (ex: ACTIONS.REBOOT, ACTIONS.SHUTDOWN).
    ]);

    // Constrói a URL base da API dinamicamente a partir da URL da página.
    // Isso garante que funcione em 'localhost', '127.0.0.1' ou no IP da rede.
    let API_BASE_URL = `${window.location.protocol}//${window.location.host}`;

    // Correção para quando o arquivo é aberto diretamente (protocolo file:) ou em ambiente de dev (Live Server)
    if (window.location.protocol === 'file:' || (['localhost', '127.0.0.1'].includes(window.location.hostname) && !['5000', '80', '443', ''].includes(window.location.port))) {
        console.warn('Ambiente local/dev detectado. Forçando API para http://127.0.0.1:5000');
        API_BASE_URL = 'http://127.0.0.1:5000';
    }

    // Define o número máximo de ações remotas a serem executadas simultaneamente.
    // Um valor maior pode acelerar o processo, mas consome mais recursos do servidor.
    // Um valor entre 5 e 10 é geralmente um bom equilíbrio.
    const MAX_CONCURRENT_TASKS = 10;

    const ipListContainer = document.getElementById('ip-list');
    const ipCountElement = document.getElementById('ip-count');
    const ipSearchInput = document.getElementById('ip-search-input');
    const selectAllCheckbox = document.getElementById('select-all');
    const actionForm = document.getElementById('action-form');
    const systemLogBox = document.getElementById('system-log');
    const submitBtn = document.getElementById('submit-btn');
    const refreshBtn = document.getElementById('refresh-btn');
    const resetBtn = document.getElementById('reset-btn');
    const viewGridBtn = document.getElementById('view-grid-btn');
    const fixKeysBtn = document.getElementById('fix-keys-btn');
    const passwordInput = document.getElementById('password'); // Continua sendo usado
    const passwordGroup = passwordInput.parentElement;
    const refreshBtnText = refreshBtn.querySelector('.btn-text');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');
    const progressContainer = document.getElementById('progress-section');
    const themeToggle = document.getElementById('theme-toggle');
    const themeLabel = document.querySelector('.theme-label');
    const messageGroup = document.getElementById('message-group');
    const messageText = document.getElementById('message-text');
    const wallpaperGroup = document.getElementById('wallpaper-group');
    const wallpaperFile = document.getElementById('wallpaper-file');
    const processNameGroup = document.getElementById('process-name-group'); // Continua sendo usado
    const processNameText = document.getElementById('process-name-text'); // Continua sendo usado
    // Elementos do novo dropdown personalizado
    const actionSelect = document.querySelector('select[multiple]'); // O select original, agora escondido

    // Garante que a opção de Wake-on-LAN exista no menu, injetando-a se necessário
    if (actionSelect && !actionSelect.querySelector(`option[value="${ACTIONS.WAKE_ON_LAN}"]`)) {
        const wolOption = document.createElement('option');
        wolOption.value = ACTIONS.WAKE_ON_LAN;
        wolOption.textContent = '⚡ Ligar (Wake-on-LAN)';
        
        // Tenta inserir junto com as opções de energia (perto de desligar/reiniciar)
        const shutdownOption = actionSelect.querySelector(`option[value="${ACTIONS.SHUTDOWN}"]`);
        if (shutdownOption && shutdownOption.parentElement.tagName === 'OPTGROUP') {
            shutdownOption.parentElement.insertBefore(wolOption, shutdownOption);
        } else {
            // Se não encontrar, adiciona ao final
            actionSelect.appendChild(wolOption);
        }
    }

    const customSelectContainer = document.getElementById('custom-action-select-container');
    const customSelectTrigger = customSelectContainer.querySelector('.custom-select-trigger');
    const customOptions = customSelectContainer.querySelector('.custom-options');
    const customOptionsContent = customSelectContainer.querySelector('.custom-options-content');
    const autoRefreshToggle = document.getElementById('auto-refresh-toggle');    
    const modalConfirmBtn = document.getElementById('modal-confirm-btn');
    const modalCancelBtn = document.getElementById('modal-cancel-btn');
    const confirmationModal = document.getElementById('confirmation-modal');
    const modalDescription = document.getElementById('modal-description');
    // Elementos do Modal de Backup
    const backupModal = document.getElementById('backup-modal');
    const backupListContainer = document.getElementById('backup-list');
    const backupConfirmBtn = document.getElementById('backup-modal-confirm-btn');
    const backupCancelBtn = document.getElementById('backup-modal-cancel-btn');
    // Elementos do Modal de Backup da Aplicação
    const appBackupModal = document.getElementById('app-backup-modal');
    const appBackupListContainer = document.getElementById('app-backup-list');
    const appBackupConfirmBtn = document.getElementById('app-backup-modal-confirm-btn');
    const appBackupCancelBtn = document.getElementById('app-backup-modal-cancel-btn');
    // Elementos do Modal de Blocklist
    const manageBlocklistBtn = document.getElementById('manage-blocklist-btn');
    const blocklistModal = document.getElementById('blocklist-modal');
    const blocklistList = document.getElementById('blocklist-list');
    const blocklistModalCloseBtn = document.getElementById('blocklist-modal-close-btn');
    const logGroupTemplate = document.getElementById('log-group-template');
    const exportIpsBtn = document.getElementById('export-ips-btn');
    const importMacsBtn = document.getElementById('import-macs-btn');
    const importMacsInput = document.getElementById('import-macs-input');
    // Elementos re-adicionados
    const logFiltersContainer = document.querySelector('.log-filters');
    const clearLogBtn = document.getElementById('clear-log-btn');
    // const connectionErrorOverlay = document.getElementById('connection-error-overlay');
    const retryConnectionBtn = document.getElementById('retry-connection-btn');
    const togglePasswordBtn = document.getElementById('toggle-password-btn');
    const passwordToggleIcon = document.getElementById('password-toggle-icon');

    let autoRefreshTimer = null;
    let statusMonitorTimer = null;
    let sessionPassword = null;
    let ipsWithKeyErrors = new Set();


    // Função de validação que habilita/desabilita o botão de submit
    function checkFormValidity() {
        const isPasswordFilled = sessionPassword !== null || passwordInput.value.length > 0;
        const selectedIps = document.querySelectorAll('input[name="ip"]:checked');
        const selectedActions = Array.from(actionSelect.selectedOptions).map(opt => opt.value);
        let isActionRequirementMet = true;

        // Validação específica para a ação de enviar mensagem
        if (selectedActions.includes(ACTIONS.SEND_MESSAGE)) {
            isActionRequirementMet = messageText.value.trim().length > 0;
        }
        // Validação específica para a ação de finalizar processo
        if (selectedActions.includes(ACTIONS.KILL_PROCESS)) {
            isActionRequirementMet = processNameText.value.trim().length > 0;
        }

        // Determina se a seleção de IP é necessária.
        // Se alguma ação selecionada NÃO for local, então a seleção de IP é obrigatória.
        const requiresIpSelection = selectedActions.some(action => !LOCAL_ACTIONS.has(action));

        // O botão é habilitado se:
        // 1. A senha estiver preenchida.
        // 2. Pelo menos uma ação estiver selecionada.
        // 3. Os requisitos da ação (ex: campo de mensagem) estiverem preenchidos.
        // 4. Se a seleção de IP for necessária, pelo menos um IP deve estar selecionado.
        submitBtn.disabled = !(isPasswordFilled && selectedActions.length > 0 && isActionRequirementMet && (!requiresIpSelection || selectedIps.length > 0));
    }

    // --- Lógica do Seletor de Tema ---
    function applyTheme(theme) {
        if (theme === 'dark') {
            document.documentElement.setAttribute('data-theme', 'dark');
            themeToggle.checked = true;
            themeLabel.textContent = '☀️';
        } else {
            document.documentElement.setAttribute('data-theme', 'light');
            themeToggle.checked = false;
            themeLabel.textContent = '🌙';
        }
    }

    themeToggle.addEventListener('change', () => {
        const newTheme = themeToggle.checked ? 'dark' : 'light';
        localStorage.setItem('theme', newTheme);
        applyTheme(newTheme);
    });

    // Aplica o tema salvo no carregamento da página
    const currentTheme = localStorage.getItem('theme') || 'dark'; // Padrão para 'dark'
    applyTheme(currentTheme);

    // --- Lógica do Botão de Visualizar Senha ---
    if (togglePasswordBtn && passwordInput && passwordToggleIcon) {
        togglePasswordBtn.addEventListener('click', () => {
            const isPassword = passwordInput.type === 'password';
            if (isPassword) {
                passwordInput.type = 'text'; 
                passwordToggleIcon.innerHTML = '<i data-feather="eye-off"></i>';
            } else {
                passwordInput.type = 'password';
                passwordToggleIcon.innerHTML = '<i data-feather="eye"></i>';
            }
            feather.replace({ width: '1em', height: '1em' }); // Redesenha o ícone
        });
    }

    // --- Lógica para garantir que os menus comecem recolhidos na primeira visita ---
    // Esta flag garante que a limpeza do estado dos menus só ocorra uma vez por sessão.
    // --- Lógica para todas as Seções Retráteis ---
    const allCollapsibles = document.querySelectorAll('.collapsible-section, .collapsible-fieldset');
    allCollapsibles.forEach(collapsible => {
        // O ID é crucial para salvar/carregar o estado individualmente.
        const id = collapsible.id;
        if (!id) return;

        const indicator = collapsible.querySelector('.collapsible-indicator');
        if (!indicator) return;

        // No carregamento da página, verifica o estado salvo e o aplica.
        // Se não houver estado salvo, respeita o atributo 'open' do HTML.
        const savedState = localStorage.getItem(`collapsible-state-${id}`);
        if (savedState === 'open') {
            collapsible.open = true;
        } else if (savedState === 'closed') {
            collapsible.open = false;
        }

        // Define o indicador inicial com base no estado atual (salvo ou padrão do HTML).
        indicator.textContent = collapsible.open ? '[-]' : '[+]';

        collapsible.addEventListener('toggle', () => {
            // Altera o texto do indicador e salva o novo estado no localStorage.
            indicator.textContent = collapsible.open ? '[-]' : '[+]';
            localStorage.setItem(`collapsible-state-${id}`, collapsible.open ? 'open' : 'closed');
        });
    });

    /**
     * Atualiza a contagem de uso de cada ação no localStorage.
     * @param {string[]} actions - Um array com os valores das ações executadas.
     */
    function updateActionUsage(actions) {
        try {
            const counts = JSON.parse(localStorage.getItem('actionUsageCounts')) || {};
            actions.forEach(action => {
                counts[action] = (counts[action] || 0) + 1;
            });
            localStorage.setItem('actionUsageCounts', JSON.stringify(counts));
        } catch (e) {
            console.error("Falha ao atualizar contagem de uso das ações:", e);
        }
    }

    /**
     * Reordena as ações no <select> original, movendo as mais frequentes para um novo grupo no topo.
     */
    function createFrequentActionsGroup() {
        const counts = JSON.parse(localStorage.getItem('actionUsageCounts')) || {};
        const allOptions = Array.from(actionSelect.querySelectorAll('option'));

        // Ordena as opções pela contagem de uso, em ordem decrescente.
        allOptions.sort((a, b) => {
            const countA = counts[a.value] || 0;
            const countB = counts[b.value] || 0;
            return countB - countA;
        });

        // Pega as 5 ações mais usadas que têm pelo menos uma execução.
        const frequentOptions = allOptions.filter(opt => (counts[opt.value] || 0) > 0).slice(0, 5);

        if (frequentOptions.length > 0) {
            const frequentActionsGroup = document.createElement('optgroup');
            frequentActionsGroup.label = '⭐ Ações Frequentes';
            frequentActionsGroup.classList.add('group-frequent'); // Adiciona classe para estilização

            frequentOptions.forEach(option => {
                frequentActionsGroup.appendChild(option.cloneNode(true)); // Clona a opção para não removê-la do grupo original
            });
            actionSelect.prepend(frequentActionsGroup);
        }
    }

    // --- Lógica dos Botões de Acesso Rápido ---
    const quickActionsContainer = document.createElement('div');
    quickActionsContainer.className = 'quick-actions-container hidden';
    // Acessa o menu de ações para inserir os botões de acesso rápido perto dele.
    const actionMenuContainer = document.getElementById('custom-action-select-container');
    if (actionMenuContainer) {
        const topControls = actionMenuContainer.closest('.top-controls');
        if (topControls && topControls.parentNode) {
            // Insere APÓS a seção de controles superiores (abaixo de ações e senha), ocupando toda a largura
            topControls.parentNode.insertBefore(quickActionsContainer, topControls.nextSibling);
        } else if (actionMenuContainer.parentNode) {
            // Fallback: Insere no local original se .top-controls não for encontrado
            actionMenuContainer.parentNode.insertBefore(quickActionsContainer, actionMenuContainer.nextSibling);
        }
    }

    function renderQuickAccessButtons() {
        const counts = JSON.parse(localStorage.getItem('actionUsageCounts')) || {};
        // Pega as 7 ações mais usadas
        const sortedActions = Object.entries(counts)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 7)
            .map(entry => entry[0]);

        if (sortedActions.length === 0) {
            quickActionsContainer.classList.add('hidden');
            return;
        }

        quickActionsContainer.innerHTML = '';
        quickActionsContainer.classList.remove('hidden');

        const label = document.createElement('div');
        label.className = 'quick-actions-label';
        label.textContent = '⚡ Mais Acessados';
        quickActionsContainer.appendChild(label);

        const buttonsWrapper = document.createElement('div');
        buttonsWrapper.className = 'quick-actions-wrapper';

        sortedActions.forEach(action => {
            const option = actionSelect.querySelector(`option[value="${action}"]`);
            if (!option) return;

            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'quick-action-btn';
            btn.innerHTML = `<span>${option.textContent.trim()}</span>`;
            btn.title = `Selecionar ação: ${option.textContent.trim()}`;
            
            btn.addEventListener('click', () => {
                // Desmarca todas as opções no select nativo e checkboxes customizados
                Array.from(actionSelect.options).forEach(opt => opt.selected = false);
                const allCheckboxes = document.querySelectorAll('.custom-options input[type="checkbox"]');
                allCheckboxes.forEach(cb => cb.checked = false);

                // Seleciona a opção desejada
                option.selected = true;
                
                // Sincroniza o checkbox correspondente no menu customizado
                const customCheckbox = document.getElementById(`custom-action-${action}`);
                if (customCheckbox) customCheckbox.checked = true;

                // Dispara evento de mudança para atualizar a UI (tags, validação)
                actionSelect.dispatchEvent(new Event('change', { bubbles: true }));
                
                // Feedback visual de clique
                btn.classList.add('active');
                setTimeout(() => btn.classList.remove('active'), 200);

                // Nova lógica: executa imediatamente se houver IPs selecionados
                const selectedIps = document.querySelectorAll('input[name="ip"]:checked');
                if (selectedIps.length > 0) {
                    // Garante que a validação seja executada antes de clicar
                    checkFormValidity(); 
                    if (!submitBtn.disabled) {
                        submitBtn.click();
                    }
                }
            });

            buttonsWrapper.appendChild(btn);
        });

        quickActionsContainer.appendChild(buttonsWrapper);
    }

    // --- Lógica do Novo Menu de Ações Customizado ---
    if (customSelectContainer && actionSelect) {
        // ETAPA 1: Criar o grupo de ações frequentes ANTES de popular o menu customizado.
        // Isso garante que o novo grupo seja incluído na renderização.
        createFrequentActionsGroup();
        
        // Renderiza os botões de acesso rápido iniciais
        renderQuickAccessButtons();

        // 1. Povoar o menu customizado a partir do select original
        const originalOptgroups = actionSelect.querySelectorAll('optgroup');
        originalOptgroups.forEach(optgroup => {
            const groupLabel = optgroup.label;
            const options = optgroup.querySelectorAll('option');

            const groupDiv = document.createElement('div');
            groupDiv.className = 'custom-option-group';

            const groupTitle = document.createElement('div');
            groupTitle.className = 'custom-option-group-title';
            groupTitle.textContent = groupLabel;
            groupDiv.appendChild(groupTitle);

            options.forEach(option => {
                const itemDiv = document.createElement('div');
                itemDiv.className = 'checkbox-item';
                
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.id = `custom-action-${option.value}`;
                checkbox.value = option.value;

                const label = document.createElement('label');
                label.htmlFor = `custom-action-${option.value}`;
                label.textContent = option.textContent;

                itemDiv.append(checkbox, label);
                groupDiv.appendChild(itemDiv);

                // Lógica executada quando um checkbox de ação é alterado
                checkbox.addEventListener('change', () => {
                    const actionValue = checkbox.value;
                    const isChecked = checkbox.checked;

                    // Se a ação foi marcada, verifica se há um conflito
                    if (isChecked) {
                        const conflictingAction = CONFLICTING_ACTIONS[actionValue];
                        if (conflictingAction) {
                            const conflictingCheckbox = customOptions.querySelector(`#custom-action-${conflictingAction}`);
                            const conflictingOriginalOption = actionSelect.querySelector(`option[value="${conflictingAction}"]`);
                            // Se o conflitante estiver marcado, desmarca-o
                            if (conflictingCheckbox && conflictingCheckbox.checked) {
                                conflictingCheckbox.checked = false;
                                if (conflictingOriginalOption) conflictingOriginalOption.selected = false;
                            }
                        }
                    }

                    // Sincroniza o select original com o estado atual do checkbox
                    const originalOption = actionSelect.querySelector(`option[value="${actionValue}"]`);
                    if (originalOption) originalOption.selected = isChecked;
                    
                    // Dispara o evento 'change' no select original para atualizar a UI (tags, etc.)
                    actionSelect.dispatchEvent(new Event('change', { bubbles: true }));
                });
            });
            customOptionsContent.appendChild(groupDiv);
        });

        // 2. Lógica para abrir/fechar o menu
        customSelectTrigger.addEventListener('click', () => {
            customSelectContainer.classList.toggle('open');
        });

        // Fecha o menu se clicar fora dele
        window.addEventListener('click', (e) => {
            if (!customSelectContainer.contains(e.target)) {
                customSelectContainer.classList.remove('open');
            }
        });

        // Lógica da barra de pesquisa de ações
        const actionSearchInput = document.getElementById('action-search-input');
        actionSearchInput.addEventListener('input', () => {
            const searchTerm = actionSearchInput.value.toLowerCase().trim();
            const allGroups = customOptionsContent.querySelectorAll('.custom-option-group');

            allGroups.forEach(group => {
                const allOptions = group.querySelectorAll('.checkbox-item');
                let groupHasVisibleOptions = false;

                allOptions.forEach(option => {
                    const label = option.querySelector('label');
                    const isVisible = label.textContent.toLowerCase().includes(searchTerm);
                    option.style.display = isVisible ? '' : 'none';
                    if (isVisible) {
                        groupHasVisibleOptions = true;
                    }
                });

                // Esconde o grupo inteiro se nenhuma de suas opções corresponder à busca
                group.style.display = groupHasVisibleOptions ? '' : 'none';
            });
        });

        // 3. Lógica para atualizar o texto do botão e os campos condicionais
        actionSelect.addEventListener('change', () => {
            const selectedOptions = Array.from(actionSelect.selectedOptions);
            const triggerContainer = customSelectTrigger.querySelector('.trigger-text-container');
            const placeholder = triggerContainer.querySelector('.trigger-placeholder');

            // Limpa as tags existentes
            triggerContainer.querySelectorAll('.selected-action-tag').forEach(tag => tag.remove());

            if (selectedOptions.length === 0) {
                placeholder.style.display = 'inline';
            } else {
                placeholder.style.display = 'none';
                selectedOptions.forEach(option => {
                    const tag = document.createElement('div');
                    tag.className = 'selected-action-tag';
                    tag.textContent = option.textContent;

                    const closeBtn = document.createElement('button');
                    closeBtn.type = 'button';
                    closeBtn.className = 'tag-close-btn';
                    closeBtn.innerHTML = '&times;';
                    closeBtn.title = `Remover "${option.textContent}"`;

                    // Evento para remover a tag e desmarcar a opção
                    closeBtn.addEventListener('click', (e) => {
                        e.stopPropagation(); // Impede que o menu abra/feche
                        option.selected = false;
                        // Sincroniza o checkbox no menu suspenso
                        const correspondingCheckbox = customOptions.querySelector(`#custom-action-${option.value}`);
                        if (correspondingCheckbox) {
                            correspondingCheckbox.checked = false;
                        }
                        // Dispara o evento de mudança para atualizar tudo
                        actionSelect.dispatchEvent(new Event('change', { bubbles: true }));
                    });

                    tag.appendChild(closeBtn);
                    triggerContainer.appendChild(tag);
                });
            }
            const selectedActions = selectedOptions.map(opt => opt.value);

            // Esconde todos os grupos condicionais por padrão
            messageGroup.classList.add('hidden');
            wallpaperGroup.classList.add('hidden');
            processNameGroup.classList.add('hidden');

            // Mostra o grupo se QUALQUER uma das ações selecionadas o exigir
            if (selectedActions.includes(ACTIONS.SEND_MESSAGE)) {
                messageGroup.classList.remove('hidden');
            } if (selectedActions.includes(ACTIONS.SET_WALLPAPER)) { // Usamos 'if' em vez de 'else if'
                wallpaperGroup.classList.remove('hidden');
            } if (selectedActions.includes(ACTIONS.KILL_PROCESS)) {
                processNameGroup.classList.remove('hidden');
            }
            checkFormValidity();
        });
    }

    // Listener para o botão "Tentar Novamente" na sobreposição de erro
    if (retryConnectionBtn) {
        retryConnectionBtn.addEventListener('click', () => {
            location.reload(); // A maneira mais simples de tentar reconectar
        });
    }

    // Função para buscar e exibir os IPs
    async function fetchAndDisplayIps() {
        refreshBtn.disabled = true;
        refreshBtn.classList.add('loading');
        refreshBtnText.textContent = 'Buscando IPs...';

        // Mantém os IPs selecionados para reaplicar a seleção após a atualização.
        const previouslySelectedIps = new Set(Array.from(document.querySelectorAll('input[name="ip"]:checked')).map(cb => cb.value));

        // Limpa a lista e exibe o esqueleto de carregamento para feedback visual imediato.
        // Carrega a ordem salva dos IPs, se existir.
        const savedIpOrder = JSON.parse(localStorage.getItem('ipOrder'));
        let orderedIps = [];

        // Função para ordenar os IPs com base na ordem salva
        const sortIps = (backendIps) => {
            // Se não houver ordem salva, retorna a lista original do backend (que já vem ordenada).
            if (!savedIpOrder || savedIpOrder.length === 0) {
                return backendIps;
            }

            // Cria um conjunto para busca rápida dos IPs que já têm uma ordem salva.
            const savedIpSet = new Set(savedIpOrder);

            // Filtra os IPs que já estão na ordem salva.
            const orderedPart = savedIpOrder.filter(ip => backendIps.includes(ip));
            // Filtra os novos IPs (que não estão na ordem salva). O backend já os envia ordenados.
            const newPart = backendIps.filter(ip => !savedIpSet.has(ip));

            // Combina as duas listas: os IPs com ordem personalizada vêm primeiro, seguidos pelos novos IPs já ordenados.
            return [...orderedPart, ...newPart];
        };

        ipListContainer.innerHTML = '';
        const skeletonCount = 12; // Número de placeholders a serem exibidos.
        const skeletonFragment = document.createDocumentFragment();
        for (let i = 0; i < skeletonCount; i++) {
            const skeletonItem = document.createElement('div');
            skeletonItem.className = 'skeleton-item';
            skeletonFragment.appendChild(skeletonItem);
        }
        ipListContainer.appendChild(skeletonFragment);

        ipListContainer.innerHTML = ''; // Limpa a lista anterior
        if (ipCountElement) ipCountElement.textContent = ''; // Limpa a contagem
        submitBtn.disabled = true;
        selectAllCheckbox.checked = false;

        try {
            const response = await fetch(`${API_BASE_URL}/discover-ips`);
            const data = await response.json();

            if (data.success) {
                // Ordena os IPs ativos com base na ordem salva antes de exibi-los
                const activeIps = sortIps(data.ips);
                // Limpa o esqueleto de carregamento antes de adicionar os IPs reais.
                ipListContainer.innerHTML = '';

                if (ipCountElement) {
                    ipCountElement.textContent = `(${activeIps.length} encontrados)`;
                }

                const fragment = document.createDocumentFragment();
                activeIps.forEach((ip, index) => {
                    const item = document.createElement('div');
                    item.className = 'ip-item draggable-item';
                    item.dataset.ip = ip;
                    item.style.animationDelay = `${index * 0.05}s`;
                    item.draggable = true; // Torna o item arrastável
                    const lastOctet = ip.split('.').pop();

                    const statusDot = document.createElement('span');
                    statusDot.className = 'status-dot';

                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.id = `ip-${ip}`;
                    checkbox.name = 'ip';
                    checkbox.value = ip;

                    const label = document.createElement('label');
                    label.htmlFor = `ip-${ip}`;
                    label.textContent = lastOctet;

                    const blockBtn = document.createElement('button');
                    blockBtn.type = 'button';
                    blockBtn.className = 'block-ip-btn';
                    blockBtn.title = `Bloquear permanentemente o IP ${ip}`;
                    blockBtn.innerHTML = '<i data-feather="x-circle"></i>';
                    blockBtn.dataset.ip = ip;

                    const vncBtn = document.createElement('button');
                    vncBtn.type = 'button';
                    vncBtn.className = 'vnc-btn';
                    vncBtn.title = `Ver tela de ${ip}`;
                    vncBtn.innerHTML = '<i data-feather="monitor"></i>';

                    const statusIcon = document.createElement('span');
                    statusIcon.className = 'status-icon';
                    statusIcon.id = `status-${ip}`;

                    if (previouslySelectedIps.has(ip)) {
                        checkbox.checked = true;
                    }

                    item.append(statusDot, checkbox, label, vncBtn, blockBtn, statusIcon);
                    fragment.appendChild(item);
                });

                if (activeIps.length > 0) {
                    ipListContainer.appendChild(fragment);
                    // Re-renderiza os ícones Feather que foram adicionados dinamicamente
                    feather.replace({ width: '1em', height: '1em' });
                    if (exportIpsBtn) exportIpsBtn.disabled = false;
                } else {
                    // Mensagem clara quando nenhum IP é encontrado na faixa configurada.
                    if (exportIpsBtn) exportIpsBtn.disabled = true;
                }
            } else {
                ipListContainer.innerHTML = ''; // Limpa o esqueleto em caso de erro
                logStatusMessage(`Erro ao descobrir IPs: ${data.message}`, 'error');
                // statusBox.innerHTML = `<p class="error-text">Erro ao descobrir IPs: ${data.message}</p>`;
                if (exportIpsBtn) exportIpsBtn.disabled = true;
            }
        } catch (error) {
            // Mostra a sobreposição de erro de conexão se o fetch falhar.
            ipListContainer.innerHTML = ''; // Limpa o esqueleto em caso de erro de conexão
            logStatusMessage(`Erro de conexão com o servidor ao buscar IPs: ${error.message}`, 'error');
            // statusBox.innerHTML = `<p class="error-text">Erro de conexão com o servidor ao buscar IPs: ${error.message}</p>`;
            if (exportIpsBtn) exportIpsBtn.disabled = true;
        } finally {
            refreshBtn.disabled = false;
            refreshBtn.classList.remove('loading');
            refreshBtnText.textContent = 'Recarregar Lista';
            checkFormValidity();
            startStatusMonitor(); // Inicia o monitor de status após a busca de IPs.
        }
    }

    // Dispara a busca inicial de IPs
    fetchAndDisplayIps();

    // Listener para o botão de atualização
    // --- Lógica do Monitor de Status ---
    const STATUS_MONITOR_INTERVAL = 30 * 1000; // 30 segundos

    function stopStatusMonitor() {
        if (statusMonitorTimer) {
            clearInterval(statusMonitorTimer);
            statusMonitorTimer = null;
            logStatusMessage('Monitor de status em tempo real pausado.', 'details');
        }
    }

    async function checkIpStatuses() {
        const password = sessionPassword || passwordInput.value;
        // Não executa se a senha não estiver disponível
        if (!password) return;

        const allVisibleIps = Array.from(document.querySelectorAll('.ip-item'))
            .filter(item => item.style.display !== 'none')
            .map(item => item.dataset.ip);

        if (allVisibleIps.length === 0) return;

        try {
            const response = await fetch(`${API_BASE_URL}/check-status`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ips: allVisibleIps, password }),
            });
            const data = await response.json();
            if (data.success) {
                updateIpItemsStatus(data.statuses);
            }
        } catch (error) {
            // Não loga erros para não poluir o log, a falha será silenciosa
            // e tentará novamente no próximo ciclo.
        }
    }

    function updateIpItemsStatus(statuses) {
        // Cria um mapa de todos os itens de IP visíveis para acesso rápido, evitando múltiplas consultas ao DOM.
        const ipItemMap = new Map();
        ipListContainer.querySelectorAll('.ip-item').forEach(item => {
            ipItemMap.set(item.dataset.ip, item);
        });
    
        for (const ip in statuses) {
            const item = ipItemMap.get(ip);
            if (!item) continue; // Pula se o item não estiver no DOM
    
            // Remove todas as classes de status para um estado limpo
            item.classList.remove('status-online', 'status-offline', 'status-auth-error');
    
            // Adiciona a classe correta com base no status recebido
            if (statuses[ip] === 'offline') {
                item.classList.add('status-offline');
            } else if (statuses[ip] === 'auth_error') {
                item.classList.add('status-auth-error');
            } else {
                // Se não for offline nem erro de autenticação, consideramos online.
                item.classList.add('status-online');
            }
        }
    }

    function startStatusMonitor() {
        stopStatusMonitor(); // Garante que não haja timers duplicados
        statusMonitorTimer = setInterval(checkIpStatuses, STATUS_MONITOR_INTERVAL);
    }

    // --- Gerenciamento de Visibilidade da Página ---
    // Pausa o monitoramento se a aba estiver oculta para economizar recursos
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            stopStatusMonitor();
            if (autoRefreshToggle.checked && autoRefreshTimer) {
                 // Opcional: Pausar também o refresh completo se desejado, 
                 // mas o status monitor é o mais frequente.
            }
        } else {
            // Retoma o monitoramento se o auto-refresh estiver ligado ou se a página acabou de carregar
            // ou simplesmente reinicia o ciclo de status para feedback imediato
            checkIpStatuses(); // Executa um check imediato ao voltar
            startStatusMonitor();
        }
    });

    refreshBtn.addEventListener('click', () => {
        // // Esconde a sobreposição de erro, se estiver visível, antes de tentar novamente.
        // if (connectionErrorOverlay && !connectionErrorOverlay.classList.contains('hidden')) {
        //     connectionErrorOverlay.classList.add('hidden');
        // }
        fetchAndDisplayIps();
    });

    // --- Lógica de Drag and Drop para a Lista de IPs ---
    if (ipListContainer) {
        let draggedItem = null;

        // Evento quando um item começa a ser arrastado
        ipListContainer.addEventListener('dragstart', (e) => {
            draggedItem = e.target.closest('.ip-item');
            if (draggedItem) {
                // Adiciona um estilo para indicar visualmente qual item está sendo arrastado
                setTimeout(() => {
                    draggedItem.classList.add('dragging');
                }, 0);
            }
        });

        // Evento quando o item arrastado está sobre outro item
        ipListContainer.addEventListener('dragover', (e) => {
            e.preventDefault(); // Necessário para permitir o 'drop'
            const targetItem = e.target.closest('.ip-item');
            if (targetItem && draggedItem && targetItem !== draggedItem) {
                // Determina se o item arrastado deve ser inserido antes ou depois do alvo
                const rect = targetItem.getBoundingClientRect();
                // Pega a posição do mouse em relação ao centro do elemento alvo
                const offset = e.clientY - rect.top - rect.height / 2;

                if (offset < 0) {
                    // Insere antes do alvo
                    ipListContainer.insertBefore(draggedItem, targetItem);
                } else {
                    // Insere depois do alvo
                    ipListContainer.insertBefore(draggedItem, targetItem.nextSibling);
                }
            }
        });

        // Evento quando o item é solto
        ipListContainer.addEventListener('drop', (e) => {
            e.preventDefault();
            if (draggedItem) {
                draggedItem.classList.remove('dragging');
                draggedItem = null;

                // Salva a nova ordem dos IPs no localStorage
                const currentIpOrder = Array.from(ipListContainer.querySelectorAll('.ip-item')).map(item => item.dataset.ip);
                localStorage.setItem('ipOrder', JSON.stringify(currentIpOrder));
                logStatusMessage('Ordem dos IPs salva.', 'details');
            }
        });

        // Evento que ocorre ao final da operação de arrastar (seja soltando ou cancelando)
        ipListContainer.addEventListener('dragend', () => {
            if (draggedItem) {
                // Garante que a classe 'dragging' seja removida
                draggedItem.classList.remove('dragging');
                draggedItem = null;
            }
        });
    }

    // --- Lógica para Visualização VNC e Bloqueio de IP ---
    ipListContainer.addEventListener('click', async (event) => {
        const blockBtn = event.target.closest('.block-ip-btn');
        if (blockBtn) {
            const ip = blockBtn.dataset.ip;
            const ipItem = blockBtn.closest('.ip-item');

            const confirmed = await showConfirmationModal(`Tem certeza que deseja bloquear permanentemente o IP ${ip}?\n\nEste dispositivo não aparecerá mais nas buscas e será removido do cache.`);
            if (!confirmed) {
                logStatusMessage(`Bloqueio do IP ${ip} cancelado.`, 'details');
                return;
            }

            try {
                const response = await fetch(`${API_BASE_URL}/block-ip`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ip: ip }),
                });
                const data = await response.json();

                if (data.success) {
                    logStatusMessage(data.message, 'success');
                    // Animação de saída suave
                    ipItem.style.transition = 'opacity 0.3s ease-out, transform 0.3s ease-out, height 0.3s ease-out, padding 0.3s ease-out, margin 0.3s ease-out';
                    ipItem.style.opacity = '0';
                    ipItem.style.transform = 'scale(0.9)';
                    ipItem.style.height = '0px';
                    ipItem.style.padding = '0';
                    ipItem.style.margin = '0';
                    setTimeout(() => ipItem.remove(), 300);
                } else {
                    logStatusMessage(`Falha ao bloquear IP ${ip}: ${data.message}`, 'error');
                }
            } catch (error) {
                logStatusMessage(`Erro de conexão ao tentar bloquear IP ${ip}: ${error.message}`, 'error');
            }
            return; // Encerra a função para não processar o clique no VNC
        }

        // Procura pelo botão mais próximo do elemento clicado.
        // Isso corrige o bug de clicar no ícone em vez do botão.
        const vncBtn = event.target.closest('.vnc-btn');
        if (!vncBtn) {
            return;
        }
        const ipItem = vncBtn.closest('.ip-item');
        const ip = ipItem.dataset.ip;

        const password = sessionPassword || passwordInput.value;

        if (!password) {
            logStatusMessage('Por favor, digite a senha para iniciar a visualização.', 'error');
            passwordInput.focus();
            return;
        }

        vncBtn.innerHTML = '<i data-feather="loader" class="spin-animation"></i>';
        vncBtn.disabled = true;

        try {
            const response = await fetch(`${API_BASE_URL}/start-vnc`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ip, password }),
            });
            const data = await response.json();

            if (data.success) {
                logStatusMessage(`Sessão de visualização para ${ip} iniciada. Abrindo em nova aba...`, 'success');
                window.open(data.url, `vnc_${ip}`, 'fullscreen=yes');
                const iconElement = document.getElementById(`status-${ip}`);
                iconElement.textContent = '✅';
                iconElement.className = 'status-icon success';
            } else {
                logStatusMessage(`Falha ao iniciar VNC para ${ip}: ${data.message}`, 'error');
            }
        } catch (error) {
            logStatusMessage(`Erro de conexão ao tentar iniciar VNC para ${ip}.`, 'error');
        } finally {
            vncBtn.innerHTML = '<i data-feather="monitor"></i>';
            vncBtn.disabled = false;
            feather.replace({ width: '1em', height: '1em' });
        }
    });

    // Função para limpar a seleção e redefinir a interface
    function resetUI() {
        // 1. Desmarcar todos os checkboxes de IP
        document.querySelectorAll('input[name="ip"]').forEach(checkbox => {
            checkbox.checked = false;
        });
        selectAllCheckbox.checked = false;

        // 1.b. Redefine o menu de ações e dispara a atualização da UI (esconde tags e campos condicionais)
        Array.from(actionSelect.options).forEach(option => option.selected = false);
        actionSelect.dispatchEvent(new Event('change', { bubbles: true }));

        // 1.c. Desmarcar e parar a atualização automática se estiver ativa
        if (autoRefreshToggle.checked) {
            autoRefreshToggle.checked = false;
            autoRefreshToggle.dispatchEvent(new Event('change'));
        }

        // Limpa campos de texto que podem ter sido preenchidos
        messageText.value = '';
        processNameText.value = '';
        wallpaperFile.value = ''; // Limpa a seleção de arquivo

        // 4. Redefinir a barra de progresso
        progressBar.style.width = '0%';
        progressText.textContent = 'Pronto para executar.';
        fixKeysBtn.classList.add('hidden'); // Esconde o botão de corrigir chaves

        // Revalidar o formulário (isso desabilitará o botão "Executar")
        checkFormValidity();
        logStatusMessage('Interface limpa.', 'details');
    }

    // Listener para o botão de limpar/resetar
    resetBtn.addEventListener('click', resetUI);

    // Listener para o checkbox "Selecionar Todos"
    selectAllCheckbox.addEventListener('change', (event) => { // Este listener ainda é útil para a lógica específica de marcar/desmarcar todos
        const isChecked = event.target.checked;
        document.querySelectorAll('input[name="ip"]').forEach(checkbox => {
            checkbox.checked = isChecked;
        });
        checkFormValidity(); // Chama a validação após a seleção
    });

    // --- Botão para Selecionar Apenas Online ---
    // A estrutura do botão agora está no HTML (#select-online-btn)
    const selectOnlineBtn = document.getElementById('select-online-btn');
    
    if (selectOnlineBtn) {
        selectOnlineBtn.addEventListener('click', () => {
            const ipItems = document.querySelectorAll('.ip-item');
            let count = 0;
            
            ipItems.forEach(item => {
                // Considera apenas itens visíveis (caso haja filtro de busca)
                if (item.style.display !== 'none') {
                    const checkbox = item.querySelector('input[name="ip"]');
                    if (checkbox) {
                        const isOnline = item.classList.contains('status-online');
                        checkbox.checked = isOnline;
                        if (isOnline) count++;
                    }
                }
            });
            
            // Atualiza o estado do checkbox "Selecionar Todos"
            const visibleItems = Array.from(ipItems).filter(item => item.style.display !== 'none');
            const total = visibleItems.length;
            
            selectAllCheckbox.checked = (count === total && total > 0);
            selectAllCheckbox.indeterminate = (count > 0 && count < total);
            
            checkFormValidity();
            logStatusMessage(`${count} dispositivo(s) online selecionado(s).`, 'details');
        });
    }

    // Função de Debounce para otimizar a pesquisa
    function debounce(func, wait) {
        let timeout;
        return function(...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    // Listener para o campo de pesquisa de IPs
    ipSearchInput.addEventListener('input', debounce(() => {
        const searchTerm = ipSearchInput.value.toLowerCase().trim();
        const ipItems = document.querySelectorAll('.ip-item');
        let visibleCount = 0;

        ipItems.forEach(item => {
            const ip = item.dataset.ip;
            const isVisible = ip.includes(searchTerm);
            item.style.display = isVisible ? '' : 'none';
            if (isVisible) {
                visibleCount++;
            }
        });

        // Opcional: Informar ao usuário se nenhum resultado for encontrado
    }, 300)); // Aguarda 300ms após a última tecla antes de filtrar

    // Centraliza a validação do formulário para todos os inputs e checkboxes
    actionForm.addEventListener('input', checkFormValidity); // Para campos de texto, como senha e mensagem

    // Usa delegação de eventos para os checkboxes de IP, que são adicionados dinamicamente.
    // O listener é adicionado ao container que sempre existe.
    ipListContainer.addEventListener('change', (event) => {
        if (event.target.matches('input[name="ip"]')) {
            checkFormValidity();
        }
    });

    // Adiciona o listener para o select de ações e outros checkboxes (como 'Selecionar Todos')
    // O listener de 'change' no formulário cobre o select de ações e os checkboxes.
    actionForm.addEventListener('change', checkFormValidity);

    // Listener para o botão de exportar IPs
    if (exportIpsBtn) {
        exportIpsBtn.addEventListener('click', () => {
            // Coleta apenas os IPs que estão atualmente visíveis na lista
            // (respeitando o filtro de pesquisa).
            const visibleIps = Array.from(document.querySelectorAll('.ip-item'))
                .filter(item => item.style.display !== 'none')
                .map(item => item.dataset.ip);

            if (visibleIps.length === 0) {
                logStatusMessage('Nenhum IP para exportar.', 'details');
                return;
            }

            // Junta os IPs, cada um em uma nova linha.
            const fileContent = visibleIps.join('\n');
            // Cria um objeto Blob, que representa o arquivo em memória.
            const blob = new Blob([fileContent], { type: 'text/plain;charset=utf-8' });

            // Cria um link temporário para iniciar o download.
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            
            // Formata a data e hora para incluir no nome do arquivo.
            const timestamp = new Date().toISOString().slice(0, 19).replace(/[-T:]/g, '');
            link.download = `ips_online_${timestamp}.txt`;

            // Adiciona o link ao corpo, clica nele e depois o remove.
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        });
    }

    // --- Lógica de Importação de MACs ---
    if (importMacsBtn && importMacsInput) {
        importMacsBtn.addEventListener('click', () => {
            importMacsInput.click();
        });

        importMacsInput.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;

            const reader = new FileReader();
            reader.onload = async (event) => {
                const text = event.target.result;
                const lines = text.split('\n');
                const entries = [];

                // Regex flexível para encontrar IP e MAC na mesma linha
                // Aceita formatos como:
                // 192.168.0.10 00:11:22:33:44:55
                // 192.168.0.10,00-11-22-33-44-55
                const lineRegex = /((?:\d{1,3}\.){3}\d{1,3})[\s,;]+([0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2})/i;

                lines.forEach(line => {
                    const match = line.match(lineRegex);
                    if (match) {
                        entries.push({ ip: match[1], mac: match[2] });
                    }
                });

                if (entries.length === 0) {
                    logStatusMessage("Nenhum par IP/MAC válido encontrado no arquivo.", "error");
                    return;
                }

                logStatusMessage(`Lendo arquivo... Encontrados ${entries.length} pares. Enviando...`, "details");

                try {
                    const response = await fetch(`${API_BASE_URL}/import-macs`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ entries }),
                    });
                    const data = await response.json();
                    logStatusMessage(data.message, data.success ? "success" : "error");
                } catch (error) {
                    logStatusMessage(`Erro de conexão ao importar: ${error.message}`, "error");
                } finally {
                    importMacsInput.value = ''; // Permite selecionar o mesmo arquivo novamente se necessário
                }
            };
            reader.readAsText(file);
        });
    }

    // Listener para o botão de limpar log
    if (clearLogBtn) {
        clearLogBtn.addEventListener('click', () => {
            systemLogBox.innerHTML = '';
            // A linha abaixo foi removida pois a função showToast não existe mais.
            // O feedback visual agora é o próprio log sendo limpo.
        });
    }

    // --- Lógica de Filtragem de Log ---
    const activeLogFilters = new Set();

    function applyLogFilters() {
        systemLogBox.querySelectorAll('.log-entry').forEach(entry => {
            const entryType = entry.dataset.logType;
            // Esconde a entrada se o seu tipo estiver no conjunto de filtros ativos.
            entry.style.display = activeLogFilters.has(entryType) ? 'none' : '';
        });
    }

    if (logFiltersContainer) {
        logFiltersContainer.addEventListener('click', (e) => {
            const filterBtn = e.target.closest('.log-filter-btn');
            if (!filterBtn) return;

            const filterType = filterBtn.dataset.filter;
            filterBtn.classList.toggle('active');

            if (activeLogFilters.has(filterType)) {
                activeLogFilters.delete(filterType); // Desativa o filtro
            } else {
                activeLogFilters.add(filterType); // Ativa o filtro
            }
            applyLogFilters();
        });
    }

    /**
     * Função auxiliar para logar mensagens na caixa de status.
     * @param {string} message - A mensagem a ser exibida (pode conter HTML).
     * @param {string} groupId - O ID do grupo de log ao qual a mensagem pertence.
     */
    const logStatusMessage = (message, type = 'info') => {
        if (systemLogBox) {
            const logEntry = document.createElement('div');
            logEntry.className = `log-entry ${type}-text`;
            logEntry.dataset.logType = type; // Adiciona o tipo de log para filtragem

            const timestamp = new Date().toLocaleTimeString();
            const icon = { success: '✅', error: '❌', details: 'ℹ️', info: '➡️' }[type] || '➡️';

            // Constrói o elemento de forma segura
            const prefixSpan = document.createElement('span');
            prefixSpan.textContent = `[${timestamp}] ${icon}`;

            // Para mensagens simples, usamos textContent por segurança.
            const messageSpan = document.createElement('span');
            messageSpan.textContent = message;

            logEntry.append(prefixSpan, messageSpan);
            systemLogBox.appendChild(logEntry);

            // Otimização: remove apenas o elemento mais antigo se o limite for excedido.
            const MAX_LOG_ENTRIES = 100;
            if (systemLogBox.children.length > MAX_LOG_ENTRIES) {
                systemLogBox.removeChild(systemLogBox.firstChild);
            }

            // Aplica o filtro à nova entrada e faz o scroll
            logEntry.style.display = activeLogFilters.has(type) ? 'none' : '';
            logEntry.scrollIntoView({ behavior: 'smooth', block: 'end' });
        }
    };


    /**
     * Lida com o clique no botão de informação de um IP específico.
     * @param {Event} event - O evento de clique.
     */
    async function handleInfoButtonClick(event) {
        const target = event.target;
        if (!target.matches('.info-btn')) return;

        // Lê o IP diretamente do atributo 'data-ip' do botão clicado.
        // A abordagem anterior (target.closest('.ip-item').dataset.ip) também funcionaria,
        // mas esta é mais direta, pois o botão agora tem a informação.
        const ip = target.dataset.ip;
        if (!ip) return; // Segurança extra

        const password = sessionPassword || passwordInput.value;
        if (!password) {
            logStatusMessage('Por favor, digite a senha para obter as informações.', 'error');
            passwordInput.focus();
            return;
        }

        const iconElement = document.getElementById(`status-${ip}`);
        iconElement.innerHTML = '🔄'; // Feedback visual imediato
        iconElement.className = 'status-icon processing';
        target.disabled = true;

        const payload = {
            password: password, // A senha é adicionada aqui
            action: 'get_system_info', // Ação específica para esta função
        };

        try {
            const result = await executeRemoteAction(ip, payload);
            // A função updateIpStatus já lida com a exibição dos dados e do ícone de status
            updateIpStatus(ip, result);
        } catch (error) {
            // Em caso de erro na execução, reverte o ícone para um estado de erro
            updateIpStatus(ip, { success: false, message: "Falha ao obter informações.", details: error.message });
        } finally {
            // Reabilita o botão após a conclusão
            target.disabled = false;
        }
    }

    /**
     * Atualiza a barra de progresso.
     * @param {number} processed - Número de IPs processados.
     * @param {number} total - Número total de IPs.
     * @param {string} [actionText=''] - O texto da ação atual (opcional).
     */
    function updateProgressBar(processed, total, actionText = '') {
        const progress = total > 0 ? Math.round((processed / total) * 100) : 0;
        const actionPrefix = actionText ? `[${actionText}] ` : '';
        progressBar.style.width = `${progress}%`;
        progressText.textContent = `${actionPrefix}Processando ${processed} de ${total} (${progress}%)`;
        // Atualiza o atributo ARIA para leitores de tela
        if (progressContainer) progressContainer.setAttribute('aria-valuenow', progress);
    }

    /**
     * Prepara a UI para o início do processamento das ações.
     */
    function prepareUIForProcessing() {
        submitBtn.disabled = true;
        submitBtn.classList.add('processing');
        fixKeysBtn.classList.add('hidden');
        submitBtn.querySelector('.btn-text').textContent = 'Processando...';
        // Não limpa o log, apenas adiciona novas entradas
        document.querySelectorAll('.status-icon').forEach(icon => (icon.className = 'status-icon'));
    }

    /**
     * Exibe um modal de confirmação e retorna uma promessa.
     * @param {string} message - A mensagem a ser exibida no modal.
     * @returns {Promise<boolean>} - Resolve com `true` se confirmado, `false` se cancelado.
     */
    function showConfirmationModal(message) {
        // Usa \n como delimitador e cria parágrafos para melhor formatação no modal.
        const formattedMessage = message.split('\n').map(line => `<p>${line}</p>`).join('');

        const previouslyFocusedElement = document.activeElement;

        return new Promise((resolve) => {
            modalDescription.innerHTML = formattedMessage;
            confirmationModal.classList.remove('hidden');
            confirmationModal.setAttribute('aria-hidden', 'false');

            const focusableElements = confirmationModal.querySelectorAll('button');
            const firstElement = focusableElements[0];
            const lastElement = focusableElements[focusableElements.length - 1];

            const cleanupAndResolve = (value) => {
                confirmationModal.classList.add('hidden');
                confirmationModal.setAttribute('aria-hidden', 'true');
                document.removeEventListener('keydown', keydownHandler);
                previouslyFocusedElement?.focus(); // Retorna o foco ao elemento original
                resolve(value);
            };
            
            const confirmHandler = () => {
                cleanupAndResolve(true);
            };

            const cancelHandler = () => {
                cleanupAndResolve(false);
            };

            const keydownHandler = (e) => {
                if (e.key === 'Escape') {
                    cancelHandler();
                }
                if (e.key === 'Tab' && firstElement) { // Garante que há elementos focáveis
                    if (e.shiftKey && document.activeElement === firstElement) {
                        e.preventDefault();
                        lastElement.focus();
                    } else if (!e.shiftKey && document.activeElement === lastElement) {
                        e.preventDefault();
                        firstElement.focus();
                    }
                }
            };

            document.addEventListener('keydown', keydownHandler);

            modalConfirmBtn.addEventListener('click', confirmHandler, { once: true });
            modalCancelBtn.addEventListener('click', cancelHandler, { once: true });

            firstElement?.focus(); // Foco inicial no modal
        });
    }

    /**
     * Exibe um modal para o usuário selecionar quais backups de atalhos restaurar.
     * @param {string} ip - O IP do dispositivo para verificar os backups.
     * @param {string} password - A senha SSH.
     * @returns {Promise<string[]|null>} - Resolve com um array de diretórios selecionados, ou `null` se cancelado.
     */
    function showBackupSelectionModal(ip, password) {
        const previouslyFocusedElement = document.activeElement;

        return new Promise(async (resolve) => {
            // Mostra um estado de carregamento no modal
            backupListContainer.innerHTML = '<p>Buscando backups...</p>';
            backupConfirmBtn.disabled = true;
            backupModal.classList.remove('hidden');
            backupModal.setAttribute('aria-hidden', 'false');

            const cleanupAndResolve = (value) => {
                backupModal.classList.add('hidden');
                backupModal.setAttribute('aria-hidden', 'true');
                document.removeEventListener('keydown', keydownHandler);
                previouslyFocusedElement?.focus();
                resolve(value);
            };

            const confirmHandler = () => {
                // Seleciona diretamente os checkboxes de arquivos individuais que estão marcados,
                // ignorando o checkbox "Restaurar Todos". A lógica de sincronização garante que,
                // se "Restaurar Todos" estiver marcado, todos os individuais também estarão.
                const selectedFiles = Array.from(backupListContainer.querySelectorAll('input[name="backup-file"]:not(#backup-__ALL__):checked'))
                    .map(cb => cb.value);
                cleanupAndResolve(selectedFiles);
            };

            const cancelHandler = () => {
                cleanupAndResolve(null); // Resolve com null no cancelamento
            };

            const keydownHandler = (e) => {
                if (e.key === 'Escape') {
                    cancelHandler();
                }
                if (e.key === 'Tab') {
                    const focusableElements = Array.from(backupModal.querySelectorAll('button, input[type="checkbox"]')).filter(el => !el.disabled);
                    if (focusableElements.length === 0) return;
                    const firstElement = focusableElements[0];
                    const lastElement = focusableElements[focusableElements.length - 1];

                    if (e.shiftKey && document.activeElement === firstElement) {
                        e.preventDefault();
                        lastElement.focus();
                    } else if (!e.shiftKey && document.activeElement === lastElement) {
                        e.preventDefault();
                        firstElement.focus();
                    }
                }
            };

            // Adiciona os listeners uma única vez
            backupConfirmBtn.addEventListener('click', confirmHandler, { once: true }); // O {once: true} já remove o listener
            backupCancelBtn.addEventListener('click', cancelHandler, { once: true });
            document.addEventListener('keydown', keydownHandler);

            try {
                const response = await fetch(`${API_BASE_URL}/list-backups`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ip, password }),
                });
                const data = await response.json();

                if (!data.success || Object.keys(data.backups).length === 0) {
                    backupListContainer.innerHTML = `<p class="error-text">${data.message || 'Nenhum backup encontrado.'}</p>`;
                } else {
                    // Popula o modal com os checkboxes dos backups encontrados
                    backupListContainer.innerHTML = `
                        <div class="checkbox-item">
                            <input type="checkbox" id="backup-__ALL__" name="backup-file" value="__ALL__">
                            <label for="backup-__ALL__"><strong>Restaurar Todos</strong></label>
                        </div>
                        <hr style="border-color: var(--border-color-light); margin: 0.5rem 0;">
                    `;
                    const fragment = document.createDocumentFragment();
                    let backupCounter = 0;
                    // Itera sobre os diretórios e seus arquivos
                    for (const directory in data.backups) {
                        const fieldset = document.createElement('fieldset');
                        const legend = document.createElement('legend');
                        legend.textContent = directory;
                        fieldset.appendChild(legend);

                        data.backups[directory].forEach(filename => {
                            const fullPath = `${directory}/${filename}`;
                            // Cria um ID seguro e único para o elemento usando um contador para evitar colisões.
                            const safeId = `backup-item-${backupCounter++}`;

                            // Constrói os elementos do DOM programaticamente para maior segurança e robustez,
                            // evitando problemas com caracteres especiais em nomes de arquivos ao usar innerHTML.
                            const div = document.createElement('div');
                            div.className = 'checkbox-item';

                            const input = document.createElement('input');
                            input.type = 'checkbox';
                            input.id = safeId;
                            input.name = 'backup-file';
                            // O valor enviado para o backend deve ser o caminho original. O backend é responsável pela normalização.
                            input.value = fullPath;

                            const label = document.createElement('label');
                            label.htmlFor = safeId;
                            // Exibe o nome de arquivo original para o usuário.
                            label.textContent = filename;

                            div.appendChild(input);
                            div.appendChild(label);
                            fieldset.appendChild(div);
                        });
                        fragment.appendChild(fieldset);
                    }
                    backupListContainer.appendChild(fragment);

                    // Adiciona lógica para o checkbox "Restaurar Todos"
                    const allCheckbox = document.getElementById('backup-__ALL__');
                    const otherCheckboxes = Array.from(backupListContainer.querySelectorAll('input[name="backup-file"]:not(#backup-__ALL__)'));

                    // Ação ao clicar no checkbox "Restaurar Todos"
                    allCheckbox.addEventListener('change', () => {
                        otherCheckboxes.forEach(cb => {
                            cb.checked = allCheckbox.checked;
                        });
                    });

                    // Ação ao clicar em qualquer outro checkbox individual
                    otherCheckboxes.forEach(cb => {
                        cb.addEventListener('change', () => {
                            // Se todos os individuais estiverem marcados, marca o "Restaurar Todos". Caso contrário, desmarca.
                            const allAreChecked = otherCheckboxes.every(item => item.checked);
                            allCheckbox.checked = allAreChecked;
                        });
                    });

                    backupConfirmBtn.disabled = false;
                    backupConfirmBtn.focus(); // Foca no botão de confirmar após o conteúdo carregar
                }
            } catch (error) {
                backupListContainer.innerHTML = `<p class="error-text">Erro ao conectar para listar backups.</p>`;
                cleanupAndResolve(null); // Garante que a promise seja resolvida em caso de erro
            }
        });
    }

    /**
     * Exibe um modal para o usuário selecionar qual backup da aplicação restaurar.
     * @returns {Promise<string|null>} - Resolve com o nome do arquivo de backup selecionado, ou `null` se cancelado.
     */
    function showAppBackupSelectionModal() {
        const previouslyFocusedElement = document.activeElement;

        return new Promise(async (resolve) => {
            // Mostra um estado de carregamento no modal
            appBackupListContainer.innerHTML = '<p>Buscando backups da aplicação...</p>';
            appBackupConfirmBtn.disabled = true;
            appBackupModal.classList.remove('hidden');
            appBackupModal.setAttribute('aria-hidden', 'false');

            const cleanupAndResolve = (value) => {
                appBackupModal.classList.add('hidden');
                appBackupModal.setAttribute('aria-hidden', 'true');
                document.removeEventListener('keydown', keydownHandler);
                previouslyFocusedElement?.focus();
                resolve(value);
            };

            const confirmHandler = () => {
                const selectedRadio = appBackupListContainer.querySelector('input[name="app-backup-file"]:checked');
                cleanupAndResolve(selectedRadio ? selectedRadio.value : null);
            };

            const cancelHandler = () => {
                cleanupAndResolve(null);
            };

            const keydownHandler = (e) => {
                if (e.key === 'Escape') {
                    cancelHandler();
                }
            };

            appBackupConfirmBtn.addEventListener('click', confirmHandler, { once: true });
            appBackupCancelBtn.addEventListener('click', cancelHandler, { once: true });
            document.addEventListener('keydown', keydownHandler);

            // Delegação de eventos para os botões de exclusão
            appBackupListContainer.addEventListener('click', async (e) => {
                const deleteBtn = e.target.closest('.delete-backup-btn');
                if (!deleteBtn) return;

                e.stopPropagation(); // Impede que o clique no botão selecione o item

                const backupItemDiv = deleteBtn.closest('.backup-item');
                const filename = backupItemDiv.dataset.filename;

                const confirmed = await showConfirmationModal(`Tem certeza que deseja excluir o backup:\n\n${filename}\n\nEsta ação não pode ser desfeita.`);
                if (!confirmed) return;

                try {
                    const response = await fetch(`${API_BASE_URL}/delete-application-backup`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ backup_file: filename }),
                    });
                    const result = await response.json();

                    if (result.success) {
                        logStatusMessage(`Backup "${filename}" excluído com sucesso.`, 'success');
                        backupItemDiv.remove(); // Remove o item da lista na UI
                    } else {
                        logStatusMessage(`Falha ao excluir backup: ${result.message}`, 'error');
                    }
                } catch (error) {
                    logStatusMessage(`Erro de conexão ao tentar excluir backup: ${error.message}`, 'error');
                }
            });

            try {
                // Assumindo que a nova rota no backend será /list-application-backups
                const response = await fetch(`${API_BASE_URL}/list-application-backups`, {
                    method: 'GET', // GET é mais apropriado para listar recursos
                });
                const data = await response.json();

                if (!data.success || data.backups.length === 0) {
                    appBackupListContainer.innerHTML = `<p class="error-text">${data.message || 'Nenhum backup da aplicação encontrado.'}</p>`;
                } else {
                    
                    const fragment = document.createDocumentFragment();
                    // O backend deve retornar a lista já ordenada do mais recente para o mais antigo
                    data.backups.forEach((filename, index) => {
                        // Extrai a data do nome do arquivo para uma exibição mais amigável
                        // Extrai a data do nome do arquivo para uma exibição mais amigável.
                        let displayDate = filename; // Valor padrão caso o regex não encontre.
                        const match = filename.match(/backup_app_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.zip/);
                        let labelText = filename;
                        if (match) {
                            const [, year, month, day, hour, minute, second] = match;
                            labelText = `Data: ${day}/${month}/${year} às ${hour}:${minute}:${second}`;
                            displayDate = `Data: ${day}/${month}/${year} às ${hour}:${minute}:${second}`;
                        }

                        const itemDiv = document.createElement('div');
                        itemDiv.className = 'backup-item';
                        itemDiv.dataset.filename = filename;

                        const input = document.createElement('input');
                        input.type = 'radio'; // Radio buttons para seleção única
                        input.id = `app-backup-${index}`;
                        input.name = 'app-backup-file';
                        input.value = filename;
                        if (index === 0) {
                            input.checked = true; // Pré-seleciona o primeiro (mais recente)
                            itemDiv.classList.add('selected');
                        }

                        const detailsDiv = document.createElement('div');
                        detailsDiv.className = 'backup-details';
                        detailsDiv.innerHTML = `${displayDate} <small style="display: block; color: var(--subtle-text-color);">${filename}</small>`;

                        const deleteBtn = document.createElement('button');
                        deleteBtn.type = 'button';
                        deleteBtn.className = 'delete-backup-btn';
                        deleteBtn.innerHTML = '🗑️';
                        deleteBtn.title = `Excluir este backup`;

                        itemDiv.append(input, detailsDiv, deleteBtn);
                        fragment.appendChild(itemDiv);
                    });
                    appBackupListContainer.innerHTML = ''; // Limpa o "carregando"
                    appBackupListContainer.appendChild(fragment);

                    // Adiciona lógica para destacar o item selecionado
                    appBackupListContainer.addEventListener('click', (e) => {
                        const targetItem = e.target.closest('.backup-item');
                        if (!targetItem) return;
                        appBackupListContainer.querySelectorAll('.backup-item').forEach(item => item.classList.remove('selected'));
                        targetItem.classList.add('selected');
                        targetItem.querySelector('input[type="radio"]').checked = true;
                    });

                    appBackupConfirmBtn.disabled = false;
                    appBackupConfirmBtn.focus();
                }
            } catch (error) {
                appBackupListContainer.innerHTML = `<p class="error-text">Erro ao conectar para listar backups da aplicação.</p>`;
            }
        });
    }

    /**
     * Executa uma única ação em um único IP, encapsulando a lógica de fetch e timeout.
     * @param {string} ip - O IP alvo.
     * @param {object} payload - O corpo da requisição para a API.
     * @param {boolean} [isLongRunning=false] - Indica se a ação pode demorar, ajustando o timeout.
     * @returns {Promise<object>} - Um objeto com o resultado da operação.
     */
    async function executeRemoteAction(ip, payload, isLongRunning = false) {
        const controller = new AbortController();
        // Ações de streaming podem demorar muito, então o timeout é maior.
        const isStreaming = STREAMING_ACTIONS.includes(payload.action);
        const timeoutDuration = isStreaming ? 300000 : 30000; // 5 minutos para streaming, 30s para o resto.
        const timeoutId = setTimeout(() => controller.abort(), timeoutDuration);

        // Para ações de streaming, gera um ID único para o log. O backend usará isso
        // para criar um logger específico para esta requisição, resolvendo o erro
        // "ssh_connect() missing 1 required positional argument: 'logger'".
        const requestBody = isStreaming
            ? { ...payload, ip, log_id: `log-group-${ip.replace(/\./g, '-')}-${Date.now()}` }
            : { ...payload, ip };

        try {
            const response = await fetch(`${API_BASE_URL}/${isStreaming ? 'stream-action' : 'gerenciar_atalhos_ip'}`, {
                method: 'POST',
                // Garante que os cabeçalhos sejam sempre um objeto literal, pois a API fetch
                // não aceita um objeto Headers quando a opção 'keepalive' é usada.
                // Isso corrige o erro "TypeError: The provided value is not of type..."
                headers: { 'Content-Type': 'application/json' }, 
                body: JSON.stringify(requestBody),
                // A opção keepalive é crucial para ações de streaming, pois impede que o
                // navegador cancele a requisição se ela demorar muito ou se o usuário
                // mudar de aba.
                keepalive: isStreaming,
                signal: controller.signal,
            });

            clearTimeout(timeoutId); // Limpa o timeout assim que a resposta chega

            if (isStreaming) {
                return processStreamResponse(ip, payload, response, requestBody.log_id);
            }

            if (!response.ok) {
                let errorMessage = `Erro do servidor (HTTP ${response.status})`;
                let errorDetails = response.statusText;
                try {
                    // Tenta extrair uma mensagem de erro mais detalhada do corpo da resposta.
                    const errorData = await response.json();
                    errorMessage = errorData.message || errorMessage;
                    errorDetails = errorData.details || errorDetails;
                } catch (e) {
                    // O corpo não era JSON ou estava vazio. Mantém a mensagem de erro HTTP padrão.
                }
                return { success: false, message: errorMessage, details: errorDetails };
            }

            return await response.json();
        } catch (error) {
            clearTimeout(timeoutId); // Garante que o timeout seja limpo em caso de erro

            // Retorna um objeto de erro padronizado para erros de rede/timeout
            const isTimeout = error.name === 'AbortError';
            const message = isTimeout ? `Ação expirou (timeout de ${timeoutDuration / 1000}s).` : 'Erro de comunicação com o servidor.';
            const details = isTimeout
                ? `A ação excedeu o limite de tempo. O dispositivo pode estar lento ou offline.`
                : `Não foi possível conectar ao backend. Verifique se ele está em execução e se não há um firewall bloqueando a conexão.`;
            return {
                success: false, message, details
            };
        } finally {
            // O clearTimeout foi movido para dentro do try/catch para ser mais preciso.
        }
    }

    /**
     * Processa a resposta de uma ação de streaming, atualizando a UI em tempo real.
     * @param {string} ip - O IP alvo.
     * @param {object} payload - O payload original enviado na requisição.
     * @param {Response} response - O objeto de resposta do fetch.
     * @returns {Promise<object>} - Um objeto com o resultado final da operação.
     */
    async function processStreamResponse(ip, payload, response, logGroupId) {
        
        // Cria a entrada de log agrupada ANTES de começar a receber o stream
        const logGroupClone = logGroupTemplate.content.cloneNode(true);
        const logGroupElement = logGroupClone.querySelector('.log-group');
        logGroupElement.id = logGroupId;
        logGroupElement.dataset.logType = 'details'; // Começa como 'details'
        logGroupElement.open = true; // Começa aberto para o usuário ver o progresso

        const actionText = Array.from(actionSelect.options).find(opt => opt.value === payload.action)?.text || payload.action;
        logGroupElement.querySelector('.log-group-icon').textContent = '⏳';
        logGroupElement.querySelector('.log-group-title').textContent = `${ip}: ${actionText}`;
        logGroupElement.querySelector('.log-group-timestamp').textContent = new Date().toLocaleTimeString();
        const logContentElement = logGroupElement.querySelector('.log-group-content');
        const copyBtn = logGroupElement.querySelector('.copy-log-btn');

        copyBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            navigator.clipboard.writeText(logContentElement.textContent)
                .then(() => {                    
                    copyBtn.innerHTML = '<i data-feather="check"></i>';
                    setTimeout(() => { copyBtn.innerHTML = '<i data-feather="copy"></i>'; feather.replace(); }, 2000);
                });
        });

        systemLogBox.appendChild(logGroupElement);
        logGroupElement.scrollIntoView({ behavior: 'smooth', block: 'end' });

        if (!response.ok || !response.body) {
            const errorText = await response.text();
            return { success: false, message: `Erro do servidor (HTTP ${response.status})`, details: errorText };
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let finalResult = { success: false, message: "Ação de streaming finalizada sem uma conclusão clara." };
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // Guarda a última linha parcial no buffer

            for (const line of lines) {
                if (line.startsWith('__STREAM_END__:')) {
                    const exitCode = parseInt(line.split(':')[1], 10);
                    finalResult.success = exitCode === 0;
                    finalResult.message = exitCode === 0 ? "Ação concluída com sucesso." : `Ação falhou com código de saída ${exitCode}.`;
                } else if (line.startsWith('__STREAM_ERROR__:')) {
                    finalResult.success = false;
                    finalResult.message = "Erro durante o streaming.";
                    finalResult.details = line.substring('__STREAM_ERROR__:'.length);
                    logGroupElement.dataset.logType = 'error';
                    logGroupElement.querySelector('.log-group-icon').textContent = '❌';
                } else if (line.trim()) { // Garante que a linha não esteja vazia
                    // Loga a linha de progresso na caixa de status
                    const logContentElement = document.querySelector(`#${logGroupId} .log-group-content`);
                    if (logContentElement) {
                        logContentElement.appendChild(document.createTextNode(line + '\n'));
                    }
                }
            }
        }
        // Atualiza o ícone final com base no resultado
        logGroupElement.querySelector('.log-group-icon').textContent = finalResult.success ? '✅' : '❌';
        logGroupElement.dataset.logType = finalResult.success ? 'success' : 'error';
        return finalResult;
    }

    /**
     * Atualiza o ícone de status e a mensagem de log para um IP específico.
     * @param {string} ip - O IP alvo.
     * @param {object} result - O objeto de resultado da função executeRemoteAction.
     */
    function updateIpStatus(ip, result, actionText = 'Ação', payload = {}) {
        const ipItem = ipListContainer.querySelector(`.ip-item[data-ip="${ip}"]`);
        if (ipItem) {
            ipItem.classList.remove('processing');
        }
        const iconElement = document.getElementById(`status-${ip}`);
        const logGroupId = `log-group-${ip.replace(/\./g, '-')}-${Date.now()}`;

        if (iconElement) {
            const icon = result.success ? '✅' : '❌';
            const cssClass = result.success ? 'success' : 'error';

            iconElement.textContent = icon;
            iconElement.className = `status-icon ${cssClass}`;

            if (!result.success && result.details && result.details.includes("ssh-keygen -R")) {
                ipsWithKeyErrors.add(ip);
            }
        }

        // Loga a mensagem de resumo principal
        const logType = result.success ? 'success' : 'error';
        logStatusMessage(`${ip}: ${result.message}`, logType);

        // Se a resposta contiver 'user_results', itera sobre eles para um log detalhado.
        if (result.user_results) {
            for (const [user, userResult] of Object.entries(result.user_results)) {
                const userLogType = userResult.success ? 'success' : 'error';
                const userIcon = userResult.success ? '✅' : '❌';
                let userMessage = `${userIcon} [${user}]: ${userResult.message}`;
                if (userResult.details) {
                    userMessage += ` | Detalhes: ${userResult.details}`;
                }
                logStatusMessage(userMessage, userLogType);
            }
        } else if (result.details) { // Para ações não-streaming, loga os detalhes se existirem.
            logStatusMessage(`[${ip}] Detalhes: ${result.details}`, 'details');
        }

        // Lógica para exibir informações detalhadas do sistema no log
        if (result.success && result.data) {
            const infoString = `CPU: ${result.data.cpu || 'N/A'} | RAM: ${result.data.memory || 'N/A'} | Disco: ${result.data.disk || 'N/A'} | Uptime: ${result.data.uptime || 'N/A'}`;
            logStatusMessage(`[${ip}] Info: ${infoString}`, 'details');
        }
    }

    // Listener para o novo botão "Visualizar Máquinas"
    if (viewGridBtn) {
        viewGridBtn.addEventListener('click', (e) => {
            const password = sessionPassword || passwordInput.value;
            if (!password) {
                logStatusMessage('Por favor, digite a senha para visualizar as máquinas.', 'error');
                passwordInput.focus();
                return;
            }

            // Coleta os IPs que estão selecionados (marcados com checkbox).
            const allVisibleIps = Array.from(document.querySelectorAll('input[type="checkbox"][id^="ip-"]:checked'))
                .map(checkbox => checkbox.value);

            if (allVisibleIps.length === 0) {
                logStatusMessage('Nenhum dispositivo na lista para visualizar.', 'details');
                return;
            }

            // Gera uma chave única para a sessão da grade
            const gridSessionKey = `vncGridSession_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
            
            // Salva os dados na localStorage, que é compartilhada entre abas
            localStorage.setItem(gridSessionKey, JSON.stringify({ ips: allVisibleIps, password }));
            
            // Abre a nova aba passando a chave da sessão como um parâmetro de URL
            window.open(`grid_view.html?session=${gridSessionKey}`, '_blank');
        });
    }
    // Listener para o evento de submit do formulário
    actionForm.addEventListener('submit', async (event) => {
        event.preventDefault(); // Impede o recarregamento da página

        let password = sessionPassword || passwordInput.value;
        let selectedActions = Array.from(actionSelect.selectedOptions).map(opt => opt.value);
        const selectedIps = Array.from(document.querySelectorAll('input[name="ip"]:checked')).map(checkbox => checkbox.value);

        // Verifica se há ações que exigem um IP selecionado.
        const hasRemoteActions = selectedActions.some(action => !LOCAL_ACTIONS.has(action));

        if (hasRemoteActions && selectedIps.length === 0) {
            logStatusMessage('Por favor, selecione pelo menos um IP.', 'error');
            return; // Aborta se ações remotas foram selecionadas sem um IP.
        }

        if (!password) {
            logStatusMessage('Por favor, digite a senha.', 'error');
            return;
        }

        if (selectedActions.length === 0) {
            logStatusMessage('Por favor, selecione pelo menos uma ação no menu suspenso.', 'error');
            return;
        }

        // --- Confirmação para Ações Perigosas ---
        if (selectedActions.some(action => DANGEROUS_ACTIONS.includes(action))) {
            // Obtém o texto da primeira ação perigosa para exibir no modal
            // Obtém o texto da ação a partir da opção selecionada no dropdown
            const actionLabel = actionSelect.options[actionSelect.selectedIndex].text;


            const confirmationMessage = `Você está prestes a executar uma ação disruptiva:\n\n• ${actionLabel}\n\nTem certeza que deseja continuar?`;

            const confirmed = await showConfirmationModal(confirmationMessage);
            if (!confirmed) {
                logStatusMessage('Operação cancelada pelo usuário.', 'details');
                return; // Aborta a execução
            }
        }

        // Função auxiliar para ler um arquivo como Data URL (base64)
        function readFileAsDataURL(file) {
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve(reader.result);
                reader.onerror = reject;
                reader.readAsDataURL(file);
            });
        }

        // Função para construir o payload de uma ação, lidando com casos assíncronos como a leitura de arquivos.
        async function buildActionPayload(action, password) {
            // O payload base sempre deve conter a senha e a ação.
            // A correção aqui é garantir que o payload inicial já contenha a senha,
            // pois algumas ações (como UPDATE_SYSTEM) não entravam nos 'if' abaixo
            // e acabavam com um payload sem a senha.
            const payload = { password: password, action: action };

            if (action === ACTIONS.SEND_MESSAGE) {
                payload.message = messageText.value;
            } else if (action === ACTIONS.KILL_PROCESS) {
                payload.process_name = processNameText.value;
            } else if (action === ACTIONS.SET_WALLPAPER) {
                if (wallpaperFile.files.length === 0) {
                    logStatusMessage('Por favor, selecione um arquivo de imagem para o papel de parede.', 'error');
                    return null; // Retorna nulo para indicar falha na construção
                }
                const file = wallpaperFile.files[0];
                try {
                    payload.wallpaper_data = await readFileAsDataURL(file);
                    payload.wallpaper_filename = file.name;
                } catch (error) {
                    logStatusMessage(`Erro ao ler o arquivo de imagem: ${error.message}`, 'error');
                    return null;
                }
            }
            return payload;
        }
        // Desabilita o botão e prepara a UI antes de qualquer coisa.
        stopStatusMonitor();
        prepareUIForProcessing();

        try {
            const actionHandlers = {
                [ACTIONS.SHUTDOWN_SERVER]: async () => {
                    logStatusMessage('Enviando comando para desligar o servidor backend...', 'details');
                    const response = await fetch(`${API_BASE_URL}/shutdown`, { method: 'POST' });
                    const data = await response.json();
                    if (data.success) {
                        logStatusMessage('Comando de desligamento aceito. O servidor será encerrado.', 'success');
                        submitBtn.textContent = 'Servidor Desligando...';
                    } else {
                        logStatusMessage(`Falha ao desligar o servidor: ${data.message}`, 'error');
                    }
                    return { success: data.success, skipFurtherProcessing: true };
                },
                [ACTIONS.BACKUP_APLICACAO]: async () => {
                    logStatusMessage('Iniciando backup da aplicação...', 'details');
                    const response = await fetch(`${API_BASE_URL}/backup-application`, { method: 'POST' });
                    const data = await response.json();
                    logStatusMessage(data.success ? `Backup da aplicação criado com sucesso: ${data.path}` : `Falha ao criar backup da aplicação: ${data.message}`, data.success ? 'success' : 'error');
                    return { success: data.success, skipFurtherProcessing: true };
                },
                [ACTIONS.RESTAURAR_BACKUP_APLICACAO]: async () => {
                    const backupFile = await showAppBackupSelectionModal();
                    if (!backupFile) {
                        logStatusMessage('Restauração de backup da aplicação cancelada.', 'details');
                        return { success: false, skipFurtherProcessing: true };
                    }
                    logStatusMessage(`Iniciando restauração do backup "${backupFile}"...`, 'details');

                    // Dispara a requisição de restauração sem esperar pela resposta,
                    // pois o servidor será reiniciado.
                    fetch(`${API_BASE_URL}/restore-application-backup`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ backup_file: backupFile }),
                    }).catch(() => {}); // Ignora o erro de fetch esperado.

                    // Exibe uma mensagem e começa a verificar se o servidor voltou.
                    logStatusMessage('Comando de restauração enviado. Aguardando o servidor reiniciar...', 'success');

                    // Define a função de verificação dentro do handler para garantir que ela só exista neste escopo.
                    function checkAndReload() {
                        const checkInterval = setInterval(async () => {
                            try {
                                // Usa a rota /check-status que é mais leve que /discover-ips
                                const response = await fetch(`${API_BASE_URL}/check-status`, {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ ips: [] }), // Envia um corpo vazio
                                    signal: AbortSignal.timeout(2000)
                                });
                                if (response.ok) {
                                    clearInterval(checkInterval);
                                    logStatusMessage('Servidor online. Recarregando a página...', 'success');
                                    setTimeout(() => window.location.reload(), 1500);
                                }
                            } catch (e) { /* Ignora erros de conexão, que são esperados */ }
                        }, 3000); // Tenta a cada 3 segundos.
                    }
                    checkAndReload(); // Inicia a verificação
                    return { success: true, skipFurtherProcessing: true };
                },
                [ACTIONS.ENABLE_SHORTCUTS]: async () => {
                    let backupFiles = null;
                    let sourceIp = null;

                    // Tenta buscar a lista de backups a partir do primeiro IP online na seleção.
                    for (const ip of selectedIps) {
                        logStatusMessage(`Tentando buscar lista de backups de ${ip}...`, 'details');
                        const files = await showBackupSelectionModal(ip, password);
                        // Se a busca for bem-sucedida (não nula) e o usuário selecionar arquivos, interrompe o loop.
                        if (files !== null) {
                            backupFiles = files;
                            sourceIp = ip;
                            break;
                        }
                        logStatusMessage(`Falha ao buscar backups de ${ip}. Tentando o próximo...`, 'details');
                    }

                    if (backupFiles === null) {
                        logStatusMessage('Restauração de atalhos cancelada pelo usuário.', 'details');
                        return { success: false, skipFurtherProcessing: true };
                    }

                    if (backupFiles.length === 0) {
                        logStatusMessage('Nenhum atalho selecionado para restauração. Pulando a ação.', 'details');
                        return { success: false, skipFurtherProcessing: true };
                    }
                    const restorePayload = { password, action: ACTIONS.ENABLE_SHORTCUTS, backup_files: backupFiles };
                    return { success: await processBatch(restorePayload, 'Restaurar Atalhos'), skipFurtherProcessing: true };
                },
            };

            async function processBatch(payload, actionText) {
                logStatusMessage(`--- Iniciando ação: "${actionText}" ---`, 'details');
                let batchSuccess = false;
                const totalIPs = selectedIps.length;
                let processedIPs = 0;
                updateProgressBar(0, totalIPs, actionText);

                const tasks = selectedIps.map(targetIp => async () => {
                    const ipItem = ipListContainer.querySelector(`.ip-item[data-ip="${targetIp}"]`);
                    if (ipItem) {
                        ipItem.classList.add('processing');
                    }

                    // Limpa o conteúdo do ícone para que apenas o spinner do CSS seja exibido.
                    const iconElement = document.getElementById(`status-${targetIp}`);
                    const result = await executeRemoteAction(targetIp, payload);
                    if (result.success) batchSuccess = true;                    
                    // Passa o payload para que a função saiba se deve pular o log (no caso de streaming)
                    updateIpStatus(targetIp, result, actionText, payload); // Passa o payload
                    processedIPs++;
                    updateProgressBar(processedIPs, totalIPs, actionText);
                });
                await runPromisesInParallel(tasks, MAX_CONCURRENT_TASKS);
                return batchSuccess;
            }

            async function runPromisesInParallel(taskFunctions, concurrency) {
                const queue = [...taskFunctions];
                const workers = Array(concurrency).fill(null).map(async () => {
                    while (queue.length > 0) {
                        const task = queue.shift();
                        if (task) await task();
                    }
                });
                await Promise.all(workers);
            }

            let anySuccess = false;
            ipsWithKeyErrors.clear();

            // Itera sobre cada ação selecionada
            // ETAPA 1: Construir todos os payloads necessários ANTES da execução.
            // Isso garante que operações assíncronas como a leitura de arquivos sejam concluídas.
            const executionQueue = [];
            for (const action of selectedActions) {
                const handler = actionHandlers[action];
                if (handler) {
                    // Adiciona o handler especial à fila de execução.
                    executionQueue.push({ type: 'handler', handler, action });
                } else {
                    // Constrói o payload para ações padrão.
                    const payload = await buildActionPayload(action, password);
                    if (payload) { // Adiciona à fila apenas se o payload for válido.
                        const actionText = Array.from(actionSelect.options).find(opt => opt.value === action)?.text || action;
                        executionQueue.push({ type: 'batch', payload, actionText });
                    }
                }
            }

            // ETAPA 2: Executar as ações da fila em sequência.
            for (const task of executionQueue) {
                let success = false;
                if (task.type === 'handler') {
                    const result = await task.handler();
                    success = result?.success || false;
                } else if (task.type === 'batch') {
                    success = await processBatch(task.payload, task.actionText);
                }
                if (success) anySuccess = true;
            }

            // Atualiza a contagem de uso para TODAS as ações que estavam na fila de execução.
            // Isso garante que tanto ações em lote (batch) quanto ações especiais (handler) sejam contadas.
            const allExecutedActions = executionQueue.map(task => {
                return task.type === 'batch' ? task.payload.action : task.action;
            }).filter(Boolean); // O .filter(Boolean) remove quaisquer valores nulos ou indefinidos.

            if (allExecutedActions.length > 0) {
                updateActionUsage(allExecutedActions);
                renderQuickAccessButtons(); // Atualiza os botões de acesso rápido
            }

            if (anySuccess && sessionPassword === null) {
                sessionPassword = password;
                passwordGroup.style.display = 'none';
                logStatusMessage('Senha salva para esta sessão. Para alterar, recarregue a página.', 'details');
            }

            logStatusMessage('--- Processamento concluído! ---', 'details');
        } catch (error) { // Captura qualquer erro inesperado que não foi tratado internamente
            console.error("Erro inesperado durante a execução das ações:", error);
            logStatusMessage(`Ocorreu um erro inesperado: ${error.message}`, 'error');
        } finally {
            // --- Finalização da UI (executado sempre) ---
            progressBar.style.width = '0%';
            progressText.textContent = 'Pronto para executar.';

            if (ipsWithKeyErrors.size > 0) {
                fixKeysBtn.classList.remove('hidden');
            }

            submitBtn.disabled = false;
            submitBtn.classList.remove('processing');
            submitBtn.querySelector('.btn-text').textContent = 'Executar Ação';

            if (autoRefreshToggle.checked) {
                startStatusMonitor();
            }
        }
    });

    // Listener para o botão "Corrigir Chaves SSH"
    fixKeysBtn.addEventListener('click', async () => {
        const ipsToFix = Array.from(ipsWithKeyErrors);
        if (ipsToFix.length === 0) return;

        fixKeysBtn.disabled = true;
        fixKeysBtn.querySelector('.btn-text').textContent = 'Corrigindo...';
        logStatusMessage(`--- Tentando corrigir chaves SSH para ${ipsToFix.length} dispositivo(s)... ---`, 'details');

        try {
            const response = await fetch(`${API_BASE_URL}/fix-ssh-keys`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ips: ipsToFix }),
            });
            const data = await response.json();

            for (const ip in data.results) {
                const result = data.results[ip];
                const logType = result.success ? 'success' : 'error';
                logStatusMessage(`[${ip}] ${result.message}`, logType);
            }
            logStatusMessage('Correção de chaves concluída. Tente executar a ação novamente.', 'details');
        } catch (error) {
            logStatusMessage('Erro de conexão ao tentar corrigir chaves SSH.', 'error');
        } finally {
            fixKeysBtn.disabled = false;
            fixKeysBtn.querySelector('.btn-text').textContent = 'Corrigir Chaves SSH';
            fixKeysBtn.classList.add('hidden'); // Esconde o botão após a tentativa
        }
    });

    // Listener para o botão de gerenciar blocklist
    if (manageBlocklistBtn) {
        manageBlocklistBtn.addEventListener('click', showBlocklistModal);
    }

    // Listener para o toggle de atualização automática (colocado no final para garantir que todas as funções estejam definidas)
    if (autoRefreshToggle) {
        autoRefreshToggle.addEventListener('change', () => {
            // Sempre limpa o timer existente para evitar múltiplos timers rodando.
            if (autoRefreshTimer) {
                clearInterval(autoRefreshTimer);
                autoRefreshTimer = null;
            }
            stopStatusMonitor(); // Também para o monitor de status

            if (autoRefreshToggle.checked) {
                autoRefreshTimer = setInterval(fetchAndDisplayIps, AUTO_REFRESH_INTERVAL);
                startStatusMonitor(); // Inicia o monitor de status junto
                logStatusMessage(`Atualização automática ativada (a cada ${AUTO_REFRESH_INTERVAL / 60000} minutos).`, 'details');
            } else {
                // A mensagem de "pausado" já é emitida por stopStatusMonitor
                logStatusMessage('Atualização automática desativada.', 'details');
            }
        });
    }

    // --- Lógica de Drag and Drop para os Botões de Ação ---
    const bottomActionsContainer = document.querySelector('.bottom-actions');
    if (bottomActionsContainer) {
        let draggedButton = null;

        bottomActionsContainer.addEventListener('dragstart', (e) => {
            // Garante que estamos arrastando um botão direto do container
            if (e.target.matches('.bottom-actions > button')) {
                draggedButton = e.target;
                setTimeout(() => {
                    draggedButton.classList.add('dragging');
                }, 0);
            }
        });

        bottomActionsContainer.addEventListener('dragover', (e) => {
            e.preventDefault();
            const targetButton = e.target.closest('.bottom-actions > button');
            if (targetButton && draggedButton && targetButton !== draggedButton) {
                const rect = targetButton.getBoundingClientRect();
                // Usa a posição X do mouse para determinar a ordem
                const offsetX = e.clientX - rect.left - rect.width / 2;

                if (offsetX < 0) {
                    bottomActionsContainer.insertBefore(draggedButton, targetButton);
                } else {
                    bottomActionsContainer.insertBefore(draggedButton, targetButton.nextSibling);
                }
            }
        });

        bottomActionsContainer.addEventListener('drop', (e) => {
            e.preventDefault();
            if (draggedButton) {
                draggedButton.classList.remove('dragging');
                draggedButton = null;

                // Salva a nova ordem dos botões no localStorage
                const currentButtonOrder = Array.from(bottomActionsContainer.querySelectorAll('button')).map(btn => btn.id);
                localStorage.setItem('buttonOrder', JSON.stringify(currentButtonOrder));
                logStatusMessage('Ordem dos botões salva.', 'details');
            }
        });

        bottomActionsContainer.addEventListener('dragend', () => {
            if (draggedButton) {
                draggedButton.classList.remove('dragging');
                draggedButton = null;
            }
        });
    }

    // --- Lógica para Restaurar a Ordem dos Botões no Carregamento ---
    const savedButtonOrder = JSON.parse(localStorage.getItem('buttonOrder'));
    if (savedButtonOrder && bottomActionsContainer) {
        const fragment = document.createDocumentFragment();
        // Adiciona os botões ao fragmento na ordem salva
        savedButtonOrder.forEach(buttonId => {
            const button = document.getElementById(buttonId);
            if (button) fragment.appendChild(button);
        });
        // Limpa o container e adiciona os botões ordenados
        bottomActionsContainer.innerHTML = '';
        bottomActionsContainer.appendChild(fragment);
    }

});
