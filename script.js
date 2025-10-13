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
        GET_SYSTEM_INFO: 'get_system_info',
    });

    // Define quais ações são consideradas perigosas e exigirão confirmação.
    const DANGEROUS_ACTIONS = Object.freeze([
        ACTIONS.REBOOT,
        ACTIONS.SHUTDOWN,
        ACTIONS.UPDATE_SYSTEM,
        ACTIONS.CLEAR_IMAGES,
        ACTIONS.DISABLE_PERIPHERALS, // Pode impedir o acesso remoto se algo der errado
    ]);

    const API_BASE_URL = 'http://127.0.0.1:5000';
    // Define o número máximo de ações remotas a serem executadas simultaneamente.
    // Um valor maior pode acelerar o processo, mas consome mais recursos do servidor.
    // Um valor entre 5 e 10 é geralmente um bom equilíbrio.
    const MAX_CONCURRENT_TASKS = 10;

    const ipListContainer = document.getElementById('ip-list');
    const ipSearchInput = document.getElementById('ip-search-input');
    const selectAllCheckbox = document.getElementById('select-all');
    const actionForm = document.getElementById('action-form');
    const statusBox = document.getElementById('status-section');
    const submitBtn = document.getElementById('submit-btn');
    const refreshBtn = document.getElementById('refresh-btn');
    const resetBtn = document.getElementById('reset-btn');
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
    const processNameGroup = document.getElementById('process-name-group');
    const processNameText = document.getElementById('process-name-text');
    const actionCheckboxGroup = document.getElementById('action-checkbox-group');
    // Elementos do Modal de Confirmação
    const confirmationModal = document.getElementById('confirmation-modal');
    const modalConfirmBtn = document.getElementById('modal-confirm-btn');
    const modalCancelBtn = document.getElementById('modal-cancel-btn');
    const modalDescription = document.getElementById('modal-description');
    // Elementos do Modal de Backup
    const backupModal = document.getElementById('backup-modal');
    const backupListContainer = document.getElementById('backup-list');
    const backupConfirmBtn = document.getElementById('backup-modal-confirm-btn');
    const backupCancelBtn = document.getElementById('backup-modal-cancel-btn');

    let sessionPassword = null;

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
        const isAnyIpSelected = document.querySelectorAll('input[name="ip"]:checked').length > 0;
        const isAnyActionSelected = document.querySelectorAll('input[name="action"]:checked').length > 0;
        let isActionRequirementMet = true;

        // Validação específica para a ação de enviar mensagem
        if (sendMessageCheckbox.checked) {
            isActionRequirementMet = messageText.value.trim().length > 0;
        }
        
        // Validação específica para a ação de finalizar processo
        if (killProcessCheckbox.checked) {
            isActionRequirementMet = processNameText.value.trim().length > 0;
        }

        submitBtn.disabled = !(isPasswordFilled && isAnyIpSelected && isAnyActionSelected && isActionRequirementMet);
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

    // --- Lógica para todas as Seções Retráteis ---
    const allCollapsibles = document.querySelectorAll('.collapsible-section, .collapsible-fieldset');
    allCollapsibles.forEach(collapsible => {
        const indicator = collapsible.querySelector('.collapsible-indicator');
        if (!indicator) return;

        collapsible.addEventListener('toggle', () => {
                // Altera o texto do indicador com base no estado (aberto/fechado) da seção.
            indicator.textContent = collapsible.open ? '[-]' : '[+]';
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

    // Mostra/esconde o campo de mensagem com base no checkbox correspondente
    sendMessageCheckbox.addEventListener('change', () => {
        if (sendMessageCheckbox.checked) {
            messageGroup.classList.remove('hidden');
        } else {
            messageGroup.classList.add('hidden');
        }
        checkFormValidity();
    });

    // Mostra/esconde o campo de upload de papel de parede
    setWallpaperCheckbox.addEventListener('change', () => {
        if (setWallpaperCheckbox.checked) {
            wallpaperGroup.classList.remove('hidden');
        } else {
            wallpaperGroup.classList.add('hidden');
        }
        checkFormValidity();
    });

    // Mostra/esconde o campo de nome do processo
    killProcessCheckbox.addEventListener('change', () => {
        if (killProcessCheckbox.checked) {
            processNameGroup.classList.remove('hidden');
        } else {
            processNameGroup.classList.add('hidden');
        }
        checkFormValidity();
    });

    // Adiciona listener para todos os checkboxes de ação
    actionCheckboxGroup.addEventListener('change', (event) => {
        const clickedCheckbox = event.target;
        // Garante que estamos lidando com um checkbox de ação
        if (!clickedCheckbox.matches('input[name="action"]')) return;

        // Lógica de ações conflitantes usando o atributo data-conflicts-with
        const conflictingActionId = clickedCheckbox.dataset.conflictsWith;
        if (clickedCheckbox.checked && conflictingActionId) {
            const conflictingCheckbox = document.getElementById(conflictingActionId);
            if (conflictingCheckbox) {
                conflictingCheckbox.checked = false;
            }
        }

        checkFormValidity();
    });

    // Função para buscar e exibir os IPs
    async function fetchAndDisplayIps() {
        refreshBtn.disabled = true;
        refreshBtn.classList.add('loading');
        refreshBtnText.textContent = 'Buscando...';

        ipListContainer.innerHTML = ''; // Limpa a lista anterior
        submitBtn.disabled = true;
        selectAllCheckbox.checked = false;

        // Exibe o "skeleton loader" para um feedback visual imediato
        for (let i = 0; i < 6; i++) {
            const skeleton = document.createElement('div');
            skeleton.className = 'skeleton-item';
            ipListContainer.appendChild(skeleton);
        }
        statusBox.innerHTML = '<p>Buscando dispositivos na rede...</p>';

        try {
            const response = await fetch(`${API_BASE_URL}/discover-ips`, {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await response.json();
            
            ipListContainer.innerHTML = ''; // Limpa o skeleton loader

            if (data.success) {
                const ipsDisponiveis = data.ips;
                if (ipsDisponiveis.length > 0) {
                    const fragment = document.createDocumentFragment();
                    ipsDisponiveis.forEach((ip, index) => {
                        const item = document.createElement('div');
                        item.className = 'ip-item';
                        item.dataset.ip = ip;
                        item.style.animationDelay = `${index * 0.05}s`; // Adiciona atraso para efeito escalonado
                        const lastOctet = ip.split('.').pop(); // Pega apenas o final do IP

                        // Usar createElement é mais seguro e performático para listas dinâmicas
                        const checkbox = document.createElement('input');
                        checkbox.type = 'checkbox';
                        checkbox.id = `ip-${ip}`;
                        checkbox.name = 'ip';
                        checkbox.value = ip;

                        const label = document.createElement('label');
                        label.htmlFor = `ip-${ip}`;
                        label.textContent = lastOctet;

                        const statusIcon = document.createElement('span');
                        statusIcon.className = 'status-icon';
                        statusIcon.id = `status-${ip}`;

                        item.append(checkbox, label, statusIcon);
                        fragment.appendChild(item);
                    });
                    ipListContainer.appendChild(fragment); // Adiciona todos os IPs de uma só vez
                    statusBox.innerHTML = '<p>Selecione os dispositivos para gerenciar.</p>';
                    // Chama a função de validação após carregar os IPs
                    checkFormValidity(); 
                } else {
                    statusBox.innerHTML = ''; // Limpa a mensagem "Buscando..."
                    logStatusMessage('Nenhum dispositivo encontrado na rede.', 'error');
                }
            } else {
                statusBox.innerHTML = '';
                logStatusMessage(`Erro ao escanear a rede: ${data.message}`, 'error');
            }
        } catch (error) {
            ipListContainer.innerHTML = ''; // Limpa o skeleton em caso de erro de conexão
            statusBox.innerHTML = ''; // Limpa a mensagem "Buscando..."
            logStatusMessage('Erro de conexão com o servidor. Verifique se o backend está rodando.', 'error');
        } finally {
            // Garante que o botão de refresh seja reativado
            refreshBtn.disabled = false;
            refreshBtn.classList.remove('loading');
            refreshBtnText.textContent = 'Atualizar Lista';
        }
    }

    // Dispara a busca inicial de IPs
    fetchAndDisplayIps();

    // Listener para o botão de atualização
    refreshBtn.addEventListener('click', () => {
        fetchAndDisplayIps();
    });

    // Função para limpar a seleção e redefinir a interface
    function resetUI() {
        // 1. Desmarcar todos os checkboxes de IP
        document.querySelectorAll('input[name="ip"]').forEach(checkbox => {
            checkbox.checked = false;
        });
        selectAllCheckbox.checked = false;

        // 1.b. Desmarcar todos os checkboxes de ação
        document.querySelectorAll('input[name="action"]').forEach(checkbox => {
            checkbox.checked = false;
        });
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
    actionForm.addEventListener('change', checkFormValidity);

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
        const controller = new AbortController();
        // Ações longas como atualização de sistema precisam de um timeout maior. O backend está
        // configurado para 300s (5 min), então usamos um valor um pouco maior aqui para
        // garantir que o timeout do cliente não ocorra antes do timeout do servidor.
        const timeoutDuration = isLongRunning ? 305000 : 30000; // ~5min ou 30s
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
            return {
                success: false,
                message: isTimeout ? 'Ação expirou (timeout).' : 'Erro de comunicação com o servidor.',
                details: isTimeout ? `A ação excedeu o limite de ${timeoutDuration / 1000} segundos.` : `Não foi possível conectar ao backend. Verifique se ele está em execução.`
            };
        } finally {
            // O clearTimeout foi movido para dentro do try/catch para ser mais preciso.
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

        // Constrói a mensagem de status programaticamente para evitar injeção de HTML.
        const p = document.createElement('p');
        const statusSpan = document.createElement('span');
        statusSpan.className = `${cssClass}-text`;
        statusSpan.textContent = `${icon} ${ip}: ${result.message}`;
        p.appendChild(statusSpan);

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

    // Listener para o evento de submit do formulário
    actionForm.addEventListener('submit', async (event) => {
        event.preventDefault(); // Impede o recarregamento da página

        const password = sessionPassword || passwordInput.value;
        const selectedActions = Array.from(document.querySelectorAll('input[name="action"]:checked')).map(cb => cb.value);
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
            const dangerousActionLabels = dangerousActionsSelected.map(action => {
                return document.querySelector(`label[for="action-${action}"]`)?.textContent || action;
            });
            const confirmationMessage = `Você está prestes a executar ações disruptivas:\n\n• ${dangerousActionLabels.join('\n• ')}\n\nTem certeza que deseja continuar?`;

            const confirmed = await showConfirmationModal(confirmationMessage);
            if (!confirmed) {
                logStatusMessage('Operação cancelada pelo usuário.', 'details');
                return; // Aborta a execução
            }
        }

        prepareUIForProcessing();

        let anySuccess = false;

        // Loop principal para executar cada ação selecionada em sequência
        for (const [index, action] of selectedActions.entries()) {
            const actionText = document.querySelector(`label[for="action-${action}"]`)?.textContent || action;
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
                basePayload.wallpaper_data = await fileReadPromise;
                basePayload.wallpaper_filename = file.name;
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
                const iconElement = document.getElementById(`status-${targetIp}`);
                iconElement.innerHTML = '🔄'; // Feedback visual imediato
                iconElement.className = 'status-icon processing';

                const isLongRunning = action === ACTIONS.UPDATE_SYSTEM;
                const result = await executeRemoteAction(targetIp, basePayload, isLongRunning);

                if (result.success) {
                    anySuccess = true;
                }
                // Atualiza o ícone e loga a mensagem principal.
                // A função updateIpStatus já lida com a exibição de dados do sistema.
                updateIpStatus(targetIp, result);

                // Loga os detalhes de erro/aviso separadamente para maior clareza,
                // mas apenas se não for uma ação de 'get_system_info' (cujos detalhes já estão formatados).
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

        submitBtn.disabled = false;
        submitBtn.textContent = 'Executar Ação';
    });
});
