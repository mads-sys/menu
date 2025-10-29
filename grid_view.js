document.addEventListener('DOMContentLoaded', async () => {
    // --- Constantes e Configurações ---
    const logConsole = document.getElementById('grid-log-console');
    const gridContainer = document.getElementById('grid-container');
    const fitToggle = document.getElementById('fit-toggle');
    const logToggle = document.getElementById('log-toggle');
    const VNC_HOST = window.location.hostname;
    const API_BASE_URL = `${window.location.protocol}//${VNC_HOST}:${window.location.port || (window.location.protocol === 'https' ? 443 : 80)}`;
    // Define o número máximo de conexões VNC a serem iniciadas simultaneamente.
    // Um valor entre 5 e 10 é um bom equilíbrio para não sobrecarregar o servidor.
    const MAX_CONCURRENT_VNC_STARTS = 8;

    /**
     * Adiciona uma mensagem ao console de log da grade.
     * @param {string} message - A mensagem a ser logada.
     * @param {string} [type='info'] - O tipo de log ('info' ou 'error').
     */
    function logToGrid(message, type = 'info') {
        const entry = document.createElement('div');
        entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
        if (type === 'error') {
            entry.className = 'log-error';
        }
        logConsole.appendChild(entry);
        logConsole.scrollTop = logConsole.scrollHeight; // Auto-scroll para a última mensagem
    }

    // --- Lógica de Visibilidade do Log ---
    // Oculta o log por padrão ao carregar a página
    logConsole.classList.add('hidden');
    // Adiciona o listener para o botão de "Visualizar Log"
    logToggle.addEventListener('change', () => {
        logConsole.classList.toggle('hidden', !logToggle.checked);
    });

    // --- Lógica de Comunicação com iFrames (para redimensionamento) ---
    window.addEventListener('message', (event) => {
        // Verificação de segurança básica: ignora mensagens que não são do noVNC.
        if (!event.data || event.data.type !== 'noVNC_Resize') {
            return;
        }

        const { token, width, height } = event.data;
        if (!token || !width || !height) return;

        // O token é o IP da máquina, que usamos para encontrar o contêiner correto.
        const safeIpId = token.replace(/\./g, '-');
        const itemBody = document.getElementById(`body-${safeIpId}`);

        if (itemBody) {
            logToGrid(`[${token}] Redimensionamento detectado: ${width}x${height}. Ajustando proporção.`);
            // Define a proporção de tela do contêiner para corresponder exatamente à da tela remota.
            itemBody.style.aspectRatio = `${width} / ${height}`;
        }
    });

    // --- Recuperação de Dados da Sessão ---
    logToGrid('Página carregada. Lendo chave de sessão da URL...');
    // Pega a chave da sessão a partir dos parâmetros da URL
    const urlParams = new URLSearchParams(window.location.search);
    const gridSessionKey = urlParams.get('session');

    if (!gridSessionKey) {
        logToGrid('ERRO: Chave de sessão não encontrada na URL.', 'error');
        gridContainer.innerHTML = `<h1>${logConsole.lastChild.textContent}</h1>`;
        return;
    }

    // Pega os dados da localStorage usando a chave e os remove imediatamente por segurança.
    logToGrid(`Recuperando dados da sessão com a chave: ${gridSessionKey}`);
    const storedData = localStorage.getItem(gridSessionKey);
    localStorage.removeItem(gridSessionKey); // Limpa os dados para não deixar a senha armazenada

    if (!storedData) {
        logToGrid('ERRO: Dados da sessão não encontrados ou expirados. Tente novamente.', 'error');
        gridContainer.innerHTML = `<h1>${logConsole.lastChild.textContent}</h1>`;
        return;
    }

    const { ips: originalIps, password } = JSON.parse(storedData);
    logToGrid(`Dados da sessão recuperados com sucesso para ${originalIps.length} IP(s).`);

    // --- Ordenação e Criação dos Placeholders ---
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

    logToGrid('Criando placeholders para cada máquina na grade...');
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
            <div class="grid-item-body loading" id="body-${ip.replace(/\./g, '-')}">
                <!-- O Iframe será inserido aqui -->
            </div>
        `;
        gridContainer.appendChild(item);
    });

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

    /**
     * Ajusta o layout da grade para preencher a tela de forma otimizada.
     * Esta função agora garante que todas as linhas caibam na altura da janela.
     * @param {number} itemCount - O número de itens na grade.
     */
    function adjustGridLayout(itemCount) {
        if (itemCount === 0) return;

        // Calcula o número de colunas e linhas para uma grade o mais "quadrada" possível.
        const cols = Math.ceil(Math.sqrt(itemCount));
        const rows = Math.ceil(itemCount / cols);

        // Define o número de colunas para preencher a largura disponível.
        gridContainer.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
        // Define a altura de cada linha para que todas as linhas caibam perfeitamente na altura da janela.
        // O '1fr' aqui significa que cada linha ocupará uma fração igual do espaço vertical total.
        gridContainer.style.gridTemplateRows = `repeat(${rows}, 1fr)`;
        logToGrid(`Layout da grade ajustado para ${rows} linha(s) e ${cols} coluna(s).`);
    }

    /**
     * Atualiza o modo de escala de todos os iframes VNC na grade.
     * @param {boolean} scale - Se o dimensionamento deve ser ativado.
     */
    function updateScaling(scale) {
        logToGrid(`Aplicando ajuste de tela: ${scale ? 'Ativado' : 'Desativado'}`);
        // Envia uma mensagem para cada iframe para que ele atualize seu próprio estado de escala.
        // Isso é muito mais eficiente do que recarregar o iframe inteiro.
        gridContainer.querySelectorAll('iframe').forEach(iframe => {
            // O '*' como segundo argumento permite a comunicação com qualquer origem,
            // o que é seguro aqui, pois estamos apenas enviando um comando para um iframe
            // que nós mesmos criamos na mesma origem.
            iframe.contentWindow.postMessage({
                type: 'noVNC_Action',
                action: 'scale',
                scale: scale
            }, '*');
        });        
    }

    /**
     * Inicia uma única sessão VNC para um IP.
     * @param {string} ip - O endereço IP do alvo.
     */
    async function startSingleVncSession(ip) {
        const safeIpId = ip.replace(/\./g, '-');
        const itemBody = document.getElementById(`body-${safeIpId}`);
        const statusEl = document.getElementById(`status-${safeIpId}`);

        logToGrid(`[${ip}] Iniciando requisição para /start-vnc...`);
        try {
            const response = await fetch(`${API_BASE_URL}/start-vnc`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ip, password }),
            });
            const data = await response.json();

            itemBody.classList.remove('loading');

            if (data.success) {
                logToGrid(`[${ip}] Sucesso na API. URL recebida: ${data.url}`);
                statusEl.textContent = '✔️';

                // Cria um iframe e aponta para a URL do noVNC retornada
                const iframe = document.createElement('iframe');
                let vncUrl = data.url;
                // Adiciona o parâmetro de escala diretamente na URL inicial se o toggle já estiver ativo.
                // Isso garante que a conexão já comece com a escala correta.
                if (fitToggle.checked) {
                    vncUrl += '&scale=true';
                }
                iframe.src = vncUrl;

                // Adiciona scrolling="no" para forçar o conteúdo a se ajustar e evitar barras de rolagem.
                iframe.setAttribute('scrolling', 'no');

                iframe.style.width = '100%';
                iframe.style.height = '100%';
                iframe.style.border = 'none';
                itemBody.appendChild(iframe);
            } else {
                logToGrid(`[${ip}] Falha na API: ${data.message}`, 'error');
                statusEl.textContent = '✖️';
                itemBody.classList.add('error');
                document.getElementById(`grid-item-${safeIpId}`).title = data.message || "Falha ao iniciar túnel VNC.";
            }
        } catch (error) {
            logToGrid(`[${ip}] Erro de conexão com o backend: ${error.message}`, 'error');
            itemBody.classList.remove('loading');
            statusEl.textContent = '✖️';
            itemBody.classList.add('error');
            document.getElementById(`grid-item-${safeIpId}`).title = `Erro de conexão: ${error.message}`;
        }
    }

    /**
     * Executa um array de funções de promessa com um limite de concorrência.
     * @param {Array<Function>} taskFunctions - Um array de funções que retornam promessas.
     * @param {number} concurrency - O número de tarefas a serem executadas em paralelo.
     */
    async function runPromisesInParallel(taskFunctions, concurrency) {
        const queue = [...taskFunctions];
        const workers = Array(concurrency).fill(null).map(async () => {
            while (queue.length > 0) await queue.shift()();
        });
        await Promise.all(workers);
    }

    // --- Ponto de Entrada da Lógica de Conexão ---
    // Ajusta o layout da grade assim que os placeholders são criados.
    adjustGridLayout(ips.length);
    // Adiciona um listener para reajustar o layout se a janela for redimensionada.
    window.addEventListener('resize', () => adjustGridLayout(ips.length));

    // Adiciona o listener para o botão de "Ajustar à Tela".
    fitToggle.addEventListener('change', () => updateScaling(fitToggle.checked));

    logToGrid(`Iniciando ${ips.length} tarefas VNC com concorrência de ${MAX_CONCURRENT_VNC_STARTS}...`);
    const vncTasks = ips.map(ip => () => startSingleVncSession(ip));
    await runPromisesInParallel(vncTasks, MAX_CONCURRENT_VNC_STARTS);
});
