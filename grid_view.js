// grid_view.js - Gerenciador de Visualização em Grid Múltiplo noVNC

// Resolve a URL base da API de forma autônoma (independente do script.js)
function getApiBaseUrl() {
    // Reutiliza se script.js já expôs em window
    if (window._API_BASE_URL) return window._API_BASE_URL;
    let host = window.location.hostname || '127.0.0.1';
    if (host === 'localhost') host = '127.0.0.1';
    if (window.location.protocol === 'file:' || (window.location.port && window.location.port !== '8000')) {
        return `http://${host}:8000`;
    }
    return window.location.origin;
}

class VNCGridManager {
    constructor() {
        this.activeTiles = new Map(); // ip -> { rfb, wsPort, element }
        this.deviceAliases = {}; // ip -> alias
        this.deviceHostnames = {}; // ip -> hostname
        this.currentCols = 'cols-auto';
        this.eventLogs = []; // Histórico de logs/eventos do Grid na sessão
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

    async fetchAliases() {
        try {
            const res = await fetch(`${getApiBaseUrl()}/get-aliases`);
            const data = await res.json();
            if (data.success) {
                if (data.aliases) this.deviceAliases = data.aliases;
                if (data.hostnames) this.deviceHostnames = data.hostnames;
            }
        } catch (e) {
            console.warn("[Grid VNC] Erro ao carregar apelidos:", e);
        }
    }

    setColumns(colsClass) {
        if (!this.container) return;
        this.currentCols = colsClass;
        this.container.className = `vnc-grid-container ${colsClass}`;
        if (colsClass === 'cols-auto' || colsClass === 'cols-fit') {
            this.autoFitGrid();
        } else {
            this.container.classList.remove('grid-fit-screen', 'grid-dense', 'grid-ultra-dense');
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

        // Testa combinações de colunas de 1 até 10 para encontrar a proporção geométrica ideal
        for (let cols = 1; cols <= Math.min(10, total); cols++) {
            const rows = Math.ceil(total / cols);
            const tileW = (availWidth - (cols - 1) * gap - 16) / cols;
            const tileH = (availHeight - (rows - 1) * gap - 16) / rows;

            if (tileW <= 40 || tileH <= 40) continue;

            const targetRatio = 16 / 10;
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

        // Tabela de Proporções Inteligentes de fallback
        if (maxTileArea === 0) {
            if (total <= 2) { bestCols = 2; bestRows = 1; }
            else if (total <= 4) { bestCols = 2; bestRows = 2; }
            else if (total <= 6) { bestCols = 3; bestRows = 2; }
            else if (total <= 8) { bestCols = 4; bestRows = 2; }
            else if (total <= 12) { bestCols = 4; bestRows = 3; }
            else if (total <= 16) { bestCols = 4; bestRows = 4; }
            else if (total <= 20) { bestCols = 5; bestRows = 4; }
            else if (total <= 25) { bestCols = 6; bestRows = 4; }
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

        this.activeTiles.forEach((tileData) => {
            if (!tileData.element) return;
            const cb = tileData.element.querySelector('.vnc-tile-checkbox');
            if (cb && cb.checked) {
                selectedCount++;
                tileData.element.classList.add('tile-selected');
            } else if (cb) {
                tileData.element.classList.remove('tile-selected');
            }
        });

        if (this.statusCountSpan) {
            this.statusCountSpan.textContent = `${totalCount} telas ativas`;
        }

        const selectedSpan = this.modal ? this.modal.querySelector('#vnc-grid-selected-count') : document.getElementById('vnc-grid-selected-count');
        if (selectedSpan) {
            selectedSpan.textContent = `${selectedCount}/${totalCount} sel.`;
        }

        this.autoFitGrid();
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

        // Se nenhum IP foi informado, tenta conectar a todas as máquinas online
        if (!targetIps || targetIps.length === 0) {
            targetIps = this.getOnlineIps();
        } else {
            targetIps = this.deduplicateIpList(targetIps);
        }

        // Conecta a todas as máquinas alvo (suporta todas as telas online sem truncamento arbitrário)
        const ipsToConnect = targetIps;

        for (const ip of ipsToConnect) {
            const parsed = this.parseTargetSpec(ip);
            if (!this.activeTiles.has(parsed.canonicalKey)) {
                await this.addTile(ip);
            }
        }
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
        const titleTooltip = hostname || alias || baseIp;
        const titleMarkup = alias ? `
            <div style="display:flex;flex-direction:column;line-height:1.2;" title="${titleTooltip}">
                <span style="font-weight:700;color:#f8fafc;font-size:0.9rem;">${alias}${displayLabel}</span>
                <span style="font-family:'JetBrains Mono',monospace;font-size:0.72rem;color:#94a3b8;opacity:0.8;">${baseIp}</span>
            </div>
        ` : hostname ? `
            <div style="display:flex;flex-direction:column;line-height:1.2;" title="${titleTooltip}">
                <span style="font-weight:700;color:#f8fafc;font-size:0.9rem;">${hostname}${displayLabel}</span>
                <span style="font-family:'JetBrains Mono',monospace;font-size:0.72rem;color:#94a3b8;opacity:0.8;">${baseIp}</span>
            </div>
        ` : `<span class="vnc-tile-ip" title="${titleTooltip}">${baseIp}${displayLabel}</span>`;

        const tileEl = document.createElement('div');
        tileEl.className = 'vnc-tile';
        tileEl.id = `vnc-tile-${idSlug}`;
        tileEl.innerHTML = `
            <div class="vnc-tile-header">
                <div class="vnc-tile-info">
                    <input type="checkbox" class="vnc-tile-checkbox" id="cb-${idSlug}" checked title="Selecionar máquina para ações em lote" />
                    <span class="vnc-status-badge connecting" id="status-badge-${idSlug}">Conectando</span>
                    ${titleMarkup}
                    <span id="user-badge-${idSlug}" class="vnc-tile-user" style="font-size:0.75rem;color:#38bdf8;font-weight:600;margin-top:2px;display:none;align-items:center;gap:3px;"></span>
                </div>
                <div class="vnc-tile-actions">
                    <button type="button" class="vnc-tile-btn lock-btn" title="Desbloqueado (Clique para Bloquear 🔒)" id="btn-lock-${idSlug}">
                        <span id="lock-icon-state-${idSlug}" style="font-size:0.85rem;line-height:1;">🔓</span>
                    </button>
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
                    <div class="vnc-tile-status-text" id="status-text-${idSlug}">Iniciando VNC em ${baseIp}${targetDisplay ? ' ' + targetDisplay : ''}...</div>
                </div>
                <div class="vnc-tile-canvas" id="canvas-container-${idSlug}"></div>
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
            isLocked: false
        };
        this.activeTiles.set(tileKey, tileData);

        if (this.tileObserver) {
            try { this.tileObserver.observe(tileEl); } catch(e) {}
        }

        const tileCb = tileEl.querySelector(`#cb-${idSlug}`);
        if (tileCb) {
            tileCb.addEventListener('change', () => {
                this.updateCount();
            });
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
        this.addLog(tileKey, status, msg);
        const tileData = this.activeTiles.get(tileKey);
        if (!tileData || !tileData.element) return;
        const idSlug = tileKey.replace(/[\/\.:]/g, '-');
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

        this.startTileConnection(tileKey);
    }

    async startTileConnection(tileKey) {
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
            const prepTimeout = setTimeout(() => prepController.abort(), 10000);

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

            // Otimização de Desempenho: FPS Adaptativo (5 FPS no Grid vs 30-60 FPS Expandido) + Viewport Lazy Render
            if (rfb._display && typeof rfb._display.flush === 'function') {
                const origFlush = rfb._display.flush.bind(rfb._display);
                let lastFlushTime = 0;
                const minFlushInterval = 200; // 5 FPS (200ms por quadro em modo grade)

                rfb._display.flush = function() {
                    // Se o tile estiver fora da área visível ou o modal minimizado, suspende o desenho no canvas
                    if (tileData.isVisible === false) {
                        return Promise.resolve();
                    }

                    const now = performance.now();
                    if (now - lastFlushTime < minFlushInterval) {
                        return Promise.resolve(); // Limita a 5 FPS na grade
                    }
                    lastFlushTime = now;
                    return origFlush();
                };
            }

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

        if (this.tileObserver && element) {
            try { this.tileObserver.unobserve(element); } catch(e) {}
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
                const hostname = this.deviceHostnames[ip] || '';
                const itemTooltip = hostname || alias || ip;
                const labelText = alias ? `<strong style="color:#f8fafc;">${alias}</strong> <span style="font-family:'JetBrains Mono',monospace;opacity:.65;font-size:.78rem;margin-left:4px;">(${ip})</span>` : hostname ? `<strong style="color:#f8fafc;">${hostname}</strong> <span style="font-family:'JetBrains Mono',monospace;opacity:.65;font-size:.78rem;margin-left:4px;">(${ip})</span>` : `<span style="font-family:'JetBrains Mono',monospace;font-weight:600;color:#f8fafc;">${ip}</span>`;
                const isSelected = this.activeTiles.has(ip) || Array.from(this.activeTiles.keys()).some(k => k.startsWith(ip));
                const item = document.createElement('label');
                item.className = 'vnc-grid-select-item';
                item.title = itemTooltip;
                item.setAttribute('data-tooltip', itemTooltip);
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
                const msg = prompt(`Digite a mensagem a ser enviada em pop-up para as ${targetIps.length} máquinas do Grid:`, 'Atenção leitores: a aula vai começar!');
                if (!msg || !msg.trim()) return;
                actionName = 'Enviar Mensagem';
                payloadAction = 'enviar_mensagem';
                extraData = { message: msg.trim() };
                break;
            case 'lock':
                actionName = 'Bloquear Tela com Cadeado';
                payloadAction = 'bloquear_tela_mensagem';
                extraData = { message: 'Atenção ao Professor!' };
                break;
            case 'unlock':
                actionName = 'Desbloquear Tela';
                payloadAction = 'desbloquear_tela_mensagem';
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
                const url = prompt(`Digite a URL para abrir no navegador das ${targetIps.length} máquinas do Grid:`, 'https://google.com');
                if (!url || !url.trim()) return;
                actionName = 'Abrir URL';
                payloadAction = 'abrir_site';
                extraData = { url: url.trim() };
                break;
            case 'restart':
                if (!confirm(`⚠️ ATENÇÃO: Tem certeza que deseja REINICIAR as ${targetIps.length} máquinas visíveis no Grid?`)) return;
                actionName = 'Reiniciar';
                payloadAction = 'reiniciar';
                break;
            case 'shutdown':
                if (!confirm(`⚠️ ATENÇÃO: Tem certeza que deseja DESLIGAR as ${targetIps.length} máquinas visíveis no Grid?`)) return;
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
                if (data && data.success !== false) {
                    successCount++;
                    if (actionType === 'lock') {
                        this.setTileLockState(rawIpSpec, true);
                    } else if (actionType === 'unlock') {
                        this.setTileLockState(rawIpSpec, false);
                    }
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

        // Execução em chunks controlados (6 simultâneos) para evitar timeout de sockets/SSH simultâneos
        const CHUNK_SIZE = 6;
        for (let i = 0; i < targetIps.length; i += CHUNK_SIZE) {
            const chunk = targetIps.slice(i, i + CHUNK_SIZE);
            await Promise.all(chunk.map(ipSpec => runSingleTarget(ipSpec)));
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
            if (data && data.success !== false) {
                this.setTileLockState(tileKey, willLock);
                this.showToast(`✅ ${targetIp} ${willLock ? 'bloqueado 🔒' : 'desbloqueado 🔓'} com sucesso!`, 'success');
                this.addLog(targetIp, willLock ? 'LOCKED' : 'UNLOCKED', `Máquina ${targetIp} ${willLock ? 'bloqueada' : 'desbloqueada'} individualmente.`);
            } else {
                this.showToast(`⚠️ Falha ao ${actionName.toLowerCase()} em ${targetIp}.`, 'error');
                this.addLog(targetIp, 'LOCK_ERROR', `Falha ao ${actionName.toLowerCase()}: ${data ? data.message : 'Erro desconhecido'}`);
            }
        } catch (err) {
            this.showToast(`⚠️ Erro de rede ao ${actionName.toLowerCase()} em ${targetIp}.`, 'error');
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
                        lockOverlay = document.createElement('div');
                        lockOverlay.id = `lock-overlay-${idSlug}`;
                        lockOverlay.className = 'vnc-tile-lock-overlay';
                        lockOverlay.innerHTML = `
                            <div class="vnc-tile-lock-icon">🔒</div>
                            <div class="vnc-tile-lock-title">🤫 TELA BLOQUEADA</div>
                            <div class="vnc-tile-lock-sub">🤫 Silêncio • Teclado e Mouse Bloqueados</div>
                            <button type="button" class="vnc-tile-btn" style="margin-top:8px;background:rgba(239,68,68,0.25);border:1px solid #ef4444;color:#fef2f2;padding:4px 10px;border-radius:6px;font-size:0.72rem;font-weight:700;cursor:pointer;" onclick="window.vncGridManager && window.vncGridManager.toggleSingleTileLock('${tileKey}')">
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

                    if (lockBadge) lockBadge.remove();
                    if (lockOverlay) lockOverlay.remove();
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
}

// Instância global do gerenciador de Grid VNC
window.vncGridManager = new VNCGridManager();

window.openVNCGrid = (ipsList = []) => {
    if (window.vncGridManager) {
        window.vncGridManager.openGrid(ipsList);
    }
};
