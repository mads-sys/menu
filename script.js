document.addEventListener('DOMContentLoaded', () => {
    const ipListContainer = document.getElementById('ip-list');
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
    const autoRefreshToggle = document.getElementById('auto-refresh-toggle');
    const sendMessageCheckbox = document.getElementById('action-enviar_mensagem');
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
    let autoRefreshIntervalId = null;

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
    const currentTheme = localStorage.getItem('theme') || 'light'; // Padrão para 'light'
    applyTheme(currentTheme);

    // Mostra/esconde o campo de mensagem com base no checkbox correspondente
    sendMessageCheckbox.addEventListener('change', () => {
        if (sendMessageCheckbox.checked) {
            messageGroup.classList.remove('hidden');
        } else {
            messageGroup.classList.add('hidden');
        }
        checkFormValidity();
    });

    // Mapeamento de ações conflitantes para evitar seleções inválidas
    const conflictingActions = {
        'desativar': 'ativar',
        'ativar': 'desativar',
        'mostrar_sistema': 'ocultar_sistema',
        'ocultar_sistema': 'mostrar_sistema',
        'desativar_barra_tarefas': 'ativar_barra_tarefas',
        'ativar_barra_tarefas': 'desativar_barra_tarefas',
        'bloquear_barra_tarefas': 'desbloquear_barra_tarefas',
        'desbloquear_barra_tarefas': 'bloquear_barra_tarefas',
        'desativar_perifericos': 'ativar_perifericos',
        'ativar_perifericos': 'desativar_perifericos'
    };

    // Adiciona listener para todos os checkboxes de ação
    actionCheckboxGroup.addEventListener('change', (event) => {
        const clickedCheckbox = event.target;
        // Garante que estamos lidando com um checkbox de ação
        if (!clickedCheckbox.matches('input[name="action"]')) return;

        const actionValue = clickedCheckbox.value;

        // Desmarca a ação conflitante se a atual for marcada
        if (clickedCheckbox.checked && conflictingActions[actionValue]) {
            const conflictingCheckbox = document.getElementById(`action-${conflictingActions[actionValue]}`);
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
            const response = await fetch('http://127.0.0.1:5000/discover-ips', {
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
                        item.innerHTML = `
                            <input type="checkbox" id="ip-${ip}" name="ip" value="${ip}">
                            <label for="ip-${ip}">${lastOctet}</label>
                            <span class="status-icon" id="status-${ip}"></span>
                        `;
                        fragment.appendChild(item);
                    });
                    ipListContainer.appendChild(fragment); // Adiciona todos os IPs de uma só vez
                    statusBox.innerHTML = '<p>Selecione os IPs para gerenciar.</p>';
                    // Chama a função de validação após carregar os IPs
                    checkFormValidity(); 
                } else {
                    statusBox.innerHTML = '<p class="error-text">Nenhum dispositivo encontrado na rede.</p>';
                }
            } else {
                statusBox.innerHTML = `<p class="error-text">Erro ao escanear a rede: ${data.message}</p>`;
            }
        } catch (error) {
            ipListContainer.innerHTML = ''; // Limpa o skeleton em caso de erro de conexão
            statusBox.innerHTML = `<p class="error-text">Erro de conexão com o servidor. Verifique se o backend está rodando.</p>`;
        } finally {
            // Garante que o botão de refresh seja reativado
            refreshBtn.disabled = false;
            refreshBtn.classList.remove('loading');
            refreshBtnText.textContent = 'Atualizar Lista';
        }
    }

    // --- Lógica da Atualização Automática ---
    function toggleAutoRefresh() {
        if (autoRefreshToggle.checked && autoRefreshIntervalId === null) {
            // Inicia o intervalo se estiver marcado e não houver um ativo
            autoRefreshIntervalId = setInterval(() => {
                // Não atualiza se uma busca manual ou uma ação já estiver em andamento
                const isActionRunning = submitBtn.textContent !== 'Executar Ação';
                if (refreshBtn.disabled || isActionRunning) {
                    return;
                }
                console.log('Atualização automática de IPs...');
                fetchAndDisplayIps();
            }, 30000); // Atualiza a cada 30 segundos
        } else if (!autoRefreshToggle.checked && autoRefreshIntervalId !== null) {
            // Para o intervalo se não estiver marcado e houver um ativo
            clearInterval(autoRefreshIntervalId);
            autoRefreshIntervalId = null;
        }
    }

    // Listener para o botão de atualização automática
    autoRefreshToggle.addEventListener('change', toggleAutoRefresh);

    // Dispara a busca inicial de IPs
    fetchAndDisplayIps();
    // Inicia o ciclo de atualização automática com base no estado inicial do checkbox
    toggleAutoRefresh();

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
        messageGroup.classList.add('hidden');

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
    selectAllCheckbox.addEventListener('change', (event) => {
        const isChecked = event.target.checked;
        document.querySelectorAll('input[name="ip"]').forEach(checkbox => {
            checkbox.checked = isChecked;
        });
        checkFormValidity(); // Chama a validação após a seleção
    });

    // Listener para o campo de senha
    passwordInput.addEventListener('input', checkFormValidity);

    // Listener para o campo de mensagem
    messageText.addEventListener('input', checkFormValidity);

    // Listener para as mudanças na lista de IPs
    ipListContainer.addEventListener('change', checkFormValidity);

    /**
     * Função auxiliar para logar mensagens na caixa de status.
     * @param {string} message - A mensagem a ser exibida (pode conter HTML).
     * @param {'success'|'error'|'details'|'info'} type - O tipo de mensagem para estilização.
     */
    function logStatusMessage(message, type = 'info') {
        const p = document.createElement('p');
        if (type === 'details') {
            p.className = 'details-text';
            p.innerHTML = `<i>${message}</i>`;
        } else {
            // Para success e error, a mensagem já vem com o span formatado
            p.innerHTML = message;
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
        const progress = total > 0 ? Math.round((processed / total) * 100) : 0;
        const actionPrefix = actionText ? `[${actionText}] ` : '';
        progressBar.style.width = `${progress}%`;
        progressText.textContent = `${actionPrefix}Processando ${processed} de ${total} (${progress}%)`;
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
        return new Promise((resolve) => {
            modalDescription.textContent = message;
            confirmationModal.classList.remove('hidden');

            const cleanup = () => {
                modalConfirmBtn.removeEventListener('click', confirmHandler);
                modalCancelBtn.removeEventListener('click', cancelHandler);
            };

            const confirmHandler = () => {
                confirmationModal.classList.add('hidden');
                cleanup();
                resolve(true);
            };

            const cancelHandler = () => {
                confirmationModal.classList.add('hidden');
                cleanup();
                resolve(false);
            };

            modalConfirmBtn.addEventListener('click', confirmHandler, { once: true });
            modalCancelBtn.addEventListener('click', cancelHandler, { once: true });
        });
    }

    /**
     * Exibe um modal para o usuário selecionar quais backups de atalhos restaurar.
     * @param {string} ip - O IP do dispositivo para verificar os backups.
     * @param {string} password - A senha SSH.
     * @returns {Promise<string[]|null>} - Resolve com um array de diretórios selecionados, ou `null` se cancelado.
     */
    function showBackupSelectionModal(ip, password) {
        return new Promise(async (resolve) => {
            // Mostra um estado de carregamento no modal
            backupListContainer.innerHTML = '<p>Buscando backups...</p>';
            backupConfirmBtn.disabled = true;
            backupModal.classList.remove('hidden');

            const cleanupAndResolve = (value) => {
                backupModal.classList.add('hidden');
                // Remove event listeners para evitar memory leaks
                backupConfirmBtn.removeEventListener('click', confirmHandler);
                backupCancelBtn.removeEventListener('click', cancelHandler);
                resolve(value);
            };

            const confirmHandler = () => {
                const allChecked = Array.from(backupListContainer.querySelectorAll('input[name="backup-file"]:checked'))
                    .map(cb => cb.value);
                console.log('Backup Modal: All checked values before filter:', allChecked);

                const selectedDirs = allChecked.filter(value => value !== '__ALL__');
                console.log('Backup Modal: Filtered values to be sent:', selectedDirs);

                cleanupAndResolve(selectedDirs);
            };

            const cancelHandler = () => {
                cleanupAndResolve(null); // Resolve com null no cancelamento
            };

            // Adiciona os listeners uma única vez
            backupConfirmBtn.addEventListener('click', confirmHandler, { once: true });
            backupCancelBtn.addEventListener('click', cancelHandler, { once: true });

            try {
                const response = await fetch('http://127.0.0.1:5000/list-backups', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ip, password }),
                });
                const data = await response.json();

                if (!data.success || Object.keys(data.backups).length === 0) {
                    backupListContainer.innerHTML = `<p class="error-text">${data.message || 'Nenhum backup encontrado.'}</p>`;
                } else {
                    backupConfirmBtn.disabled = false;
                    // Popula o modal com os checkboxes dos backups encontrados
                    backupListContainer.innerHTML = `
                        <div class="checkbox-item">
                            <input type="checkbox" id="backup-__ALL__" name="backup-file" value="__ALL__">
                            <label for="backup-__ALL__"><strong>Restaurar Todos</strong></label>
                        </div>
                        <hr style="border-color: var(--border-color-light); margin: 0.5rem 0;">
                    `;
                    const fragment = document.createDocumentFragment();
                    // Itera sobre os diretórios e seus arquivos
                    for (const directory in data.backups) {
                        const fieldset = document.createElement('fieldset');
                        const legend = document.createElement('legend');
                        legend.textContent = directory;
                        fieldset.appendChild(legend);

                        data.backups[directory].forEach(filename => {
                            const fullPath = `${directory}/${filename}`;
                            // Cria um ID seguro para o elemento
                            const safeId = `backup-${fullPath.replace(/[^a-zA-Z0-9]/g, '-')}`;
                            const div = document.createElement('div');
                            div.className = 'checkbox-item';
                            div.innerHTML = `
                                <input type="checkbox" id="${safeId}" name="backup-file" value="${fullPath}">
                                <label for="${safeId}">${filename}</label>
                            `;
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
            }
        });
    }

    // Listener para o evento de submit do formulário
    actionForm.addEventListener('submit', async (event) => {
        event.preventDefault(); // Impede o recarregamento da página

        const password = sessionPassword || passwordInput.value;
        const selectedActions = Array.from(document.querySelectorAll('input[name="action"]:checked')).map(cb => cb.value);
        const selectedIps = Array.from(document.querySelectorAll('input[name="ip"]:checked')).map(checkbox => checkbox.value);

        if (selectedIps.length === 0) {
            logStatusMessage('<span class="error-text">Por favor, selecione pelo menos um IP.</span>', 'error');
            return;
        }

        if (!password) {
            logStatusMessage('<span class="error-text">Por favor, digite a senha.</span>', 'error');
            return;
        }

        if (selectedActions.length === 0) {
            logStatusMessage('<span class="error-text">Por favor, selecione pelo menos uma ação.</span>', 'error');
            return;
        }

        prepareUIForProcessing();

        let anySuccess = false;

        // Loop principal para executar cada ação selecionada em sequência
        for (const [index, action] of selectedActions.entries()) {
            const actionText = document.querySelector(`label[for="action-${action}"]`).textContent;
            logStatusMessage(`--- [${index + 1}/${selectedActions.length}] Iniciando ação: "${actionText}" ---`, 'details');

            // Cria um payload base para a ação atual
            const basePayload = {
                password: password,
                action: action,
            };

            // --- Lógica especial para a ação "Restaurar Atalhos" ---
            if (action === 'ativar') {
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
            if (action === 'enviar_mensagem') {
                basePayload.message = messageText.value;
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
                iconElement.innerHTML = '🔄';
                iconElement.className = 'status-icon processing';

                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 30000);

                let statusMessage = '';

                try {
                    const currentPayload = { ...basePayload, ip: targetIp };
                    const response = await fetch('http://127.0.0.1:5000/gerenciar_atalhos_ip', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(currentPayload),
                        signal: controller.signal,
                    });
                    const data = await response.json();

                    if (data.success) {
                        anySuccess = true;
                        iconElement.innerHTML = '✅';
                        iconElement.className = 'status-icon success';
                        statusMessage = `<span class="success-text">✅ ${targetIp}: ${data.message}</span>`;
                    } else {
                        iconElement.innerHTML = '❌';
                        iconElement.className = 'status-icon error';
                        statusMessage = `<span class="error-text">❌ ${targetIp}: ${data.message}</span>`;
                    }
                    if (data.details) statusMessage += `<br><small class="details-text">${data.details}</small>`;
                } catch (error) {
                    iconElement.innerHTML = '❌';
                    iconElement.className = 'status-icon error';
                    statusMessage = `<span class="error-text">❌ ${targetIp}: ${error.name === 'AbortError' ? 'Ação expirou (timeout).' : 'Erro de conexão.'}</span>`;
                } finally {
                    clearTimeout(timeoutId);
                    logStatusMessage(statusMessage);
                    processedIPs++;
                    updateProgressBar(processedIPs, totalIPs, actionText);
                }
            });

            // Executa as tarefas para a ação atual com concorrência
            await runPromisesInParallel(tasks, 5);
        }

        // --- Finalização da UI ---

        // Se pelo menos uma ação foi bem-sucedida, salva a senha para a sessão
        if (anySuccess && sessionPassword === null) {
            sessionPassword = password;
            passwordGroup.style.display = 'none';
            // Usa prepend para colocar a mensagem no topo
            const sessionMsg = document.createElement('p');
            sessionMsg.className = 'details-text';
            sessionMsg.innerHTML = `<i>Senha salva para esta sessão. Para alterar, recarregue a página.</i>`;
            statusBox.prepend(sessionMsg);
        }
        logStatusMessage(`-----------------------------------<br>Processamento concluído!`);

        // Oculta e reseta a barra de progresso para a próxima execução
        progressContainer.classList.add('hidden');
        progressBar.style.width = '0%';
        progressText.textContent = '0%';

        submitBtn.disabled = false;
        submitBtn.textContent = 'Executar Ação';
    });
});
