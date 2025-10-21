document.addEventListener('DOMContentLoaded', () => {
    // --- Constantes de Configuração ---
    const ACTIONS = Object.freeze({
        DISABLE_SHORTCUTS: 'desativar',
        ENABLE_SHORTCUTS: 'ativar',
        SHOW_SYSTEM_ICONS: 'mostrar_sistema',
        HIDE_SYSTEM_ICONS: 'ocultar_sistema',
        CLEAR_IMAGES: 'limpar_imagens',
        UPDATE_SYSTEM: 'atualizar_sistema',
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
        SHUTDOWN: 'desligar',
        SET_FIREFOX_DEFAULT: 'definir_firefox_padrao',
        SET_CHROME_DEFAULT: 'definir_chrome_padrao',
        SET_WALLPAPER: 'definir_papel_de_parede',
        KILL_PROCESS: 'kill_process',
        REMOVE_NEMO: 'remover_nemo',
        INSTALL_NEMO: 'instalar_nemo',
        DISABLE_SLEEP_BUTTON: 'disable_sleep_button',
        ENABLE_DEEP_LOCK: 'ativar_deep_lock',
        ENABLE_SLEEP_BUTTON: 'enable_sleep_button',
        DISABLE_DEEP_LOCK: 'desativar_deep_lock',
        INSTALL_MONITOR_TOOLS: 'instalar_monitor_tools',
        UNINSTALL_SCRATCHJR: 'desinstalar_scratchjr',
        INSTALL_SCRATCHJR: 'instalar_scratchjr',
        GET_SYSTEM_INFO: 'get_system_info',
        VIEW_VNC: 'view_vnc',
    });

    // Ações que devem usar a rota de streaming para feedback em tempo real.
    const STREAMING_ACTIONS = Object.freeze([
        ACTIONS.UPDATE_SYSTEM,
        ACTIONS.INSTALL_MONITOR_TOOLS,
    ]);

    const AUTO_REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutos

    // Define quais ações são consideradas perigosas e exigirão confirmação.
    const DANGEROUS_ACTIONS = Object.freeze([
        // A confirmação para ações perigosas foi desativada para agilizar o uso em ambiente de laboratório.
        // Para reativar, adicione as ações desejadas aqui (ex: ACTIONS.REBOOT, ACTIONS.SHUTDOWN).
    ]);

    // Constrói a URL base da API dinamicamente a partir da URL da página.
    // Isso garante que funcione em 'localhost', '127.0.0.1' ou no IP da rede.
    const API_BASE_URL = `${window.location.protocol}//${window.location.host}`;
    // Define o número máximo de ações remotas a serem executadas simultaneamente.
    // Um valor maior pode acelerar o processo, mas consome mais recursos do servidor.
    // Um valor entre 5 e 10 é geralmente um bom equilíbrio.
    const MAX_CONCURRENT_TASKS = 10;

    const ipListContainer = document.getElementById('ip-list');
    const ipCountElement = document.getElementById('ip-count');
    const ipSearchInput = document.getElementById('ip-search-input');
    const selectAllCheckbox = document.getElementById('select-all');
    const actionForm = document.getElementById('action-form');
    const statusBox = document.getElementById('status-box');
    const submitBtn = document.getElementById('submit-btn');
    const refreshBtn = document.getElementById('refresh-btn');
    const resetBtn = document.getElementById('reset-btn');
    const viewGridBtn = document.getElementById('view-grid-btn');
    const fixKeysBtn = document.getElementById('fix-keys-btn');
    const passwordInput = document.getElementById('password');
    const passwordGroup = passwordInput.parentElement;
    const refreshBtnText = refreshBtn.querySelector('.btn-text');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');
    const progressContainer = document.getElementById('progress-section');
    const themeToggle = document.getElementById('theme-toggle');
    const themeLabel = document.querySelector('.theme-label');
    const messageGroup = document.getElementById('message-group');
    const messageText = document.getElementById('message-text');
    const sendMessageCheckbox = document.getElementById(`action-${ACTIONS.SEND_MESSAGE}`);
    const setWallpaperCheckbox = document.getElementById(`action-${ACTIONS.SET_WALLPAPER}`);
    const wallpaperGroup = document.getElementById('wallpaper-group');
    const wallpaperFile = document.getElementById('wallpaper-file');
    const killProcessCheckbox = document.getElementById(`action-${ACTIONS.KILL_PROCESS}`);
    const processNameGroup = document.getElementById('process-name-group'); // Continua sendo usado
    const processNameText = document.getElementById('process-name-text'); // Continua sendo usado
    const actionSelect = document.getElementById('action-select');
    const autoRefreshToggle = document.getElementById('auto-refresh-toggle');    
    const modalConfirmBtn = document.getElementById('modal-confirm-btn');
    const modalCancelBtn = document.getElementById('modal-cancel-btn');
    const modalDescription = document.getElementById('modal-description');
    // Elementos do Modal de Backup
    const backupModal = document.getElementById('backup-modal');
    const backupListContainer = document.getElementById('backup-list');
    const backupConfirmBtn = document.getElementById('backup-modal-confirm-btn');
    const backupCancelBtn = document.getElementById('backup-modal-cancel-btn');
    const exportIpsBtn = document.getElementById('export-ips-btn');
    // Elementos da Sobreposição de Erro de Conexão
    const clearLogBtn = document.getElementById('clear-log-btn');
    const connectionErrorOverlay = document.getElementById('connection-error-overlay');
    const retryConnectionBtn = document.getElementById('retry-connection-btn');

    let autoRefreshTimer = null;
    let actionCheckboxes = []; // Armazena os checkboxes de ação para fácil acesso
    let sessionPassword = null;
    let ipsWithKeyErrors = new Set();


    /**
     * Define pares de ações que são mutuamente exclusivas.
     * Adiciona o atributo 'data-conflicts-with' dinamicamente aos checkboxes,
     * mantendo o HTML limpo e a lógica de conflito centralizada aqui.
     * @param {string} action1 - O valor da primeira ação (ex: 'reiniciar').
     * @param {string} action2 - O valor da segunda ação (ex: 'desligar').
     */
    function setConflict(action1, action2) {
        const check1 = document.getElementById(`action-${action1}`);
        const check2 = document.getElementById(`action-${action2}`);
        if (check1 && check2) {
            // Adiciona o atributo data-* para que o listener de 'change' funcione
            check1.dataset.conflictsWith = `action-${action2}`;
            check2.dataset.conflictsWith = `action-${action1}`;
        }
    }

    // Função de validação que habilita/desabilita o botão de submit
    function checkFormValidity() {
        const isPasswordFilled = sessionPassword !== null || passwordInput.value.length > 0;
        const selectedIps = document.querySelectorAll('input[name="ip"]:checked');
        const selectedActions = document.querySelectorAll('.action-checkbox-group input[type="checkbox"]:checked');
        let isActionRequirementMet = true;

        const selectedActionValues = Array.from(selectedActions).map(cb => cb.value);

        // Validação específica para a ação de enviar mensagem
        if (selectedActionValues.includes(ACTIONS.SEND_MESSAGE)) {
            isActionRequirementMet = messageText.value.trim().length > 0;
        }
        // Validação específica para a ação de finalizar processo
        if (selectedActionValues.includes(ACTIONS.KILL_PROCESS)) {
            isActionRequirementMet = processNameText.value.trim().length > 0;
        }

        submitBtn.disabled = !(isPasswordFilled && selectedIps.length > 0 && selectedActions.length > 0 && isActionRequirementMet);
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

    // --- Central de Configuração de Conflitos de Ações ---
    // Chame setConflict para cada par de ações que não pode ser selecionado junto.
    setConflict(ACTIONS.DISABLE_SHORTCUTS, ACTIONS.ENABLE_SHORTCUTS);
    setConflict(ACTIONS.SHOW_SYSTEM_ICONS, ACTIONS.HIDE_SYSTEM_ICONS);
    setConflict(ACTIONS.DISABLE_TASKBAR, ACTIONS.ENABLE_TASKBAR);
    setConflict(ACTIONS.LOCK_TASKBAR, ACTIONS.UNLOCK_TASKBAR);
    setConflict(ACTIONS.DISABLE_PERIPHERALS, ACTIONS.ENABLE_PERIPHERALS);
    setConflict(ACTIONS.REBOOT, ACTIONS.SHUTDOWN);
    setConflict(ACTIONS.DISABLE_RIGHT_CLICK, ACTIONS.ENABLE_RIGHT_CLICK);
    setConflict(ACTIONS.SET_FIREFOX_DEFAULT, ACTIONS.SET_CHROME_DEFAULT);
    setConflict(ACTIONS.REMOVE_NEMO, ACTIONS.INSTALL_NEMO);
    setConflict(ACTIONS.DISABLE_SLEEP_BUTTON, ACTIONS.ENABLE_SLEEP_BUTTON);
    setConflict(ACTIONS.ENABLE_DEEP_LOCK, ACTIONS.DISABLE_DEEP_LOCK);

    setConflict(ACTIONS.INSTALL_SCRATCHJR, ACTIONS.UNINSTALL_SCRATCHJR);

    // --- Lógica dos Checkboxes de Ação ---
    // Seleciona todos os checkboxes de ação uma vez para otimizar.
    actionCheckboxes = document.querySelectorAll('.action-checkbox-group input[type="checkbox"]');

    // Adiciona um único listener de evento ao contêiner dos checkboxes.
    const actionCheckboxGroup = document.querySelector('.action-checkbox-group');
    if (actionCheckboxGroup) {
        actionCheckboxGroup.addEventListener('change', (event) => {
            const checkbox = event.target;
            if (checkbox.type !== 'checkbox') return;

            // Lógica para mostrar/esconder campos condicionais
            if (checkbox.id === `action-${ACTIONS.SEND_MESSAGE}`) {
                messageGroup.classList.toggle('hidden', !checkbox.checked);
            }
            if (checkbox.id === `action-${ACTIONS.SET_WALLPAPER}`) {
                wallpaperGroup.classList.toggle('hidden', !checkbox.checked);
            }
            if (checkbox.id === `action-${ACTIONS.KILL_PROCESS}`) {
                processNameGroup.classList.toggle('hidden', !checkbox.checked);
            }

            // Lógica de conflitos
            if (checkbox.checked && checkbox.dataset.conflictsWith) {
                const conflictingCheckbox = document.getElementById(checkbox.dataset.conflictsWith);
                if (conflictingCheckbox && conflictingCheckbox.checked) {
                    conflictingCheckbox.checked = false;
                    // Dispara o evento 'change' no checkbox conflitante para garantir que
                    // qualquer lógica associada a ele (como esconder um campo) seja executada.
                    conflictingCheckbox.dispatchEvent(new Event('change'));
                    logStatusMessage(`Ação "${conflictingCheckbox.nextElementSibling.textContent}" desmarcada por ser conflitante.`, 'details');
                }
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

        ipListContainer.innerHTML = ''; // Limpa a lista anterior
        if (ipCountElement) ipCountElement.textContent = ''; // Limpa a contagem
        submitBtn.disabled = true;
        selectAllCheckbox.checked = false;

        statusBox.innerHTML = '<p>Iniciando busca de IPs na rede...</p>';

        try {
            const response = await fetch(`${API_BASE_URL}/discover-ips`);
            const data = await response.json();

            if (data.success) {
                const activeIps = data.ips;
                if (ipCountElement) {
                    ipCountElement.textContent = `(${activeIps.length} encontrados)`;
                }

                const fragment = document.createDocumentFragment();
                activeIps.forEach((ip, index) => {
                    const item = document.createElement('div');
                    item.className = 'ip-item';
                    item.dataset.ip = ip;
                    item.style.animationDelay = `${index * 0.05}s`;
                    const lastOctet = ip.split('.').pop();

                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.id = `ip-${ip}`;
                    checkbox.name = 'ip';
                    checkbox.value = ip;

                    const label = document.createElement('label');
                    label.htmlFor = `ip-${ip}`;
                    label.textContent = lastOctet;

            const vncBtn = document.createElement('button');
            vncBtn.type = 'button';
            vncBtn.className = 'vnc-btn';
            vncBtn.title = `Ver tela de ${ip}`;
            vncBtn.innerHTML = '🖥️';

            const statusIcon = document.createElement('span');
            statusIcon.className = 'status-icon';
            statusIcon.id = `status-${ip}`;

            if (previouslySelectedIps.has(ip)) {
                checkbox.checked = true;
            }

            item.append(checkbox, label, vncBtn, statusIcon);
            fragment.appendChild(item);
        });
        ipListContainer.appendChild(fragment);
                statusBox.innerHTML = '<p>Busca de IPs concluída. Selecione os dispositivos para gerenciar.</p>';
                if (exportIpsBtn) exportIpsBtn.disabled = false;

            } else {
                logStatusMessage(`Erro ao descobrir IPs: ${data.message}`, 'error');
                statusBox.innerHTML = `<p class="error-text">Erro ao descobrir IPs: ${data.message}</p>`;
                if (exportIpsBtn) exportIpsBtn.disabled = true;
            }
        } catch (error) {
            logStatusMessage(`Erro de conexão com o servidor ao buscar IPs: ${error.message}`, 'error');
            statusBox.innerHTML = `<p class="error-text">Erro de conexão com o servidor ao buscar IPs: ${error.message}</p>`;
            if (exportIpsBtn) exportIpsBtn.disabled = true;
        } finally {
            refreshBtn.disabled = false;
            refreshBtn.classList.remove('loading');
            refreshBtnText.textContent = 'Recarregar Lista';
            checkFormValidity();
        }
    }

    // Dispara a busca inicial de IPs
    fetchAndDisplayIps();

    // Listener para o botão de atualização
    refreshBtn.addEventListener('click', () => {
        // Esconde a sobreposição de erro, se estiver visível, antes de tentar novamente.
        if (connectionErrorOverlay && !connectionErrorOverlay.classList.contains('hidden')) {
            connectionErrorOverlay.classList.add('hidden');
        }
        fetchAndDisplayIps();
    });

    // --- Lógica para Visualização VNC ---
    ipListContainer.addEventListener('click', async (event) => {
        if (!event.target.classList.contains('vnc-btn')) {
            return;
        }

        const vncBtn = event.target;
        const ipItem = vncBtn.closest('.ip-item');
        const ip = ipItem.dataset.ip;
        const password = sessionPassword || passwordInput.value;

        if (!password) {
            logStatusMessage('Por favor, digite a senha para iniciar a visualização.', 'error');
            passwordInput.focus();
            return;
        }

        vncBtn.textContent = '🔄';
        vncBtn.disabled = true;

        try {
            // A ação é sempre iniciar a sessão, pois não há mais o estado 'ativo' no botão.
            const response = await fetch(`${API_BASE_URL}/start-vnc`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ip, password }),
            });
            const data = await response.json();

            if (data.success) {
                logStatusMessage(`Sessão de visualização para ${ip} iniciada. Abrindo em nova aba...`, 'success');
                // Adiciona 'fullscreen=yes' para sugerir ao navegador que abra em tela cheia.
                // A combinação com a alteração no vnc.html garante o comportamento.
                window.open(data.url, `vnc_${ip}`, 'fullscreen=yes');
                // Atualiza o status do IP para indicar que a conexão foi bem-sucedida.
                const iconElement = document.getElementById(`status-${ip}`);
                iconElement.textContent = '✅';
                iconElement.className = 'status-icon success';
            } else {
                logStatusMessage(`Falha ao iniciar VNC para ${ip}: ${data.message}`, 'error');
                const iconElement = document.getElementById(`status-${ip}`);
                iconElement.textContent = '❌';
                iconElement.className = 'status-icon error';
            }
        } catch (error) {
            logStatusMessage(`Erro de conexão ao tentar iniciar VNC para ${ip}.`, 'error');
        } finally {
            vncBtn.textContent = '🖥️';
            vncBtn.disabled = false;
        }
    });

    // Função para limpar a seleção e redefinir a interface
    function resetUI() {
        // 1. Desmarcar todos os checkboxes de IP
        document.querySelectorAll('input[name="ip"]').forEach(checkbox => {
            checkbox.checked = false;
        });
        selectAllCheckbox.checked = false;

        // 1.b. Desmarcar todos os checkboxes de ação (agora usando a variável `actionCheckboxes`)
        actionCheckboxes.forEach(checkbox => checkbox.checked = false);

        // 1.c. Desmarcar e parar a atualização automática se estiver ativa
        if (autoRefreshToggle.checked) {
            autoRefreshToggle.checked = false;
            // Dispara o evento 'change' para garantir que o timer seja limpo e a mensagem de log seja exibida.
            autoRefreshToggle.dispatchEvent(new Event('change'));
        }

        messageGroup.classList.add('hidden'); // Garante que a caixa de mensagem seja escondida
        wallpaperGroup.classList.add('hidden'); // Esconde o input de wallpaper
        processNameGroup.classList.add('hidden'); // Esconde o input de nome de processo

        // 2. Limpar os ícones de status de cada IP
        document.querySelectorAll('.status-icon').forEach(icon => {
            icon.innerHTML = '';
            icon.className = 'status-icon';
        });

        // 3. Redefinir la caixa de status
        statusBox.innerHTML = '<p>Aguardando comando...</p>';

        // 4. Ocultar e redefinir a barra de progresso
        progressContainer.classList.add('hidden');
        progressBar.style.width = '0%';
        progressText.textContent = '0%';
        fixKeysBtn.classList.add('hidden'); // Esconde o botão de corrigir chaves

        // Revalidar o formulário (isso desabilitará o botão "Executar")
        checkFormValidity();
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

    // Listener para o campo de pesquisa de IPs
    ipSearchInput.addEventListener('input', () => {
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
    });

    // Centraliza a validação do formulário para todos os inputs e checkboxes
    actionForm.addEventListener('input', checkFormValidity);

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

    // Listener para o botão de limpar log
    if (clearLogBtn) {
        clearLogBtn.addEventListener('click', () => {
            statusBox.innerHTML = '<p><i>Log limpo. Aguardando novo comando...</i></p>';
            // Opcional: rolar para o topo da caixa de log
            statusBox.scrollTop = 0;
        });
    }
    /**
     * Função auxiliar para logar mensagens na caixa de status.
     * @param {string} message - A mensagem a ser exibida (pode conter HTML).
     * @param {'success'|'error'|'details'|'info'} type - O tipo de mensagem para estilização.
     */
    function logStatusMessage(message, type = 'info') {
        const p = document.createElement('p');
        switch (type) {
            case 'details':
                p.className = 'details-text';
                const i = document.createElement('i');
                i.textContent = message;
                p.appendChild(i);
                break;
            default: // 'info', 'success', 'error'
                p.className = `${type}-text`;
                p.textContent = message;
        }
        statusBox.appendChild(p);
        statusBox.scrollTop = statusBox.scrollHeight; // Auto-scroll para a última mensagem
    }

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
        const progressBarContainer = document.getElementById('progress-bar-container');
        const progress = total > 0 ? Math.round((processed / total) * 100) : 0;
        const actionPrefix = actionText ? `[${actionText}] ` : '';
        progressBar.style.width = `${progress}%`;
        progressText.textContent = `${actionPrefix}Processando ${processed} de ${total} (${progress}%)`;
        // Atualiza o atributo ARIA para leitores de tela
        if (progressBarContainer) progressBarContainer.setAttribute('aria-valuenow', progress);
    }

    /**
     * Prepara a UI para o início do processamento das ações.
     */
    function prepareUIForProcessing() {
        submitBtn.disabled = true;
        fixKeysBtn.classList.add('hidden');
        submitBtn.textContent = 'Processando...';
        progressContainer.classList.remove('hidden');
        statusBox.innerHTML = ''; // Limpa o status box antes de começar
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
                    backupConfirmBtn.disabled = false;
                    backupConfirmBtn.focus(); // Foca no botão de confirmar quando o conteúdo carregar
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
                }
            } catch (error) {
                backupListContainer.innerHTML = `<p class="error-text">Erro ao conectar para listar backups.</p>`;
                cleanupAndResolve(null); // Garante que a promise seja resolvida em caso de erro
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
        // Se a ação for de streaming, usa a nova rota e lógica.
        if (STREAMING_ACTIONS.includes(payload.action)) {
            return executeStreamingAction(ip, payload);
        }

        // Lógica original para ações que não são de streaming.
        const controller = new AbortController();
        const timeoutDuration = 30000; // 30s para ações normais
        const timeoutId = setTimeout(() => controller.abort(), timeoutDuration);

        try {
            const response = await fetch(`${API_BASE_URL}/gerenciar_atalhos_ip`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ...payload, ip }), // Adiciona o IP ao payload
                signal: controller.signal,
            });

            clearTimeout(timeoutId); // Limpa o timeout assim que a resposta chega

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
     * Executa uma ação de longa duração e processa a saída em tempo real (streaming).
     * @param {string} ip - O IP alvo.
     * @param {object} payload - O corpo da requisição para a API.
     * @returns {Promise<object>} - Um objeto com o resultado final da operação.
     */
    async function executeStreamingAction(ip, payload) {
        try {
            const response = await fetch(`${API_BASE_URL}/stream-action`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ...payload, ip }),
                // keepalive é importante para garantir que a requisição não seja cancelada
                // se o usuário mudar de aba, por exemplo.
                keepalive: true,
            });

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
                    } else if (line.trim()) {
                        // Loga a linha de progresso na caixa de status
                        logStatusMessage(`[${ip}] ${line}`, 'details');
                    }
                }
            }
            return finalResult;

        } catch (error) {
            return { success: false, message: "Erro de rede ao iniciar o streaming.", details: error.message };
        }
    }

    /**
     * Atualiza o ícone de status e a mensagem de log para um IP específico.
     * @param {string} ip - O IP alvo.
     * @param {object} result - O objeto de resultado da função executeRemoteAction.
     */
    function updateIpStatus(ip, result) {
        const iconElement = document.getElementById(`status-${ip}`);
        const icon = result.success ? '✅' : '❌';
        const cssClass = result.success ? 'success' : 'error';

        // Usar textContent em vez de innerHTML para segurança contra XSS.
        iconElement.textContent = icon;
        iconElement.className = `status-icon ${cssClass}`;

        // Rastreia IPs com erro de chave de host para habilitar o botão de correção
        if (!result.success && result.details && result.details.includes("ssh-keygen -R")) {
            ipsWithKeyErrors.add(ip);
        }

        // Constrói a mensagem de status programaticamente para evitar injeção de HTML.
        const p = document.createElement('p');
        const statusSpan = document.createElement('span');
        statusSpan.className = `${cssClass}-text`;
        statusSpan.textContent = `${icon} ${ip}: ${result.message}`;
        p.appendChild(statusSpan);

        // Se a mensagem contiver quebras de linha (como no script de atualização),
        // formata a saída para melhor legibilidade.
        if (result.message && result.message.includes('\n')) {
            const lines = result.message.split('\n');
            // A primeira linha já foi exibida, então mostramos o resto como detalhes.
            statusSpan.textContent = `${icon} ${ip}: ${lines[0]}`;

            const detailsContainer = document.createElement('div');
            detailsContainer.className = 'system-info-details'; // Reutiliza o estilo
            lines.slice(1).forEach(line => {
                const small = document.createElement('small');
                small.textContent = line;
                detailsContainer.appendChild(small);
            });
            p.appendChild(detailsContainer);
        }

        // Lógica para exibir informações detalhadas do sistema
        if (result.success && result.data) {
            const infoContainer = document.createElement('div');
            infoContainer.className = 'system-info-details';

            // Cria e anexa os detalhes de forma robusta
            const createDetail = (label, value) => {
                const small = document.createElement('small');
                small.textContent = `${label}: ${value || 'N/A'}`;
                return small;
            };

            infoContainer.appendChild(createDetail('CPU', result.data.cpu));
            infoContainer.appendChild(createDetail('RAM', result.data.memory));
            infoContainer.appendChild(createDetail('Disco', result.data.disk));
            infoContainer.appendChild(createDetail('Uptime', result.data.uptime));

            p.appendChild(infoContainer);

        // Lógica para exibir detalhes de erro ou avisos para outras ações
        } // A lógica de detalhes agora é tratada na resposta agregada do backend

        statusBox.appendChild(p);
        statusBox.scrollTop = statusBox.scrollHeight;
    }

    // Listener para o novo botão "Visualizar Máquinas"
    if (viewGridBtn) {
        viewGridBtn.addEventListener('click', () => {
            const password = sessionPassword || passwordInput.value;
            if (!password) {
                logStatusMessage('Por favor, digite a senha para visualizar as máquinas.', 'error');
                passwordInput.focus();
                return;
            }

            // Coleta todos os IPs atualmente visíveis na lista
            const allVisibleIps = Array.from(document.querySelectorAll('.ip-item'))
                .filter(item => item.style.display !== 'none')
                .map(item => item.dataset.ip);

            if (allVisibleIps.length === 0) {
                logStatusMessage('Nenhum dispositivo na lista para visualizar.', 'details');
                return;
            }

            // Salva os dados na sessionStorage para a nova aba ler
            sessionStorage.setItem('vncGridData', JSON.stringify({ ips: allVisibleIps, password }));
            window.open('grid_view.html', '_blank');
        });
    }
    // Listener para o evento de submit do formulário
    actionForm.addEventListener('submit', async (event) => {
        event.preventDefault(); // Impede o recarregamento da página

        const password = sessionPassword || passwordInput.value;
        const selectedActions = Array.from(document.querySelectorAll('.action-checkbox-group input[type="checkbox"]:checked')).map(cb => cb.value);
        const selectedIps = Array.from(document.querySelectorAll('input[name="ip"]:checked')).map(checkbox => checkbox.value);

        if (selectedIps.length === 0) {
            logStatusMessage('Por favor, selecione pelo menos um IP.', 'error');
            return;
        }

        if (!password) {
            logStatusMessage('Por favor, digite a senha.', 'error');
            return;
        }

        if (selectedActions.length === 0) {
            logStatusMessage('Por favor, selecione pelo menos uma ação.', 'error');
            return;
        }

        // --- Confirmação para Ações Perigosas ---
        const dangerousActionsSelected = selectedActions.filter(action => DANGEROUS_ACTIONS.includes(action));

        if (dangerousActionsSelected.length > 0) {
            // Obtém os labels das ações perigosas a partir dos elementos de label associados aos checkboxes
            const dangerousActionLabels = dangerousActionsSelected.map(actionValue => {
                return document.querySelector(`label[for="action-${actionValue}"]`)?.textContent || actionValue;
            });
            const confirmationMessage = `Você está prestes a executar ações disruptivas:\n\n• ${dangerousActionLabels.join('\n• ')}\n\nTem certeza que deseja continuar?`;

            const confirmed = await showConfirmationModal(confirmationMessage);
            if (!confirmed) {
                logStatusMessage('Operação cancelada pelo usuário.', 'details');
                return; // Aborta a execução
            }
        }

        // --- Lógica Especial para Visualização VNC ---
        // Se a ação de VNC for selecionada, ela é tratada separadamente.
        if (selectedActions.includes(ACTIONS.VIEW_VNC)) {
            logStatusMessage(`--- Iniciando ação: "Visualizar Tela (VNC)" ---`, 'details');
            
            for (const ip of selectedIps) {
                const iconElement = document.getElementById(`status-${ip}`);
                iconElement.innerHTML = '🔄';
                iconElement.className = 'status-icon processing';

                try {
                    const response = await fetch(`${API_BASE_URL}/start-vnc`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ ip, password }),
                    });
                    const data = await response.json();
                    if (data.success) {
                        logStatusMessage(`[${ip}] Sessão de visualização iniciada. Abrindo em nova aba...`, 'success');
                        window.open(data.url, `vnc_${ip}`, 'fullscreen=yes');
                        updateIpStatus(ip, { success: true, message: "Sessão VNC iniciada." });
                    } else {
                        updateIpStatus(ip, { success: false, message: `Falha ao iniciar VNC: ${data.message}` });
                    }
                } catch (error) {
                    updateIpStatus(ip, { success: false, message: `Erro de conexão ao tentar iniciar VNC.` });
                }
            }
        }

        prepareUIForProcessing();

        let anySuccess = false;
        ipsWithKeyErrors.clear(); // Limpa a lista de erros de chave antes de uma nova execução
        let wallpaperPayloadForCleanup = null; // Armazena o payload para limpeza posterior

        // Loop principal para executar cada ação selecionada em sequência
        const otherActions = selectedActions.filter(a => a !== ACTIONS.VIEW_VNC); // Filtra a ação VNC
        for (const [index, action] of otherActions.entries()) { // Itera sobre as outras ações
            // Obtém o texto da ação a partir do label do checkbox
            const actionLabel = document.querySelector(`label[for="action-${action}"]`);
            const actionText = actionLabel ? actionLabel.textContent : action;

            logStatusMessage(`--- [${index + 1}/${selectedActions.length}] Iniciando ação: "${actionText}" ---`, 'details');

            // Cria um payload base para a ação atual
            const basePayload = {
                password: password,
                action: action,
            };

            // --- Lógica especial para a ação "Restaurar Atalhos" ---
            if (action === ACTIONS.ENABLE_SHORTCUTS) {
                // Pega o primeiro IP selecionado para buscar a lista de backups
                const firstIp = selectedIps[0];
                const selectedBackupFiles = await showBackupSelectionModal(firstIp, password);

                // Se o usuário cancelou o modal ou não selecionou nada, pula para a próxima ação.
                if (!selectedBackupFiles || selectedBackupFiles.length === 0) {
                    logStatusMessage(`Ação "${actionText}" pulada (nenhum backup selecionado ou ação cancelada).`, 'details');
                    continue; // Pula para a próxima ação no loop
                }
                // Adiciona os diretórios selecionados ao payload
                basePayload.backup_files = selectedBackupFiles;
            }

            // Adiciona a mensagem ao payload se a ação for correspondente
            if (action === ACTIONS.SEND_MESSAGE) {
                basePayload.message = messageText.value;
            }

            // Adiciona o nome do processo ao payload se a ação for correspondente
            if (action === ACTIONS.KILL_PROCESS) {
                basePayload.process_name = processNameText.value;
            }

            // --- Lógica especial para a ação "Definir Papel de Parede" ---
            if (action === ACTIONS.SET_WALLPAPER) {
                const file = wallpaperFile.files[0];
                if (!file) {
                    logStatusMessage(`Ação "${actionText}" pulada (nenhum arquivo de imagem selecionado).`, 'details');
                    continue;
                }

                // Lê o arquivo como Data URL (Base64) e o adiciona ao payload
                const reader = new FileReader();
                const fileReadPromise = new Promise((resolve, reject) => {
                    reader.onload = () => resolve(reader.result);
                    reader.onerror = reject;
                    reader.readAsDataURL(file);
                });
                const wallpaperData = await fileReadPromise;
                const wallpaperFilename = file.name;
                basePayload.wallpaper_data = wallpaperData;
                basePayload.wallpaper_filename = wallpaperFilename;
                wallpaperPayloadForCleanup = { wallpaper_filename: wallpaperFilename };
            }

            const totalIPs = selectedIps.length;
            let processedIPs = 0;
            updateProgressBar(0, totalIPs, actionText); // Reseta a barra para a nova ação

            // Função para executar promessas com um limite de concorrência
            async function runPromisesInParallel(taskFunctions, concurrency) {
                const queue = [...taskFunctions];

                async function worker() {
                    while (queue.length > 0) {
                        const task = queue.shift();
                        if (task) await task();
                    }
                }

                const workers = Array(concurrency).fill(null).map(worker);
                await Promise.all(workers);
            }

            // Cria um array de "tarefas" para a ação atual
            const tasks = selectedIps.map(targetIp => async () => {
                // ATUALIZAÇÃO: Define o ícone de processamento ANTES de iniciar a tarefa.
                const iconElement = document.getElementById(`status-${targetIp}`);
                iconElement.innerHTML = '🔄'; // Feedback visual imediato
                iconElement.className = 'status-icon processing';

                const result = await executeRemoteAction(targetIp, basePayload);

                if (result.success) {
                    anySuccess = true;
                }
                // Atualiza o ícone e loga a mensagem principal.
                // A função updateIpStatus já lida com a exibição de dados do sistema.
                updateIpStatus(targetIp, result);
                if (result.details) {
                    const detailsSmall = document.createElement('small');
                    detailsSmall.className = 'details-text';
                    // Adiciona o IP ao detalhe para fácil identificação quando várias máquinas falham.
                    detailsSmall.textContent = `[${targetIp}] Detalhes: ${result.details}`;
                    statusBox.appendChild(detailsSmall);
                }

                processedIPs++;
                updateProgressBar(processedIPs, totalIPs, actionText);
            });

            // Executa as tarefas para a ação atual com concorrência
            await runPromisesInParallel(tasks, MAX_CONCURRENT_TASKS);
        }

        // --- Limpeza do Papel de Parede (executado após todas as outras ações) ---
        if (wallpaperPayloadForCleanup) {
            logStatusMessage('--- Iniciando limpeza dos arquivos de papel de parede... ---', 'details');
            const cleanupPayload = {
                password: password,
                action: 'cleanup_wallpaper',
                ...wallpaperPayloadForCleanup
            };
            
            const cleanupTasks = selectedIps.map(targetIp => async () => {
                const result = await executeRemoteAction(targetIp, cleanupPayload);
                if (!result.success) { /* Loga a falha, mas não a trata como erro crítico */ }
            });

            await runPromisesInParallel(cleanupTasks, MAX_CONCURRENT_TASKS);
        }

        // --- Finalização da UI ---

        // Se pelo menos uma ação foi bem-sucedida, salva a senha para a sessão
        if (anySuccess && sessionPassword === null) {
            sessionPassword = password;
            passwordGroup.style.display = 'none';
            // Usa prepend para colocar a mensagem no topo
            const sessionMsg = document.createElement('p');
            sessionMsg.className = 'details-text';
            const i = document.createElement('i');
            i.textContent = 'Senha salva para esta sessão. Para alterar, recarregue a página.';
            sessionMsg.appendChild(i);
            statusBox.prepend(sessionMsg);
        }

        logStatusMessage('--- Processamento concluído! ---', 'details');

        // Oculta e reseta a barra de progresso para a próxima execução
        progressContainer.classList.add('hidden');
        progressBar.style.width = '0%';
        progressText.textContent = '0%';

        // Mostra o botão de correção de chaves apenas no final, se houver erros.
        if (ipsWithKeyErrors.size > 0) {
            fixKeysBtn.classList.remove('hidden');
        }

        submitBtn.disabled = false;
        submitBtn.textContent = 'Executar Ação';
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

    // Listener para o toggle de atualização automática (colocado no final para garantir que todas as funções estejam definidas)
    if (autoRefreshToggle) {
        autoRefreshToggle.addEventListener('change', () => {
            // Sempre limpa o timer existente para evitar múltiplos timers rodando.
            if (autoRefreshTimer) {
                clearInterval(autoRefreshTimer);
                autoRefreshTimer = null;
            }

            if (autoRefreshToggle.checked) {
                autoRefreshTimer = setInterval(fetchAndDisplayIps, AUTO_REFRESH_INTERVAL);
                logStatusMessage(`Atualização automática ativada (a cada ${AUTO_REFRESH_INTERVAL / 60000} minutos).`, 'details');
            } else {
                logStatusMessage('Atualização automática desativada.', 'details');
            }
        });
    }

});
