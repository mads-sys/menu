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
    const actionSelect = document.getElementById('action');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');
    const progressContainer = document.getElementById('progress-section');
    const themeToggle = document.getElementById('theme-toggle');
    const themeLabel = document.querySelector('.theme-label');
    const messageGroup = document.getElementById('message-group');
    const messageText = document.getElementById('message-text');
    const autoRefreshToggle = document.getElementById('auto-refresh-toggle');

    let sessionPassword = null;
    let autoRefreshIntervalId = null;

    // Função de validação que habilita/desabilita o botão de submit
    function checkFormValidity() {
        const isPasswordFilled = sessionPassword !== null || passwordInput.value.length > 0;
        const isAnyIpSelected = document.querySelectorAll('input[name="ip"]:checked').length > 0;
        let isActionRequirementMet = true;

        // Validação específica para a ação de enviar mensagem
        if (actionSelect.value === 'enviar_mensagem') {
            isActionRequirementMet = messageText.value.trim().length > 0;
        }
        
        submitBtn.disabled = !(isPasswordFilled && isAnyIpSelected && isActionRequirementMet);
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

    // Mostra/esconde o campo de mensagem com base na ação selecionada
    actionSelect.addEventListener('change', () => {
        if (actionSelect.value === 'enviar_mensagem') {
            messageGroup.style.display = 'block';
        } else {
            messageGroup.style.display = 'none';
        }
        // Revalida o formulário sempre que a ação muda
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
                        ipListContainer.appendChild(item);
                    });
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

        // 2. Limpar os ícones de status de cada IP
        document.querySelectorAll('.status-icon').forEach(icon => {
            icon.innerHTML = '';
            icon.className = 'status-icon';
        });

        // 3. Redefinir la caixa de status
        statusBox.innerHTML = '<p>Aguardando comando...</p>';

        // 4. Ocultar e redefinir a barra de progresso
        progressContainer.style.display = 'none';
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

    // Listener para o evento de submit do formulário
    actionForm.addEventListener('submit', async (event) => {
        event.preventDefault(); // Impede o recarregamento da página

        const action = actionSelect.value;
        const actionsToConfirm = ['desativar_perifericos', 'ocultar_sistema', 'reiniciar', 'desligar', 'limpar_imagens'];

        if (actionsToConfirm.includes(action)) {
            const userConfirmed = window.confirm(
                "Esta é uma ação potencialmente disruptiva. Você tem certeza que deseja continuar?"
            );
            if (!userConfirmed) {
                return; // Aborta a execução se o usuário cancelar
            }
        }

        const password = sessionPassword || passwordInput.value;
        const selectedIps = Array.from(document.querySelectorAll('input[name="ip"]:checked')).map(checkbox => checkbox.value);

        if (selectedIps.length === 0) {
            statusBox.innerHTML = '<p class="error-text">Por favor, selecione pelo menos um IP.</p>';
            return;
        }

        if (!password) {
            statusBox.innerHTML = '<p class="error-text">Por favor, digite a senha.</p>';
            return;
        }

        // Cria um payload base com as informações comuns
        const basePayload = {
            password: password,
            action: action,
        };
        // Adiciona a mensagem ao payload se a ação for correspondente
        if (action === 'enviar_mensagem') {
            basePayload.message = messageText.value;
        }

        submitBtn.disabled = true;
        submitBtn.textContent = 'Processando...';
        progressContainer.style.display = 'block';
        statusBox.innerHTML = ''; // Limpa o status box antes de começar
        
        document.querySelectorAll('.status-icon').forEach(icon => {
            icon.innerHTML = '';
            icon.className = 'status-icon';
        });

        const totalIPs = selectedIps.length;
        let processedIPs = 0;
        let anySuccess = false;
        
        // Função para executar promessas com um limite de concorrência
        async function runPromisesInParallel(taskFunctions, concurrency) {
            const queue = [...taskFunctions];

            async function worker() {
                while (queue.length > 0) {
                    const task = queue.shift(); // Pega a próxima tarefa da fila
                    if (task) {
                        await task();
                    }
                }
            }

            const workers = Array(concurrency).fill(null).map(worker);
            await Promise.all(workers);
        }

        // Cria um array de "tarefas" (funções que retornam uma promessa)
        const tasks = selectedIps.map(targetIp => async () => {
            const iconElement = document.getElementById(`status-${targetIp}`);
            iconElement.innerHTML = '🔄';
            iconElement.className = 'status-icon processing';

            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 30000); // Timeout aumentado para 30 segundos

            let statusMessage = '';

            try {
                const currentPayload = { ...basePayload, ip: targetIp };
                const response = await fetch('http://127.0.0.1:5000/gerenciar_atalhos_ip', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(currentPayload),
                    signal: controller.signal, // Adiciona o sinal de abortar
                });
                const data = await response.json();

                if (data.success) {
                    anySuccess = true;
                    iconElement.innerHTML = '✅';
                    iconElement.className = 'status-icon success';
                    statusMessage = `<span class="success-text">✅ ${targetIp}: ${data.message}</span>`;
                    if (data.details) statusMessage += `<br><small class="details-text">${data.details}</small>`;
                } else {
                    iconElement.innerHTML = '❌';
                    iconElement.className = 'status-icon error';
                    statusMessage = `<span class="error-text">❌ ${targetIp}: ${data.message}</span>`;
                    if (data.details) statusMessage += `<br><small class="details-text">${data.details}</small>`;
                }
            } catch (error) {
                iconElement.innerHTML = '❌';
                iconElement.className = 'status-icon error';
                if (error.name === 'AbortError') {
                    statusMessage = `<span class="error-text">❌ ${targetIp}: Ação expirou (timeout de 30s). O dispositivo pode estar offline ou o servidor sobrecarregado.</span>`;
                } else if (error instanceof SyntaxError) {
                    statusMessage = `<span class="error-text">❌ ${targetIp}: Resposta inválida do servidor.</span><br><small class="details-text">O backend (Python) provavelmente encontrou um erro e retornou uma página HTML. Verifique os logs do servidor.</small>`;
                } else {
                    statusMessage = `<span class="error-text">❌ ${targetIp}: Erro de conexão.</span><br><small class="details-text">${error.message}</small>`;
                }
            } finally {
                clearTimeout(timeoutId); // Limpa o timeout para evitar vazamento de memória

                // Adiciona a mensagem de status em tempo real
                const p = document.createElement('p');
                p.innerHTML = statusMessage;
                statusBox.appendChild(p);
                statusBox.scrollTop = statusBox.scrollHeight; // Auto-scroll para a última mensagem

                processedIPs++;
                const progress = Math.round((processedIPs / totalIPs) * 100);
                progressBar.style.width = `${progress}%`;
                progressText.textContent = `Processando ${processedIPs} de ${totalIPs} (${progress}%)`;
            }
        });

        // Executa as tarefas com uma concorrência de 5 (processa 5 IPs por vez)
        await runPromisesInParallel(tasks, 5);

        // Se pelo menos uma ação foi bem-sucedida, salva a senha para a sessão
        if (anySuccess && sessionPassword === null) {
            sessionPassword = password;
            passwordGroup.style.display = 'none';
            const p = document.createElement('p');
            p.className = 'details-text';
            p.innerHTML = `<i>Senha salva para esta sessão. Para alterar, recarregue a página.</i>`;
            statusBox.prepend(p); // Adiciona a mensagem no topo do log
        }

        const p = document.createElement('p');
        p.innerHTML = `-----------------------------------<br>Processamento concluído!`;
        statusBox.appendChild(p);
        statusBox.scrollTop = statusBox.scrollHeight; // Garante que o scroll chegue ao fim

        submitBtn.disabled = false;
        submitBtn.textContent = 'Executar Ação';
    });
});
