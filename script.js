document.getElementById('submit-btn').addEventListener('click', async () => {
    // Definimos o prefixo da rede fixo
    const networkPrefix = '192.168.0'; 
    
    const startOctetInput = document.getElementById('start-octet').value;
    const endOctetInput = document.getElementById('end-octet').value;
    const password = document.getElementById('password').value;
    const action = document.getElementById('action').value;
    const statusBox = document.getElementById('status');
    const submitBtn = document.getElementById('submit-btn');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');
    const progressContainer = document.getElementById('progress-container');

    // Validação de campos e conversão para números
    if (!startOctetInput || !endOctetInput || !password) {
        statusBox.innerHTML = '<p class="error-text">Por favor, preencha todos os campos.</p>';
        statusBox.className = 'status-box error';
        return;
    }

    const startOctet = parseInt(startOctetInput);
    const endOctet = parseInt(endOctetInput);
    
    // Validação de números válidos
    if (isNaN(startOctet) || startOctet < 0 || startOctet > 255) {
        statusBox.innerHTML = '<p class="error-text">Por favor, insira um número inicial de IP válido (0-255).</p>';
        statusBox.className = 'status-box error';
        return;
    }
    
    if (isNaN(endOctet) || endOctet < 0 || endOctet > 255) {
        statusBox.innerHTML = '<p class="error-text">Por favor, insira um número final de IP válido (0-255).</p>';
        statusBox.className = 'status-box error';
        return;
    }
    
    if (endOctet < startOctet) {
        statusBox.innerHTML = '<p class="error-text">O IP final não pode ser menor que o IP inicial.</p>';
        statusBox.className = 'status-box error';
        return;
    }

    // Desabilita o botão e inicia a barra de progresso
    submitBtn.disabled = true;
    submitBtn.textContent = 'Processando...';
    progressContainer.style.display = 'block';
    statusBox.innerHTML = ``;
    statusBox.className = 'status-box';
    
    const totalIPs = endOctet - startOctet + 1;
    let processedIPs = 0;

    for (let i = startOctet; i <= endOctet; i++) {
        const targetIp = `${networkPrefix}.${i}`;
        
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
    // progressContainer.style.display = 'none'; // Descomente para esconder a barra no final
});