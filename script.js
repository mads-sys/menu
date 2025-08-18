document.getElementById('submit-btn').addEventListener('click', async () => {
    // Definimos o prefixo da rede fixo
    const networkPrefix = '192.168.0'; 
    
    const ipEndingsInput = document.getElementById('ip-endings').value;
    const password = document.getElementById('password').value;
    const action = document.getElementById('action').value;
    const statusBox = document.getElementById('status');
    const submitBtn = document.getElementById('submit-btn');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');
    const progressContainer = document.getElementById('progress-container');

    // Validação de campos
    if (!ipEndingsInput || !password) {
        statusBox.innerHTML = '<p class="error-text">Por favor, preencha todos os campos.</p>';
        statusBox.className = 'status-box error';
        return;
    }

    const ipEndingsArray = ipEndingsInput.split(',').map(ending => ending.trim());
    const ipList = [];

    // Valida cada número na lista e constrói a lista de IPs completos
    for (const ending of ipEndingsArray) {
        const num = parseInt(ending);
        if (isNaN(num) || num < 0 || num > 255) {
            statusBox.innerHTML = `<p class="error-text">O valor "${ending}" não é um número de IP válido (0-255). Por favor, corrija a lista.</p>`;
            statusBox.className = 'status-box error';
            return;
        }
        ipList.push(`${networkPrefix}.${num}`);
    }
    
    // Desabilita o botão e inicia a barra de progresso
    submitBtn.disabled = true;
    submitBtn.textContent = 'Processando...';
    progressContainer.style.display = 'block';
    statusBox.innerHTML = ``;
    statusBox.className = 'status-box';
    
    const totalIPs = ipList.length;
    let processedIPs = 0;

    for (const targetIp of ipList) {
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