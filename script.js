document.addEventListener('DOMContentLoaded', () => {
    const ipListContainer = document.getElementById('ip-list');
    const selectAllCheckbox = document.getElementById('select-all');
    const actionForm = document.getElementById('action-form');
    const statusBox = document.getElementById('status-section');
    const submitBtn = document.getElementById('submit-btn');
    const refreshBtn = document.getElementById('refresh-btn');
    const passwordInput = document.getElementById('password');
    const actionSelect = document.getElementById('action');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');
    const progressContainer = document.getElementById('progress-section');
    const themeToggle = document.getElementById('theme-toggle');
    const themeLabel = document.querySelector('.theme-label');
    const messageGroup = document.getElementById('message-group');
    const messageText = document.getElementById('message-text');

    // Função de validação que habilita/desabilita o botão de submit
    function checkFormValidity() {
        const isPasswordFilled = passwordInput.value.length > 0;
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
        }
    }

    // Dispara a busca inicial de IPs
    fetchAndDisplayIps();

    // Listener para o botão de atualização
    refreshBtn.addEventListener('click', () => {
        fetchAndDisplayIps();
    });

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

        const password = passwordInput.value;
        const selectedIps = Array.from(document.querySelectorAll('input[name="ip"]:checked')).map(checkbox => checkbox.value);
        const payload = {
            ip: '', // será preenchido no loop
            password: password,
            action: action,
        };

        if (selectedIps.length === 0) {
            statusBox.innerHTML = '<p class="error-text">Por favor, selecione pelo menos um IP.</p>';
            statusBox.className = 'status-box error';
            return;
        }

        if (!password) {
            statusBox.innerHTML = '<p class="error-text">Por favor, digite a senha.</p>';
            statusBox.className = 'status-box error';
            return;
        }

        // Adiciona a mensagem ao payload se a ação for correspondente
        if (action === 'enviar_mensagem') {
            payload.message = messageText.value;
        }

        submitBtn.disabled = true;
        submitBtn.textContent = 'Processando...';
        progressContainer.style.display = 'block';
        statusBox.innerHTML = '';
        statusBox.className = 'status-box';
        
        document.querySelectorAll('.status-icon').forEach(icon => {
            icon.innerHTML = '';
            icon.className = 'status-icon';
        });

        const totalIPs = selectedIps.length;
        let processedIPs = 0;
        const statusMessages = [];

        const promises = selectedIps.map(targetIp => {
            return new Promise(async resolve => {
                const iconElement = document.getElementById(`status-${targetIp}`);
                
                iconElement.innerHTML = '🔄';
                iconElement.className = 'status-icon processing';
                
                try {
                    payload.ip = targetIp; // Define o IP para a iteração atual
                    const response = await fetch('http://127.0.0.1:5000/gerenciar_atalhos_ip', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload), // Envia o payload completo, incluindo a mensagem
                    });
                    const data = await response.json();
                    
                    if (data.success) {
                        iconElement.innerHTML = '✅';
                        iconElement.className = 'status-icon success';
                        let message = `<span class="success-text">✅ ${targetIp}: ${data.message}</span>`;
                        if (data.details) {
                            message += `<br><small class="details-text">${data.details}</small>`;
                        }
                        statusMessages.push(`<p>${message}</p>`);
                    } else {
                        iconElement.innerHTML = '❌';
                        iconElement.className = 'status-icon error';
                        let message = `<span class="error-text">❌ ${targetIp}: ${data.message}</span>`;
                        if (data.details) {
                            message += `<br><small class="details-text">${data.details}</small>`;
                        }
                        statusMessages.push(`<p>${message}</p>`);
                    }
                } catch (error) {
                    iconElement.innerHTML = '❌';
                    iconElement.className = 'status-icon error';
                    statusMessages.push(`<p><span class="error-text">❌ ${targetIp}: Erro de conexão - O servidor pode não estar respondendo.</span><br><small class="details-text">${error.message}</small></p>`);
                } finally {
                    processedIPs++;
                    const progress = Math.round((processedIPs / totalIPs) * 100);
                    progressBar.style.width = `${progress}%`;
                    progressText.textContent = `Processando ${processedIPs} de ${totalIPs} (${progress}%)`;
                    resolve();
                }
            });
        });

        await Promise.all(promises);

        statusMessages.push(`<p>-----------------------------------</p><p>Processamento concluído!</p>`);
        statusBox.innerHTML = statusMessages.join('');

        submitBtn.disabled = false;
        submitBtn.textContent = 'Executar Ação';
    });
});
