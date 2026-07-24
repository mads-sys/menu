// grid_view.js - Gerenciador de Visualização em Grid Múltiplo noVNC

// Resolve a URL base da API de forma autônoma (independente do script.js)
function getApiBaseUrl() {
    // Reutiliza se script.js já expôs em window
    if (window._API_BASE_URL) return window._API_BASE_URL;
    let host = window.location.hostname || '127.0.0.1';
    if (host === 'localhost') host = '127.0.0.1';
    if (window.location.port === '5000') return window.location.origin;
    if (window.location.protocol === 'file:') return 'http://127.0.0.1:5000';
    return `${window.location.protocol}//${host}:5000`;
}

class VNCGridManager {
    constructor() {
        this.activeTiles = new Map(); // ip -> { rfb, wsPort, element }
        this.deviceAliases = {}; // ip -> alias
        this.currentCols = 'cols-auto';
        this.modal = null;
        this.container = null;
        this.statusCountSpan = null;
        this.initDOM();
    }

    initDOM() {
        this.modal = document.getElementById('vnc-grid-modal') || document.querySelector('.standalone-grid-wrapper') || document.body;
        this.container = document.getElementById('vnc-grid-container');
        this.statusCountSpan = document.getElementById('vnc-grid-count');

        if (!this.container) return;

        // Carrega apelidos da API
        this.fetchAliases();

        // Botões do Toolbar
        const closeBtn = document.getElementById('vnc-grid-close-btn');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => this.closeGrid());
        }

        const fullscreenBtn = document.getElementById('vnc-grid-fullscreen-btn');
        if (fullscreenBtn) {
            fullscreenBtn.addEventListener('click', () => {
                const content = this.modal.querySelector('.vnc-grid-modal-content');
                if (content) content.classList.toggle('fullscreen');
            });
        }

        const selectIpsBtn = document.getElementById('vnc-grid-select-ips-btn');
        if (selectIpsBtn) {
            selectIpsBtn.addEventListener('click', () => this.openIpSelectorModal());
        }

        const newtabBtn = document.getElementById('vnc-grid-newtab-btn');
        if (newtabBtn) {
            newtabBtn.addEventListener('click', () => {
                const activeIpsArray = Array.from(this.activeTiles.keys()).map(k => k.split('__')[0]);
                const uniqueIps = Array.from(new Set(activeIpsArray));
                const query = uniqueIps.length > 0 ? `?ips=${uniqueIps.join(',')}` : '';
                window.open(`/grid_view.html${query}`, '_blank');
            });
        }

        // Botões de Colunas
        const colBtns = this.modal.querySelectorAll('[data-grid-cols]');
        colBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                colBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const cols = btn.getAttribute('data-grid-cols');
                this.setColumns(cols);
            });
        });
    }

    async fetchAliases() {
        try {
            const res = await fetch(`${getApiBaseUrl()}/get-aliases`);
            const data = await res.json();
            if (data.success && data.aliases) {
                this.deviceAliases = data.aliases;
            }
        } catch (e) {
            console.warn("[Grid VNC] Erro ao carregar apelidos:", e);
        }
    }

    setColumns(colsClass) {
        if (!this.container) return;
        this.container.className = `vnc-grid-container ${colsClass}`;
        this.currentCols = colsClass;
    }

    updateCount() {
        if (this.statusCountSpan) {
            this.statusCountSpan.textContent = `${this.activeTiles.size} telas ativas`;
        }
    }

    async openGrid(targetIps = []) {
        if (!this.modal) this.initDOM();
        if (!this.modal) return;

        this.modal.classList.remove('hidden');

        // Garante que os apelidos estejam carregados antes de conectar
        await this.fetchAliases();

        // Se nenhum IP foi informado, tenta conectar a todas as máquinas online
        if (!targetIps || targetIps.length === 0) {
            targetIps = this.getOnlineIps();
        }

        // Limita a 12 máquinas no grid inicial por performance
        const ipsToConnect = targetIps.slice(0, 12);

        for (const ip of ipsToConnect) {
            if (!this.activeTiles.has(ip)) {
                await this.addTile(ip);
            }
        }
    }

    getOnlineIps() {
        const onlineSet = new Set();

        // 1. IPs com checkboxes marcados no painel principal
        document.querySelectorAll('input[name="ip"]:checked').forEach(cb => {
            if (cb.value) onlineSet.add(cb.value);
        });

        // 2. Elementos de máquina marcados como status-online
        if (onlineSet.size === 0) {
            document.querySelectorAll('.ip-item.status-online, .ip-item:not(.status-offline)').forEach(el => {
                if (el.dataset && el.dataset.ip) {
                    onlineSet.add(el.dataset.ip);
                }
            });
        }

        // 3. Fallback: Todos os checkboxes de IP presentes na página
        if (onlineSet.size === 0) {
            document.querySelectorAll('input[name="ip"]').forEach(cb => {
                if (cb.value) onlineSet.add(cb.value);
            });
        }

        return Array.from(onlineSet);
    }

    getAllAvailableIps() {
        const ipSet = new Set();
        document.querySelectorAll('input[name="ip"]').forEach(cb => {
            if (cb.value) ipSet.add(cb.value);
        });
        document.querySelectorAll('.ip-item').forEach(el => {
            if (el.dataset && el.dataset.ip) {
                ipSet.add(el.dataset.ip);
            }
        });
        this.activeTiles.forEach((_, key) => {
            const rawIp = key.split('__')[0];
            if (rawIp) ipSet.add(rawIp);
        });
        return Array.from(ipSet);
    }

    async addTile(ip, display = null) {
        // Chave única: ip__:1 para multiseat, ou só ip para single seat
        const tileKey = display ? `${ip}__${display}` : ip;
        if (this.activeTiles.has(tileKey)) return;

        // Slug seguro para usar em IDs HTML (sem pontos, dois-pontos, etc.)
        const idSlug = tileKey.replace(/[.:]/g, '-');
        const displayLabel = display ? ` <span style="opacity:.65;font-size:.75rem">${display}</span>` : '';

        const alias = this.deviceAliases[ip];
        const titleMarkup = alias ? `
            <div style="display:flex;flex-direction:column;line-height:1.2;">
                <span style="font-weight:700;color:#f8fafc;font-size:0.9rem;">${alias}${displayLabel}</span>
                <span style="font-family:'JetBrains Mono',monospace;font-size:0.72rem;color:#94a3b8;opacity:0.8;">${ip}</span>
            </div>
        ` : `<span class="vnc-tile-ip">${ip}${displayLabel}</span>`;

        const tileEl = document.createElement('div');
        tileEl.className = 'vnc-tile';
        tileEl.id = `vnc-tile-${idSlug}`;
        tileEl.innerHTML = `
            <div class="vnc-tile-header">
                <div class="vnc-tile-info">
                    <span class="vnc-status-badge connecting" id="status-badge-${idSlug}">Conectando</span>
                    ${titleMarkup}
                    <span id="user-badge-${idSlug}" class="vnc-tile-user" style="font-size:0.75rem;color:#38bdf8;font-weight:600;margin-top:2px;display:none;align-items:center;gap:3px;"></span>
                </div>
                <div class="vnc-tile-actions">
                    <button type="button" class="vnc-tile-btn" title="Expandir VNC" id="btn-expand-${idSlug}">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg>
                    </button>
                    <button type="button" class="vnc-tile-btn" title="Reconectar Agora" id="btn-refresh-${idSlug}">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
                    </button>
                    <button type="button" class="vnc-tile-btn" title="Ctrl+Alt+Del" id="btn-cad-${idSlug}">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 8h4M14 8h4M6 12h12"/></svg>
                    </button>
                    <button type="button" class="vnc-tile-btn" title="Fechar" id="btn-close-${idSlug}">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                    </button>
                </div>
            </div>
            <div class="vnc-tile-body">
                <div class="vnc-tile-overlay" id="overlay-${idSlug}">
                    <div class="vnc-tile-spinner"></div>
                    <div class="vnc-tile-status-text" id="status-text-${idSlug}">Iniciando VNC em ${ip}${display ? ' ' + display : ''}...</div>
                </div>
                <div class="vnc-tile-canvas" id="canvas-container-${idSlug}"></div>
            </div>
        `;

        this.container.appendChild(tileEl);
        this.updateCount();

        // Registra a sessão do tile no gerenciador
        const tileData = {
            rfb: null,
            wsPort: null,
            element: tileEl,
            ip: ip,
            display: display,
            retryCount: 0,
            retryTimer: null,
            isManuallyClosed: false
        };
        this.activeTiles.set(tileKey, tileData);

        // Eventos dos botões do Tile
        const btnClose = tileEl.querySelector(`#btn-close-${idSlug}`);
        if (btnClose) btnClose.onclick = () => this.removeTile(tileKey);

        const btnRefresh = tileEl.querySelector(`#btn-refresh-${idSlug}`);
        if (btnRefresh) {
            btnRefresh.onclick = () => {
                if (tileData.retryTimer) {
                    clearInterval(tileData.retryTimer);
                    tileData.retryTimer = null;
                }
                tileData.retryCount = 0;
                this.reconnectTile(tileKey);
            };
        }

        const btnExpand = tileEl.querySelector(`#btn-expand-${idSlug}`);
        const expandAction = () => {
            if (typeof window.openWebVNC !== 'function') {
                console.warn('[Grid VNC] window.openWebVNC não disponível ainda.');
                return;
            }
            const gridModal = document.getElementById('vnc-grid-modal');
            if (gridModal) gridModal.style.display = 'none';

            window.openWebVNC(ip, display);

            const vncDesktopModal = document.getElementById('vnc-desktop-modal');
            if (vncDesktopModal) {
                const restoreGrid = (mutations) => {
                    for (const m of mutations) {
                        if (m.attributeName === 'class' && vncDesktopModal.classList.contains('hidden')) {
                            if (gridModal) gridModal.style.display = '';
                            observer.disconnect();
                        }
                    }
                };
                const observer = new MutationObserver(restoreGrid);
                observer.observe(vncDesktopModal, { attributes: true });
            }
        };
        if (btnExpand) btnExpand.onclick = expandAction;

        // Duplo clique em qualquer área do tile abre o VNC expandido
        tileEl.style.cursor = 'pointer';
        tileEl.title = 'Duplo clique para abrir em tela cheia';
        tileEl.addEventListener('dblclick', (e) => {
            if (e.target.closest('.vnc-tile-btn')) return;
            e.stopPropagation();
            e.preventDefault();
            expandAction();
        }, true);

        // Inicia a tentativa de conexão
        this.startTileConnection(tileKey);
    }

    updateTileUI(tileKey, status, msg) {
        const tileData = this.activeTiles.get(tileKey);
        if (!tileData || !tileData.element) return;
        const idSlug = tileKey.replace(/[.:]/g, '-');
        const statusBadge = tileData.element.querySelector(`#status-badge-${idSlug}`);
        const statusText = tileData.element.querySelector(`#status-text-${idSlug}`);
        const overlay = tileData.element.querySelector(`#overlay-${idSlug}`);

        if (statusBadge) {
            statusBadge.className = `vnc-status-badge ${status}`;
            statusBadge.textContent = status === 'connected' ? 'Ativo' : (status === 'connecting' ? 'Conectando' : 'Erro');
        }
        if (statusText) statusText.textContent = msg;
        if (status === 'connected' && overlay) {
            overlay.classList.add('hidden');
        } else if (overlay) {
            overlay.classList.remove('hidden');
        }
    }

    scheduleAutoReconnect(tileKey, delaySeconds = 5) {
        const tileData = this.activeTiles.get(tileKey);
        if (!tileData || tileData.isManuallyClosed) return;

        tileData.retryCount = (tileData.retryCount || 0) + 1;
        if (tileData.retryCount > 8) {
            this.updateTileUI(tileKey, 'disconnected', `Conexão falhou após 8 tentativas. Clique em 🔄 para tentar novamente.`);
            return;
        }

        if (tileData.retryTimer) {
            clearInterval(tileData.retryTimer);
            tileData.retryTimer = null;
        }

        let secondsLeft = delaySeconds;
        this.updateTileUI(tileKey, 'connecting', `Conexão oscilou. Reconectando em ${secondsLeft}s... (${tileData.retryCount}/8)`);

        tileData.retryTimer = setInterval(() => {
            if (!this.activeTiles.has(tileKey) || tileData.isManuallyClosed) {
                if (tileData.retryTimer) clearInterval(tileData.retryTimer);
                return;
            }
            secondsLeft--;
            if (secondsLeft > 0) {
                this.updateTileUI(tileKey, 'connecting', `Conexão oscilou. Reconectando em ${secondsLeft}s... (${tileData.retryCount}/8)`);
            } else {
                clearInterval(tileData.retryTimer);
                tileData.retryTimer = null;
                this.reconnectTile(tileKey);
            }
        }, 1000);
    }

    async reconnectTile(tileKey) {
        const tileData = this.activeTiles.get(tileKey);
        if (!tileData || tileData.isManuallyClosed) return;

        if (tileData.rfb) {
            try { tileData.rfb.disconnect(); } catch(e) {}
            tileData.rfb = null;
        }
        if (tileData.wsPort) {
            try {
                fetch(`${getApiBaseUrl()}/api/stop-vnc`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ws_port: tileData.wsPort })
                }).catch(() => {});
            } catch(e) {}
            tileData.wsPort = null;
        }

        this.startTileConnection(tileKey);
    }

    async startTileConnection(tileKey) {
        const tileData = this.activeTiles.get(tileKey);
        if (!tileData || tileData.isManuallyClosed) return;

        const { ip, display, element: tileEl } = tileData;
        const idSlug = tileKey.replace(/[.:]/g, '-');
        const canvasContainer = tileEl.querySelector(`#canvas-container-${idSlug}`);

        const expandAction = () => {
            if (typeof window.openWebVNC === 'function') {
                window.openWebVNC(ip, display);
            }
        };

        // Pré-verificação de conectividade
        this.updateTileUI(tileKey, 'connecting', `Testando conectividade em ${ip}...`);
        try {
            const checkRes = await fetch(`${getApiBaseUrl()}/api/ping-check`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ips: [ip] })
            });
            const checkData = await checkRes.json();
            if (checkData.success && checkData.results && checkData.results[ip]) {
                const info = checkData.results[ip];
                if (!info.reachable) {
                    this.updateTileUI(tileKey, 'disconnected', `Máquina offline ou desligada`);
                    this.scheduleAutoReconnect(tileKey, 6);
                    return;
                }
                if (!info.ssh && !info.vnc) {
                    this.updateTileUI(tileKey, 'disconnected', `SSH (porta 22) inacessível no host`);
                    this.scheduleAutoReconnect(tileKey, 6);
                    return;
                }
            }
        } catch (e) {}

        const activePassword = typeof getActivePassword === 'function' ? getActivePassword() : 'qwe123';
        let wsPort = 6080;

        try {
            const bodyData = { ip, username: 'aluno', password: activePassword };
            if (display) bodyData.display = display;

            const prepRes = await fetch(`${getApiBaseUrl()}/api/start-vnc`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(bodyData)
            });
            const prepData = await prepRes.json();

            if (prepData.multiseat && prepData.displays && prepData.displays.length > 0) {
                if (tileEl && tileEl.parentNode) tileEl.parentNode.removeChild(tileEl);
                this.activeTiles.delete(ip);
                this.updateCount();

                for (const d of prepData.displays) {
                    const seatKey = `${ip}__${d.display}`;
                    if (!this.activeTiles.has(seatKey)) {
                        await this.addTile(ip, d.display);
                    }
                }
                return;
            } else if (prepData.success && prepData.ws_port) {
                wsPort = prepData.ws_port;
                tileData.wsPort = wsPort;
                this.updateTileUI(tileKey, 'connecting', 'Conectando ao display...');

                if (prepData.logged_user) {
                    const userBadge = tileEl.querySelector(`#user-badge-${idSlug}`);
                    if (userBadge) {
                        userBadge.textContent = `👤 ${prepData.logged_user}`;
                        userBadge.style.display = 'inline-flex';
                    }
                }
            } else {
                this.updateTileUI(tileKey, 'disconnected', prepData.message || 'Falha ao iniciar VNC');
                this.scheduleAutoReconnect(tileKey, 6);
                return;
            }
        } catch (err) {
            this.updateTileUI(tileKey, 'disconnected', 'Erro ao contatar backend');
            this.scheduleAutoReconnect(tileKey, 6);
            return;
        }

        const wsHost = window.location.hostname || '127.0.0.1';
        const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const wsUrl = `${protocol}://${wsHost}:${wsPort}/websockify`;

        try {
            if (typeof window.RFB !== 'function') {
                throw new Error("Biblioteca noVNC não carregada");
            }

            const rfb = new window.RFB(canvasContainer, wsUrl);
            rfb.scaleViewport = true;
            rfb.resizeSession = false;
            rfb.viewOnly = true;
            tileData.rfb = rfb;

            canvasContainer.addEventListener('dblclick', (e) => {
                e.stopPropagation();
                e.preventDefault();
                expandAction();
            }, true);

            rfb.addEventListener('connect', () => {
                tileData.retryCount = 0; // Sucesso: reseta o contador de tentativas
                this.updateTileUI(tileKey, 'connected', `Conectado -> ${ip}`);
                const innerCanvas = canvasContainer.querySelector('canvas');
                if (innerCanvas) {
                    innerCanvas.style.cursor = 'pointer';
                    innerCanvas.addEventListener('dblclick', (e) => {
                        e.stopPropagation();
                        e.preventDefault();
                        expandAction();
                    }, true);
                }
            });

            rfb.addEventListener('disconnect', (e) => {
                this.updateTileUI(tileKey, 'disconnected', 'Conexão encerrada');
                this.scheduleAutoReconnect(tileKey, 5);
            });

            rfb.addEventListener('credentialsrequired', () => {
                rfb.sendCredentials({ password: '' });
            });

            const btnCad = tileEl.querySelector(`#btn-cad-${idSlug}`);
            if (btnCad) {
                btnCad.onclick = () => {
                    try { rfb.sendCtrlAltDel(); } catch(e) {}
                };
            }

            this.updateCount();

        } catch (err) {
            this.updateTileUI(tileKey, 'disconnected', `Erro: ${err.message}`);
            this.scheduleAutoReconnect(tileKey, 6);
        }
    }

    async removeTile(tileKey) {
        const tileData = this.activeTiles.get(tileKey);
        if (!tileData) return;

        tileData.isManuallyClosed = true;
        if (tileData.retryTimer) {
            clearInterval(tileData.retryTimer);
            tileData.retryTimer = null;
        }

        const { rfb, wsPort, element } = tileData;

        if (rfb) {
            try { rfb.disconnect(); } catch(e) {}
        }

        if (wsPort) {
            try {
                fetch(`${getApiBaseUrl()}/api/stop-vnc`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ws_port: wsPort })
                }).catch(() => {});
            } catch(e) {}
        }

        if (element && element.parentNode) {
            element.parentNode.removeChild(element);
        }

        this.activeTiles.delete(tileKey);
        this.updateCount();
    }

    async closeGrid() {
        for (const [ip] of Array.from(this.activeTiles.entries())) {
            await this.removeTile(ip);
        }
        if (this.container) this.container.innerHTML = '';
        if (this.modal) this.modal.classList.add('hidden');
    }

    async openIpSelectorModal() {
        const selectorModal = document.getElementById('vnc-grid-selector-modal');
        const listContainer = document.getElementById('vnc-grid-selector-list');
        if (!selectorModal || !listContainer) return;

        listContainer.innerHTML = '';
        let availableIps = this.getAllAvailableIps();

        if (availableIps.length === 0) {
            try {
                const res = await fetch(`${getApiBaseUrl()}/discover-ips`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                });
                const data = await res.json();
                if (data.ips && data.ips.length > 0) {
                    availableIps = data.ips.map(item => typeof item === 'object' ? item.ip : item);
                }
            } catch (e) {}
        }

        if (availableIps.length === 0) {
            listContainer.innerHTML = '<div style="color:#94a3b8;padding:12px;text-align:center;">Nenhuma máquina detectada no momento.</div>';
        } else {
            availableIps.forEach(ip => {
                const alias = this.deviceAliases[ip];
                const labelText = alias ? `<strong style="color:#f8fafc;">${alias}</strong> <span style="font-family:'JetBrains Mono',monospace;opacity:.65;font-size:.78rem;margin-left:4px;">(${ip})</span>` : `<span style="font-family:'JetBrains Mono',monospace;font-weight:600;color:#f8fafc;">${ip}</span>`;
                const isSelected = this.activeTiles.has(ip) || Array.from(this.activeTiles.keys()).some(k => k.startsWith(ip));
                const item = document.createElement('label');
                item.className = 'vnc-grid-select-item';
                item.innerHTML = `
                    <input type="checkbox" value="${ip}" ${isSelected ? 'checked' : ''} />
                    <span>${labelText}</span>
                `;
                listContainer.appendChild(item);
            });
        }

        selectorModal.classList.remove('hidden');

        const confirmBtn = document.getElementById('vnc-grid-selector-confirm-btn');
        if (confirmBtn) {
            confirmBtn.onclick = () => {
                const checkedInputs = listContainer.querySelectorAll('input[type="checkbox"]:checked');
                const selectedIps = Array.from(checkedInputs).map(cb => cb.value);

                // Remove tiles desmarcados
                for (const [ip] of Array.from(this.activeTiles.entries())) {
                    if (!selectedIps.includes(ip)) {
                        this.removeTile(ip);
                    }
                }

                // Adiciona novos tiles marcados
                selectedIps.forEach(ip => {
                    if (!this.activeTiles.has(ip)) {
                        this.addTile(ip);
                    }
                });

                selectorModal.classList.add('hidden');
            };
        }
    }
}

// Instância global do gerenciador de Grid VNC
window.vncGridManager = new VNCGridManager();

window.openVNCGrid = (ipsList = []) => {
    if (window.vncGridManager) {
        window.vncGridManager.openGrid(ipsList);
    }
};
