document.addEventListener('DOMContentLoaded', async () => {
    const gridContainer = document.getElementById('grid-container');
    const fitToggle = document.getElementById('fit-toggle');
    // Extrai o host e a porta da URL atual para construir a URL do WebSocket dinamicamente.
    // Isso torna a aplicação mais flexível, funcionando com 'localhost', '127.0.0.1' ou um IP de rede.
    const VNC_HOST = window.location.hostname;
    const API_BASE_URL = `${window.location.protocol}//${VNC_HOST}:${window.location.port || (window.location.protocol === 'https' ? 443 : 80)}`;

    // Pega os dados da sessionStorage
    const storedData = sessionStorage.getItem('vncGridData');
    if (!storedData) {
        gridContainer.innerHTML = '<h1>Erro: Nenhum dado de visualização encontrado.</h1>';
        return;
    }

    const { ips, password } = JSON.parse(storedData);

    // Cria os placeholders na grade
    ips.forEach(ip => {
        const item = document.createElement('div');
        item.className = 'grid-item';
        item.id = `grid-item-${ip.replace(/\./g, '-')}`;
        item.innerHTML = `
            <div class="grid-item-header" title="${ip}">
                <span class="ip-address">${ip}</span>
                <span class="status" id="status-${ip.replace(/\./g, '-')}"></span>
            </div>
            <div class="grid-item-body loading">
                <canvas id="canvas-${ip.replace(/\./g, '-')}"></canvas>
            </div>
        `;
        gridContainer.appendChild(item);
    });

    // --- Lógica de Ajuste de Layout ---
    fitToggle.addEventListener('change', () => adjustGridLayout(ips.length));
    window.addEventListener('resize', () => adjustGridLayout(ips.length));
    // Chama uma vez no início para o caso de o usuário recarregar a página com o ajuste ativo.
    adjustGridLayout(ips.length);

    // Chama o novo endpoint para iniciar todas as sessões VNC
    try {
        const response = await fetch(`${API_BASE_URL}/start-vnc-grid`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ips, password }),
        });

        const data = await response.json();

        if (data.success) {
            data.results.forEach(result => {
                const ip = result.ip;
                const safeIpId = ip.replace(/\./g, '-');
                const itemBody = document.querySelector(`#grid-item-${safeIpId} .grid-item-body`);
                const statusEl = document.getElementById(`status-${safeIpId}`);

                itemBody.classList.remove('loading');

                if (result.success) {
                    statusEl.textContent = '✅';
                    connectVnc(ip, result.port);
                } else {
                    itemBody.classList.add('error');
                    statusEl.textContent = '❌';
                    // Adiciona a mensagem de erro específica como um 'title' para o usuário ver ao passar o mouse.
                    document.getElementById(`grid-item-${safeIpId}`).title = result.message || "Falha ao conectar.";
                }
            });
        } else {
            // Falha geral na chamada da API
            gridContainer.innerHTML = `<h1>Erro ao iniciar sessões: ${data.message}</h1>`;
        }
    } catch (error) {
        gridContainer.innerHTML = `<h1>Erro de conexão com o servidor: ${error.message}</h1>`;
    }

    function connectVnc(ip, port) {
        const safeIpId = ip.replace(/\./g, '-');
        const canvas = document.getElementById(`canvas-${safeIpId}`);
        const statusEl = document.getElementById(`status-${safeIpId}`);

        // A classe RFB foi anexada ao 'window' no grid_view.html
        const rfb = new window.RFB(canvas, `ws://${VNC_HOST}:${port}`, {
            credentials: { password: '' }, // A senha já foi usada para o túnel SSH
        });

        rfb.addEventListener('connect', (event) => {
            console.log(`VNC conectado com sucesso a ${ip} na porta ${port}.`);
            // O status já foi definido como '✅' anteriormente, então não precisamos mudar.
        });

        rfb.addEventListener('disconnect', (event) => {
            console.warn(`VNC desconectado de ${ip}:`, event.detail);
            const itemBody = document.querySelector(`#grid-item-${safeIpId} .grid-item-body`);
            
            // Se a desconexão foi anormal (não limpa), marca como erro.
            if (!event.detail.clean) {
                statusEl.textContent = '❌';
                itemBody.classList.add('error');
                itemBody.classList.remove('loading'); // Garante que o ícone de erro apareça
            } else {
                statusEl.textContent = '🔌'; // Ícone de desconectado
            }
        });

        // Desativa o scaling para melhor performance em grade
        rfb.scaleViewport = true; // Alterado para 'true' para que a imagem se ajuste ao canvas.
    }
});