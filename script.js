document.getElementById('remove-btn').addEventListener('click', async () => {
    const startIp = document.getElementById('start-ip').value;
    const endIp = document.getElementById('end-ip').value;
    const password = document.getElementById('password').value; // Coleta a senha
    const statusBox = document.getElementById('status');
    
    if (!startIp || !endIp || !password) {
        statusBox.innerHTML = '<p>Por favor, insira a faixa de IPs e a senha.</p>';
        statusBox.className = 'status-box error';
        return;
    }

    statusBox.innerHTML = `<p>Processando de ${startIp} a ${endIp}...</p>`;
    statusBox.className = 'status-box';

    try {
        const response = await fetch('http://172.31.97.238:5000/remove_shortcuts_range', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ start_ip: startIp, end_ip: endIp, password: password }), // Envia a senha
        });

        const data = await response.json();

        if (response.ok) {
            let outputHtml = '<h4>Resultados:</h4><ul>';
            const results = data.results;
            for (const ip in results) {
                const result = results[ip];
                const icon = result.success ? '✅' : '❌';
                const colorClass = result.success ? 'success-text' : 'error-text';
                outputHtml += `<li><span class="${colorClass}">${icon} ${ip}: ${result.message}</span></li>`;
            }
            outputHtml += '</ul>';
            statusBox.innerHTML = outputHtml;
            statusBox.className = 'status-box';
        } else {
            statusBox.innerHTML = `<p>Erro: ${data.message}</p>`;
            statusBox.className = 'status-box error';
        }
    } catch (error) {
        statusBox.innerHTML = `<p>Erro de conexão: ${error.message}</p>`;
        statusBox.className = 'status-box error';
    }
});
