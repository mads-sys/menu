document.addEventListener('DOMContentLoaded', () => {
    // Lista de IPs de exemplo que seriam obtidos de uma fonte real (ex: API)
    const ipsDisponiveis = [
        '192.168.0.101',
        '192.168.0.103',
        '192.168.0.104',
        '192.168.0.105',
        '192.168.0.106',
        '192.168.0.107',
        '192.168.0.108',
        '192.168.0.109',
        '192.168.0.110',
        '192.168.0.111',
        '192.168.0.112',
        '192.168.0.113',
        '192.168.0.114',
        '192.168.0.115',
        '192.168.0.116',
        '192.168.0.117',
        '192.168.0.118',
        '192.168.0.119',
        '192.168.0.120',
        '192.168.0.121',
        '192.168.0.122',
        '192.168.0.123',
        '192.168.0.124',
        '192.168.0.125'
    ];

    const ipListContainer = document.getElementById('ip-list');
    const selectAllCheckbox = document.getElementById('select-all');

    // Gera a lista de IPs dinamicamente com checkboxes
    ipsDisponiveis.forEach(ip => {
        const item = document.createElement('div');
        item.className = 'ip-item';
        item.innerHTML = `
            <input type="checkbox" id="ip-${ip}" name="ip" value="${ip}">
            <label for="ip-${ip}">${ip}</label>
        `;
        ipListContainer.appendChild(item);
    });

    // Adiciona evento ao checkbox "Selecionar Todos"
    selectAllCheckbox.addEventListener('change', (event) => {
        const isChecked = event.target.checked;
        document.querySelectorAll('input[name="ip"]').forEach(checkbox => {
            checkbox.checked = isChecked;
        });
    });

    document.getElementById('submit-btn').addEventListener('click', async () => {
        const password = document.getElementById('password').value;
        const action = document.getElementById('action').value;
        const statusBox = document.getElementById('status');
        const submitBtn = document.getElementById('submit-btn');
        const progressBar = document.getElementById('progress-bar');
        const progressText = document.getElementById('progress-text');
        const progressContainer = document.getElementById('progress-container');

        // Pega todos os IPs que foram marcados
        const selectedIps = Array.from(document.querySelectorAll('input[name="ip"]:checked')).map(checkbox => checkbox.value);

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
        
        // Desabilita o botão e inicia a barra de progresso
        submitBtn.disabled = true;
        submitBtn.textContent = 'Processando...';
        progressContainer.style.display = 'block';
        statusBox.innerHTML = ``;
        statusBox.className = 'status-box';
        
        const totalIPs = selectedIps.length;
        let processedIPs = 0;

        for (const targetIp of selectedIps) {
            try {
                const response = await fetch('http://127.0.0.1:5000/gerenciar_atalhos_ip', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ ip: targetIp, password: password, action: action }),
                });
        
                const data = await response.json();
                
                const icon = data.success ? '✅' : '❌';
                const colorClass = data.success ? 'success-text' : 'error-text';
                statusBox.innerHTML += `<p><span class="${colorClass}">${icon} ${targetIp}: ${data.message}</span></p>`;
                
            } catch (error) {
                statusBox.innerHTML += `<p><span class="error-text">❌ ${targetIp}: Erro de conexão - O servidor pode não estar respondendo.</span></p>`;
            }

            // Atualiza o progresso após cada iteração
            processedIPs++;
            const progress = Math.round((processedIPs / totalIPs) * 100);
            progressBar.style.width = `${progress}%`;
            progressText.textContent = `Processando ${processedIPs} de ${totalIPs} (${progress}%)`;
        }

        // Finaliza o processo, reabilita o botão e esconde a barra
        statusBox.innerHTML += `<p>-----------------------------------</p><p>Processamento concluído!</p>`;
        submitBtn.disabled = false;
        submitBtn.textContent = 'Executar Ação';
    });
});