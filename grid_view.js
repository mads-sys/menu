import RFB from './novnc/core/rfb.js';

document.addEventListener('DOMContentLoaded', async () => {
    const gridContainer = document.getElementById('grid-container');
    const fitToggle = document.getElementById('fit-toggle');
    // Extrai o host e a porta da URL atual para construir a URL do WebSocket dinamicamente.
    // Isso torna a aplicação mais flexível, funcionando com 'localhost', '127.0.0.1' ou um IP de rede.
    const VNC_HOST = window.location.hostname;
    const API_BASE_URL = `${window.location.protocol}//${VNC_HOST}:${window.location.port || (window.location.protocol === 'https' ? 443 : 80)}`;

    // Pega a chave da sessão a partir dos parâmetros da URL
    const urlParams = new URLSearchParams(window.location.search);
    const gridSessionKey = urlParams.get('session');

    if (!gridSessionKey) {
        gridContainer.innerHTML = '<h1>Erro: Chave de sessão de visualização não encontrada.</h1>';
        return;
    }

    // Pega os dados da localStorage usando a chave e os remove imediatamente por segurança.
    const storedData = localStorage.getItem(gridSessionKey);
    localStorage.removeItem(gridSessionKey); // Limpa os dados para não deixar a senha armazenada

    if (!storedData) {
        gridContainer.innerHTML = '<h1>Erro: Dados da sessão de visualização expirados ou não encontrados. Por favor, feche esta aba e tente novamente.</h1>';
        return;
    }

    const { ips: originalIps, password } = JSON.parse(storedData);

    // Carrega a ordem salva da grade e ordena os IPs antes de exibi-los
    const savedGridOrder = JSON.parse(localStorage.getItem('vncGridOrder'));
    let ips = originalIps;
    if (savedGridOrder) {
        ips.sort((a, b) => {
            const indexA = savedGridOrder.indexOf(a);
            const indexB = savedGridOrder.indexOf(b);
            // Trata IPs não encontrados na ordem salva como se estivessem no infinito, colocando-os no final.
            const sortA = indexA === -1 ? Infinity : indexA;
            const sortB = indexB === -1 ? Infinity : indexB;
            return sortA - sortB;
        });
    }

    // Cria os placeholders na grade
    ips.forEach(ip => {
        const item = document.createElement('div');
        item.className = 'grid-item draggable-item';
        // Adiciona o IP ao dataset para facilitar a recuperação posterior
        item.dataset.ip = ip;
        item.id = `grid-item-${ip.replace(/\./g, '-')}`;
        item.draggable = true; // Torna o item da grade arrastável
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

    // Função de ajuste de layout (pode ser implementada no futuro se necessário)
    function adjustGridLayout(itemCount) {
        // Lógica para ajustar o layout da grade pode ser adicionada aqui.
    }

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

    // --- Lógica de Drag and Drop para a Grade VNC ---
    if (gridContainer) {
        let draggedItem = null;

        gridContainer.addEventListener('dragstart', (e) => {
            draggedItem = e.target.closest('.grid-item');
            if (draggedItem) {
                setTimeout(() => {
                    draggedItem.classList.add('dragging');
                }, 0);
            }
        });

        gridContainer.addEventListener('dragover', (e) => {
            e.preventDefault();
            const targetItem = e.target.closest('.grid-item');
            if (targetItem && draggedItem && targetItem !== draggedItem) {
                const rect = targetItem.getBoundingClientRect();
                // Usa a posição X do mouse para determinar a ordem em layout de grade
                const offsetX = e.clientX - rect.left - rect.width / 2;

                if (offsetX < 0) {
                    gridContainer.insertBefore(draggedItem, targetItem);
                } else {
                    gridContainer.insertBefore(draggedItem, targetItem.nextSibling);
                }
            }
        });

        gridContainer.addEventListener('drop', (e) => {
            e.preventDefault();
            if (draggedItem) {
                draggedItem.classList.remove('dragging');
                draggedItem = null;

                // Salva a nova ordem da grade no localStorage
                const currentGridOrder = Array.from(gridContainer.querySelectorAll('.grid-item'))
                    .map(item => item.dataset.ip);
                localStorage.setItem('vncGridOrder', JSON.stringify(currentGridOrder));
                console.log('Ordem da grade VNC salva localmente.');
            }
        });

        gridContainer.addEventListener('dragend', () => {
            if (draggedItem) {
                draggedItem.classList.remove('dragging');
                draggedItem = null;
            }
        });
    }

    function connectVnc(ip, port) {
        const safeIpId = ip.replace(/\./g, '-');
        const canvas = document.getElementById(`canvas-${safeIpId}`);
        const statusEl = document.getElementById(`status-${safeIpId}`);

        // A classe RFB é importada diretamente como um módulo.
        const rfb = new RFB(canvas, `ws://${VNC_HOST}:${port}`, {
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
