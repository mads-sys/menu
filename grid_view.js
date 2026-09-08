// grid_view.js - Gerenciador de Visualização em Grid Múltiplo noVNC

// Resolve a URL base da API de forma autônoma (independente do script.js)
function getApiBaseUrl() {
    // Reutiliza se script.js já expôs em window
    if (window._API_BASE_URL) return window._API_BASE_URL;
    let host = window.location.hostname || '127.0.0.1';
    if (host === 'localhost') host = '127.0.0.1';
    const isBackendPort = (p) => p === '5050' || p === '8000';
    if (window.location.protocol === 'file:' || (window.location.port && !isBackendPort(window.location.port))) {
        return `http://${host}:5050`;
    }
    return window.location.origin;
}

class VNCGridManager {
    constructor() {
        this.activeTiles = new Map(); // ip -> { rfb, wsPort, element }
        this.deviceAliases = {}; // ip -> alias
        this.deviceHostnames = {}; // ip -> hostname
        this.currentCols = 'cols-auto';
        this.currentFilter = 'all';
        this.targetFps = 15;
        this.eventLogs = []; // Histórico de logs/eventos do Grid na sessão
        this.connectionQueue = []; // Fila de conexões por lote (throttling anti-OOM)
        this.activeConnectingCount = 0;
        this.MAX_CONCURRENT_CONNECTS = 4; // Conexões simultâneas máximas no backend
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

                // Alterna Modo Tela Cheia Real (HTML5 Fullscreen API)
                if (!document.fullscreenElement && !document.webkitFullscreenElement) {
                    const targetEl = document.documentElement || this.modal;
                    if (targetEl.requestFullscreen) {
                        targetEl.requestFullscreen().catch(e => console.warn('[Grid VNC] Fullscreen:', e));
                    } else if (targetEl.webkitRequestFullscreen) {
                        targetEl.webkitRequestFullscreen();
                    }
                } else {
                    if (document.exitFullscreen) {
                        document.exitFullscreen().catch(e => console.warn('[Grid VNC] Exit Fullscreen:', e));
                    } else if (document.webkitExitFullscreen) {
                        document.webkitExitFullscreen();
                    }
                }
            });
        }

        // Atualiza estado visual ao alternar fullscreen
        document.addEventListener('fullscreenchange', () => {
            const fsBtn = document.getElementById('vnc-grid-fullscreen-btn');
            if (fsBtn) {
                const isFs = !!document.fullscreenElement;
                fsBtn.classList.toggle('toggle-active', isFs);
                fsBtn.title = isFs ? 'Sair da Tela Cheia (Esc)' : 'Alternar Tela Cheia';
            }
        });

        const selectIpsBtn = document.getElementById('vnc-grid-select-ips-btn');
        if (selectIpsBtn) {
            selectIpsBtn.addEventListener('click', () => this.openIpSelectorModal());
        }

        // Botão de Alternar Efeito Visual de Scanlines CRT (NOC Monitor)
        const scanlineBtn = document.getElementById('vnc-grid-scanline-btn');
        if (scanlineBtn) {
            const savedScanlines = localStorage.getItem('vnc_grid_scanlines') === 'true';
            if (savedScanlines && this.container) {
                this.container.classList.add('vnc-scanlines-active');
                scanlineBtn.classList.add('toggle-active');
            }
            scanlineBtn.addEventListener('click', () => {
                const isActive = this.container.classList.toggle('vnc-scanlines-active');
                scanlineBtn.classList.toggle('toggle-active', isActive);
                try { localStorage.setItem('vnc_grid_scanlines', isActive ? 'true' : 'false'); } catch(e){}
                this.showToast(isActive ? '📺 Scanlines CRT Ativadas' : '📺 Scanlines CRT Desativadas', 'info', 2500);
            });
        }

        // Listener de Redimensionamento da Janela (Auto-Fit Dinâmico 100%)
        window.addEventListener('resize', () => {
            if (this.currentCols === 'cols-auto' || this.currentCols === 'cols-fit') {
                this.autoFitGrid();
            }
        });

        const copyLogBtns = this.modal.querySelectorAll('#vnc-grid-copy-log-btn, .vnc-grid-copy-log-btn');
        copyLogBtns.forEach(btn => {
            btn.addEventListener('click', () => this.copyLogsToClipboard());
        });

        const newtabBtn = document.getElementById('vnc-grid-newtab-btn');
        if (newtabBtn) {
            newtabBtn.addEventListener('click', () => {
                const activeIpsArray = Array.from(this.activeTiles.keys()).map(k => k.split('__')[0]);
                const uniqueIps = Array.from(new Set(activeIpsArray));
                const queryIps = uniqueIps.length > 0 ? `ips=${uniqueIps.join(',')}` : '';
                const currentPwd = this.getGridPassword();
                const queryPwd = currentPwd ? `${queryIps ? '&' : ''}password=${encodeURIComponent(currentPwd)}` : '';
                const query = (queryIps || queryPwd) ? `?${queryIps}${queryPwd}` : '';
                window.open(`/grid_view.html${query}`, '_blank');
            });
        }

        // Select de Colunas (Layout Recolhido)
        const colSelects = this.modal.querySelectorAll('#vnc-grid-cols-select');
        colSelects.forEach(select => {
            select.addEventListener('change', (e) => {
                const cols = e.target.value;
                this.setColumns(cols);
            });
        });

        // Botões de Colunas (caso existam)
        const colBtns = this.modal.querySelectorAll('[data-grid-cols]');
        colBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                colBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const cols = btn.getAttribute('data-grid-cols');
                this.setColumns(cols);
            });
        });

        // Botões de Ações em Lote do Grid
        const batchBtns = this.modal.querySelectorAll('[data-batch-action]');
        batchBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const act = btn.getAttribute('data-batch-action');
                if (act) this.handleBatchAction(act);
            });
        });

        // Botões de Seleção em Lote (Todas / Nenhum)
        const selectAllBtns = this.modal.querySelectorAll('#vnc-grid-select-all-btn, .vnc-grid-select-all-btn');
        selectAllBtns.forEach(btn => btn.addEventListener('click', () => this.selectAllTiles(true)));

        const unselectAllBtns = this.modal.querySelectorAll('#vnc-grid-unselect-all-btn, .vnc-grid-unselect-all-btn');
        unselectAllBtns.forEach(btn => btn.addEventListener('click', () => this.selectAllTiles(false)));

        // Seletor de FPS / Limite de Banda
        const fpsSelect = document.getElementById('vnc-grid-fps-select');
        if (fpsSelect) {
            fpsSelect.addEventListener('change', (e) => {
                e.stopPropagation();
                const targetFps = parseInt(e.target.value, 10) || 15;
                this.targetFps = targetFps;
                this.showToast(`⚡ Taxa de Atualização configurada para ${targetFps} FPS`, 'info', 2000);
            });
            fpsSelect.addEventListener('click', (e) => e.stopPropagation());
            fpsSelect.addEventListener('dblclick', (e) => e.stopPropagation());
        }



        // Oculta menu de contexto ao clicar em qualquer lugar da tela
        document.addEventListener('click', (e) => {
            const ctxMenu = document.getElementById('vnc-grid-context-menu');
            if (ctxMenu && !ctxMenu.contains(e.target)) {
                ctxMenu.classList.add('hidden');
            }
        });
        document.addEventListener('contextmenu', (e) => {
            if (!e.target.closest('.vnc-tile')) {
                const ctxMenu = document.getElementById('vnc-grid-context-menu');
                if (ctxMenu) ctxMenu.classList.add('hidden');
            }
        });

        // Virtualização do Grid (IntersectionObserver) para economia de CPU/Banda
        if ('IntersectionObserver' in window && !this.tileObserver) {
            const rootEl = (this.modal && this.modal !== document.body) ? (this.modal.querySelector('.vnc-grid-modal-content') || this.modal) : null;
            this.tileObserver = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    const tileEl = entry.target;
                    const tileKey = tileEl.dataset ? tileEl.dataset.tileKey : null;
                    if (!tileKey) return;
                    const tileData = this.activeTiles.get(tileKey);
                    if (!tileData) return;

                    const isVisible = entry.isIntersecting;
                    tileData.isVisible = isVisible;

                    if (isVisible) {
                        tileEl.classList.remove('tile-offscreen');
                    } else {
                        tileEl.classList.add('tile-offscreen');
                    }
                });
            }, {
                root: rootEl,
                rootMargin: '100px 0px',
                threshold: 0.01
            });
        }
    }

    applyFilter(filterType = 'all') {
        this.currentFilter = filterType;
        this.activeTiles.forEach((tileData) => {
            if (!tileData.element) return;
            const el = tileData.element;
            const isOnline = tileData.isConnected;
            const cb = el.querySelector('.vnc-tile-checkbox');
            const isSelected = cb ? cb.checked : false;

            let show = true;
            if (filterType === 'online') show = isOnline;
            else if (filterType === 'offline') show = !isOnline;
            else if (filterType === 'selected') show = isSelected;

            if (show) {
                el.classList.remove('vnc-tile-hidden');
            } else {
                el.classList.add('vnc-tile-hidden');
            }
        });
        this.autoFitGrid();
    }

    async fetchAliases() {
        try {
            const res = await fetch(`${getApiBaseUrl()}/get-aliases`);
            const data = await res.json();
            if (data.success) {
                if (data.aliases) this.deviceAliases = data.aliases;
            }
        } catch (e) {
            console.warn("[Grid VNC] Erro ao carregar apelidos:", e);
        }
    }

    setColumns(colsClass) {
        if (!this.container) return;
        this.currentCols = colsClass;
        this.container.className = `vnc-grid-container ${colsClass}`;
        
        // Sincroniza o valor dos elementos de select de layout
        const colSelects = this.modal ? this.modal.querySelectorAll('#vnc-grid-cols-select') : document.querySelectorAll('#vnc-grid-cols-select');
        colSelects.forEach(select => {
            if (select.value !== colsClass) select.value = colsClass;
        });

        if (colsClass === 'cols-auto' || colsClass === 'cols-fit') {
            this.autoFitGrid();
        } else {
            this.container.classList.remove('grid-fit-screen');
            if (colsClass === 'cols-5') {
                this.container.classList.add('grid-dense');
                this.container.classList.remove('grid-ultra-dense');
            } else if (colsClass === 'cols-6') {
                this.container.classList.add('grid-ultra-dense');
                this.container.classList.remove('grid-dense');
            } else {
                this.container.classList.remove('grid-dense', 'grid-ultra-dense');
            }
            this.container.style.removeProperty('--grid-cols');
            this.container.style.removeProperty('--grid-rows');
            this.container.style.removeProperty('--grid-gap');
        }
    }

    autoFitGrid() {
        if (!this.container) return;
        const total = this.activeTiles.size;
        if (total === 0) return;

        // Se o usuário selecionou manualmente uma coluna fixa (ex: cols-2, cols-3, etc.)
        if (this.currentCols && this.currentCols !== 'cols-auto' && this.currentCols !== 'cols-fit') {
            return;
        }

        const rect = this.container.getBoundingClientRect();
        const availWidth = rect.width > 0 ? rect.width : window.innerWidth - 24;
        const availHeight = rect.height > 0 ? rect.height : window.innerHeight - 80;

        let bestCols = 1;
        let bestRows = 1;
        let maxTileArea = 0;
        const gap = total > 16 ? 6 : (total > 8 ? 8 : 10);

        // Testa combinações de colunas de 1 até 12 para encontrar a proporção geométrica ideal (16:9)
        for (let cols = 1; cols <= Math.min(12, total); cols++) {
            const rows = Math.ceil(total / cols);
            const tileW = (availWidth - (cols - 1) * gap - 16) / cols;
            const tileH = (availHeight - (rows - 1) * gap - 16) / rows;

            if (tileW <= 40 || tileH <= 40) continue;

            const targetRatio = 16 / 9;
            let effectiveW = tileW;
            let effectiveH = tileH;

            if (tileW / tileH > targetRatio) {
                effectiveW = tileH * targetRatio;
            } else {
                effectiveH = tileW / targetRatio;
            }

            const area = effectiveW * effectiveH;
            if (area > maxTileArea) {
                maxTileArea = area;
                bestCols = cols;
                bestRows = rows;
            }
        }

        // Tabela de Proporções Inteligentes de fallback (Otimizada para 16:9 Widescreen)
        if (maxTileArea === 0) {
            if (total <= 2) { bestCols = 2; bestRows = 1; }
            else if (total <= 4) { bestCols = 2; bestRows = 2; }
            else if (total <= 6) { bestCols = 3; bestRows = 2; }
            else if (total <= 8) { bestCols = 4; bestRows = 2; }
            else if (total <= 12) { bestCols = 4; bestRows = 3; }
            else if (total <= 16) { bestCols = 4; bestRows = 4; }
            else if (total <= 20) { bestCols = 5; bestRows = 4; }
            else if (total <= 24) { bestCols = 6; bestRows = 4; }
            else if (total <= 30) { bestCols = 6; bestRows = 5; }
            else { bestCols = 6; bestRows = Math.ceil(total / 6); }
        }

        this.container.classList.add('grid-fit-screen');
        this.container.style.setProperty('--grid-cols', bestCols);
        this.container.style.setProperty('--grid-rows', bestRows);
        this.container.style.setProperty('--grid-gap', `${gap}px`);

        // Classes de densidade para miniaturização das barras superiores e botões
        if (total >= 20 || bestRows >= 4) {
            this.container.classList.add('grid-ultra-dense');
            this.container.classList.remove('grid-dense');
        } else if (total >= 10 || bestRows >= 3) {
            this.container.classList.add('grid-dense');
            this.container.classList.remove('grid-ultra-dense');
        } else {
            this.container.classList.remove('grid-dense', 'grid-ultra-dense');
        }
    }

    updateCount() {
        let totalCount = this.activeTiles.size;
        let selectedCount = 0;
        let onlineCount = 0;

        this.activeTiles.forEach((tileData) => {
            if (!tileData.element) return;
            const cb = tileData.element.querySelector('.vnc-tile-checkbox');
            if (cb && cb.checked) {
                selectedCount++;
                tileData.element.classList.add('tile-selected');
            } else if (cb) {
                tileData.element.classList.remove('tile-selected');
            }
            if (tileData.isConnected) onlineCount++;
        });

        if (this.statusCountSpan) {
            this.statusCountSpan.textContent = `${onlineCount}/${totalCount} online`;
        }

        const selectedSpan = this.modal ? this.modal.querySelector('#vnc-grid-selected-count') : document.getElementById('vnc-grid-selected-count');
        if (selectedSpan) {
            selectedSpan.textContent = `${selectedCount}/${totalCount} sel.`;
        }

        const headerTitle = document.getElementById('vnc-grid-header-title');
        if (headerTitle) {
            headerTitle.textContent = `Grid VNC`;
        }

        try {
            document.title = `Grid VNC — ${onlineCount}/${totalCount} online`;
        } catch(e) {}

        this.autoFitGrid();
    }

    saveSelectedIpsToLocalStorage() {
        try {
            const currentKeys = [];
            if (this.container) {
                this.container.querySelectorAll('.vnc-tile').forEach(el => {
                    if (el.dataset && el.dataset.tileKey) {
                        currentKeys.push(el.dataset.tileKey);
                    }
                });
            }
            if (currentKeys.length === 0) {
                Array.from(this.activeTiles.keys()).forEach(k => currentKeys.push(k));
            }
            localStorage.setItem('vnc_grid_selected_ips', JSON.stringify(currentKeys));
        } catch(e) {
            console.warn('[Grid VNC] Erro ao salvar seleção no localStorage:', e);
        }
    }

    sortIpList(ipList) {
        if (!Array.isArray(ipList)) return [];
        const clean = this.deduplicateIpList(ipList);
        return clean.sort((a, b) => {
            const parsedA = this.parseTargetSpec(a);
            const parsedB = this.parseTargetSpec(b);
            const baseA = parsedA.baseIp || a;
            const baseB = parsedB.baseIp || b;
            const nameA = this.deviceAliases[baseA] || this.deviceHostnames[baseA] || parsedA.canonicalKey;
            const nameB = this.deviceAliases[baseB] || this.deviceHostnames[baseB] || parsedB.canonicalKey;
            return String(nameA).localeCompare(String(nameB), undefined, { numeric: true, sensitivity: 'base' });
        });
    }

    sortTilesByStatus() {
        if (!this.container) return;
        const tiles = Array.from(this.container.querySelectorAll('.vnc-tile'));
        if (tiles.length <= 1) return;

        tiles.sort((a, b) => {
            const keyA = a.dataset.tileKey;
            const keyB = b.dataset.tileKey;
            const dataA = this.activeTiles.get(keyA);
            const dataB = this.activeTiles.get(keyB);

            const isOnlineA = dataA && dataA.isConnected ? 1 : 0;
            const isOnlineB = dataB && dataB.isConnected ? 1 : 0;

            if (isOnlineA !== isOnlineB) {
                return isOnlineB - isOnlineA; // Online primeiro (1), Offline por último (0)
            }

            // Ordena alfanumericamente/numericamente se o status for o mesmo
            const baseIpA = dataA ? dataA.baseIp : keyA;
            const baseIpB = dataB ? dataB.baseIp : keyB;
            const nameA = dataA ? (this.deviceAliases[baseIpA] || this.deviceHostnames[baseIpA] || keyA) : keyA;
            const nameB = dataB ? (this.deviceAliases[baseIpB] || this.deviceHostnames[baseIpB] || keyB) : keyB;
            return String(nameA).localeCompare(String(nameB), undefined, { numeric: true, sensitivity: 'base' });
        });

        tiles.forEach(tileEl => {
            this.container.appendChild(tileEl);
        });
    }

    selectAllTiles(checked = true) {
        this.activeTiles.forEach((tileData) => {
            if (!tileData.element) return;
            const cb = tileData.element.querySelector('.vnc-tile-checkbox');
            if (cb) {
                cb.checked = checked;
            }
        });
        this.updateCount();
    }

    getSelectedIps() {
        const selected = [];
        this.activeTiles.forEach((tileData, tileKey) => {
            const cb = tileData.element ? tileData.element.querySelector('.vnc-tile-checkbox') : null;
            if (cb && cb.checked) {
                const targetIp = tileData.baseIp || tileData.ip || tileKey.split('__')[0];
                if (targetIp) selected.push(targetIp);
            }
        });
        const unique = Array.from(new Set(selected)).filter(Boolean);
        return unique;
    }

    parseTargetSpec(targetSpec, explicitDisplay = null) {
        if (!targetSpec || typeof targetSpec !== 'string') {
            return { baseIp: '', display: null, canonicalKey: '' };
        }

        let str = targetSpec.trim();
        let baseIp = str;
        let userOrDisplay = explicitDisplay;

        if (!userOrDisplay) {
            if (str.includes('__')) {
                const parts = str.split('__', 2);
                baseIp = parts[0].trim();
                userOrDisplay = parts[1].trim();
            } else if (str.includes('/')) {
                const parts = str.split('/', 2);
                baseIp = parts[0].trim();
                userOrDisplay = parts[1].trim();
            }
        }

        let canonicalDisplay = null;
        if (userOrDisplay) {
            const u = String(userOrDisplay).trim().toLowerCase();
            if (u === 'aluno1' || u === 'seat0' || u === '0' || u === ':0') {
                canonicalDisplay = ':0';
            } else if (u === 'aluno2' || u === 'seat1' || u === '1' || u === ':1') {
                canonicalDisplay = ':1';
            } else if (u.startsWith(':') && !isNaN(u.slice(1))) {
                canonicalDisplay = u;
            } else if (!isNaN(u)) {
                canonicalDisplay = `:${u}`;
            } else {
                canonicalDisplay = userOrDisplay;
            }
        }

        const canonicalKey = canonicalDisplay ? `${baseIp}__${canonicalDisplay}` : baseIp;
        return { baseIp, display: canonicalDisplay, userOrDisplay, canonicalKey, rawSpec: targetSpec };
    }

    deduplicateIpList(rawList) {
        if (!Array.isArray(rawList)) return [];
        const seenKeys = new Set();
        const cleanList = [];
        for (const item of rawList) {
            if (!item || typeof item !== 'string') continue;
            const parsed = this.parseTargetSpec(item);
            if (!parsed.canonicalKey || seenKeys.has(parsed.canonicalKey)) continue;

            seenKeys.add(parsed.canonicalKey);
            cleanList.push(item);
        }
        return cleanList;
    }

    async openGrid(targetIps = []) {
        if (!this.modal) this.initDOM();
        if (!this.modal) return;

        this.modal.classList.remove('hidden');

        // Garante que os apelidos estejam carregados antes de conectar
        await this.fetchAliases();

        // Se nenhum IP foi informado, tenta restaurar seleção salva
        if (!targetIps || targetIps.length === 0) {
            try {
                const saved = localStorage.getItem('vnc_grid_selected_ips');
                if (saved) {
                    const parsed = JSON.parse(saved);
                    if (Array.isArray(parsed) && parsed.length > 0) {
                        targetIps = parsed;
                    }
                }
            } catch(e) {}

            // Fallback: máquinas online do painel
            if (!targetIps || targetIps.length === 0) {
                targetIps = this.getOnlineIps();
            }
        } else {
            targetIps = this.deduplicateIpList(targetIps);
        }

        const ipsToConnect = this.sortIpList(targetIps);

        for (const ip of ipsToConnect) {
            const parsed = this.parseTargetSpec(ip);
            if (!this.activeTiles.has(parsed.canonicalKey)) {
                await this.addTile(ip);
            }
        }
        this.sortTilesByStatus();
    }

    getOnlineIps() {
        const onlineSet = new Set();

        // 1. IPs com checkboxes marcados no painel principal
        document.querySelectorAll('input[name="ip"]:checked').forEach(cb => {
            if (cb.value) onlineSet.add(cb.value.trim());
        });

        // 2. Elementos de máquina marcados como status-online
        if (onlineSet.size === 0) {
            document.querySelectorAll('.ip-item.status-online, .ip-item:not(.status-offline)').forEach(el => {
                if (el.dataset && el.dataset.ip) {
                    onlineSet.add(el.dataset.ip.trim());
                }
            });
        }

        // 3. Fallback: Todos os checkboxes de IP presentes na página
        if (onlineSet.size === 0) {
            document.querySelectorAll('input[name="ip"]').forEach(cb => {
                if (cb.value) onlineSet.add(cb.value.trim());
            });
        }

        return this.deduplicateIpList(Array.from(onlineSet));
    }

    getAllAvailableIps() {
        const ipSet = new Set();
        document.querySelectorAll('input[name="ip"]').forEach(cb => {
            if (cb.value) ipSet.add(cb.value.trim());
        });
        document.querySelectorAll('.ip-item').forEach(el => {
            if (el.dataset && el.dataset.ip) {
                ipSet.add(el.dataset.ip.trim());
            }
        });
        this.activeTiles.forEach((_, key) => {
            const rawIp = key.split('__')[0].split('/')[0];
            if (rawIp) ipSet.add(rawIp.trim());
        });
        return this.deduplicateIpList(Array.from(ipSet));
    }

    async addTile(ip, display = null) {
        if (!ip) return;
        const parsed = this.parseTargetSpec(ip, display);
        const { baseIp, display: targetDisplay, canonicalKey } = parsed;

        if (this.activeTiles.has(canonicalKey)) return;

        const tileKey = canonicalKey;
        const idSlug = tileKey.replace(/[\/\.:]/g, '-');
        const displayLabel = targetDisplay ? ` <span style="opacity:.85;font-size:.72rem;color:#38bdf8;font-weight:700;background:rgba(56,189,248,0.12);padding:1px 4px;border-radius:3px;">${targetDisplay}</span>` : '';

        const alias = this.deviceAliases[baseIp];
        const hostname = this.deviceHostnames[baseIp] || '';
        const titleTooltip = `${baseIp}${hostname ? ' — ' + hostname : ''}`;
        const shortIp = '.' + (baseIp.split('.').pop() || baseIp);
        const titleMarkup = alias ? `
            <div style="display:flex;flex-direction:column;line-height:1.2;" title="${titleTooltip}">
                <span style="font-weight:700;color:#f8fafc;font-size:0.9rem;">${alias}${displayLabel}</span>
                <span style="font-family:'JetBrains Mono',monospace;font-size:0.72rem;color:#64748b;opacity:0.9;">${baseIp}</span>
            </div>
        ` : hostname ? `
            <div style="display:flex;flex-direction:column;line-height:1.2;" title="${titleTooltip}">
                <span style="font-weight:700;color:#f8fafc;font-size:0.9rem;">${hostname}${displayLabel}</span>
                <span style="font-family:'JetBrains Mono',monospace;font-size:0.72rem;color:#64748b;opacity:0.9;">${baseIp}</span>
            </div>
        ` : `<span class="vnc-tile-ip" title="${titleTooltip}">${baseIp}${displayLabel}</span>`;

        const displayName = alias || hostname || baseIp;

        const tileEl = document.createElement('div');
        tileEl.className = 'vnc-tile';
        tileEl.id = `vnc-tile-${idSlug}`;
        tileEl.innerHTML = `
            <!-- Cabeçalho: botões de ação (aparece no hover) -->
            <div class="vnc-tile-header" draggable="false">
                <div class="vnc-tile-info">
                    <input type="checkbox" class="vnc-tile-checkbox" id="cb-${idSlug}" checked title="Selecionar máquina para ações em lote" />
                </div>
                <div class="vnc-tile-actions">
                    <button type="button" class="vnc-tile-btn pin-btn" title="Fixar Máquina no Topo do Grid" id="btn-pin-${idSlug}">
                        <span id="pin-icon-${idSlug}" style="font-size:0.8rem;line-height:1;">📌</span>
                    </button>
                    <button type="button" class="vnc-tile-btn focus-btn" title="Focar / Ampliar este Monitor (Zoom)" id="btn-focus-${idSlug}">
                        <span style="font-size:0.8rem;line-height:1;">🔍</span>
                    </button>
                    <button type="button" class="vnc-tile-btn lock-btn" title="Desbloqueado (Clique para Bloquear 🔒)" id="btn-lock-${idSlug}">
                        <span id="lock-icon-state-${idSlug}" style="font-size:0.85rem;line-height:1;">🔓</span>
                    </button>
                    <button type="button" class="vnc-tile-btn" title="Expandir VNC (Duplo clique na tela)" id="btn-expand-${idSlug}">
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

            <!-- Corpo: canvas VNC -->
            <div class="vnc-tile-body">
                <div class="vnc-tile-overlay" id="overlay-${idSlug}">
                    <div class="vnc-tile-spinner"></div>
                    <div class="vnc-tile-status-text" id="status-text-${idSlug}">Iniciando VNC em ${baseIp}${targetDisplay ? ' ' + targetDisplay : ''}...</div>
                </div>
                <div class="vnc-tile-canvas" id="canvas-container-${idSlug}"></div>

                <!-- Rodapé fixo: dot de status + nome da máquina + usuário -->
                <div class="vnc-tile-footer" id="footer-${idSlug}">
                    <div style="display:flex;align-items:center;gap:6px;min-width:0;">
                        <span class="vnc-footer-dot connecting" id="footer-dot-${idSlug}" title="Status da conexão: Conectando"></span>
                        <span class="vnc-tile-footer-name" id="footer-name-${idSlug}" title="${titleTooltip}">${displayName}${displayLabel}</span>
                    </div>
                    <span class="vnc-tile-footer-user" id="user-badge-${idSlug}" style="display:none;"></span>
                </div>

                <!-- Hint de duplo clique (aparece no hover, estilo Veyon) -->
                <div class="vnc-dblclick-hint">
                    <span class="vnc-dblclick-icon">🖥️</span>
                    <span class="vnc-dblclick-text">Duplo clique para controlar</span>
                </div>
            </div>
        `;

        this.container.appendChild(tileEl);
        this.updateCount();

        // Registra a sessão do tile no gerenciador
        tileEl.dataset.tileKey = tileKey;
        const tileData = {
            rfb: null,
            wsPort: null,
            element: tileEl,
            ip: baseIp,
            display: targetDisplay,
            baseIp: baseIp,
            retryCount: 0,
            retryTimer: null,
            isManuallyClosed: false,
            isVisible: true,
            isLocked: false,
            isConnected: false,
            lastFrame: null
        };
        this.activeTiles.set(tileKey, tileData);
        this.saveSelectedIpsToLocalStorage();

        // ===== DRAG & DROP: reordenar cards arrastando =====
        tileEl.setAttribute('draggable', 'true');
        tileEl.addEventListener('dragstart', (e) => {
            if (e.target.closest('.vnc-tile-btn') || e.target.closest('.vnc-tile-checkbox')) {
                e.preventDefault();
                return;
            }
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', tileKey);
            tileEl.classList.add('tile-dragging');
            this._dragSrcKey = tileKey;
        });
        tileEl.addEventListener('dragend', () => {
            tileEl.classList.remove('tile-dragging');
            this.container.querySelectorAll('.vnc-tile').forEach(t => t.classList.remove('tile-drag-over'));
            this._dragSrcKey = null;
            this.saveSelectedIpsToLocalStorage();
        });
        tileEl.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            if (this._dragSrcKey && this._dragSrcKey !== tileKey) {
                this.container.querySelectorAll('.vnc-tile').forEach(t => t.classList.remove('tile-drag-over'));
                tileEl.classList.add('tile-drag-over');
            }
        });
        tileEl.addEventListener('dragleave', (e) => {
            if (!tileEl.contains(e.relatedTarget)) {
                tileEl.classList.remove('tile-drag-over');
            }
        });
        tileEl.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const srcKey = e.dataTransfer.getData('text/plain') || this._dragSrcKey;
            if (!srcKey || srcKey === tileKey) return;
            const srcEl = this.container.querySelector(`[data-tile-key="${srcKey}"]`);
            if (!srcEl) return;
            // Inserir antes do target
            this.container.insertBefore(srcEl, tileEl);
            tileEl.classList.remove('tile-drag-over');
            this.saveSelectedIpsToLocalStorage();
        });
        // ====================================================

        if (this.tileObserver) {
            try { this.tileObserver.observe(tileEl); } catch(e) {}
        }

        const tileCb = tileEl.querySelector(`#cb-${idSlug}`);
        if (tileCb) {
            tileCb.addEventListener('change', () => {
                this.updateCount();
                if (this.currentFilter === 'selected') this.applyFilter('selected');
            });
        }

        // Botão de Fixar Máquina no Topo (Pin)
        const btnPin = tileEl.querySelector(`#btn-pin-${idSlug}`);
        if (btnPin) {
            btnPin.onclick = (e) => {
                e.stopPropagation();
                const isPinned = tileEl.classList.toggle('tile-pinned');
                btnPin.classList.toggle('active', isPinned);
                tileData.isPinned = isPinned;
                if (isPinned) {
                    tileEl.style.order = '-10';
                    this.showToast(`📌 ${displayName} fixado no topo do Grid`, 'info', 2000);
                } else {
                    tileEl.style.order = '';
                    this.showToast(`📌 ${displayName} desafixado`, 'info', 1500);
                }
            };
        }

        // Botão de Foco / Zoom no Monitor
        const btnFocus = tileEl.querySelector(`#btn-focus-${idSlug}`);
        if (btnFocus) {
            btnFocus.onclick = (e) => {
                e.stopPropagation();
                const isFocused = tileEl.classList.toggle('tile-focused');
                btnFocus.classList.toggle('active', isFocused);
                if (isFocused) {
                    this.showToast(`🔍 Monitor ${baseIp} focado com zoom`, 'info', 2000);
                }
            };
        }

        // Eventos dos botões do Tile
        const btnLock = tileEl.querySelector(`#btn-lock-${idSlug}`);
        if (btnLock) {
            btnLock.onclick = (e) => {
                e.stopPropagation();
                this.toggleSingleTileLock(tileKey);
            };
        }

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

            window.openWebVNC(baseIp, targetDisplay);

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

        // ===== 🖱️ DUPLO CLIQUE EM QUALQUER ÁREA DO TILE (Abre VNC Interativo/Controle) =====
        tileEl.style.cursor = 'pointer';
        tileEl.title = 'Duplo clique em qualquer área para controlar em tela cheia';
        let lastTileClickTime = 0;
        const handleDblClickOrFastClick = (e) => {
            if (e.target.closest('.vnc-tile-btn') || e.target.closest('.vnc-tile-checkbox') || e.target.closest('input')) return;
            if (e.button && e.button !== 0) return; // Apenas botão esquerdo do mouse

            const now = Date.now();
            const timeDiff = now - lastTileClickTime;
            if (e.type === 'dblclick' || (timeDiff > 0 && timeDiff < 420)) {
                e.stopPropagation();
                e.preventDefault();
                lastTileClickTime = 0;
                expandAction();
            } else if (e.type === 'mousedown') {
                lastTileClickTime = now;
            }
        };

        tileEl.addEventListener('dblclick', handleDblClickOrFastClick, true);
        tileEl.addEventListener('mousedown', handleDblClickOrFastClick, true);

        // ===== 🖱️ BOTÃO DIREITO: Menu de Contexto em QUALQUER área do Tile (fase de captura) =====
        const handleRightClick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.showContextMenu(e, tileKey, baseIp, targetDisplay, displayName, btnFocus, btnPin, btnLock, btnRefresh, btnExpand);
        };

        tileEl.addEventListener('contextmenu', handleRightClick, true);
        
        // Impede que o noVNC capture o botão direito como clique interno no modo Grid
        tileEl.addEventListener('mousedown', (e) => {
            if (e.button === 2) {
                e.preventDefault();
                e.stopPropagation();
            }
        }, true);

        // Inicia a tentativa de conexão
        this.startTileConnection(tileKey);
    }

    showContextMenu(e, tileKey, baseIp, targetDisplay, displayName, btnFocus, btnPin, btnLock, btnRefresh, btnExpand) {
        const menu = document.getElementById('vnc-grid-context-menu');
        const title = document.getElementById('vnc-context-title');
        if (!menu) return;

        if (title) {
            title.textContent = `🖥️ ${displayName}${targetDisplay ? ' (' + targetDisplay + ')' : ''} (${baseIp})`;
        }

        // Exibe o menu primeiro para medir sua largura e altura reais
        menu.style.animation = 'none';
        menu.classList.remove('hidden');

        const menuWidth = menu.offsetWidth || 350;
        const menuHeight = menu.offsetHeight || 300;

        let x = e.clientX;
        let y = e.clientY;

        // Ajusta as coordenadas para evitar estouros nas bordas da tela (direita/inferior)
        if (x + menuWidth > window.innerWidth - 10) {
            x = window.innerWidth - menuWidth - 10;
        }
        if (y + menuHeight > window.innerHeight - 10) {
            y = window.innerHeight - menuHeight - 10;
        }

        menu.style.left = `${Math.max(10, x)}px`;
        menu.style.top = `${Math.max(10, y)}px`;

        // Reinicia a animação de entrada fluida
        void menu.offsetWidth;
        menu.style.animation = null;

        // Mapeia ações dos itens do menu de contexto
        const bindCtxItem = (id, handler) => {
            const item = document.getElementById(id);
            if (!item) return;
            item.onclick = (evt) => {
                evt.stopPropagation();
                menu.classList.add('hidden');
                handler();
            };
        };

        bindCtxItem('ctx-expand', () => { if (btnExpand) btnExpand.click(); });
        bindCtxItem('ctx-focus', () => { if (btnFocus) btnFocus.click(); });
        bindCtxItem('ctx-pin', () => { if (btnPin) btnPin.click(); });
        bindCtxItem('ctx-demo', () => {
            this.executeSingleCommand(tileKey, 'iniciar_modo_demo', `Transmitir Tela para ${displayName}`);
        });
        bindCtxItem('ctx-clean', () => {
            this.executeSingleCommand(tileKey, 'limpar_tela', `Limpar Tela de ${displayName}`);
        });
        bindCtxItem('ctx-lock', () => { if (btnLock) btnLock.click(); });
        bindCtxItem('ctx-refresh', () => { if (btnRefresh) btnRefresh.click(); });
        bindCtxItem('ctx-cad', () => { this.sendSingleCtrlAltDel(tileKey); });

        bindCtxItem('ctx-msg', () => {
            this.openPresetMessageModal('single', tileKey, displayName);
        });

        bindCtxItem('ctx-url', () => {
            this.openPresetUrlModal('single', tileKey, displayName);
        });

        bindCtxItem('ctx-restart', () => {
            this.executeSingleCommand(tileKey, 'reiniciar', `Reiniciar ${displayName}`);
        });

        bindCtxItem('ctx-shutdown', () => {
            this.executeSingleCommand(tileKey, 'desligar', `Desligar ${displayName}`);
        });

        bindCtxItem('ctx-block-stickers', () => {
            this.executeSingleCommand(tileKey, 'bloquear_stickers', `Bloquear Stickers & Perfil em ${displayName}`);
        });

        bindCtxItem('ctx-unblock-stickers', () => {
            this.executeSingleCommand(tileKey, 'desbloquear_stickers', `Desbloquear Stickers & Perfil em ${displayName}`);
        });
    }

    async executeSingleCommand(rawIpSpec, payloadAction, actionName = 'Comando', extraData = {}) {
        const parsed = this.parseTargetSpec(rawIpSpec);
        const targetIp = parsed.baseIp;
        const targetDisplay = parsed.display;
        const activePassword = this.getGridPassword();
        const displayName = this.deviceAliases[targetIp] || this.deviceHostnames[targetIp] || targetIp;

        this.showToast(`⏳ Executando '${actionName}' em ${displayName}...`, 'info', 2500);

        try {
            const body = {
                ip: targetIp,
                action: payloadAction,
                password: activePassword,
                display: targetDisplay,
                target_display: targetDisplay,
                ...extraData
            };
            const res = await fetch(`${getApiBaseUrl()}/gerenciar_atalhos_ip`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            const data = await res.json();

            if (data && data.success !== false) {
                this.showToast(`✅ '${actionName}' enviado para ${displayName}!`, 'success', 3000);
                this.addLog(rawIpSpec, 'CMD', `'${actionName}' executado com sucesso.`);
                if (payloadAction === 'bloquear_tela_mensagem') {
                    this.setTileLockState(rawIpSpec, true);
                } else if (payloadAction === 'desbloquear_tela_mensagem') {
                    this.setTileLockState(rawIpSpec, false);
                }
                return true;
            } else {
                const errMsg = data ? (data.message || data.error) : 'Falha na resposta do servidor';
                this.showToast(`❌ Erro em ${displayName}: ${errMsg}`, 'error', 4000);
                this.addLog(rawIpSpec, 'CMD_ERRO', `'${actionName}' falhou: ${errMsg}`);
                return false;
            }
        } catch(err) {
            this.showToast(`❌ Falha de rede ao enviar comando para ${displayName}`, 'error', 4000);
            this.addLog(rawIpSpec, 'CMD_ERRO', `Erro de conexão ao enviar '${actionName}'.`);
            return false;
        }
    }

    updateTileUI(tileKey, status, msg) {
        this.addLog(tileKey, status, msg);
        const tileData = this.activeTiles.get(tileKey);
        if (!tileData || !tileData.element) return;
        const tileEl = tileData.element;
        const idSlug = tileKey.replace(/[\/\.:]/g, '-');
        const statusText = tileEl.querySelector(`#status-text-${idSlug}`);
        const overlay = tileEl.querySelector(`#overlay-${idSlug}`);
        const footerDot = tileEl.querySelector(`#footer-dot-${idSlug}`);
        const canvasContainer = tileEl.querySelector(`#canvas-container-${idSlug}`);

        // 1. Atualiza a bolinha colorida no rodapé (🟢 online / 🔴 offline / 🟡 conectando)
        if (footerDot) {
            footerDot.className = `vnc-footer-dot ${status}`;
            const dotTitle = status === 'connected' ? 'Conectado (🟢 Online)' : (status === 'connecting' ? 'Conectando (🟡)' : 'Desconectado (🔴 Offline)');
            footerDot.title = dotTitle;
        }

        if (statusText) statusText.textContent = msg;

        if (status === 'connected') {
            tileData.isConnected = true;
            if (overlay) {
                overlay.classList.add('hidden');
                overlay.classList.remove('has-frozen-frame');
            }

            // Remove imagem congelada do frame anterior (se existir)
            if (canvasContainer) {
                canvasContainer.style.backgroundImage = '';
                canvasContainer.style.filter = '';
            }
            tileEl.classList.remove('tile-offline');
        } else {
            tileData.isConnected = false;

            // 2. Captura o último frame antes/ao desconectar
            if (canvasContainer) {
                try {
                    const canvas = canvasContainer.querySelector('canvas');
                    if (canvas && canvas.width > 0 && canvas.height > 0) {
                        tileData.lastFrame = canvas.toDataURL('image/jpeg', 0.6);
                    }
                } catch(e) {}
            }

            // Exibe miniatura congelada por baixo do overlay translúcido
            if (tileData.lastFrame && canvasContainer) {
                canvasContainer.style.backgroundImage = `url('${tileData.lastFrame}')`;
                canvasContainer.style.backgroundSize = 'contain';
                canvasContainer.style.backgroundPosition = 'center';
                canvasContainer.style.backgroundRepeat = 'no-repeat';
                canvasContainer.style.filter = 'brightness(0.9) contrast(0.95)';
                if (overlay) overlay.classList.add('has-frozen-frame');
            }

            if (overlay) overlay.classList.remove('hidden');
            tileEl.classList.add('tile-offline');
        }

        // 6. Ordenação automática: máquinas conectadas (online) primeiro e desconectadas por último
        this.sortTilesByStatus();

        this.updateCount();
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
                if (tileData.retryTimer) clearInterval(tileData.retryTimer);
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

        this.startTileConnection(tileKey, true); // Prioridade para reconexão manual
    }

    startTileConnection(tileKey, priority = false) {
        const tileData = this.activeTiles.get(tileKey);
        if (!tileData || tileData.isManuallyClosed) return;

        if (!tileData.isConnected) {
            this.updateTileUI(tileKey, 'connecting', 'Na fila de conexão...');
        }

        if (!this.connectionQueue.includes(tileKey)) {
            if (priority) {
                this.connectionQueue.unshift(tileKey);
            } else {
                this.connectionQueue.push(tileKey);
            }
        }
        this.processConnectionQueue();
    }

    async processConnectionQueue() {
        if (this.activeConnectingCount >= this.MAX_CONCURRENT_CONNECTS) return;
        if (this.connectionQueue.length === 0) return;

        const tileKey = this.connectionQueue.shift();
        const tileData = this.activeTiles.get(tileKey);
        if (!tileData || tileData.isManuallyClosed) {
            this.processConnectionQueue();
            return;
        }

        this.activeConnectingCount++;
        try {
            await this._executeTileConnection(tileKey);
        } catch (err) {
            console.warn(`[Grid VNC] Erro ao conectar ${tileKey}:`, err);
        } finally {
            this.activeConnectingCount = Math.max(0, this.activeConnectingCount - 1);
            setTimeout(() => this.processConnectionQueue(), 120);
        }
    }

    async _executeTileConnection(tileKey) {
        const tileData = this.activeTiles.get(tileKey);
        if (!tileData || tileData.isManuallyClosed) return;

        const { ip, baseIp, display, element: tileEl } = tileData;
        const targetHostIp = baseIp || ip;
        const idSlug = tileKey.replace(/[\/\.:]/g, '-');
        const canvasContainer = tileEl.querySelector(`#canvas-container-${idSlug}`);

        const expandAction = () => {
            if (typeof window.openWebVNC === 'function') {
                window.openWebVNC(targetHostIp, display);
            }
        };

        // Pré-verificação de conectividade
        this.updateTileUI(tileKey, 'connecting', `Testando conectividade em ${targetHostIp}...`);
        try {
            const pingController = new AbortController();
            const pingTimeout = setTimeout(() => pingController.abort(), 4000);

            const checkRes = await fetch(`${getApiBaseUrl()}/api/ping-check`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ips: [targetHostIp] }),
                signal: pingController.signal
            });
            clearTimeout(pingTimeout);

            const checkData = await checkRes.json();
            if (checkData.success && checkData.results && checkData.results[targetHostIp]) {
                const info = checkData.results[targetHostIp];
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
        } catch (e) {
            console.warn(`[Grid VNC] Ping-check timeout/erro em ${targetHostIp}:`, e);
        }

        const activePassword = this.getGridPassword();
        let wsPort = 6080;

        try {
            const bodyData = { ip: targetHostIp, username: 'aluno', password: activePassword };
            if (display) bodyData.display = display;

            const prepController = new AbortController();
            const prepTimeout = setTimeout(() => prepController.abort(), 25000);

            const prepRes = await fetch(`${getApiBaseUrl()}/api/start-vnc`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(bodyData),
                signal: prepController.signal
            });
            clearTimeout(prepTimeout);
            const prepData = await prepRes.json();

            if (prepData.multiseat && prepData.displays && prepData.displays.length > 0) {
                if (tileEl && tileEl.parentNode) tileEl.parentNode.removeChild(tileEl);
                this.activeTiles.delete(tileKey);
                this.activeTiles.delete(targetHostIp);
                this.updateCount();

                for (const d of prepData.displays) {
                    const parsedSeat = this.parseTargetSpec(targetHostIp, d.display);
                    if (!this.activeTiles.has(parsedSeat.canonicalKey)) {
                        await this.addTile(targetHostIp, d.display);
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
                        userBadge.style.display = 'inline';
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

            // Captura periódica por Hardware GPU (createImageBitmap Downscaling Acelerado)
            tileData._frameInterval = setInterval(async () => {
                if (!tileData.isConnected || tileData.isVisible === false) return;
                try {
                    const innerCanvas = canvasContainer.querySelector('canvas');
                    if (innerCanvas && innerCanvas.width > 0 && innerCanvas.height > 0) {
                        if ('createImageBitmap' in window) {
                            const bitmap = await createImageBitmap(innerCanvas, {
                                resizeWidth: 320,
                                resizeHeight: 180,
                                resizeQuality: 'medium'
                            });
                            const offscreenCanvas = document.createElement('canvas');
                            offscreenCanvas.width = 320;
                            offscreenCanvas.height = 180;
                            const offCtx = offscreenCanvas.getContext('2d', { desynchronized: true, alpha: false });
                            if (offCtx) {
                                offCtx.drawImage(bitmap, 0, 0);
                                tileData.lastFrame = offscreenCanvas.toDataURL('image/jpeg', 0.65);
                            }
                            bitmap.close();
                        } else {
                            tileData.lastFrame = innerCanvas.toDataURL('image/jpeg', 0.6);
                        }
                    }
                } catch(e) {}
            }, 3000);

            canvasContainer.addEventListener('dblclick', (e) => {
                e.stopPropagation();
                e.preventDefault();
                expandAction();
            }, true);

            const updateResolutionBadge = () => {
                try {
                    const w = rfb._fbWidth || (rfb._display ? rfb._display._fbWidth : 0);
                    const h = rfb._fbHeight || (rfb._display ? rfb._display._fbHeight : 0);
                    const resBadge = tileEl.querySelector(`#res-badge-${idSlug}`);
                    if (resBadge && w && h) {
                        resBadge.textContent = `🖥️ ${w}x${h}`;
                    }
                } catch(e) {}
            };

            // 📡 DELTA FRAME SKIP: Detecção de inatividade de tela (>5s sem mudança)
            tileData.lastActivityTime = Date.now();
            tileData.isIdle = false;

            const checkIdleStatus = () => {
                if (!tileData.isConnected || tileData.isManuallyClosed) return;
                const idleDuration = Date.now() - (tileData.lastActivityTime || Date.now());
                if (idleDuration > 5000 && !tileData.isIdle) {
                    tileData.isIdle = true;
                }
            };
            tileData._idleInterval = setInterval(checkIdleStatus, 3000);

            rfb.addEventListener('connect', () => {
                tileData.retryCount = 0; // Sucesso: reseta o contador de tentativas
                tileData.lastActivityTime = Date.now();
                tileData.isIdle = false;
                this.updateTileUI(tileKey, 'connected', `Conectado -> ${ip}`);
                updateResolutionBadge();
                const innerCanvas = canvasContainer.querySelector('canvas');
                if (innerCanvas) {
                    innerCanvas.style.cursor = 'pointer';
                    try {
                        // Aceleração de renderização desincronizada de Canvas (Desynchronized Low-latency Pipeline)
                        const ctx = innerCanvas.getContext('2d', { desynchronized: true, alpha: false, willReadFrequently: false });
                        if (ctx) ctx.imageSmoothingEnabled = false;
                    } catch(e) {}
                    innerCanvas.addEventListener('dblclick', (e) => {
                        e.stopPropagation();
                        e.preventDefault();
                        expandAction();
                    }, true);
                }
            });

            rfb.addEventListener('fbresize', () => {
                tileData.lastActivityTime = Date.now();
                tileData.isIdle = false;
                updateResolutionBadge();
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
                    tileData.lastActivityTime = Date.now();
                    tileData.isIdle = false;
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

        // 🧹 LIMPEZA RIGOROSA DE TIMERS (PREVENT MEMORY LEAKS)
        if (tileData.retryTimer) {
            clearInterval(tileData.retryTimer);
            tileData.retryTimer = null;
        }
        if (tileData._idleInterval) {
            clearInterval(tileData._idleInterval);
            tileData._idleInterval = null;
        }
        if (tileData._frameInterval) {
            clearInterval(tileData._frameInterval);
            tileData._frameInterval = null;
        }

        const { rfb, wsPort, element } = tileData;

        // 🧹 DESCONEXÃO E DESTRUIÇÃO DE OBJETOS RFB & EVENT LISTENERS
        if (rfb) {
            try {
                rfb.disconnect();
            } catch(e) {}
            tileData.rfb = null;
        }

        // 🧹 LIBERAÇÃO DE CANVAS E RECURSOS 2D DE MEMÓRIA (GARBAGE COLLECTION)
        if (element) {
            const canvases = element.querySelectorAll('canvas');
            canvases.forEach(canvas => {
                try {
                    canvas.width = 0;
                    canvas.height = 0;
                } catch(e){}
            });
            if (this.tileObserver) {
                try { this.tileObserver.unobserve(element); } catch(e) {}
            }
            if (element.parentNode) {
                element.parentNode.removeChild(element);
            }
        }

        if (wsPort) {
            try {
                fetch(`${getApiBaseUrl()}/api/stop-vnc`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ws_port: wsPort })
                }).catch(() => {});
            } catch(e) {}
            tileData.wsPort = null;
        }

        // 🧹 NULIFICA PONTEIROS E REFERÊNCIAS PARA O GARBAGE COLLECTOR
        tileData.element = null;
        tileData.lastFrame = null;
        this.activeTiles.delete(tileKey);

        this.saveSelectedIpsToLocalStorage();
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
                    data.ips.forEach(item => {
                        if (typeof item === 'object' && item.ip && item.hostname) {
                            this.deviceHostnames[item.ip] = item.hostname;
                        }
                    });
                    availableIps = data.ips.map(item => typeof item === 'object' ? item.ip : item);
                }
            } catch (e) {}
        }

        // Helper: atualiza o badge de contagem
        const updateCountBadge = () => {
            const badge = document.getElementById('vnc-selector-count-badge');
            if (badge) {
                const n = listContainer.querySelectorAll('input[type="checkbox"]:checked').length;
                badge.textContent = `${n} selecionada${n !== 1 ? 's' : ''}`;
            }
        };

        // Renderiza um item chip
        const renderItem = (ip, isSelected) => {
            const alias = this.deviceAliases[ip];
            const hostname = this.deviceHostnames[ip] || '';
            const displayName = alias || hostname || ip;
            const isKnown = alias || hostname;

            const label = document.createElement('label');
            label.className = 'vnc-grid-select-item';
            label.dataset.ip = ip;
            label.dataset.name = displayName.toLowerCase();
            label.style.cssText = `
                display:flex; flex-direction:column; align-items:flex-start; gap:2px;
                padding:8px 10px; background:#1e293b;
                border:1.5px solid ${isSelected ? 'rgba(99,102,241,0.6)' : 'rgba(255,255,255,0.06)'};
                border-radius:8px; cursor:pointer; transition:all 0.15s ease;
                ${isSelected ? 'box-shadow: 0 0 10px rgba(99,102,241,0.25);' : ''}
            `;
            label.innerHTML = `
                <div style="display:flex; align-items:center; gap:6px; width:100%;">
                    <input type="checkbox" value="${ip}" ${isSelected ? 'checked' : ''} style="width:14px;height:14px;accent-color:#6366f1;flex-shrink:0;">
                    <span style="font-weight:700; font-size:0.82rem; color:${isKnown ? '#f8fafc' : '#94a3b8'}; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:100px;">${displayName}</span>
                </div>
                <span style="font-family:'JetBrains Mono',monospace; font-size:0.68rem; color:#475569; margin-left:20px;">${isKnown ? ip : ''}</span>
            `;
            label.querySelector('input').addEventListener('change', (e) => {
                const checked = e.target.checked;
                label.style.borderColor = checked ? 'rgba(99,102,241,0.6)' : 'rgba(255,255,255,0.06)';
                label.style.boxShadow = checked ? '0 0 10px rgba(99,102,241,0.25)' : 'none';
                updateCountBadge();
            });
            label.addEventListener('mouseenter', () => {
                if (!label.querySelector('input').checked) {
                    label.style.borderColor = 'rgba(255,255,255,0.15)';
                    label.style.background = '#253048';
                }
            });
            label.addEventListener('mouseleave', () => {
                if (!label.querySelector('input').checked) {
                    label.style.borderColor = 'rgba(255,255,255,0.06)';
                    label.style.background = '#1e293b';
                }
            });
            return label;
        };

        if (availableIps.length === 0) {
            listContainer.innerHTML = '<div style="color:#94a3b8;padding:12px;text-align:center;grid-column:1/-1;">Nenhuma máquina detectada no momento.</div>';
        } else {
            availableIps.forEach(ip => {
                const isSelected = this.activeTiles.has(ip) || Array.from(this.activeTiles.keys()).some(k => k.startsWith(ip));
                listContainer.appendChild(renderItem(ip, isSelected));
            });
            updateCountBadge();
        }

        // Busca em tempo real
        const searchInput = document.getElementById('vnc-selector-search');
        if (searchInput) {
            searchInput.value = '';
            searchInput.oninput = () => {
                const q = searchInput.value.toLowerCase().trim();
                listContainer.querySelectorAll('.vnc-grid-select-item').forEach(el => {
                    const match = !q || el.dataset.name.includes(q) || (el.dataset.ip && el.dataset.ip.includes(q));
                    el.style.display = match ? '' : 'none';
                });
            };
        }

        // Botão "Todas"
        const selAllBtn = document.getElementById('vnc-sel-all-btn');
        if (selAllBtn) {
            selAllBtn.onclick = () => {
                listContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                    if (cb.closest('.vnc-grid-select-item').style.display !== 'none') {
                        cb.checked = true;
                        cb.dispatchEvent(new Event('change'));
                    }
                });
            };
        }

        // Botão "Nenhuma"
        const selNoneBtn = document.getElementById('vnc-sel-none-btn');
        if (selNoneBtn) {
            selNoneBtn.onclick = () => {
                listContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                    cb.checked = false;
                    cb.dispatchEvent(new Event('change'));
                });
            };
        }

        selectorModal.classList.remove('hidden');

        const confirmBtn = document.getElementById('vnc-grid-selector-confirm-btn');
        if (confirmBtn) {
            confirmBtn.onclick = () => {
                const checkedInputs = listContainer.querySelectorAll('input[type="checkbox"]:checked');
                const selectedIps = Array.from(checkedInputs).map(cb => cb.value);

                // Persiste seleção no localStorage (melhoria 5)
                try { localStorage.setItem('vnc_grid_selected_ips', JSON.stringify(selectedIps)); } catch(e) {}

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

    getActiveIps() {
        const ips = Array.from(this.activeTiles.keys()).map(k => k.split('__')[0]);
        return Array.from(new Set(ips)).filter(Boolean);
    }

    showToast(msg, type = 'info', duration = 4500) {
        let toast = document.getElementById('vnc-grid-toast-el');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'vnc-grid-toast-el';
            toast.className = 'vnc-grid-toast';
            document.body.appendChild(toast);
        }
        toast.className = `vnc-grid-toast ${type}`;
        toast.innerHTML = `<span>${msg}</span>`;
        toast.style.display = 'flex';

        if (this._toastTimer) clearTimeout(this._toastTimer);
        this._toastTimer = setTimeout(() => {
            if (toast) toast.style.display = 'none';
        }, duration);
    }

    async handleBatchAction(actionType) {
        const targetIps = this.getSelectedIps();
        if (targetIps.length === 0) {
            this.showToast('⚠️ Nenhuma máquina selecionada no Grid. Marque o checkbox das máquinas desejadas.', 'error');
            return;
        }

        let actionName = '';
        let payloadAction = '';
        let extraData = {};

        switch(actionType) {
            case 'msg':
                this.openPresetMessageModal('batch');
                return;
            case 'demo':
                if (this._isDemoTransmitting) {
                    this._isDemoTransmitting = false;
                    actionName = 'Parar Transmissão da Tela';
                    payloadAction = 'parar_modo_demo';
                    const demoBtn = document.querySelector('[data-batch-action="demo"]');
                    if (demoBtn) {
                        demoBtn.classList.remove('toggle-active');
                        demoBtn.innerHTML = '📺 Transmitir';
                    }
                } else {
                    this._isDemoTransmitting = true;
                    actionName = 'Iniciar Transmissão da Tela do Professor';
                    payloadAction = 'iniciar_modo_demo';
                    const demoBtn = document.querySelector('[data-batch-action="demo"]');
                    if (demoBtn) {
                        demoBtn.classList.add('toggle-active');
                        demoBtn.innerHTML = '⏹️ Parar Transmissão';
                    }
                }
                break;
            case 'lock':
                actionName = 'Bloquear Tela com Cadeado';
                payloadAction = 'bloquear_tela_mensagem';
                extraData = { message: 'Atenção ao Professor!' };
                break;
            case 'lock-toggle': {
                // Lê o estado atual do botão toggle para decidir a ação
                const toggleBtn = this.modal.querySelector('[data-batch-action="lock-toggle"]');
                const currentlyLocked = toggleBtn && toggleBtn.dataset.locked === 'true';
                if (currentlyLocked) {
                    actionName = 'Desbloquear Tela';
                    payloadAction = 'desbloquear_tela_mensagem';
                    extraData = {};
                } else {
                    actionName = 'Bloquear Tela com Cadeado';
                    payloadAction = 'bloquear_tela_mensagem';
                    extraData = { message: 'Atenção ao Professor!' };
                }
                // O estado visual do toggle será atualizado após o envio, em runSingleTarget
                extraData._lockToggleWillLock = !currentlyLocked;
                break;
            }
            case 'stickers-toggle': {
                const stickersBtn = this.modal.querySelector('[data-batch-action="stickers-toggle"]');
                const currentlyBlocked = stickersBtn && stickersBtn.dataset.blocked === 'true';
                if (currentlyBlocked) {
                    actionName = 'Desbloquear Stickers & Perfil';
                    payloadAction = 'desbloquear_stickers';
                } else {
                    actionName = 'Bloquear Stickers & Perfil';
                    payloadAction = 'bloquear_stickers';
                }
                extraData._stickersToggleWillBlock = !currentlyBlocked;
                break;
            }
            case 'clean':
                actionName = 'Limpar Tela e Fechar Programas';
                payloadAction = 'limpar_tela';
                break;
            case 'pwd':
                const curPwd = this.getGridPassword();
                const newPassword = prompt('🔑 Alterar/Verificar Senha SSH do Laboratório:\n\nDigite a senha SSH das máquinas remotas para conexões e desbloqueio:', curPwd === 'qwe123' ? '' : curPwd);
                if (newPassword !== null && newPassword.trim()) {
                    const cleanPwd = newPassword.trim();
                    try {
                        sessionStorage.setItem('app_ssh_password', cleanPwd);
                        localStorage.setItem('app_ssh_password', cleanPwd);
                    } catch(e){}
                    this.gridPassword = cleanPwd;
                    if (window.getActivePassword) {
                        window.sessionPassword = cleanPwd;
                    }
                    this.showToast('🔑 Senha SSH atualizada com sucesso!', 'success');
                }
                return;
            case 'url':
                this.openPresetUrlModal('batch');
                return;
            case 'restart':
                actionName = 'Reiniciar';
                payloadAction = 'reiniciar';
                break;
            case 'shutdown':
                actionName = 'Desligar';
                payloadAction = 'desligar';
                break;
            default:
                return;
        }

        this.showToast(`⚡ Executando '${actionName}' em ${targetIps.length} máquinas...`, 'info', 12000);

        let activePassword = this.getGridPassword();
        let successCount = 0;
        let failCount = 0;

        const runSingleTarget = async (rawIpSpec, isRetry = false) => {
            const parsed = this.parseTargetSpec(rawIpSpec);
            const targetIp = parsed.baseIp;
            const targetDisplay = parsed.display;

            try {
                const body = {
                    ip: targetIp,
                    action: payloadAction,
                    password: activePassword,
                    display: targetDisplay,
                    target_display: targetDisplay,
                    ...extraData
                };
                const res = await fetch(`${getApiBaseUrl()}/gerenciar_atalhos_ip`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                const data = await res.json();
                if (actionType === 'lock') {
                    this.setTileLockState(rawIpSpec, true);
                } else if (actionType === 'unlock') {
                    this.setTileLockState(rawIpSpec, false);
                } else if (actionType === 'lock-toggle') {
                    this.setTileLockState(rawIpSpec, extraData._lockToggleWillLock);
                }

                if (data && data.success !== false) {
                    successCount++;
                    return true;
                } else if (!isRetry) {
                    await new Promise(r => setTimeout(r, 400));
                    return await runSingleTarget(rawIpSpec, true);
                } else {
                    failCount++;
                    return false;
                }
            } catch (err) {
                if (!isRetry) {
                    await new Promise(r => setTimeout(r, 400));
                    return await runSingleTarget(rawIpSpec, true);
                } else {
                    failCount++;
                    return false;
                }
            }
        };

        // Execução 100% simultânea em paralelo para todas as máquinas do Grid ao mesmo tempo
        await Promise.all(targetIps.map(ipSpec => runSingleTarget(ipSpec)));

        // Atualiza o visual do botão lock-toggle após execução em lote
        if (actionType === 'lock-toggle') {
            this.updateLockToggleBtns(extraData._lockToggleWillLock);
        }
        // Atualiza o visual do botão stickers-toggle após execução em lote
        if (actionType === 'stickers-toggle') {
            this.updateStickersToggleBtns(extraData._stickersToggleWillBlock);
        }

        if (failCount === 0) {
            this.showToast(`✅ '${actionName}' executado com sucesso em todas as ${successCount} máquinas!`, 'success');
            this.addLog('GRID', 'LOTE', `Ação em lote '${actionName}' concluída com sucesso em ${successCount} máquinas.`);
        } else if (failCount === targetIps.length) {
            this.addLog('GRID', 'LOTE_ERRO', `Ação em lote '${actionName}': 0 sucessos, ${failCount} falhas. Verifique a senha SSH.`);
            const newPwd = prompt(`⚠️ Falha de autenticação SSH em todas as ${targetIps.length} máquinas do Grid.\n\nDigite a senha SSH correta do laboratório para re-tentar:`, activePassword === 'qwe123' ? '' : activePassword);
            if (newPwd && newPwd.trim()) {
                const cleanPwd = newPwd.trim();
                try {
                    sessionStorage.setItem('app_ssh_password', cleanPwd);
                    localStorage.setItem('app_ssh_password', cleanPwd);
                } catch(e){}
                this.showToast(`🔑 Nova senha salva. Re-tentando '${actionName}'...`, 'info');
                return this.handleBatchAction(actionType);
            } else {
                this.showToast(`⚠️ '${actionName}': 0 sucessos, ${failCount} falhas (senha incorreta).`, 'error');
            }
        } else {
            this.showToast(`⚠️ '${actionName}': ${successCount} sucessos, ${failCount} falhas.`, 'error');
            this.addLog('GRID', 'LOTE_ERRO', `Ação em lote '${actionName}': ${successCount} sucessos, ${failCount} falhas.`);
        }
    }

    /**
     * Atualiza todos os botões lock-toggle no DOM para refletir o estado atual de bloqueio.
     * @param {boolean} isLocked - true se o estado passou para bloqueado, false para desbloqueado
     */
    updateLockToggleBtns(isLocked) {
        document.querySelectorAll('[data-batch-action="lock-toggle"]').forEach(btn => {
            btn.dataset.locked = isLocked ? 'true' : 'false';
            const iconEl = btn.querySelector('.lock-toggle-icon');
            const labelEl = btn.querySelector('.lock-toggle-label');
            if (iconEl) iconEl.textContent = isLocked ? '🔒' : '🔓';
            if (labelEl) labelEl.textContent = isLocked ? 'Desbloq' : 'Bloq';
            btn.title = isLocked
                ? 'Desbloquear Telas Selecionadas (atualmente BLOQUEADAS)'
                : 'Bloquear Telas Selecionadas (atualmente desbloqueadas)';
            if (isLocked) {
                btn.classList.add('lock-toggle-locked');
            } else {
                btn.classList.remove('lock-toggle-locked');
            }
        });
    }

    /**
     * Atualiza todos os botões stickers-toggle no DOM para refletir o estado atual de bloqueio.
     * @param {boolean} isBlocked - true se passou para bloqueado, false para desbloqueado
     */
    updateStickersToggleBtns(isBlocked) {
        document.querySelectorAll('[data-batch-action="stickers-toggle"]').forEach(btn => {
            btn.dataset.blocked = isBlocked ? 'true' : 'false';
            const iconEl = btn.querySelector('.stickers-toggle-icon');
            const labelEl = btn.querySelector('.stickers-toggle-label');
            if (iconEl) iconEl.textContent = isBlocked ? '✅' : '🚫';
            if (labelEl) labelEl.textContent = isBlocked ? 'Stickers' : 'Stickers';
            btn.title = isBlocked
                ? 'Desbloquear Stickers & Perfil (atualmente BLOQUEADOS)'
                : 'Bloquear Stickers & Perfil (atualmente desbloqueados)';
            if (isBlocked) {
                btn.classList.add('stickers-toggle-blocked');
            } else {
                btn.classList.remove('stickers-toggle-blocked');
            }
        });
    }


    getGridPassword() {
        if (this.gridPassword) return this.gridPassword;
        const storedPwd = sessionStorage.getItem('app_ssh_password') || localStorage.getItem('app_ssh_password');
        if (storedPwd) return storedPwd;

        if (typeof window.getActivePassword === 'function') {
            const pwd = window.getActivePassword();
            if (pwd && pwd !== 'qwe123') return pwd;
        }
        const urlParams = new URLSearchParams(window.location.search);
        const urlPwd = urlParams.get('password');
        if (urlPwd) return urlPwd;

        const inputPwd = document.getElementById('password')?.value;
        if (inputPwd) return inputPwd;

        return 'qwe123';
    }

    async toggleSingleTileLock(tileKey) {
        const tileData = this.activeTiles.get(tileKey);
        if (!tileData) return;

        const parsed = this.parseTargetSpec(tileKey);
        const targetIp = parsed.baseIp;
        const targetDisplay = parsed.display;
        const willLock = !tileData.isLocked;

        const actionName = willLock ? 'Bloquear Tela' : 'Desbloquear Tela';
        const payloadAction = willLock ? 'bloquear_tela_mensagem' : 'desbloquear_tela_mensagem';
        const activePassword = this.getGridPassword();

        this.showToast(`⚡ ${actionName} em ${targetIp}...`, 'info', 4000);

        try {
            const body = {
                ip: targetIp,
                action: payloadAction,
                password: activePassword,
                display: targetDisplay,
                target_display: targetDisplay,
                message: 'Atenção ao Professor!'
            };
            const res = await fetch(`${getApiBaseUrl()}/gerenciar_atalhos_ip`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            const data = await res.json();
            // Sempre atualiza a interface visual local do tile para desbloquear imediatamente se o usuário solicitou
            this.setTileLockState(tileKey, willLock);

            if (data && data.success !== false) {
                this.showToast(`✅ ${targetIp} ${willLock ? 'bloqueado 🔒' : 'desbloqueado 🔓'} com sucesso!`, 'success');
                this.addLog(targetIp, willLock ? 'LOCKED' : 'UNLOCKED', `Máquina ${targetIp} ${willLock ? 'bloqueada' : 'desbloqueada'} individualmente.`);
            } else {
                this.showToast(`⚠️ Comando enviado para ${targetIp}. Status: ${data ? (data.message || 'Alerta') : 'Aviso'}.`, 'warning');
                this.addLog(targetIp, 'LOCK_WARNING', `Resposta backend: ${data ? data.message : 'Aviso'}`);
            }
        } catch (err) {
            // Em caso de erro de rede, garante a alteração visual local para desbloqueio
            this.setTileLockState(tileKey, willLock);
            this.showToast(`⚠️ Estado alterado localmente. Erro de rede ao contatar ${targetIp}.`, 'warning');
            this.addLog(targetIp, 'LOCK_ERROR', `Erro de rede: ${err.message}`);
        }
    }

    setTileLockState(ipSpec, isLocked) {
        this.activeTiles.forEach((tileData, tileKey) => {
            const parsedTile = this.parseTargetSpec(tileKey);
            const parsedTarget = this.parseTargetSpec(ipSpec);

            if (parsedTile.canonicalKey === parsedTarget.canonicalKey || tileData.ip === ipSpec || parsedTile.baseIp === ipSpec) {
                const idSlug = tileKey.replace(/[\/\.:]/g, '-');
                const infoEl = tileData.element.querySelector('.vnc-tile-info');
                const bodyEl = tileData.element.querySelector('.vnc-tile-body');
                let lockBadge = tileData.element.querySelector(`#lock-badge-${idSlug}`);
                let lockOverlay = tileData.element.querySelector(`#lock-overlay-${idSlug}`);
                let lockBtn = tileData.element.querySelector(`#btn-lock-${idSlug}`);
                let lockIconState = tileData.element.querySelector(`#lock-icon-state-${idSlug}`);

                tileData.isLocked = isLocked;

                if (isLocked) {
                    if (lockBtn) {
                        lockBtn.title = `Bloqueado (Clique para Desbloquear 🔓)`;
                        lockBtn.classList.add('active-locked');
                    }
                    if (lockIconState) lockIconState.textContent = '🔒';

                    if (!lockBadge) {
                        lockBadge = document.createElement('span');
                        lockBadge.id = `lock-badge-${idSlug}`;
                        lockBadge.className = 'vnc-tile-lock-badge';
                        lockBadge.innerHTML = '🔒 Bloqueado';
                        lockBadge.style.cssText = 'background:#991b1b;color:#fef2f2;font-size:0.68rem;padding:2px 5px;border-radius:4px;font-weight:700;margin-left:4px;display:inline-flex;align-items:center;gap:2px;box-shadow:0 1px 3px rgba(0,0,0,0.3);';
                        if (infoEl) infoEl.appendChild(lockBadge);
                    }
                    if (!lockOverlay && bodyEl) {
                        const targetIp = tileData.baseIp || tileData.ip || parsedTarget.baseIp;
                        const alias = this.deviceAliases[targetIp];
                        const hostname = this.deviceHostnames[targetIp];
                        const displayName = alias || hostname || targetIp;
                        const ipSub = (alias || hostname) ? ` (${targetIp})` : '';

                        lockOverlay = document.createElement('div');
                        lockOverlay.id = `lock-overlay-${idSlug}`;
                        lockOverlay.className = 'vnc-tile-lock-overlay';
                        lockOverlay.innerHTML = `
                            <div class="vnc-tile-lock-holo-ring"></div>
                            <div class="vnc-tile-lock-icon">🔒</div>
                            <div class="vnc-tile-lock-machine" style="font-size:1.05rem;font-weight:800;color:#38bdf8;margin-bottom:2px;letter-spacing:-0.2px;text-shadow:0 0 10px rgba(56,189,248,0.4);position:relative;z-index:2;">🖥️ ${displayName}${ipSub}</div>
                            <div class="vnc-tile-lock-title" style="position:relative;z-index:2;">🤫 TELA BLOQUEADA</div>
                            <div class="vnc-tile-lock-sub" style="position:relative;z-index:2;">Teclado e Mouse Bloqueados</div>
                            <button type="button" class="vnc-tile-unlock-btn" style="position:relative;z-index:2;" onclick="window.vncGridManager && window.vncGridManager.toggleSingleTileLock('${tileKey}')">
                                🔓 Desbloquear Agora
                            </button>
                        `;
                        bodyEl.appendChild(lockOverlay);
                    }
                    tileData.element.classList.add('tile-locked');
                } else {
                    if (lockBtn) {
                        lockBtn.title = `Desbloqueado (Clique para Bloquear 🔒)`;
                        lockBtn.classList.remove('active-locked');
                    }
                    if (lockIconState) lockIconState.textContent = '🔓';

                    tileData.element.querySelectorAll('.vnc-tile-lock-badge').forEach(el => el.remove());
                    tileData.element.querySelectorAll('.vnc-tile-lock-overlay').forEach(el => el.remove());
                    tileData.element.classList.remove('tile-locked');
                }
            }
        });
    }

    addLog(ip, status, message) {
        if (!this.eventLogs) this.eventLogs = [];
        const timestamp = new Date().toLocaleTimeString();
        const entry = `[${timestamp}] [${ip || 'GRID'}] [${String(status).toUpperCase()}] ${message}`;
        this.eventLogs.push(entry);
        if (this.eventLogs.length > 400) this.eventLogs.shift();
    }

    async copyLogsToClipboard() {
        const activeIps = this.getActiveIps();
        const nowStr = new Date().toLocaleString();
        
        let formattedText = `=== LOG DE MONITORAMENTO EM GRID VNC ===\n`;
        formattedText += `Data/Hora: ${nowStr}\n`;
        formattedText += `Telas Ativas (${activeIps.length}): ${activeIps.join(', ') || 'Nenhuma'}\n`;
        formattedText += `========================================\n\n`;

        if (!this.eventLogs || this.eventLogs.length === 0) {
            formattedText += `[INFO] Nenhum evento ou erro registrado até o momento.\n`;
        } else {
            formattedText += this.eventLogs.join('\n') + `\n`;
        }

        formattedText += `\n========================================\n`;

        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(formattedText);
            } else {
                const textarea = document.createElement('textarea');
                textarea.value = formattedText;
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand('copy');
                document.body.removeChild(textarea);
            }
            this.showToast('📋 Log do Grid copiado para a área de transferência! Cole aqui no chat.', 'success', 5000);
        } catch (err) {
            console.error("Erro ao copiar log:", err);
            this.showToast('⚠️ Falha ao copiar log automaticamente.', 'error');
        }
    }

    // ===== 💬 GERENCIADOR DE MENSAGENS PRÉ-CADASTRADAS =====
    getPresetMessages() {
        try {
            const saved = localStorage.getItem('vnc_preset_messages');
            if (saved) return JSON.parse(saved);
        } catch(e){}
        return [
            "📢 Atenção do Professor! Olhe para a frente.",
            "📖 Iniciando a aula. Por favor, abram o material de estudo.",
            "⏳ Restam 5 minutos para finalizar a atividade!",
            "🤫 Silêncio no laboratório, por favor.",
            "🚀 Parabéns pelo excelente trabalho!"
        ];
    }

    savePresetMessages(list) {
        try { localStorage.setItem('vnc_preset_messages', JSON.stringify(list)); } catch(e){}
    }

    openPresetMessageModal(targetMode = 'batch', targetSpec = null, displayName = '') {
        const modal = document.getElementById('vnc-grid-preset-msg-modal');
        const desc = document.getElementById('preset-msg-target-desc');
        const listContainer = document.getElementById('vnc-preset-msg-list');
        const newMsgInput = document.getElementById('vnc-new-preset-msg-input');
        const customMsgInput = document.getElementById('vnc-custom-msg-input');
        const addBtn = document.getElementById('vnc-add-preset-msg-btn');
        const sendBtn = document.getElementById('vnc-preset-msg-send');
        const closeBtn = document.getElementById('vnc-preset-msg-close');
        const cancelBtn = document.getElementById('vnc-preset-msg-cancel');

        if (!modal || !listContainer) return;

        const targetIps = targetMode === 'batch' ? this.getSelectedIps() : [targetSpec];
        if (desc) {
            desc.textContent = targetMode === 'batch' 
                ? `Enviar mensagem para ${targetIps.length} máquina(s) selecionada(s) no Grid`
                : `Enviar mensagem individual para ${displayName || targetSpec}`;
        }

        let presets = this.getPresetMessages();

        const renderList = () => {
            listContainer.innerHTML = '';
            presets.forEach((msgText, idx) => {
                const item = document.createElement('div');
                item.style.cssText = `
                    display:flex; align-items:center; justify-content:space-between; gap:10px;
                    padding:8px 12px; background:#1e293b; border:1px solid rgba(255,255,255,0.06);
                    border-radius:8px; cursor:pointer; transition:all 0.15s ease;
                `;
                item.innerHTML = `
                    <span style="font-size:0.82rem; color:#f8fafc; font-weight:600; flex:1;">${msgText}</span>
                    <button type="button" style="background:transparent; border:none; color:#ef4444; cursor:pointer; font-size:0.85rem;" title="Excluir pré-definição">&times;</button>
                `;
                item.onclick = (e) => {
                    if (e.target.tagName === 'BUTTON') {
                        e.stopPropagation();
                        presets.splice(idx, 1);
                        this.savePresetMessages(presets);
                        renderList();
                    } else {
                        if (customMsgInput) customMsgInput.value = msgText;
                        listContainer.querySelectorAll('div').forEach(d => d.style.borderColor = 'rgba(255,255,255,0.06)');
                        item.style.borderColor = '#6366f1';
                    }
                };
                listContainer.appendChild(item);
            });
        };

        renderList();
        if (customMsgInput) customMsgInput.value = presets[0] || '';

        if (addBtn) {
            addBtn.onclick = () => {
                const val = newMsgInput ? newMsgInput.value.trim() : '';
                if (val) {
                    presets.push(val);
                    this.savePresetMessages(presets);
                    if (newMsgInput) newMsgInput.value = '';
                    renderList();
                    this.showToast('💬 Nova mensagem cadastrada!', 'success', 2000);
                }
            };
        }

        const closeModal = () => modal.classList.add('hidden');
        if (closeBtn) closeBtn.onclick = closeModal;
        if (cancelBtn) cancelBtn.onclick = closeModal;

        if (sendBtn) {
            sendBtn.onclick = async () => {
                const msgToSend = customMsgInput ? customMsgInput.value.trim() : '';
                if (!msgToSend) {
                    this.showToast('⚠️ Digite ou selecione uma mensagem.', 'error');
                    return;
                }
                closeModal();

                if (targetMode === 'batch') {
                    this.showToast(`⏳ Enviando mensagem para ${targetIps.length} máquinas em paralelo...`, 'info', 2500);
                    let successCount = 0;
                    await Promise.all(targetIps.map(async (rawIpSpec) => {
                        const parsed = this.parseTargetSpec(rawIpSpec);
                        const body = {
                            ip: parsed.baseIp,
                            action: 'enviar_mensagem',
                            password: this.getGridPassword(),
                            display: parsed.display,
                            target_display: parsed.display,
                            message: msgToSend
                        };
                        try {
                            const res = await fetch(`${getApiBaseUrl()}/gerenciar_atalhos_ip`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(body)
                            });
                            const data = await res.json();
                            if (data && data.success !== false) successCount++;
                        } catch(e){}
                    }));
                    this.showToast(`✅ Mensagem enviada simultaneamente para ${successCount} máquinas!`, 'success', 3500);
                } else {
                    this.executeSingleCommand(targetSpec, 'bloquear_tela_mensagem', `Enviar Mensagem`, { message: msgToSend });
                }
            };
        }

        modal.classList.remove('hidden');
    }

    // ===== 🌐 GERENCIADOR DE URLS / SITES PRÉ-CADASTRO (Sincronizado com backend físico preset_urls.json) =====
    async fetchPresetUrls() {
        try {
            const res = await fetch(`${getApiBaseUrl()}/api/preset-urls`);
            if (res.ok) {
                const data = await res.json();
                if (data && Array.isArray(data.urls) && data.urls.length > 0) {
                    try { localStorage.setItem('vnc_preset_urls', JSON.stringify(data.urls)); } catch(e){}
                    return data.urls;
                }
            }
        } catch(e) {
            console.warn('[Grid VNC] Falha ao consultar /api/preset-urls, usando cache:', e);
        }
        return this.getPresetUrls();
    }

    getPresetUrls() {
        try {
            const saved = localStorage.getItem('vnc_preset_urls');
            if (saved) return JSON.parse(saved);
        } catch(e){}
        return [
            "https://google.com",
            "https://wikipedia.org",
            "https://github.com",
            "https://scratch.mit.edu",
            "https://phet.colorado.edu"
        ];
    }

    async savePresetUrls(list) {
        // 1. Atualiza cache local instantâneo
        try { localStorage.setItem('vnc_preset_urls', JSON.stringify(list)); } catch(e){}
        
        // 2. Grava fisicamente no arquivo do backend
        try {
            await fetch(`${getApiBaseUrl()}/api/preset-urls`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ urls: list })
            });
        } catch(e) {
            console.warn('[Grid VNC] Falha ao persistir preset_urls.json no backend:', e);
        }
    }

    async openPresetUrlModal(targetMode = 'batch', targetSpec = null, displayName = '') {
        const modal = document.getElementById('vnc-grid-preset-url-modal');
        const desc = document.getElementById('preset-url-target-desc');
        const listContainer = document.getElementById('vnc-preset-url-list');
        const newUrlInput = document.getElementById('vnc-new-preset-url-input');
        const customUrlInput = document.getElementById('vnc-custom-url-input');
        const addBtn = document.getElementById('vnc-add-preset-url-btn');
        const sendBtn = document.getElementById('vnc-preset-url-send');
        const closeBtn = document.getElementById('vnc-preset-url-close');
        const cancelBtn = document.getElementById('vnc-preset-url-cancel');

        if (!modal || !listContainer) return;

        const targetIps = targetMode === 'batch' ? this.getSelectedIps() : [targetSpec];
        if (desc) {
            desc.textContent = targetMode === 'batch' 
                ? `Abrir site nas ${targetIps.length} máquina(s) selecionada(s) no Grid`
                : `Abrir site individualmente em ${displayName || targetSpec}`;
        }

        // Carrega sempre a versão mais recente salva no arquivo do servidor
        let presets = await this.fetchPresetUrls();

        const renderList = () => {
            listContainer.innerHTML = '';
            presets.forEach((urlText, idx) => {
                const item = document.createElement('div');
                item.style.cssText = `
                    display:flex; align-items:center; justify-space-between; gap:10px;
                    padding:8px 12px; background:#1e293b; border:1px solid rgba(255,255,255,0.06);
                    border-radius:8px; cursor:pointer; transition:all 0.15s ease;
                `;
                item.innerHTML = `
                    <span style="font-size:0.82rem; color:#38bdf8; font-weight:600; flex:1; font-family:'JetBrains Mono',monospace;">${urlText}</span>
                    <button type="button" style="background:transparent; border:none; color:#ef4444; cursor:pointer; font-size:0.85rem;" title="Excluir pré-definição">&times;</button>
                `;
                item.onclick = async (e) => {
                    if (e.target.tagName === 'BUTTON') {
                        e.stopPropagation();
                        presets.splice(idx, 1);
                        await this.savePresetUrls(presets);
                        renderList();
                    } else {
                        if (customUrlInput) customUrlInput.value = urlText;
                        listContainer.querySelectorAll('div').forEach(d => d.style.borderColor = 'rgba(255,255,255,0.06)');
                        item.style.borderColor = '#0284c7';
                    }
                };
                listContainer.appendChild(item);
            });
        };

        renderList();
        if (customUrlInput) customUrlInput.value = presets[0] || 'https://google.com';

        if (addBtn) {
            addBtn.onclick = async () => {
                let val = newUrlInput ? newUrlInput.value.trim() : '';
                if (val) {
                    if (!val.startsWith('http://') && !val.startsWith('https://')) {
                        val = 'https://' + val;
                    }
                    if (!presets.includes(val)) {
                        presets.push(val);
                        await this.savePresetUrls(presets);
                    }
                    if (newUrlInput) newUrlInput.value = '';
                    renderList();
                    this.showToast('🌐 Nova URL cadastrada no servidor!', 'success', 2000);
                }
            };
        }

        const closeModal = () => modal.classList.add('hidden');
        if (closeBtn) closeBtn.onclick = closeModal;
        if (cancelBtn) cancelBtn.onclick = closeModal;

        if (sendBtn) {
            sendBtn.onclick = async () => {
                let urlToSend = customUrlInput ? customUrlInput.value.trim() : '';
                if (!urlToSend) {
                    this.showToast('⚠️ Digite ou selecione uma URL.', 'error');
                    return;
                }
                if (!urlToSend.startsWith('http://') && !urlToSend.startsWith('https://')) {
                    urlToSend = 'https://' + urlToSend;
                }
                closeModal();

                if (targetMode === 'batch') {
                    this.showToast(`⏳ Abrindo site em ${targetIps.length} máquinas em paralelo...`, 'info', 2500);
                    let successCount = 0;
                    await Promise.all(targetIps.map(async (rawIpSpec) => {
                        const parsed = this.parseTargetSpec(rawIpSpec);
                        const body = {
                            ip: parsed.baseIp,
                            action: 'abrir_site',
                            password: this.getGridPassword(),
                            display: parsed.display,
                            target_display: parsed.display,
                            url: urlToSend
                        };
                        try {
                            const res = await fetch(`${getApiBaseUrl()}/gerenciar_atalhos_ip`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(body)
                            });
                            const data = await res.json();
                            if (data && data.success !== false) successCount++;
                        } catch(e){}
                    }));
                    this.showToast(`✅ URL aberta simultaneamente em ${successCount} máquinas!`, 'success', 3500);
                } else {
                    this.executeSingleCommand(targetSpec, 'abrir_site', `Abrir Site`, { url: urlToSend });
                }
            };
        }

        modal.classList.remove('hidden');
    }

    /**
     * Sistema Global de Notificações Toast Glassmorphism
     * @param {string} message - Mensagem a ser exibida
     * @param {'info'|'success'|'warning'|'error'} type - Tipo da notificação
     * @param {number} duration - Duração em ms (padrão 4000)
     */
    showToast(message, type = 'info', duration = 4000) {
        if (typeof window.showAppToast === 'function') {
            window.showAppToast(message, type, duration);
        } else {
            console.log(`[Toast ${type.toUpperCase()}] ${message}`);
        }
    }
}

/**
 * Função Global para Notificações Toast Estilo Glassmorphism com Barra de Tempo
 */
window.showAppToast = function(message, type = 'info', duration = 4000) {
    let container = document.getElementById('app-toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'app-toast-container';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `app-toast ${type}`;

    let iconText = 'ℹ️';
    let titleText = 'Informação';
    if (type === 'success') { iconText = '✅'; titleText = 'Sucesso'; }
    else if (type === 'error') { iconText = '🛑'; titleText = 'Erro'; }
    else if (type === 'warning') { iconText = '⚠️'; titleText = 'Atenção'; }

    toast.innerHTML = `
        <div class="app-toast-icon">${iconText}</div>
        <div class="app-toast-content">
            <div class="app-toast-title">${titleText}</div>
            <div class="app-toast-msg">${message}</div>
        </div>
        <button type="button" class="app-toast-close" title="Fechar">&times;</button>
        <div class="app-toast-progress" style="animation-duration: ${duration}ms;"></div>
    `;

    container.appendChild(toast);

    // Animação de entrada
    requestAnimationFrame(() => {
        toast.classList.add('show');
    });

    let dismissTimer = null;
    const dismiss = () => {
        if (dismissTimer) clearTimeout(dismissTimer);
        toast.classList.remove('show');
        toast.classList.add('hide');
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 400);
    };

    dismissTimer = setTimeout(dismiss, duration);

    const closeBtn = toast.querySelector('.app-toast-close');
    if (closeBtn) {
        closeBtn.onclick = (e) => {
            e.stopPropagation();
            dismiss();
        };
    }
};

// Instância global do gerenciador de Grid VNC
window.vncGridManager = new VNCGridManager();

window.openVNCGrid = (ipsList = []) => {
    if (window.vncGridManager) {
        window.vncGridManager.openGrid(ipsList);
    }
};
