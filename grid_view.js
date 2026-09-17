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
        this.targetFps = 1.5;
        this.globalGridFps = 1.5; // Adaptive FPS padrão: 1.5 FPS para miniaturas (Reduz em até 95% o tráfego de rede)
        this.globalGridQuality = 3; // Qualidade JPEG moderada para thumbnails
        this.globalGridCompression = 7; // Compressão Tight / zlib alta para miniaturas
        this._isAllPaused = false;
        this.eventLogs = []; // Histórico de logs/eventos do Grid na sessão
        this.connectionQueue = []; // Fila de conexões por lote (throttling anti-OOM)
        this.activeConnectingCount = 0;
        this.MAX_CONCURRENT_CONNECTS = 16; // Conexões simultâneas máximas no backend
        this.modal = null;
        this.container = null;
        this.statusCountSpan = null;
        this.domInitialized = false;

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.initDOM());
        } else {
            this.initDOM();
        }
    }

    initDOM() {
        if (this.domInitialized && this.container) return;

        this.modal = document.getElementById('vnc-grid-modal') || document.querySelector('.standalone-grid-wrapper') || document.body;
        this.container = document.getElementById('vnc-grid-container');
        this.statusCountSpan = document.getElementById('vnc-grid-count');

        if (!this.container) return;
        this.domInitialized = true;

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

        // Select de Adaptive FPS (Taxa de Quadros Adaptativa do Grid)
        const fpsSelects = this.modal.querySelectorAll('#vnc-grid-fps-select');
        fpsSelects.forEach(select => {
            select.addEventListener('change', (e) => {
                const fps = parseFloat(e.target.value) || 1.5;
                this.setGlobalFps(fps);
            });
        });

        // Botões de Filtro de Status (Todas / Online / Offline)
        const filterBtns = this.modal.querySelectorAll('[data-grid-filter]');
        filterBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                filterBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const filterType = btn.getAttribute('data-grid-filter');
                this.applyFilter(filterType);
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

        // Oculta menu de contexto ao clicar fora ou rolar
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

        // Virtualização do Grid (IntersectionObserver) para economia inteligente de CPU e Banda
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
                        if (tileData.rfb && !this._isAllPaused) {
                            tileData.rfb.paused = false;
                        }
                    } else {
                        tileEl.classList.add('tile-offscreen');
                        if (tileData.rfb) {
                            // Pausa o envio de frames para tiles fora da área visível do scroll
                            tileData.rfb.paused = true;
                        }
                    }
                });
            }, {
                root: rootEl,
                rootMargin: '100px 0px',
                threshold: 0.01
            });
        }

        // Listener de visibilidade da aba do navegador (pausa/retomada de streaming com 0 bps em background)
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this.pauseAllTiles();
            } else {
                this.resumeVisibleTiles();
            }
        });
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

    setGlobalFps(fps = 1.5) {
        this.globalGridFps = fps;
        let quality = 3;
        let compression = 7;
        let badgeLabel = '🌱 1.5 FPS (Eco Banda)';
        let badgeClass = 'vnc-bandwidth-badge';

        if (fps >= 15) {
            quality = 6;
            compression = 2;
            badgeLabel = '🔥 15 FPS (Fluido / +Banda)';
            badgeClass = 'vnc-bandwidth-badge fluid';
        } else if (fps >= 5) {
            quality = 4;
            compression = 4;
            badgeLabel = '🚀 5 FPS (Rápido)';
            badgeClass = 'vnc-bandwidth-badge fast';
        } else if (fps >= 3) {
            quality = 3;
            compression = 6;
            badgeLabel = '⚡ 3 FPS (Médio)';
            badgeClass = 'vnc-bandwidth-badge';
        }

        this.globalGridQuality = quality;
        this.globalGridCompression = compression;

        // Sincroniza selects de FPS
        document.querySelectorAll('#vnc-grid-fps-select').forEach(sel => {
            if (sel.value !== String(fps)) sel.value = String(fps);
        });

        // Atualiza badge visual no cabeçalho
        const badge = document.getElementById('vnc-grid-bandwidth-badge');
        if (badge) {
            badge.textContent = badgeLabel;
            badge.className = badgeClass;
        }

        // Aplica para todos os tiles de miniatura ativos
        this.activeTiles.forEach((tileData) => {
            if (tileData.rfb && !tileData.isFocused) {
                tileData.rfb.targetFps = fps;
                tileData.rfb.qualityLevel = quality;
                tileData.rfb.compressionLevel = compression;
            }
        });
    }

    pauseAllTiles() {
        this._isAllPaused = true;
        this.activeTiles.forEach((tileData) => {
            if (tileData.rfb) {
                tileData.rfb.paused = true;
            }
        });
    }

    resumeVisibleTiles() {
        this._isAllPaused = false;
        this.activeTiles.forEach((tileData) => {
            if (tileData.rfb && tileData.isVisible !== false && !tileData.isManuallyClosed) {
                tileData.rfb.paused = false;
            }
        });
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
        if (!this.domInitialized || !this.container) this.initDOM();
        if (!this.modal) return;

        this.modal.classList.remove('hidden');
        this.resumeVisibleTiles();

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

    getAvatarGradient(str) {
        const gradients = [
            'linear-gradient(135deg, #3b82f6, #1d4ed8)', // Blue
            'linear-gradient(135deg, #10b981, #047857)', // Emerald
            'linear-gradient(135deg, #8b5cf6, #6d28d9)', // Purple
            'linear-gradient(135deg, #f59e0b, #b45309)', // Amber
            'linear-gradient(135deg, #ec4899, #be185d)', // Pink
            'linear-gradient(135deg, #06b6d4, #0e7490)', // Cyan
            'linear-gradient(135deg, #f43f5e, #be123c)', // Rose
            'linear-gradient(135deg, #6366f1, #4338ca)'  // Indigo
        ];
        let hash = 0;
        const text = str || 'PC';
        for (let i = 0; i < text.length; i++) {
            hash = text.charCodeAt(i) + ((hash << 5) - hash);
        }
        const index = Math.abs(hash) % gradients.length;
        return gradients[index];
    }

    getAvatarInitial(name, fallbackIp) {
        if (name && typeof name === 'string' && name.trim()) {
            const clean = name.trim();
            if (clean.includes('-')) {
                const parts = clean.split('-');
                const student = parts[parts.length - 1].trim();
                if (student) return student.charAt(0).toUpperCase();
            }
            const words = clean.split(/\s+/);
            if (words.length > 1 && !words[0].toLowerCase().startsWith('pc')) {
                return (words[0][0] + words[1][0]).toUpperCase();
            }
            if (clean.toLowerCase().startsWith('pc') && words.length > 1) {
                return words[1].substring(0, 2).toUpperCase();
            }
            return clean.substring(0, 2).toUpperCase();
        }
        const octet = fallbackIp ? fallbackIp.split('.').pop() : '';
        return octet ? octet.padStart(2, '0').slice(-2) : 'PC';
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
        const displayName = alias || hostname || `PC ${shortIp.replace('.', '')}`;
        const avatarGradient = this.getAvatarGradient(alias || hostname || baseIp);
        const avatarInitial = this.getAvatarInitial(alias || hostname, baseIp);

        const tileEl = document.createElement('div');
        tileEl.className = 'vnc-tile';
        tileEl.id = `vnc-tile-${idSlug}`;
        tileEl.innerHTML = `
            <!-- Cabeçalho Consolidado Fixo: Seleção + Status Dot + Avatar + Nome/Apelido + Ações -->
            <div class="vnc-tile-header" draggable="false">
                <div class="vnc-tile-info">
                    <input type="checkbox" class="vnc-tile-checkbox" id="cb-${idSlug}" checked title="Selecionar máquina para ações em lote" />
                    <div class="vnc-student-badge" id="student-badge-${idSlug}" title="Clique para renomear este computador (${titleTooltip})">
                        <span class="vnc-pulse-dot connecting" id="pulse-dot-${idSlug}" title="Status da conexão: Conectando"></span>
                        <div class="vnc-student-avatar" id="avatar-${idSlug}" style="background:${avatarGradient};">
                            ${avatarInitial}
                        </div>
                        <span class="vnc-student-name" id="student-name-${idSlug}">${displayName}${displayLabel}</span>
                        <span class="vnc-student-ip-short" id="ip-short-${idSlug}">(${shortIp})</span>
                        <span class="vnc-edit-name-hint" title="Renomear máquina">✏️</span>
                    </div>
                </div>
                <div class="vnc-tile-actions">
                    <button type="button" class="vnc-tile-btn lock-btn" title="Bloquear / Desbloquear Tela" id="btn-lock-${idSlug}">
                        <span id="lock-icon-state-${idSlug}" style="font-size:0.85rem;line-height:1;">🔓</span>
                    </button>
                    <button type="button" class="vnc-tile-btn expand-btn" title="Expandir VNC em Tela Cheia (ou Duplo Clique)" id="btn-expand-${idSlug}">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg>
                    </button>
                    <button type="button" class="vnc-tile-btn close-btn" title="Ocultar do Grid" id="btn-close-${idSlug}">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                    </button>
                </div>
            </div>

            <!-- Corpo: canvas VNC (100% da área sem obstrução de rodapé) -->
            <div class="vnc-tile-body">
                <div class="vnc-tile-overlay" id="overlay-${idSlug}">
                    <div class="vnc-tile-spinner"></div>
                    <div class="vnc-tile-status-text" id="status-text-${idSlug}">Iniciando VNC em ${baseIp}${targetDisplay ? ' ' + targetDisplay : ''}...</div>
                </div>
                <div class="vnc-tile-canvas" id="canvas-container-${idSlug}"></div>

                <!-- Hint de duplo clique (aparece no hover, estilo Veyon) -->
                <div class="vnc-dblclick-hint">
                    <span class="vnc-dblclick-icon">🖥️</span>
                    <span class="vnc-dblclick-text">Duplo clique para controlar</span>
                </div>
            </div>
        `;

        this.container.appendChild(tileEl);
        this.updateCount();

        // Vincula clique no badge consolidado do cabeçalho para renomear em 1 clique
        const studentBadge = tileEl.querySelector(`#student-badge-${idSlug}`);
        if (studentBadge) {
            studentBadge.onclick = (e) => {
                e.stopPropagation();
                this.openRenameModal(baseIp, this.deviceAliases[baseIp] || this.deviceHostnames[baseIp] || '');
            };
        }

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
            isPeripheralsLocked: false,
            loggedUser: '',
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

        // 🖱️ Bloquear / Desbloquear Teclado e Mouse do Aluno
        const btnPeripherals = tileEl.querySelector(`#btn-peripherals-${idSlug}`);
        if (btnPeripherals) {
            btnPeripherals.onclick = async (e) => {
                e.stopPropagation();
                const willLock = !tileData.isPeripheralsLocked;
                const action = willLock ? 'desativar_perifericos' : 'ativar_perifericos';
                const actionName = willLock ? 'Bloquear Mouse & Teclado' : 'Desbloquear Mouse & Teclado';
                const ok = await this.executeSingleCommand(tileKey, action, actionName, {
                    target_user: tileData.loggedUser || ''
                });
                if (ok) {
                    tileData.isPeripheralsLocked = willLock;
                    btnPeripherals.classList.toggle('active-locked', willLock);
                    const iconSpan = btnPeripherals.querySelector(`#peripherals-icon-state-${idSlug}`);
                    if (iconSpan) iconSpan.textContent = willLock ? '🚫' : '🖱️';
                    btnPeripherals.title = willLock ? 'Teclado e Mouse BLOQUEADOS (Clique para Ativar 🖱️)' : 'Teclado e Mouse Ativos (Clique para Bloquear 🚫)';
                }
            };
        }

        // 🧹 Fechar Janelas e Programas Abertos
        const btnClean = tileEl.querySelector(`#btn-clean-${idSlug}`);
        if (btnClean) {
            btnClean.onclick = async (e) => {
                e.stopPropagation();
                await this.executeSingleCommand(tileKey, 'limpar_tela', `Fechar Janelas de ${displayName}`, {
                    target_user: tileData.loggedUser || ''
                });
            };
        }

        // 🚪 Deslogar Navegadores & Contas
        const btnLogoutBrowser = tileEl.querySelector(`#btn-logout-browser-${idSlug}`);
        if (btnLogoutBrowser) {
            btnLogoutBrowser.onclick = async (e) => {
                e.stopPropagation();
                await this.executeSingleCommand(tileKey, 'deslogar_navegadores', `Deslogar Navegadores em ${displayName}`, {
                    target_user: tileData.loggedUser || ''
                });
            };
        }

        // 🔄 Reiniciar Computador do Aluno
        const btnReboot = tileEl.querySelector(`#btn-reboot-${idSlug}`);
        if (btnReboot) {
            btnReboot.onclick = async (e) => {
                e.stopPropagation();
                if (confirm(`Deseja realmente reiniciar o computador ${displayName} (${baseIp})?`)) {
                    await this.executeSingleCommand(tileKey, 'reiniciar', `Reiniciar ${displayName}`);
                }
            };
        }

        const btnCAD = tileEl.querySelector(`#btn-cad-${idSlug}`);
        if (btnCAD) {
            btnCAD.onclick = (e) => {
                e.stopPropagation();
                this.sendSingleCtrlAltDel(tileKey);
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

            // Pausa streams do grid em segundo plano para dedicar 100% de banda ao VNC focado
            this.pauseAllTiles();

            window.openWebVNC(baseIp, targetDisplay);

            const vncDesktopModal = document.getElementById('vnc-desktop-modal');
            if (vncDesktopModal) {
                const restoreGrid = (mutations) => {
                    for (const m of mutations) {
                        if (m.attributeName === 'class' && vncDesktopModal.classList.contains('hidden')) {
                            if (gridModal) gridModal.style.display = '';
                            // Retoma streams das miniaturas visíveis na volta ao Grid
                            this.resumeVisibleTiles();
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
        bindCtxItem('ctx-alias', () => {
            this.openRenameModal(baseIp, this.deviceAliases[baseIp] || this.deviceHostnames[baseIp] || '');
        });
        bindCtxItem('ctx-silence', () => {
            this.executeSingleCommand(tileKey, 'pedir_silencio', `Pedir Silêncio para ${displayName}`);
        });
        bindCtxItem('ctx-voice', () => {
            this.openTtsVoiceModal('single', tileKey, displayName);
        });
        bindCtxItem('ctx-demo', () => {
            this.executeSingleCommand(tileKey, 'iniciar_modo_demo', `Transmitir Tela para ${displayName}`);
        });
        bindCtxItem('ctx-lock', () => { if (btnLock) btnLock.click(); });
        bindCtxItem('ctx-peripherals', () => {
            const btnP = tileData.element ? tileData.element.querySelector(`[id^="btn-peripherals-"]`) : null;
            if (btnP) btnP.click();
            else this.executeSingleCommand(tileKey, 'desativar_perifericos', `Bloquear Periféricos de ${displayName}`);
        });
        bindCtxItem('ctx-clean', () => {
            this.executeSingleCommand(tileKey, 'limpar_tela', `Fechar Janelas de ${displayName}`, {
                target_user: tileData.loggedUser || ''
            });
        });
        bindCtxItem('ctx-logout-browsers', () => {
            this.executeSingleCommand(tileKey, 'deslogar_navegadores', `Deslogar Navegadores em ${displayName}`, {
                target_user: tileData.loggedUser || ''
            });
        });
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

    openRenameModal(baseIp, currentAlias = '') {
        const modal = document.getElementById('vnc-grid-alias-modal');
        const desc = document.getElementById('vnc-alias-modal-ip-desc');
        const input = document.getElementById('vnc-alias-modal-input');
        const preview = document.getElementById('vnc-alias-avatar-preview');
        const suggestionsBox = document.getElementById('vnc-alias-quick-suggestions');
        const saveBtn = document.getElementById('vnc-alias-modal-save');
        const clearBtn = document.getElementById('vnc-alias-modal-clear');
        const cancelBtn = document.getElementById('vnc-alias-modal-cancel');
        const closeBtn = document.getElementById('vnc-alias-modal-close');

        if (!modal || !input) return;

        const lastOctet = baseIp.split('.').pop() || '01';
        const paddedOctet = lastOctet.padStart(2, '0');

        if (desc) desc.textContent = `Endereço IP: ${baseIp}`;
        input.value = currentAlias || '';

        const updateModalPreview = () => {
            const val = input.value.trim();
            const grad = this.getAvatarGradient(val || baseIp);
            const init = this.getAvatarInitial(val, baseIp);
            if (preview) {
                preview.style.background = grad;
                preview.textContent = init;
            }
        };

        updateModalPreview();
        input.oninput = updateModalPreview;

        // Gera sugestões rápidas
        if (suggestionsBox) {
            suggestionsBox.innerHTML = '';
            const suggestions = [
                `PC ${paddedOctet}`,
                `PC ${paddedOctet} - Aluno`,
                `Bancada ${paddedOctet}`,
                `Aluno ${paddedOctet}`,
                `Notebook ${paddedOctet}`,
                `Professor`
            ];
            suggestions.forEach(sug => {
                const chip = document.createElement('button');
                chip.type = 'button';
                chip.className = 'vnc-alias-quick-chip';
                chip.textContent = sug;
                chip.onclick = () => {
                    input.value = sug;
                    updateModalPreview();
                    input.focus();
                };
                suggestionsBox.appendChild(chip);
            });
        }

        const closeModal = () => modal.classList.add('hidden');
        if (closeBtn) closeBtn.onclick = closeModal;
        if (cancelBtn) cancelBtn.onclick = closeModal;

        const saveAlias = async (newVal) => {
            const cleanVal = (newVal || '').trim();
            try {
                const res = await fetch(`${getApiBaseUrl()}/set-alias`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ip: baseIp, alias: cleanVal })
                });
                if (cleanVal) {
                    this.deviceAliases[baseIp] = cleanVal;
                } else {
                    delete this.deviceAliases[baseIp];
                }
                this.updateAllTileAliases(baseIp, cleanVal);
                closeModal();
                if (cleanVal) {
                    this.showToast(`🏷️ Máquina identificada como "${cleanVal}"!`, 'success', 2500);
                } else {
                    this.showToast(`🗑️ Identificação personalizada removida para ${baseIp}.`, 'info', 2000);
                }
            } catch(e) {
                console.error('Erro ao salvar apelido:', e);
                this.showToast('🛑 Erro ao salvar nome do aluno.', 'error');
            }
        };

        if (saveBtn) {
            saveBtn.onclick = () => saveAlias(input.value);
        }

        if (clearBtn) {
            clearBtn.onclick = () => saveAlias('');
        }

        input.onkeydown = (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                saveAlias(input.value);
            }
        };

        modal.classList.remove('hidden');
        setTimeout(() => input.focus(), 100);
    }

    updateAllTileAliases(baseIp, newAlias) {
        this.activeTiles.forEach((tileData, tileKey) => {
            if (tileData.baseIp === baseIp) {
                const idSlug = tileKey.replace(/[\/\.:]/g, '-');
                const displayName = newAlias || this.deviceHostnames[baseIp] || `PC ${baseIp.split('.').pop()}`;
                const grad = this.getAvatarGradient(displayName);
                const init = this.getAvatarInitial(newAlias || this.deviceHostnames[baseIp], baseIp);

                const avatarEl = document.getElementById(`avatar-${idSlug}`);
                if (avatarEl) {
                    avatarEl.style.background = grad;
                    avatarEl.textContent = init;
                }

                const nameEl = document.getElementById(`student-name-${idSlug}`);
                if (nameEl) {
                    const displayLabel = tileData.display ? ` ${tileData.display}` : '';
                    nameEl.textContent = `${displayName}${displayLabel}`;
                }
            }
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
        const canvasContainer = tileEl.querySelector(`#canvas-container-${idSlug}`);

        // 1. Atualiza a bolinha colorida e o tooltip de status no cabeçalho (🟢 online / 🔴 offline / 🟡 conectando)
        const pulseDot = tileEl.querySelector(`#pulse-dot-${idSlug}`);
        if (pulseDot) {
            pulseDot.className = `vnc-pulse-dot ${status}`;
            const dotTitle = status === 'connected' ? 'Conectado (🟢 Online)' : (status === 'connecting' ? 'Conectando (🟡)' : 'Desconectado (🔴 Offline)');
            pulseDot.title = dotTitle;
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
                    tileData.loggedUser = prepData.logged_user;
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
            // Modo Miniatura (Grid): 1.5 FPS com qualidade equilibrada para economia massiva de banda (reduz de ~100 Mbps para ~2 Mbps)
            rfb.qualityLevel = this.globalGridQuality || 3;
            rfb.compressionLevel = this.globalGridCompression || 7;
            rfb.targetFps = this.globalGridFps || 1.5;
            rfb.paused = (tileData.isVisible === false || this._isAllPaused);
            rfb.clipViewport = false;
            rfb.showDotCursor = false;
            rfb.background = '#020617';
            tileData.rfb = rfb;

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
        closeAllVncDropdowns();
        this.pauseAllTiles();
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
            case 'silence':
                actionName = 'Pedir Silêncio (Alerta Piscante)';
                payloadAction = 'pedir_silencio';
                extraData = { message: 'O professor solicitou silêncio imediato e atenção de todos na sala de aula.' };
                break;
            case 'voice':
            case 'tts':
                this.openTtsVoiceModal('batch');
                return;
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
        let authErrorCount = 0;
        let lastErrorMessage = '';

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
                } else {
                    const errMsg = (data && (data.message || data.details) ? (data.message + ' ' + (data.details || '')) : '').toLowerCase();
                    if (errMsg.includes('autentica') || errMsg.includes('authentication') || errMsg.includes('password') || errMsg.includes('permission denied')) {
                        authErrorCount++;
                    }
                    if (data && data.message) lastErrorMessage = data.message;
                    if (!isRetry) {
                        await new Promise(r => setTimeout(r, 400));
                        return await runSingleTarget(rawIpSpec, true);
                    } else {
                        failCount++;
                        return false;
                    }
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
            if (authErrorCount > 0) {
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
                const finalErr = lastErrorMessage || 'Erro na execução remota';
                this.showToast(`❌ '${actionName}' falhou em todas as ${failCount} máquinas: ${finalErr}`, 'error', 5000);
                this.addLog('GRID', 'LOTE_ERRO', `Ação em lote '${actionName}': ${failCount} falhas. Motivo: ${finalErr}`);
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

    // ===== 🔊 VOZ DO PROFESSOR (Sintetizador TTS em Português) =====
    openTtsVoiceModal(targetMode = 'batch', targetSpec = null, displayName = '') {
        const modal = document.getElementById('tts-voice-modal');
        const subtitle = document.getElementById('tts-voice-target-subtitle');
        const customInput = document.getElementById('tts-voice-custom-text');
        const sendBtn = document.getElementById('send-tts-voice-modal-btn');
        const closeBtn = document.getElementById('close-tts-voice-modal-btn');
        const cancelBtn = document.getElementById('cancel-tts-voice-modal-btn');
        const feedback = document.getElementById('tts-voice-status-feedback');

        if (!modal) return;

        const targetIps = targetMode === 'batch' ? this.getSelectedIps() : [targetSpec];
        if (subtitle) {
            subtitle.textContent = targetMode === 'batch'
                ? `Transmitir aviso por voz para ${targetIps.length} máquina(s) selecionada(s) no Grid`
                : `Transmitir aviso por voz para ${displayName || targetSpec}`;
        }

        // Preset chips listeners
        const presetBtns = modal.querySelectorAll('.modal-tts-preset-btn');
        presetBtns.forEach(btn => {
            btn.onclick = () => {
                const phrase = btn.getAttribute('data-text') || '';
                if (customInput) customInput.value = phrase;
            };
        });

        if (sendBtn) {
            sendBtn.onclick = async () => {
                const message = customInput ? customInput.value.trim() : '';
                if (!message) {
                    this.showToast('⚠️ Digite ou escolha uma mensagem de voz para falar.', 'warning');
                    return;
                }

                sendBtn.disabled = true;
                const oldLabel = sendBtn.innerHTML;
                sendBtn.innerHTML = '<span>⏳</span> Transmitindo voz...';
                if (feedback) feedback.textContent = '🔊 Reproduzindo áudio nos computadores dos alunos...';

                try {
                    const res = await fetch(`${getApiBaseUrl()}/api/tts/speak`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            message: message,
                            ips: targetIps
                        })
                    });
                    const data = await res.json();
                    if (data && data.success) {
                        this.showToast(`🔊 Voz do professor transmitida para ${data.delivered_count || targetIps.length} estações!`, 'success', 4000);
                        modal.classList.add('hidden');
                    } else {
                        this.showToast('⚠️ Erro ao sintetizar áudio: ' + (data.message || 'Falha na transmissão.'), 'error');
                    }
                } catch(err) {
                    this.showToast('⚠️ Erro de comunicação com o servidor: ' + err.message, 'error');
                } finally {
                    sendBtn.disabled = false;
                    sendBtn.innerHTML = oldLabel;
                    if (feedback) feedback.textContent = '🔊 Síntese de voz em alta fidelidade';
                }
            };
        }

        const closeModal = () => modal.classList.add('hidden');
        if (closeBtn) closeBtn.onclick = closeModal;
        if (cancelBtn) cancelBtn.onclick = closeModal;

        modal.classList.remove('hidden');
        if (customInput) {
            customInput.focus();
            if (!customInput.value) {
                customInput.value = "Atenção turma: por favor, prestem atenção nas orientações do professor.";
            }
        }
    }

    // ===== 🌐 CATÁLOGO EDUCATIVO & ABERTURA REMOTA DE SITES (Sincronizado com backend físico preset_urls.json) =====
    async fetchPresetUrls() {
        try {
            const res = await fetch(`${getApiBaseUrl()}/api/preset-urls`);
            if (res.ok) {
                const data = await res.json();
                if (data && Array.isArray(data.urls) && data.urls.length > 0) {
                    const normalized = data.urls.map(item => this.normalizeEduItem(item));
                    try { localStorage.setItem('vnc_preset_urls', JSON.stringify(normalized)); } catch(e){}
                    return normalized;
                }
            }
        } catch(e) {
            console.warn('[Grid VNC] Falha ao consultar /api/preset-urls, usando cache:', e);
        }
        return this.getPresetUrls();
    }

    normalizeEduItem(item) {
        if (typeof item === 'string') {
            const clean = item.trim();
            const url = clean.startsWith('http') ? clean : `https://${clean}`;
            const host = clean.replace('https://', '').replace('http://', '').split('/')[0];
            return {
                id: 'custom_' + Math.random().toString(36).substring(2, 7),
                title: host,
                url: url,
                category: 'Personalizados',
                icon: '🌐',
                desc: 'Link personalizado do professor',
                badge: 'Link',
                custom: true
            };
        }
        return {
            id: item.id || ('edu_' + Math.random().toString(36).substring(2, 7)),
            title: item.title || 'Site Educativo',
            url: item.url.startsWith('http') ? item.url : `https://${item.url}`,
            category: item.category || 'Geral',
            icon: item.icon || '🌐',
            desc: item.desc || 'Plataforma educativa para os alunos',
            badge: item.badge || item.category || 'Edu',
            custom: !!item.custom
        };
    }

    getPresetUrls() {
        try {
            const saved = localStorage.getItem('vnc_preset_urls');
            if (saved) {
                const parsed = JSON.parse(saved);
                if (Array.isArray(parsed) && parsed.length > 0) {
                    return parsed.map(i => this.normalizeEduItem(i));
                }
            }
        } catch(e){}
        return [
            { id: "scratch", title: "Scratch MIT", url: "https://scratch.mit.edu", category: "Programação", icon: "🐱", desc: "Programação em blocos e criação de jogos", badge: "Popular" },
            { id: "kahoot", title: "Kahoot! Jogos", url: "https://kahoot.it", category: "Jogos & Quizzes", icon: "🎮", desc: "Quizzes interativos e gincanas ao vivo", badge: "Interativo" },
            { id: "classroom", title: "Google Sala de Aula", url: "https://classroom.google.com", category: "Geral", icon: "🏫", desc: "Turmas, tarefas e atividades Classroom", badge: "Oficial" },
            { id: "geogebra", title: "GeoGebra", url: "https://www.geogebra.org", category: "Matemática", icon: "📐", desc: "Geometria dinâmica, álgebra e gráficos 3D", badge: "Matemática" },
            { id: "canva", title: "Canva Educação", url: "https://www.canva.com", category: "Criatividade", icon: "🎨", desc: "Apresentações, infográficos e cartazes", badge: "Design" },
            { id: "youtube_edu", title: "YouTube Educativo", url: "https://www.youtube.com", category: "Vídeo & Aulas", icon: "▶️", desc: "Vídeo-aulas, documentários e tutoriais", badge: "Multimídia" },
            { id: "matific", title: "Matific Aluno", url: "https://www.matific.com/bra/pt-br/login-page/", category: "Matemática", icon: "🔢", desc: "Jogos e desafios pedagógicos de matemática", badge: "Gamificado" },
            { id: "elefante", title: "Elefante Letrado", url: "https://login.elefanteletrado.com.br/student", category: "Alfabetização", icon: "🐘", desc: "Biblioteca digital e incentivo à leitura", badge: "Leitura" },
            { id: "code_org", title: "Code.org", url: "https://code.org", category: "Programação", icon: "💻", desc: "Hora do Código e Ciência da Computação", badge: "Programação" },
            { id: "wordwall", title: "Wordwall", url: "https://wordwall.net/pt", category: "Jogos & Quizzes", icon: "🧩", desc: "Jogos pedagógicos, roletas e palavras-cruzadas", badge: "Atividades" },
            { id: "duolingo", title: "Duolingo", url: "https://www.duolingo.com", category: "Idiomas", icon: "🦉", desc: "Aprendizado de idiomas gamificado", badge: "Idiomas" },
            { id: "tinkercad", title: "Tinkercad 3D", url: "https://www.tinkercad.com", category: "Criatividade", icon: "🧊", desc: "Modelagem 3D, robótica e circuitos", badge: "Maker / 3D" },
            { id: "phet", title: "PhET Simulações", url: "https://phet.colorado.edu", category: "Ciências", icon: "🔬", desc: "Simulações interativas de física e química", badge: "Laboratório" }
        ];
    }

    async savePresetUrls(list) {
        try { localStorage.setItem('vnc_preset_urls', JSON.stringify(list)); } catch(e){}
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
        const searchInput = document.getElementById('vnc-edu-search-input');
        const searchClear = document.getElementById('vnc-edu-search-clear');
        const chipsContainer = document.getElementById('vnc-edu-category-chips');
        const customUrlInput = document.getElementById('vnc-custom-url-input');
        const addBtn = document.getElementById('vnc-add-preset-url-btn');
        const sendBtn = document.getElementById('vnc-preset-url-send');
        const closeBtn = document.getElementById('vnc-preset-url-close');
        const cancelBtn = document.getElementById('vnc-preset-url-cancel');
        const previewEl = document.getElementById('vnc-edu-selected-preview');

        if (!modal || !listContainer) return;

        const targetIps = targetMode === 'batch' ? this.getSelectedIps() : [targetSpec];
        if (desc) {
            desc.textContent = targetMode === 'batch' 
                ? `Abrir instantaneamente nas ${targetIps.length} máquina(s) selecionada(s) no Grid`
                : `Abrir instantaneamente em ${displayName || targetSpec}`;
        }

        let presets = await this.fetchPresetUrls();
        let selectedCategory = 'all';
        let currentSearch = '';
        let selectedUrl = presets[0] ? presets[0].url : 'https://scratch.mit.edu';

        const updatePreview = (url, title = '') => {
            selectedUrl = url;
            if (customUrlInput) customUrlInput.value = url;
            if (previewEl) {
                previewEl.innerHTML = title 
                    ? `<span style="color:#f8fafc; font-weight:700;">${title}:</span> <span style="color:#38bdf8;">${url}</span>`
                    : `<span style="color:#38bdf8;">${url}</span>`;
            }
        };

        const launchUrl = async (urlToOpen, siteTitle = '') => {
            let finalUrl = (urlToOpen || '').trim();
            if (!finalUrl) {
                this.showToast('⚠️ Digite ou selecione uma URL.', 'error');
                return;
            }
            if (!finalUrl.startsWith('http://') && !finalUrl.startsWith('https://')) {
                finalUrl = 'https://' + finalUrl;
            }

            modal.classList.add('hidden');

            if (targetMode === 'batch') {
                const label = siteTitle ? `"${siteTitle}"` : finalUrl;
                this.showToast(`⏳ Abrindo ${label} em ${targetIps.length} máquina(s)...`, 'info', 2500);
                let successCount = 0;
                await Promise.all(targetIps.map(async (rawIpSpec) => {
                    const parsed = this.parseTargetSpec(rawIpSpec);
                    const body = {
                        ip: parsed.baseIp,
                        action: 'abrir_site',
                        password: this.getGridPassword(),
                        display: parsed.display,
                        target_display: parsed.display,
                        url: finalUrl
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
                this.showToast(`🚀 ${label} aberto com sucesso em ${successCount} máquina(s)!`, 'success', 3500);
            } else {
                this.executeSingleCommand(targetSpec, 'abrir_site', `Abrir Site (${siteTitle || finalUrl})`, { url: finalUrl });
            }
        };

        const renderList = () => {
            listContainer.innerHTML = '';
            const filtered = presets.filter(item => {
                const matchesCat = selectedCategory === 'all' || item.category === selectedCategory;
                const searchLower = currentSearch.toLowerCase();
                const matchesSearch = !currentSearch || 
                    item.title.toLowerCase().includes(searchLower) ||
                    item.url.toLowerCase().includes(searchLower) ||
                    (item.desc && item.desc.toLowerCase().includes(searchLower)) ||
                    (item.category && item.category.toLowerCase().includes(searchLower));
                return matchesCat && matchesSearch;
            });

            if (filtered.length === 0) {
                listContainer.innerHTML = `
                    <div style="grid-column: 1/-1; text-align:center; padding:35px 20px; color:#94a3b8;">
                        <span style="font-size:2rem; display:block; margin-bottom:8px;">🔍</span>
                        <div style="font-weight:700; color:#f8fafc; font-size:0.92rem;">Nenhum site educativo encontrado</div>
                        <div style="font-size:0.75rem; margin-top:4px;">Tente outra busca ou digite o link abaixo no campo personalizado.</div>
                    </div>
                `;
                return;
            }

            filtered.forEach(item => {
                const card = document.createElement('div');
                card.className = `edu-card ${selectedUrl === item.url ? 'selected' : ''}`;
                
                card.innerHTML = `
                    <div class="edu-card-top">
                        <div class="edu-card-icon-box">${item.icon || '🌐'}</div>
                        <div class="edu-card-info">
                            <div class="edu-card-title">
                                <span>${item.title}</span>
                            </div>
                            <span class="edu-card-badge">${item.badge || item.category}</span>
                        </div>
                    </div>
                    <div class="edu-card-desc">${item.desc || item.url}</div>
                    <div class="edu-card-bottom">
                        <span class="edu-card-url-hint">${item.url.replace('https://', '').replace('http://', '').split('/')[0]}</span>
                        <div style="display:flex; align-items:center; gap:4px;">
                            ${item.custom ? `<button type="button" class="edu-card-delete-btn" title="Excluir link salvo">&times;</button>` : ''}
                            <button type="button" class="edu-card-launch-btn">
                                <span>🚀</span> Abrir
                            </button>
                        </div>
                    </div>
                `;

                // Selecionar ao clicar no card
                card.onclick = (e) => {
                    const isDelete = e.target.closest('.edu-card-delete-btn');
                    const isLaunch = e.target.closest('.edu-card-launch-btn');

                    if (isDelete) {
                        e.stopPropagation();
                        const idx = presets.findIndex(p => p.id === item.id || p.url === item.url);
                        if (idx >= 0) {
                            presets.splice(idx, 1);
                            this.savePresetUrls(presets);
                            renderList();
                            this.showToast('🗑️ Link removido do catálogo.', 'info', 2000);
                        }
                        return;
                    }

                    if (isLaunch) {
                        e.stopPropagation();
                        launchUrl(item.url, item.title);
                        return;
                    }

                    // Seleção regular
                    listContainer.querySelectorAll('.edu-card').forEach(c => c.classList.remove('selected'));
                    card.classList.add('selected');
                    updatePreview(item.url, item.title);
                };

                // Duplo clique abre direto
                card.ondblclick = () => {
                    launchUrl(item.url, item.title);
                };

                listContainer.appendChild(card);
            });
        };

        // Eventos dos Chips de Categoria
        if (chipsContainer) {
            chipsContainer.querySelectorAll('.edu-chip').forEach(chip => {
                chip.onclick = () => {
                    chipsContainer.querySelectorAll('.edu-chip').forEach(c => c.classList.remove('active'));
                    chip.classList.add('active');
                    selectedCategory = chip.getAttribute('data-category') || 'all';
                    renderList();
                };
            });
        }

        // Busca em tempo real
        if (searchInput) {
            searchInput.value = '';
            currentSearch = '';
            searchInput.oninput = () => {
                currentSearch = searchInput.value.trim();
                if (searchClear) {
                    searchClear.classList.toggle('hidden', !currentSearch);
                }
                renderList();
            };
        }

        if (searchClear) {
            searchClear.classList.add('hidden');
            searchClear.onclick = () => {
                if (searchInput) searchInput.value = '';
                currentSearch = '';
                searchClear.classList.add('hidden');
                renderList();
                if (searchInput) searchInput.focus();
            };
        }

        // Salvar novo link no catálogo do professor
        if (addBtn) {
            addBtn.onclick = async () => {
                let val = customUrlInput ? customUrlInput.value.trim() : '';
                if (!val) {
                    this.showToast('⚠️ Digite um link para salvar no catálogo.', 'warning', 2500);
                    return;
                }
                if (!val.startsWith('http://') && !val.startsWith('https://')) {
                    val = 'https://' + val;
                }
                const exists = presets.some(p => p.url === val);
                if (!exists) {
                    const newItem = this.normalizeEduItem(val);
                    presets.unshift(newItem);
                    await this.savePresetUrls(presets);
                    this.showToast('⭐ Link adicionado ao Catálogo Educativo!', 'success', 2500);
                    renderList();
                } else {
                    this.showToast('ℹ️ Este site já está cadastrado no catálogo.', 'info', 2000);
                }
            };
        }

        // Abertura via botão "Abrir Agora" ou tecla Enter no input
        if (sendBtn) {
            sendBtn.onclick = () => {
                let urlVal = customUrlInput ? customUrlInput.value.trim() : selectedUrl;
                launchUrl(urlVal);
            };
        }

        if (customUrlInput) {
            customUrlInput.onkeydown = (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    launchUrl(customUrlInput.value.trim());
                }
            };
        }

        const closeModal = () => modal.classList.add('hidden');
        if (closeBtn) closeBtn.onclick = closeModal;
        if (cancelBtn) cancelBtn.onclick = closeModal;

        // Renderiza lista inicial e preview
        renderList();
        updatePreview(presets[0] ? presets[0].url : 'https://scratch.mit.edu', presets[0] ? presets[0].title : 'Scratch MIT');

        modal.classList.remove('hidden');
        setTimeout(() => {
            if (searchInput) searchInput.focus();
        }, 100);
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

// Gerenciador do menu dropdown de ações do Grid VNC
function toggleVncDropdown(toggleBtn) {
    if (!toggleBtn) return;
    const dropdown = toggleBtn.closest('.vnc-dropdown') || document.getElementById('vnc-grid-more-actions-dropdown');
    if (!dropdown) return;

    const willOpen = !dropdown.classList.contains('open');

    // Fecha todos os dropdowns abertos antes
    closeAllVncDropdowns();

    if (willOpen) {
        dropdown.classList.add('open');
    }
}

function closeAllVncDropdowns() {
    document.querySelectorAll('.vnc-dropdown.open').forEach(d => d.classList.remove('open'));
}

// Global listener para abertura, fechamento e execução de ações do dropdown
document.addEventListener('click', (e) => {
    const toggleBtn = e.target.closest('#vnc-grid-more-actions-btn, .vnc-dropdown-toggle');
    if (toggleBtn) {
        e.preventDefault();
        e.stopPropagation();
        toggleVncDropdown(toggleBtn);
        return;
    }

    // Executa ação de batch action e fecha o dropdown se o clique ocorreu no menu
    const batchBtn = e.target.closest('[data-batch-action]');
    if (batchBtn && (batchBtn.closest('.vnc-dropdown-menu') || batchBtn.closest('.vnc-dropdown'))) {
        const act = batchBtn.getAttribute('data-batch-action');
        closeAllVncDropdowns();
        if (act && window.vncGridManager) {
            window.vncGridManager.handleBatchAction(act);
        }
        return;
    }

    const copyLogBtn = e.target.closest('#vnc-grid-copy-log-btn, .vnc-grid-copy-log-btn');
    if (copyLogBtn && (copyLogBtn.closest('.vnc-dropdown-menu') || copyLogBtn.closest('.vnc-dropdown'))) {
        closeAllVncDropdowns();
        if (window.vncGridManager) {
            window.vncGridManager.copyLogsToClipboard();
        }
        return;
    }

    const dropdownItem = e.target.closest('.vnc-dropdown-item');
    if (dropdownItem) {
        closeAllVncDropdowns();
        return;
    }

    // Fecha se o clique ocorreu fora do dropdown
    if (!e.target.closest('.vnc-dropdown')) {
        closeAllVncDropdowns();
    }
});

window.addEventListener('resize', closeAllVncDropdowns);
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeAllVncDropdowns();
});
