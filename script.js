import { ACTIONS, CONFLICTING_ACTIONS, LOCAL_ACTIONS, NO_PASSWORD_ACTIONS } from './constants.js';

// --- Função Global de Troca de Abas do Medidor de Ruído (Disponível Imediatamente) ---
window.switchDecibelTab = function(targetTab) {
    if (!targetTab) return;
    window._activeDecibelTab = targetTab;
    const allTabs = document.querySelectorAll('.decibel-tab-btn');
    const allPanes = document.querySelectorAll('.decibel-tab-pane');

    allTabs.forEach(t => {
        const isMatch = t.getAttribute('data-tab') === targetTab;
        if (isMatch) {
            t.classList.add('active');
        } else {
            t.classList.remove('active');
        }
    });

    allPanes.forEach(pane => {
        const isMatch = pane.id === `decibel-tab-${targetTab}`;
        if (isMatch) {
            pane.classList.add('active');
            pane.classList.remove('hidden');
            pane.style.setProperty('display', 'flex', 'important');
        } else {
            pane.classList.remove('active');
            pane.classList.add('hidden');
            pane.style.setProperty('display', 'none', 'important');
        }
    });

    if (targetTab === 'history') {
        if (typeof window.loadNoiseHistoryReport === 'function') {
            window.loadNoiseHistoryReport();
        }
    }
};

// Listener global com delegação para garantir funcionamento seguro dos cliques nas abas
document.addEventListener('click', (e) => {
    const btn = e.target && e.target.closest ? e.target.closest('.decibel-tab-btn') : null;
    if (btn) {
        const tabId = btn.getAttribute('data-tab');
        if (tabId && typeof window.switchDecibelTab === 'function') {
            e.preventDefault();
            window.switchDecibelTab(tabId);
        }
    }
});

function mainInit() {
    // Define a URL base para as chamadas de API de forma dinâmica
    let API_HOST = window.location.hostname || '127.0.0.1';
    if (API_HOST === 'localhost') API_HOST = '127.0.0.1';
    let API_BASE_URL = window.location.origin;

    const isBackendPort = (p) => p === '5050' || p === '5055' || p === '5950' || p === '8000';
    if (window.location.protocol === 'file:' || (window.location.port && !isBackendPort(window.location.port))) {
        API_BASE_URL = `http://${API_HOST}:5950`;
    }
    window._API_BASE_URL = API_BASE_URL;

    // Cache local de dispositivos e metadados (declarados no topo para evitar TDZ em chamadas assíncronas)
    let deviceAliases = {}; // Cache local de apelidos
    let deviceHostnames = {}; // Cache local de hostnames remotos
    let deviceMacs = {}; // Cache local de MACs remotos
    let deviceMetadataMap = {}; // Cache local de metadados
    let deviceGroupsMap = {}; // Cache local de grupos por IP
    let deviceUsers = {}; // Cache local de usuários por IP
    let ipsWithKeyErrors = new Set();

    try {
        const savedHn = localStorage.getItem('app_device_hostnames');
        if (savedHn) deviceHostnames = Object.assign({}, JSON.parse(savedHn));
        const savedAl = localStorage.getItem('app_device_aliases');
        if (savedAl) deviceAliases = Object.assign({}, JSON.parse(savedAl));
        window.deviceHostnames = Object.assign({}, deviceHostnames);
        window.deviceAliases = Object.assign({}, deviceAliases);
    } catch (e) { }

    function syncDeviceMetadataGlobals() {
        try {
            window.deviceHostnames = Object.assign({}, deviceHostnames);
            window.deviceAliases = Object.assign({}, deviceAliases);
            localStorage.setItem('app_device_hostnames', JSON.stringify(deviceHostnames));
            localStorage.setItem('app_device_aliases', JSON.stringify(deviceAliases));
        } catch (e) { }
    }

    let logBuffer = [];
    let isLogUpdatePending = false;
    // --- Tratamento de Erros Global ---
    // Captura erros síncronos e exceções não tratadas (ex: Cannot read properties of undefined)
    window.addEventListener('error', (event) => {
        const message = event.message || 'Erro desconhecido';
        const filename = event.filename || 'script';
        const lineno = event.lineno || '0';
        const msg = `Erro Crítico: ${message} em ${filename}:${lineno}`;
        console.error("[Global Error]", event.error);
        // Tenta logar na UI se as funções de log já estiverem disponíveis
        if (typeof logStatusMessage === 'function') logStatusMessage(msg, 'error');
    });

    // Captura rejeições de Promises não tratadas (ex: falhas de rede no fetch sem .catch)
    window.addEventListener('unhandledrejection', (event) => {
        const msg = `Rejeição de Promessa não tratada: ${event.reason}`;
        console.error("[Unhandled Rejection]", event.reason);
        if (typeof logStatusMessage === 'function') logStatusMessage(msg, 'error');
    });

    // --- Relógio Digital em Tempo Real ---
    const clockContainer = document.createElement('div');
    clockContainer.id = 'live-clock';
    clockContainer.className = 'live-clock';
    
    const header = document.querySelector('header');
    const themeSwitcher = document.querySelector('.theme-switcher-container');

    if (header) {
        // Captura o container de estatísticas antes de limpar o cabeçalho
        const headerStats = header.querySelector('.header-stats');

        // 1. Envolve o título e subtítulo em uma div para ficarem juntos à esquerda
        const headerInfo = document.createElement('div');
        headerInfo.className = 'header-info';

        // Adiciona o logotipo
        const logoLink = document.createElement('a');
        logoLink.href = '/';
        logoLink.style.display = 'contents'; // Permite que o link herde o comportamento do container pai

        const logo = document.createElement('img');
        logo.src = 'logo.png'; // Assumindo que o logo está na raiz do projeto
        logo.alt = 'Logo Dashboard';
        logo.className = 'app-logo';

        // Fallback caso a imagem não exista
        logo.onerror = () => {
            logo.remove();
            logoLink.innerHTML = '<i data-feather="server" class="logo-fallback-icon"></i>';
            if (window.feather) feather.replace();
        };

        logoLink.appendChild(logo);
        headerInfo.appendChild(logoLink);

        const titleAndSubtitleWrapper = document.createElement('div');
        titleAndSubtitleWrapper.className = 'title-subtitle-wrapper';

        // Move h1 e p para o novo wrapper
        const h1Element = header.querySelector('h1');
        const pElement = header.querySelector('p');
        if (h1Element) {
            const fullText = h1Element.textContent.trim();
            h1Element.textContent = ''; // Limpa o texto para iniciar a digitação

            const textSpan = document.createElement('span');
            textSpan.className = 'typing-container';
            h1Element.appendChild(textSpan);

            if (pElement) pElement.classList.add('hidden-typing');

            let charIndex = 0;
            const typeEffect = () => {
                if (charIndex < fullText.length) {
                    textSpan.textContent += fullText.charAt(charIndex);
                    charIndex++;
                    setTimeout(typeEffect, 80); // Velocidade da digitação
                } else if (pElement) {
                    // Quando termina de digitar, mostra o subtítulo
                    pElement.classList.remove('hidden-typing');
                    pElement.classList.add('fade-in-text');
                }
            };
            typeEffect();
            titleAndSubtitleWrapper.appendChild(h1Element);
        }
        if (pElement) titleAndSubtitleWrapper.appendChild(pElement);
        headerInfo.appendChild(titleAndSubtitleWrapper);

        // Limpa o conteúdo original do header antes de anexar a nova estrutura
        while (header.firstChild) {
            header.removeChild(header.firstChild);
        }
        header.appendChild(headerInfo);

        // 2. Cria um container para as ferramentas (Estatísticas + Relógio + Tema) à direita
        const headerTools = document.createElement('div');
        headerTools.className = 'header-tools';
        if (headerStats) headerTools.appendChild(headerStats);
        headerTools.appendChild(clockContainer);
        if (themeSwitcher) headerTools.appendChild(themeSwitcher);
        header.appendChild(headerTools);

        // Inicializa os novos ícones inseridos dinamicamente
        if (window.feather) feather.replace({ 'container': header });
    }
    const updateClock = () => {
        const now = new Date();
        const rawDate = now.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' });
        const weekdayStr = now.toLocaleDateString('pt-BR', { weekday: 'short' }).replace('.', '');
        const capitalizedWeekday = weekdayStr.charAt(0).toUpperCase() + weekdayStr.slice(1);
        const timeStr = now.toLocaleTimeString('pt-BR');

        clockContainer.innerHTML = `
            <span class="clock-date-group">
                <i data-feather="calendar" class="clock-icon"></i>
                <span class="clock-date">${capitalizedWeekday}, ${rawDate}</span>
            </span>
            <span class="clock-separator">•</span>
            <span class="clock-time-group">
                <i data-feather="clock" class="clock-icon"></i>
                <span class="clock-time">${timeStr}</span>
            </span>
        `;
        if (window.feather) feather.replace({ 'container': clockContainer });
    };
    setInterval(updateClock, 1000);
    updateClock();

    // --- Controle de Visibilidade das Tarefas ---
    const toggleTasksBtn = document.getElementById('toggle-tasks-btn');
    const tasksSection = document.getElementById('scheduled-tasks-section');
    if (toggleTasksBtn && tasksSection) {
        toggleTasksBtn.addEventListener('click', () => {
            tasksSection.open = !tasksSection.open;
        });
    }

    // --- Gestão de Tarefas Agendadas ---
    let lastRenderedTaskIds = new Set(); // Keep track of rendered task IDs for highlighting new ones
    const scheduledTasksList = document.getElementById('scheduled-tasks-list');

    async function fetchScheduledTasks() {
        if (!scheduledTasksList) return;
        try {
            const response = await fetch(`${API_BASE_URL}/api/scheduled-tasks`);
            const data = await response.json();
            if (data.success) {
                renderScheduledTasks(data.tasks);
            }
        } catch (error) {
            console.error("Erro ao buscar tarefas agendadas:", error);
        }
    }

    function renderScheduledTasks(tasks) {
        if (!scheduledTasksList) return;
        scheduledTasksList.innerHTML = '';
        const pendingTasks = (tasks || []).filter(t => t.status === 'pending');
        const currentTaskIds = new Set(pendingTasks.map(t => t.id));
        
        // Atualiza o badge de contagem na barra do cabeçalho
        const countBadge = document.getElementById('scheduled-tasks-count');
        if (countBadge) {
            countBadge.textContent = pendingTasks.length;
            if (pendingTasks.length > 0) {
                countBadge.classList.add('has-tasks');
            } else {
                countBadge.classList.remove('has-tasks');
            }
        }
        
        if (pendingTasks.length === 0) {
            scheduledTasksList.innerHTML = '<p class="details-text">Nenhum agendamento pendente.</p>';
            lastRenderedTaskIds = currentTaskIds;
            return;
        }

        pendingTasks.forEach(task => {
            const item = document.createElement('div');
            item.className = 'task-item';

            // Se já tínhamos carregado tarefas antes e esta é nova (ID não estava no Set anterior), aplicamos o destaque
            if (lastRenderedTaskIds.size > 0 && !lastRenderedTaskIds.has(task.id)) {
                item.classList.add('new-task-highlight');
            }
            const actionLabel = (typeof ACTION_METADATA !== 'undefined' && ACTION_METADATA[task.action]?.label) || task.action;
            let ips = [];
            try { ips = JSON.parse(task.ips); } catch (e) { ips = [task.ips]; }
            
            item.innerHTML = `
                <div class="task-info">
                    <span class="task-action">${actionLabel}</span>
                    <span class="task-details">${ips.length} máquina(s) selecionada(s)</span>
                    <span class="task-time">⏰ ${task.execution_time ? task.execution_time.replace('T', ' ') : ''}</span>
                </div>
                <button class="cancel-task-btn" data-id="${task.id}" title="Cancelar Agendamento">
                    <i data-feather="trash-2"></i>
                </button>
            `;
            scheduledTasksList.appendChild(item);
        });
        lastRenderedTaskIds = currentTaskIds;
        if (window.feather) feather.replace({ 'container': scheduledTasksList });

        scheduledTasksList.querySelectorAll('.cancel-task-btn').forEach(btn => {
            btn.onclick = async () => {
                if (await showConfirmationModal("Deseja realmente cancelar este agendamento?")) {
                    await cancelTask(btn.dataset.id);
                }
            };
        });
    }

    async function cancelTask(taskId) {
        try {
            const response = await fetch(`${API_BASE_URL}/api/scheduled-tasks/${taskId}`, { method: 'DELETE' });
            const data = await response.json();
            if (data.success) {
                showToast("Agendamento cancelado", "success");
                fetchScheduledTasks();
            }
        } catch (error) {
            showToast("Erro ao cancelar tarefa", "error");
        }
    }

    // --- Reorganização da UI para economizar espaço ---
    // --- Gerenciamento Inteligente de Entrada de Faixas de IP ---
    let detectedSubnetPrefix = '192.168.50.'; // Fallback padrão inicial

    // Função para obter a sub-rede ativa do backend
    async function fetchDetectedSubnetInfo() {
        try {
            const res = await fetch(`${API_BASE_URL}/api/network-info`);
            if (res.ok) {
                const data = await res.json();
                if (data && data.success && data.ip_prefix) {
                    detectedSubnetPrefix = data.ip_prefix;
                    const badge = document.getElementById('detected-subnet-badge');
                    if (badge) {
                        badge.textContent = `${detectedSubnetPrefix}x`;
                        badge.title = `Sub-rede ativa detectada no servidor: ${detectedSubnetPrefix}0/24 (IP Servidor: ${data.server_ip || 'N/A'})`;
                    }
                }
            }
        } catch (e) {
            console.warn('[NetworkInfo] Não foi possível obter info da rede:', e);
        }
    }

    // Parser universal para cálculo de hosts e validação semântica
    function parseIpRangeInput(startVal = '', endVal = '', prefix = detectedSubnetPrefix) {
        startVal = (startVal || '').trim();
        endVal = (endVal || '').trim();

        if (!startVal && !endVal) {
            return { isValid: true, isEmpty: true, count: 0, resolvedText: '', isSingleMode: false };
        }

        const cleanPrefix = prefix.endsWith('.') ? prefix : (prefix + '.');

        // Helper para validar octeto 0-255
        const isValidOctet = (numStr) => {
            if (!/^\d{1,3}$/.test(numStr)) return false;
            const n = parseInt(numStr, 10);
            return n >= 0 && n <= 255;
        };

        // Helper para validar IP completo IPv4
        const isValidIpv4 = (ipStr) => {
            const parts = ipStr.split('.');
            return parts.length === 4 && parts.every(isValidOctet);
        };

        // Caso 1: startVal contém delimitadores compostos (hífen, vírgula, 'a', '/', '*' ou 'x')
        // Nesse caso, tratamos como entrada única completa (Single Mode)
        const hasCompoundNotation = /[,/\\*xX]|\s+(?:a|to|-)\s+|^\d{1,3}\s*-\s*\d{1,3}$|^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\s*-\s*\d{1,3}/i.test(startVal);

        if (hasCompoundNotation || (!endVal && startVal.includes('-')) || startVal.includes('/') || startVal.includes('*')) {
            const parts = startVal.split(',').map(p => p.trim()).filter(Boolean);
            let totalHosts = 0;
            let hasError = false;
            let errorMsg = '';

            for (const part of parts) {
                // CIDR (ex: 192.168.0.0/24 ou /24)
                if (part.includes('/')) {
                    const cidrMatch = part.match(/^(?:(\d{1,3}(?:\.\d{1,3}){3})\/)?(\d{1,2})$/);
                    if (cidrMatch) {
                        const mask = parseInt(cidrMatch[2], 10);
                        if (mask >= 16 && mask <= 32) {
                            const usable = mask === 32 ? 1 : mask === 31 ? 2 : Math.pow(2, 32 - mask) - 2;
                            totalHosts += Math.max(1, usable);
                            continue;
                        }
                    }
                    hasError = true;
                    errorMsg = 'Máscara CIDR inválida (use /16 a /32)';
                    break;
                }

                // Wildcard (ex: 192.168.0.* ou 192.168.0.x)
                if (/^(\d{1,3}\.\d{1,3}\.\d{1,3}\.)[*xX]$/.test(part) || part === '*' || part.toLowerCase() === 'x') {
                    totalHosts += 254;
                    continue;
                }

                // Faixa de octetos curtos (ex: 101-140 ou 101 a 140)
                const octetRangeMatch = part.match(/^(\d{1,3})\s*(?:-|a|to|\s)\s*(\d{1,3})$/i);
                if (octetRangeMatch) {
                    const s = parseInt(octetRangeMatch[1], 10);
                    const e = parseInt(octetRangeMatch[2], 10);
                    if (isValidOctet(octetRangeMatch[1]) && isValidOctet(octetRangeMatch[2])) {
                        totalHosts += Math.abs(e - s) + 1;
                        continue;
                    } else {
                        hasError = true;
                        errorMsg = 'Octeto deve estar entre 0 e 255';
                        break;
                    }
                }

                // Prefixo + faixa de octetos (ex: 192.168.0.101-140)
                const shortRangeMatch = part.match(/^(\d{1,3}\.\d{1,3}\.\d{1,3}\.)(\d{1,3})\s*(?:-|a|to|\s)\s*(\d{1,3})$/i);
                if (shortRangeMatch) {
                    const s = parseInt(shortRangeMatch[2], 10);
                    const e = parseInt(shortRangeMatch[3], 10);
                    if (isValidOctet(shortRangeMatch[2]) && isValidOctet(shortRangeMatch[3])) {
                        totalHosts += Math.abs(e - s) + 1;
                        continue;
                    } else {
                        hasError = true;
                        errorMsg = 'Octeto final deve estar entre 0 e 255';
                        break;
                    }
                }

                // Dois IPs completos (ex: 192.168.0.100 - 192.168.0.150)
                const fullIpMatch = part.match(/^(\d{1,3}(?:\.\d{1,3}){3})\s*(?:-|a|to|\s)\s*(\d{1,3}(?:\.\d{1,3}){3})$/i);
                if (fullIpMatch) {
                    if (isValidIpv4(fullIpMatch[1]) && isValidIpv4(fullIpMatch[2])) {
                        const s4 = parseInt(fullIpMatch[1].split('.')[3], 10);
                        const e4 = parseInt(fullIpMatch[2].split('.')[3], 10);
                        totalHosts += Math.abs(e4 - s4) + 1;
                        continue;
                    } else {
                        hasError = true;
                        errorMsg = 'IPs completos inválidos';
                        break;
                    }
                }

                // Octeto isolado (ex: 105)
                if (isValidOctet(part)) {
                    totalHosts += 1;
                    continue;
                }

                // IP isolado (ex: 192.168.0.105)
                if (isValidIpv4(part)) {
                    totalHosts += 1;
                    continue;
                }

                hasError = true;
                errorMsg = `Formato não reconhecido em '${part}'`;
                break;
            }

            return {
                isValid: !hasError && totalHosts > 0,
                isEmpty: false,
                count: totalHosts,
                errorMsg,
                resolvedText: startVal,
                isSingleMode: true
            };
        }

        // Caso 2: Modo Dual Clássico (Start e End separados)
        if (startVal && endVal) {
            const isStartOctet = isValidOctet(startVal);
            const isEndOctet = isValidOctet(endVal);
            const isStartIp = isValidIpv4(startVal);
            const isEndIp = isValidIpv4(endVal);

            if (isStartOctet && isEndOctet) {
                const s = parseInt(startVal, 10);
                const e = parseInt(endVal, 10);
                const count = Math.abs(e - s) + 1;
                const low = Math.min(s, e);
                const high = Math.max(s, e);
                return {
                    isValid: true,
                    isEmpty: false,
                    count,
                    resolvedText: `${cleanPrefix}${low} a ${cleanPrefix}${high}`,
                    isSingleMode: false
                };
            }

            if (isStartIp && isEndIp) {
                const s4 = parseInt(startVal.split('.')[3], 10);
                const e4 = parseInt(endVal.split('.')[3], 10);
                return {
                    isValid: true,
                    isEmpty: false,
                    count: Math.abs(e4 - s4) + 1,
                    resolvedText: `${startVal} a ${endVal}`,
                    isSingleMode: false
                };
            }

            if (isStartIp && isEndOctet) {
                const parts = startVal.split('.');
                const prefixStr = parts.slice(0, 3).join('.') + '.';
                const s4 = parseInt(parts[3], 10);
                const e4 = parseInt(endVal, 10);
                return {
                    isValid: true,
                    isEmpty: false,
                    count: Math.abs(e4 - s4) + 1,
                    resolvedText: `${startVal} a ${prefixStr}${e4}`,
                    isSingleMode: false
                };
            }

            return {
                isValid: false,
                isEmpty: false,
                count: 0,
                errorMsg: 'Valores inicial e final incompatíveis (use octetos 0-255 ou IPs válidos)',
                resolvedText: `${startVal} a ${endVal}`,
                isSingleMode: false
            };
        }

        // Caso 3: Apenas Start preenchido (único octeto ou IP isolado)
        if (startVal && !endVal) {
            if (isValidOctet(startVal)) {
                return {
                    isValid: true,
                    isEmpty: false,
                    count: 1,
                    resolvedText: `${cleanPrefix}${startVal}`,
                    isSingleMode: false
                };
            }
            if (isValidIpv4(startVal)) {
                return {
                    isValid: true,
                    isEmpty: false,
                    count: 1,
                    resolvedText: startVal,
                    isSingleMode: false
                };
            }
            return {
                isValid: false,
                isEmpty: false,
                count: 0,
                errorMsg: 'Octeto (0-255) ou IP completo inválido',
                resolvedText: startVal,
                isSingleMode: false
            };
        }

        return { isValid: true, isEmpty: true, count: 0, resolvedText: '', isSingleMode: false };
    }

    // Helper global para obter a string de faixa configurada atual
    function getComputedCustomRange() {
        const rangeStart = document.getElementById('network-range-start');
        const rangeEnd = document.getElementById('network-range-end');
        const startVal = rangeStart ? rangeStart.value.trim() : '';
        const endVal = rangeEnd ? rangeEnd.value.trim() : '';

        if (!startVal && !endVal) return '';

        const parseResult = parseIpRangeInput(startVal, endVal, detectedSubnetPrefix);
        if (parseResult.isSingleMode) {
            return startVal;
        }
        if (startVal && endVal) {
            return `${startVal} a ${endVal}`;
        }
        return startVal;
    }

    // --- Reorganização da UI para economizar espaço e inicialização de controles ---
    const ipListSection = document.querySelector('.ip-list-section');
    if (ipListSection) {
        const header = ipListSection.querySelector('h3');
        const controls = ipListSection.querySelector('.ip-list-controls');
        const rangeStart = document.getElementById('network-range-start');
        const rangeEnd = document.getElementById('network-range-end');
        const countBadge = document.getElementById('ip-range-count-badge');
        const rangeWrapper = document.getElementById('main-range-input-wrapper') || document.querySelector('.range-input-wrapper');

        if (rangeStart && rangeEnd) {
            // Carrega o valor salvo anteriormente no navegador
            const savedRange = localStorage.getItem('customNetworkRange') || '';
            if (savedRange.includes(' a ')) {
                const [s, e] = savedRange.split(' a ');
                rangeStart.value = s.trim();
                rangeEnd.value = e.trim();
            } else {
                rangeStart.value = savedRange.trim();
            }

            // Atualizador em tempo real de feedback visual e contador de IPs
            const validateAndRenderFeedback = () => {
                const startVal = rangeStart.value.trim();
                const endVal = rangeEnd.value.trim();
                const refreshBtn = document.getElementById('refresh-btn');
                const isBtnLoading = refreshBtn?.classList.contains('loading');
                
                const parseResult = parseIpRangeInput(startVal, endVal, detectedSubnetPrefix);

                // Alterna modo de exibição único/duplo dinamicamente
                if (rangeWrapper) {
                    rangeWrapper.classList.toggle('single-mode', Boolean(parseResult.isSingleMode && !endVal));
                }

                if (parseResult.isEmpty) {
                    rangeWrapper?.classList.remove('valid', 'invalid');
                    if (countBadge) {
                        countBadge.classList.add('hidden');
                        countBadge.textContent = '';
                    }
                    if (refreshBtn && !isBtnLoading) {
                        refreshBtn.disabled = false;
                        refreshBtn.setAttribute('data-tooltip', 'Recarregar lista de dispositivos na rede atual');
                    }
                    return;
                }

                rangeWrapper?.classList.toggle('valid', parseResult.isValid);
                rangeWrapper?.classList.toggle('invalid', !parseResult.isValid);

                if (countBadge) {
                    countBadge.classList.remove('hidden', 'count-success', 'count-info', 'count-warning', 'count-danger');
                    if (parseResult.isValid) {
                        const count = parseResult.count;
                        countBadge.textContent = `${count} ${count === 1 ? 'host' : 'hosts'}`;
                        countBadge.title = `Alvos estimados: ${count} dispositivo(s) (${parseResult.resolvedText})`;

                        if (count <= 40) {
                            countBadge.classList.add('count-success');
                        } else if (count <= 254) {
                            countBadge.classList.add('count-info');
                        } else if (count <= 512) {
                            countBadge.classList.add('count-warning');
                            countBadge.title += ' - Faixa ampla: varredura pode levar alguns segundos.';
                        } else {
                            countBadge.classList.add('count-danger');
                            countBadge.title += ' - Atenção: faixa muito grande (>512).';
                        }
                    } else {
                        countBadge.textContent = 'Inválido';
                        countBadge.title = parseResult.errorMsg || 'Formato de faixa inválido. Use: 101-140, 192.168.1.x, ou /24';
                        countBadge.classList.add('count-danger');
                    }
                }

                // Salva no localStorage quando válido
                if (parseResult.isValid) {
                    const combined = (startVal && endVal) ? `${startVal} a ${endVal}` : startVal;
                    localStorage.setItem('customNetworkRange', combined);
                }

                if (refreshBtn && !isBtnLoading) {
                    refreshBtn.disabled = !parseResult.isValid;
                    refreshBtn.setAttribute('data-tooltip', parseResult.isValid ? 
                        `Buscar dispositivos na faixa (${parseResult.count} alvos)` : 
                        (parseResult.errorMsg || 'Formato inválido. Ex: 101-140, 192.168.1.x, /24'));
                }
            };

            rangeStart.addEventListener('input', validateAndRenderFeedback);
            rangeEnd.addEventListener('input', validateAndRenderFeedback);

            // Ergonomia de teclado inteligente:
            // Digitar hífen, 'a ' ou espaço no campo início avança suavemente para o campo fim
            rangeStart.addEventListener('keydown', (e) => {
                if ((e.key === '-' || e.key === 'Tab') && rangeStart.value.trim() && !rangeEnd.value) {
                    if (e.key === '-') {
                        // Se for apenas um número curto, avança para o fim
                        if (/^\d{1,3}$/.test(rangeStart.value.trim())) {
                            e.preventDefault();
                            rangeEnd.focus();
                            rangeEnd.select();
                        }
                    }
                }
                if (e.key === 'Escape') {
                    clearRangeBtn?.click();
                }
                if (e.key === 'Enter') {
                    const refreshBtn = document.getElementById('refresh-btn');
                    if (refreshBtn && !refreshBtn.disabled) refreshBtn.click();
                }
            });

            rangeEnd.addEventListener('keydown', (e) => {
                if (e.key === 'Backspace' && !rangeEnd.value) {
                    rangeStart.focus();
                }
                if (e.key === 'Escape') {
                    clearRangeBtn?.click();
                }
                if (e.key === 'Enter') {
                    const refreshBtn = document.getElementById('refresh-btn');
                    if (refreshBtn && !refreshBtn.disabled) refreshBtn.click();
                }
            });

            // Função auxiliar para disparar busca e atualização imediata da lista
            function triggerIpListReload() {
                const refreshBtn = document.getElementById('refresh-btn');
                if (typeof fetchAndDisplayIps === 'function') {
                    fetchAndDisplayIps();
                } else if (refreshBtn && !refreshBtn.disabled) {
                    refreshBtn.click();
                }
            }

            // Botão de limpar inputs
            const clearRangeBtn = document.getElementById('clear-range-btn');
            if (clearRangeBtn) {
                clearRangeBtn.addEventListener('click', () => {
                    rangeStart.value = '';
                    rangeEnd.value = '';
                    localStorage.removeItem('customNetworkRange');
                    validateAndRenderFeedback();
                    rangeStart.focus();
                    if (typeof showToast === 'function') {
                        showToast('Faixa de IP redefinida para detecção automática.', 'info', 2500);
                    }
                    triggerIpListReload();
                });
            }

            // Presets rápidos (Chips de sub-rede)
            document.querySelectorAll('.ip-preset-chip').forEach(chip => {
                chip.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const targetRange = chip.getAttribute('data-range');
                    if (targetRange) {
                        if (targetRange.includes('-')) {
                            const [s, eVal] = targetRange.split('-');
                            rangeStart.value = s.trim();
                            rangeEnd.value = eVal.trim();
                        } else {
                            rangeStart.value = targetRange.trim();
                            rangeEnd.value = '';
                        }
                        validateAndRenderFeedback();
                        const dropdownMenu = document.getElementById('ip-range-dropdown-menu');
                        const toggleBtn = document.getElementById('ip-range-dropdown-toggle');
                        dropdownMenu?.classList.add('hidden');
                        toggleBtn?.classList.remove('open');
                        document.getElementById('main-range-input-wrapper')?.classList.remove('dropdown-open');
                        if (typeof showToast === 'function') {
                            showToast(`Atalho aplicado: ${targetRange}. Buscando dispositivos...`, 'success', 2500);
                        }
                        triggerIpListReload();
                    }
                });
            });

            // Inicializa dropdown e carrega subnet info
            initIpRangeDropdown();
            fetchDetectedSubnetInfo().then(() => validateAndRenderFeedback());
            validateAndRenderFeedback();
        }
        
        const instruction = Array.from(ipListSection.querySelectorAll('p')).find(p => 
            p.textContent.toLowerCase().includes('marque os ips')
        );
        if (instruction) instruction.remove();
        if (header && controls) {
            const newHeaderWrapper = document.createElement('div');
            newHeaderWrapper.className = 'ip-list-header';
            newHeaderWrapper.appendChild(header);
            newHeaderWrapper.appendChild(controls);
            ipListSection.prepend(newHeaderWrapper);
        }
    }

    console.log(`[Config] API_BASE_URL: ${API_BASE_URL}`);

    // Helper simples para sanitização de HTML
    const safeText = (str) => String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

    // --- Gerenciamento de Faixas de IP Mais Usadas & Favoritas (Lookup Dropdown) ---
    async function fetchFrequentIpRanges() {
        const dropdownMenu = document.getElementById('ip-range-dropdown-menu');
        const dropdownList = document.getElementById('ip-range-dropdown-list');
        const datalistStart = document.getElementById('frequent-ranges-start-list');
        const datalistEnd = document.getElementById('frequent-ranges-end-list');

        if (!dropdownList) return;

        try {
            const response = await fetch(`${API_BASE_URL}/api/ip-ranges`);
            const data = await response.json();
            
            let ranges = (data && data.success && Array.isArray(data.ranges)) ? data.ranges : [];
            
            if (ranges.length === 0) {
                try {
                    ranges = JSON.parse(localStorage.getItem('frequentIpRangesHistory') || '[]');
                } catch(e) { ranges = []; }
            } else {
                localStorage.setItem('frequentIpRangesHistory', JSON.stringify(ranges));
            }

            dropdownList.innerHTML = '';
            if (datalistStart) datalistStart.innerHTML = '';
            if (datalistEnd) datalistEnd.innerHTML = '';

            if (ranges.length === 0) {
                dropdownList.innerHTML = '<li class="ip-range-empty">Nenhuma faixa gravada ainda</li>';
                return;
            }

            ranges.forEach(item => {
                const rangeStr = item.range_str;
                const count = item.usage_count || 1;
                const startVal = item.range_start || '';
                const endVal = item.range_end || '';
                const label = item.label || '';
                const isFavorite = Boolean(item.is_favorite);

                const li = document.createElement('li');
                li.className = `ip-range-item ${isFavorite ? 'is-favorite' : ''}`;
                li.innerHTML = `
                    <div class="ip-range-info">
                        ${label ? `<div class="ip-range-label-row"><span class="ip-range-label">${safeText(label)}</span></div>` : ''}
                        <span class="ip-range-text" title="${safeText(rangeStr)}">${safeText(rangeStr)}</span>
                    </div>
                    <div class="ip-range-actions">
                        <span class="ip-range-badge">${count}×</span>
                        <button type="button" class="ip-range-star-btn ${isFavorite ? 'active' : ''}" title="${isFavorite ? 'Remover dos favoritos' : 'Fixar como favorito'}">
                            <i data-feather="star"></i>
                        </button>
                        <button type="button" class="ip-range-delete-btn" title="Remover esta faixa">
                            <i data-feather="x"></i>
                        </button>
                    </div>
                `;

                // Clique para selecionar a faixa
                li.addEventListener('click', (e) => {
                    if (e.target.closest('.ip-range-delete-btn') || e.target.closest('.ip-range-star-btn')) return;

                    const rangeStartInput = document.getElementById('network-range-start');
                    const rangeEndInput = document.getElementById('network-range-end');

                    if (rangeStr.includes(' a ')) {
                        const parts = rangeStr.split(' a ');
                        if (rangeStartInput) rangeStartInput.value = parts[0].trim();
                        if (rangeEndInput) rangeEndInput.value = parts[1].trim();
                    } else if (startVal || endVal) {
                        if (rangeStartInput) rangeStartInput.value = startVal;
                        if (rangeEndInput) rangeEndInput.value = endVal;
                    } else {
                        if (rangeStartInput) rangeStartInput.value = rangeStr;
                        if (rangeEndInput) rangeEndInput.value = '';
                    }

                    const toggleBtn = document.getElementById('ip-range-dropdown-toggle');
                    dropdownMenu?.classList.add('hidden');
                    toggleBtn?.classList.remove('open');
                    document.getElementById('main-range-input-wrapper')?.classList.remove('dropdown-open');

                    if (rangeStartInput) {
                        rangeStartInput.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                    if (typeof showToast === 'function') {
                        showToast(`Faixa selecionada: ${label ? label + ' (' + rangeStr + ')' : rangeStr}. Recarregando...`, 'info', 2500);
                    }
                    const refreshBtn = document.getElementById('refresh-btn');
                    if (refreshBtn && !refreshBtn.disabled) {
                        refreshBtn.click();
                    }
                });

                // Botão de Favoritar (Star)
                const starBtn = li.querySelector('.ip-range-star-btn');
                if (starBtn) {
                    starBtn.addEventListener('click', async (e) => {
                        e.stopPropagation();
                        try {
                            const res = await fetch(`${API_BASE_URL}/api/ip-ranges/favorite`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ range_str: rangeStr })
                            });
                            const favData = await res.json();
                            if (favData.success) {
                                fetchFrequentIpRanges();
                            }
                        } catch (err) {
                            console.error('[toggleFavorite] Erro:', err);
                        }
                    });
                }

                // Botão de Excluir Faixa
                const deleteBtn = li.querySelector('.ip-range-delete-btn');
                if (deleteBtn) {
                    deleteBtn.addEventListener('click', async (e) => {
                        e.stopPropagation();
                        await deleteFrequentIpRange(rangeStr);
                    });
                }

                dropdownList.appendChild(li);

                if (startVal && datalistStart) {
                    const optStart = document.createElement('option');
                    optStart.value = startVal;
                    optStart.label = label ? `${label} (${rangeStr})` : rangeStr;
                    datalistStart.appendChild(optStart);
                }
                if (endVal && datalistEnd) {
                    const optEnd = document.createElement('option');
                    optEnd.value = endVal;
                    optEnd.label = label ? `${label} (${rangeStr})` : rangeStr;
                    datalistEnd.appendChild(optEnd);
                }
            });

            if (typeof feather !== 'undefined') {
                feather.replace();
            }
        } catch (err) {
            console.error('[fetchFrequentIpRanges] Erro ao carregar faixas de IP:', err);
        }
    }

    async function saveFrequentIpRange(start, end, customRange, label = '') {
        const rangeStr = customRange || ((start && end) ? `${start} a ${end}` : start);
        if (!rangeStr) return;

        try {
            await fetch(`${API_BASE_URL}/api/ip-ranges`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ start, end, range_str: rangeStr, label })
            });
            fetchFrequentIpRanges();
        } catch (err) {
            console.warn('[saveFrequentIpRange] Falha ao sincronizar faixa:', err);
        }
    }

    async function deleteFrequentIpRange(rangeStr) {
        if (!rangeStr) return;
        try {
            await fetch(`${API_BASE_URL}/api/ip-ranges`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ range_str: rangeStr })
            });
            if (typeof showToast === 'function') {
                showToast(`Faixa '${rangeStr}' removida do histórico.`, 'info');
            }
            fetchFrequentIpRanges();
        } catch (err) {
            console.error('[deleteFrequentIpRange] Erro ao excluir faixa:', err);
        }
    }

    function initIpRangeDropdown() {
        const toggleBtn = document.getElementById('ip-range-dropdown-toggle');
        const dropdownMenu = document.getElementById('ip-range-dropdown-menu');
        const rangeWrapper = document.getElementById('main-range-input-wrapper') || toggleBtn?.closest('.range-input-wrapper');

        if (!toggleBtn || !dropdownMenu) return;

        const openMenu = () => {
            fetchFrequentIpRanges();
            dropdownMenu.classList.remove('hidden');
            toggleBtn.classList.add('open');
            rangeWrapper?.classList.add('dropdown-open');
            rangeWrapper?.closest('.controls-group')?.classList.add('dropdown-open');
            rangeWrapper?.closest('.ip-list-controls')?.classList.add('dropdown-open');
            rangeWrapper?.closest('.ip-list-section')?.classList.add('dropdown-open');
        };

        const closeMenu = () => {
            dropdownMenu.classList.add('hidden');
            toggleBtn.classList.remove('open');
            rangeWrapper?.classList.remove('dropdown-open');
            rangeWrapper?.closest('.controls-group')?.classList.remove('dropdown-open');
            rangeWrapper?.closest('.ip-list-controls')?.classList.remove('dropdown-open');
            rangeWrapper?.closest('.ip-list-section')?.classList.remove('dropdown-open');
        };

        toggleBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const isHidden = dropdownMenu.classList.contains('hidden');
            if (isHidden) {
                openMenu();
            } else {
                closeMenu();
            }
        });

        document.addEventListener('click', (e) => {
            if (!dropdownMenu.classList.contains('hidden')) {
                if (!dropdownMenu.contains(e.target) && !toggleBtn.contains(e.target)) {
                    closeMenu();
                }
            }
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !dropdownMenu.classList.contains('hidden')) {
                closeMenu();
            }
        });

        fetchFrequentIpRanges();
    }


    // Helper global para obter SVG do Feather sem disparar scan do DOM
    const getIconSvg = (name, options = { width: 14, height: 14 }) => {
        if (window.feather && feather.icons && feather.icons[name]) {
            return feather.icons[name].toSvg(options);
        }
        return `<i data-feather="${name}"></i>`;
    };

    // Socket.IO compartilhado para eventos em tempo real e ações em lote de alto desempenho
    let dashboardSocket = null;
    function getDashboardSocket() {
        if (!dashboardSocket && typeof io !== 'undefined') {
            try {
                dashboardSocket = io({
                    transports: ['websocket', 'polling'],
                    reconnection: true,
                    reconnectionDelay: 1000,
                    reconnectionAttempts: 25
                });
                dashboardSocket.on('connect', () => {
                    console.log('[Dashboard Socket] Conectado com sucesso ao backend Socket.IO via', dashboardSocket.io?.engine?.transport?.name);
                });
            } catch (e) {
                console.warn('[Dashboard Socket] Falha ao instanciar Socket.IO:', e);
            }
        }
        return dashboardSocket;
    }
    // Inicialização proativa da conexão WebSocket
    getDashboardSocket();

    // Variáveis globais de estado das ações
    let STREAMING_ACTIONS = [];
    let DANGEROUS_ACTIONS = [];
    let ACTION_METADATA = {};

    // Descrições amigáveis para os tooltips das ações (ainda aqui por enquanto, para simplificar o diff)
    const ACTION_DESCRIPTIONS = {
        [ACTIONS.DISABLE_SHORTCUTS]: 'Bloqueia atalhos como Alt+Tab e Tecla Windows',
        [ACTIONS.ENABLE_SHORTCUTS]: 'Restaura o funcionamento de todos os atalhos',
        [ACTIONS.SHOW_SYSTEM_ICONS]: 'Exibe ícones na área de trabalho',
        [ACTIONS.HIDE_SYSTEM_ICONS]: 'Oculta ícones para um visual mais limpo',
        [ACTIONS.SHUTDOWN]: 'Desliga os computadores selecionados imediatamente',
        [ACTIONS.REBOOT]: 'Reinicia os computadores selecionados',
        [ACTIONS.WAKE_ON_LAN]: 'Envia sinal mágico para ligar máquinas via rede',
        [ACTIONS.SEND_MESSAGE]: 'Exibe um pop-up com mensagem na tela dos usuários',
        [ACTIONS.KILL_PROCESS]: 'Força o encerramento de um programa pelo nome',
        [ACTIONS.SET_WALLPAPER]: 'Altera o plano de fundo da área de trabalho',
        [ACTIONS.LOCK_TASKBAR]: 'Impede modificações na barra de tarefas',
        [ACTIONS.UNLOCK_TASKBAR]: 'Permite modificações na barra de tarefas',
        [ACTIONS.DISABLE_PERIPHERALS]: 'Desativa portas USB e armazenamento externo',
        [ACTIONS.ENABLE_PERIPHERALS]: 'Reativa o uso de portas USB',
        [ACTIONS.UPDATE_SYSTEM]: 'Atualiza pacotes do sistema (apt update/upgrade)',
        [ACTIONS.INSTALL_MONITOR_TOOLS]: 'Instala ferramentas de monitoramento remoto',
        [ACTIONS.BACKUP_APLICACAO]: 'Cria um backup local deste servidor',
        [ACTIONS.SCAN_MULTISEAT]: 'Gerencia assentos e dispositivos (Multiseat)',
        [ACTIONS.ATTACH_SEAT_DEVICE]: 'Vincula um dispositivo USB a um assento específico',
        [ACTIONS.SET_FIREFOX_DEFAULT]: 'Define o Firefox como navegador padrão',
        [ACTIONS.SET_CHROME_DEFAULT]: 'Define o Chrome como navegador padrão',
        [ACTIONS.DISABLE_RIGHT_CLICK]: 'Desabilita o menu de contexto (botão direito)',
        [ACTIONS.ENABLE_RIGHT_CLICK]: 'Habilita o menu de contexto (botão direito)',
        [ACTIONS.SYNC_TIME]: 'Força a sincronização imediata do relógio via NTP',
        [ACTIONS.UNINSTALL_CALCULATOR]: 'Remove a calculadora do sistema',
        [ACTIONS.INSTALL_CALCULATOR]: 'Instala a calculadora do GNOME',
        [ACTIONS.MONITOR_NETWORK]: 'Exibe o tráfego de entrada/saída (KB/s) em tempo real por 15 segundos',
        [ACTIONS.LOCK_KEYBINDINGS]: 'Bloqueia combinações de teclas como Alt+Tab, Alt+F4, Tecla Windows e Ctrl+Alt+T',
        [ACTIONS.UNLOCK_KEYBINDINGS]: 'Restaura o funcionamento padrão de todas as combinações de teclas',
    };

    // Elementos do novo overlay de erro do backend
    const backendErrorOverlay = document.getElementById('backend-error-overlay');
    const retryBackendConnectionBtn = document.getElementById('retry-backend-connection-btn');

    /**
     * Toca um som sutil de notificação usando Web Audio API.
     * Isso evita a dependência de arquivos externos e garante que o som funcione
     * mesmo quando o servidor está inacessível.
     */
    function playAlertSound() {
        try {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (!AudioContext) return;
            
            const ctx = new AudioContext();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();

            osc.type = 'sine';
            // Frequência de 660Hz (E5) descendo para 330Hz (E4) em 0.3s
            osc.frequency.setValueAtTime(660, ctx.currentTime); 
            osc.frequency.exponentialRampToValueAtTime(330, ctx.currentTime + 0.3);
            
            gain.gain.setValueAtTime(0.1, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);

            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.3);
        } catch (e) {
            // Navegadores bloqueiam áudio sem interação prévia do usuário.
            // Como este dashboard requer interações, o áudio funcionará na maioria dos casos.
        }
    }

    /**
     * Toca um som de confirmação sutil para interações da UI.
     */
    function playConfirmSound() {
        try {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (!AudioContext) return;
            
            const ctx = new AudioContext();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();

            osc.type = 'sine';
            // Frequência de 880Hz (A5) descendo para 440Hz (A4) em apenas 0.1s
            osc.frequency.setValueAtTime(880, ctx.currentTime); 
            osc.frequency.exponentialRampToValueAtTime(440, ctx.currentTime + 0.1);
            
            gain.gain.setValueAtTime(0.05, ctx.currentTime); // Volume mais baixo que o alerta
            gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.1);

            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.1);
        } catch (e) {}
    }

    async function loadMetadata() {
        console.log(`[Conexão] Tentando carregar metadados de: ${API_BASE_URL}/api/metadata`);
        const logo = document.querySelector('.app-logo, .logo-fallback-icon');
        try {
            let response;
            try {
                response = await fetch(`${API_BASE_URL}/api/metadata`);
            } catch (initialErr) {
                const fallbackUrls = [
                    `http://${API_HOST}:5050`,
                    'http://127.0.0.1:5050',
                    'http://localhost:5050',
                    `http://${API_HOST}:8000`,
                    'http://127.0.0.1:8000'
                ];
                let reconnected = false;
                for (const fbUrl of fallbackUrls) {
                    if (fbUrl === API_BASE_URL) continue;
                    try {
                        console.warn(`[Conexão] Tentando fallback em ${fbUrl}...`);
                        const fbRes = await fetch(`${fbUrl}/api/metadata`);
                        if (fbRes && fbRes.ok) {
                            response = fbRes;
                            API_BASE_URL = fbUrl;
                            window._API_BASE_URL = fbUrl;
                            reconnected = true;
                            break;
                        }
                    } catch (fbErr) {}
                }
                if (!reconnected && (!response || !response.ok)) {
                    throw initialErr;
                }
            }

            if (!response || !response.ok) throw new Error(`HTTP ${response ? response.status : 'desconhecido'}`);
            
            const data = await response.json();
            if (data.success) {
                ACTION_METADATA = data.metadata;
                renderDynamicActionMenu(data.metadata);
                STREAMING_ACTIONS = Object.keys(data.metadata).filter(k => data.metadata[k].is_streaming || k.includes('install') || k.includes('atualizar'));
                DANGEROUS_ACTIONS = Object.keys(data.metadata).filter(k => data.metadata[k].is_dangerous || k === 'desligar' || k === 'reiniciar');
                window.recentCommitsData = data.recent_commits || [];
                displayAppVersion(data.version, data.branch, data.commit_date, data.commit_msg, data.commit_hash, data.commit_author);
                if (logo) logo.classList.remove('logo-error-glow');
                backendErrorOverlay.classList.add('hidden');
                console.log("[Conexão] Metadados carregados com sucesso.");
            }
        } catch (e) {
            console.error(`[Erro de Conexão] Falha ao conectar ao backend em ${API_BASE_URL}:`, e);
            if (logo) logo.classList.add('logo-error-glow');
            playAlertSound();
            logStatusMessage(`Falha ao carregar metadados das ações. Verifique se o servidor está rodando em ${API_BASE_URL}`, "error");
            backendErrorOverlay.classList.remove('hidden');
        } finally {
            console.log("[Conexão] Inicialização de metadados finalizada.");
        }
    }

    /**
     * Retorna a classe CSS de grupo com base na categoria da ação definida no metadado ou no optgroup.
     */
    function getCategoryClass(actionKey) {
        const meta = (typeof ACTION_METADATA !== 'undefined') ? ACTION_METADATA[actionKey] : null;
        if (meta && meta.category) {
            const cleanCat = meta.category.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, '-');
            return `group-${cleanCat}`;
        }
        if (typeof actionSelect !== 'undefined' && actionSelect) {
            const opt = actionSelect.querySelector(`option[value="${actionKey}"]`);
            if (opt && opt.parentElement && opt.parentElement.tagName === 'OPTGROUP') {
                const optgroup = opt.parentElement;
                if (optgroup.className && optgroup.className.startsWith('group-')) {
                    return optgroup.className;
                }
                const label = optgroup.label || '';
                const clean = label.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, '-');
                return `group-${clean}`;
            }
        }
        return '';
    }

    let selectedGitCommit = null;
    let currentAppCommitHash = null;

    function renderGitCommitsList(commits = []) {
        const listEl = document.getElementById('git-commits-list');
        const restoreBtn = document.getElementById('restore-git-commit-btn');
        const restoreBtnText = document.getElementById('restore-git-commit-btn-text');
        if (!listEl) return;
        const list = (commits && commits.length > 0) ? commits : (window.recentCommitsData || []);
        if (list.length === 0) {
            listEl.innerHTML = '<p style="text-align:center; color:#94a3b8; font-size:0.8rem; padding:20px;">Carregando histórico de commits do repositório...</p>';
            if (restoreBtn) {
                restoreBtn.disabled = true;
                restoreBtn.setAttribute('disabled', 'true');
            }
            return;
        }

        // Se ainda não houver commit selecionado, seleciona o primeiro por padrão
        if (!selectedGitCommit && list.length > 0) {
            selectedGitCommit = list[0];
        }

        const updateRestoreButtonState = () => {
            if (!restoreBtn) return;
            if (!selectedGitCommit) {
                restoreBtn.disabled = true;
                restoreBtn.setAttribute('disabled', 'true');
                if (restoreBtnText) restoreBtnText.textContent = 'Restaurar Commit';
                return;
            }

            const isCurrent = currentAppCommitHash && (
                selectedGitCommit.hash.toLowerCase() === currentAppCommitHash.toLowerCase() ||
                currentAppCommitHash.toLowerCase().startsWith(selectedGitCommit.hash.toLowerCase()) ||
                selectedGitCommit.hash.toLowerCase().startsWith(currentAppCommitHash.toLowerCase())
            );

            // Sempre habilita o botão para o commit selecionado
            restoreBtn.disabled = false;
            restoreBtn.removeAttribute('disabled');
            restoreBtn.style.opacity = '1';
            restoreBtn.style.cursor = 'pointer';
            restoreBtn.style.pointerEvents = 'auto';

            if (restoreBtnText) {
                restoreBtnText.textContent = isCurrent
                    ? `Restaurar para ${selectedGitCommit.hash} (Atual)`
                    : `Restaurar para ${selectedGitCommit.hash}`;
            }
        };

        listEl.innerHTML = list.map((c, idx) => {
            const isLatest = idx === 0;
            const isCurrent = currentAppCommitHash && (
                c.hash.toLowerCase() === currentAppCommitHash.toLowerCase() ||
                currentAppCommitHash.toLowerCase().startsWith(c.hash.toLowerCase()) ||
                c.hash.toLowerCase().startsWith(currentAppCommitHash.toLowerCase())
            );
            const isSelected = selectedGitCommit && selectedGitCommit.hash === c.hash;

            return `
                <div class="git-commit-card ${isLatest ? 'is-latest' : ''} ${isSelected ? 'is-selected' : ''}" 
                     data-hash="${c.hash}" 
                     data-message="${encodeURIComponent(c.message || '')}"
                     data-date="${encodeURIComponent(c.date || '')}"
                     data-author="${encodeURIComponent(c.author || '')}">
                    <div class="git-commit-card-header">
                        <span class="commit-hash" style="font-size:0.82rem; font-weight:700;">${c.hash}</span>
                        ${isCurrent ? '<span class="current-commit-pill">COMMIT ATUAL</span>' : ''}
                        ${isLatest && !isCurrent ? '<span class="latest-commit-pill">ÚLTIMO COMMIT</span>' : ''}
                        <span class="git-commit-card-meta" style="margin-left:auto;">${c.date}</span>
                    </div>
                    <div class="git-commit-card-title">${c.message || 'Sem mensagem'}</div>
                    <div class="git-commit-card-footer">
                        <div class="git-commit-card-meta">
                            <span>${getIconSvg('user', { width: 12, height: 12 })} ${c.author || 'Autor'}</span>
                        </div>
                        <button type="button" 
                                class="git-commit-restore-btn ${isCurrent ? 'is-current' : ''}" 
                                data-restore-hash="${c.hash}"
                                data-restore-msg="${encodeURIComponent(c.message || '')}"
                                title="Restaurar a aplicação para este commit">
                            ${getIconSvg('rotate-ccw', { width: 12, height: 12 })} ${isCurrent ? 'Reaplicar' : 'Restaurar'}
                        </button>
                    </div>
                </div>
            `;
        }).join('');

        if (window.feather) feather.replace({ container: listEl });
        updateRestoreButtonState();

        // Delegação de clique segura no container da lista
        listEl.onclick = (e) => {
            const card = e.target.closest('.git-commit-card');
            if (!card) return;

            const restoreBtnClicked = e.target.closest('.git-commit-restore-btn');
            const hash = card.dataset.hash;
            const message = decodeURIComponent(card.dataset.message || '');
            const date = decodeURIComponent(card.dataset.date || '');
            const author = decodeURIComponent(card.dataset.author || '');

            selectedGitCommit = { hash, message, date, author };

            listEl.querySelectorAll('.git-commit-card').forEach(cEl => {
                cEl.classList.toggle('is-selected', cEl.dataset.hash === hash);
            });

            updateRestoreButtonState();

            if (restoreBtnClicked) {
                e.stopPropagation();
                triggerGitCommitRestore(hash, message);
            }
        };
    }

    async function triggerGitCommitRestore(hash, message) {
        if (!hash) return;

        const confirmMsg = `Deseja realmente restaurar a aplicação para o commit ${hash}?\n\n"${message || 'Sem mensagem'}"\n\n⚠️ Todos os arquivos do projeto serão revertidos para esta versão e o servidor será reiniciado.`;
        const confirmed = await showConfirmationModal(confirmMsg);
        if (!confirmed) return;

        const restoreBtn = document.getElementById('restore-git-commit-btn');
        const restoreBtnText = document.getElementById('restore-git-commit-btn-text');
        if (restoreBtn) {
            restoreBtn.disabled = true;
            restoreBtn.setAttribute('disabled', 'true');
        }
        if (restoreBtnText) restoreBtnText.textContent = 'Restaurando...';

        showToast(`⏳ Restaurando para o commit ${hash}... O servidor será reiniciado.`, 'info', 6000);

        try {
            const res = await fetch(`${API_BASE_URL || ''}/api/git/restore-commit`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ hash })
            });
            const data = await res.json();
            if (res.ok && data.success) {
                showToast(`✅ ${data.message || 'Restaurado com sucesso!'}`, 'success', 8000);
                setTimeout(() => {
                    window.location.reload();
                }, 2500);
            } else {
                showToast(`❌ ${data.message || 'Falha ao restaurar commit.'}`, 'error', 6000);
                if (restoreBtn) {
                    restoreBtn.disabled = false;
                    restoreBtn.removeAttribute('disabled');
                }
                if (restoreBtnText) restoreBtnText.textContent = `Restaurar para ${hash}`;
            }
        } catch (err) {
            console.error('[Git Restore] Erro:', err);
            showToast(`❌ Falha de conexão ao tentar restaurar: ${err.message}`, 'error', 6000);
            if (restoreBtn) {
                restoreBtn.disabled = false;
                restoreBtn.removeAttribute('disabled');
            }
            if (restoreBtnText) restoreBtnText.textContent = `Restaurar para ${hash}`;
        }
    }

    async function openGitCommitsModal() {
        const modal = document.getElementById('git-commits-modal');
        if (!modal) return;
        modal.classList.remove('hidden');
        renderGitCommitsList();

        const restoreBtn = document.getElementById('restore-git-commit-btn');
        if (restoreBtn) {
            restoreBtn.onclick = (e) => {
                e.preventDefault();
                if (selectedGitCommit) {
                    triggerGitCommitRestore(selectedGitCommit.hash, selectedGitCommit.message);
                }
            };
        }

        if (!window.recentCommitsData || window.recentCommitsData.length === 0) {
            try {
                const res = await fetch(`${API_BASE_URL || ''}/api/metadata`);
                if (res.ok) {
                    const data = await res.json();
                    if (data && data.recent_commits) {
                        window.recentCommitsData = data.recent_commits;
                        renderGitCommitsList(data.recent_commits);
                        if (data.branch) {
                            const branchInfoEl = document.getElementById('git-commits-branch-info');
                            if (branchInfoEl) branchInfoEl.textContent = `Branch: ${data.branch}`;
                        }
                    }
                }
            } catch (err) {
                console.error('[Git Commits Modal] Falha ao carregar commits:', err);
            }
        }
    }

    function closeGitCommitsModal() {
        const modal = document.getElementById('git-commits-modal');
        if (modal) modal.classList.add('hidden');
    }

    window.openGitCommitsModal = openGitCommitsModal;
    window.closeGitCommitsModal = closeGitCommitsModal;
    window.triggerGitCommitRestore = triggerGitCommitRestore;

    // Delegação de evento global para abrir/fechar o modal de commits e disparar ações
    document.addEventListener('click', (e) => {
        const commitBtn = e.target.closest('#footer-commit-badge, .commit-badge');
        if (commitBtn) {
            e.preventDefault();
            e.stopPropagation();
            openGitCommitsModal();
            return;
        }
        const restoreGitBtn = e.target.closest('#restore-git-commit-btn');
        if (restoreGitBtn) {
            e.preventDefault();
            e.stopPropagation();
            if (selectedGitCommit) {
                triggerGitCommitRestore(selectedGitCommit.hash, selectedGitCommit.message);
            }
            return;
        }
        const modal = document.getElementById('git-commits-modal');
        if (modal && !modal.classList.contains('hidden')) {
            if (e.target === modal || e.target.closest('#close-git-commits-modal-btn') || e.target.closest('#close-git-commits-btn')) {
                e.preventDefault();
                closeGitCommitsModal();
            }
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeGitCommitsModal();
        }
    });

    function displayAppVersion(version, branch, commitDate, commitMsg, commitHash, commitAuthor) {
        const container = document.querySelector('.container');
        if (!container) return;
        
        let footer = document.querySelector('.app-version-footer');
        if (!footer) {
            footer = document.createElement('footer');
            footer.className = 'app-version-footer';
            container.appendChild(footer);
        }

        const hash = commitHash || (version && version.length <= 10 && version !== 'Desconhecida' ? version : '');
        currentAppCommitHash = hash || null;
        const msg = commitMsg || '';
        const author = commitAuthor ? ` • ${commitAuthor}` : '';
        const date = commitDate || '';
        const commitText = hash ? `Commit ${hash}: "${msg}" (${date}${author})` : 'Informações do Git';

        const commitBadge = `
            <button type="button" class="footer-badge commit-badge" id="footer-commit-badge" onclick="window.openGitCommitsModal && window.openGitCommitsModal()" data-tooltip="Clique para ver todos os commits" title="Clique para ver o histórico completo de commits">
                ${getIconSvg('git-commit', { width: 13, height: 13 })} 
                <strong>Commit:</strong> <span class="commit-hash">${hash || '...'}</span> 
                ${msg ? `<span class="commit-sep">—</span> <span class="commit-msg">"${msg}"</span>` : '<span class="commit-msg">Ver histórico de commits</span>'}
            </button>`;

        const authorBadge = commitAuthor ? `<span class="footer-badge author-badge" data-tooltip="Autor: ${commitAuthor}" title="Autor: ${commitAuthor}">${getIconSvg('user', { width: 12, height: 12 })} ${commitAuthor}</span>` : '';
        const branchBadge = branch && branch !== 'Desconhecida' ? `<span class="footer-badge branch-badge" data-tooltip="Branch Ativa: ${branch}" title="Branch: ${branch}">${getIconSvg('git-branch', { width: 12, height: 12 })} ${branch}</span>` : '';
        const dateBadge = date ? `<span class="footer-badge date-badge" data-tooltip="Data e Hora do Último Commit: ${date}" title="Data do Commit: ${date}">${getIconSvg('clock', { width: 12, height: 12 })} ${date}</span>` : '';
        const activePort = window.location.port || '5050';
        const restartBtnBadge = `<button type="button" id="restart-backend-btn" class="footer-badge restart-badge" title="Reiniciar o processo do Servidor Backend (Flask/Python)">${getIconSvg('rotate-cw', { width: 12, height: 12 })} <span>Reiniciar Backend</span></button>`;
        const liveStatusBadge = `<span id="backend-status-badge" class="backend-status-badge online" title="Servidor online e comunicando na porta ${activePort}"><span class="status-dot-mini"></span> 🟢 Servidor Online (${activePort})</span>`;

        footer.innerHTML = `
            <div class="footer-content">
                <div class="footer-left">
                    <span class="footer-title">${getIconSvg('github', { width: 14, height: 14 })} <strong>Menu Admin</strong></span>
                    ${commitBadge}
                </div>
                <div class="footer-badges">
                    ${restartBtnBadge}
                    ${liveStatusBadge}
                    ${branchBadge}
                    ${authorBadge}
                    ${dateBadge}
                </div>
            </div>
        `;

        const branchInfoEl = document.getElementById('git-commits-branch-info');
        if (branchInfoEl && branch) branchInfoEl.textContent = `Branch: ${branch}`;

        const commitBtn = footer.querySelector('#footer-commit-badge');
        if (commitBtn) {
            commitBtn.onclick = (e) => {
                e.preventDefault();
                openGitCommitsModal();
            };
        }
    }

    function updateBackendLiveStatus(state) {
        const badge = document.getElementById('backend-status-badge');
        if (!badge) return;
        if (state === true || state === 'online') {
            const activePort = window.location.port || '5050';
            badge.className = 'backend-status-badge online';
            badge.innerHTML = `<span class="status-dot-mini"></span> 🟢 Servidor Online (${activePort})`;
            badge.title = 'Servidor online e comunicando via WebSocket/HTTP';
        } else if (state === 'warning' || state === 'error' || state === 'auth_error') {
            badge.className = 'backend-status-badge warning';
            badge.innerHTML = '<span class="status-dot-mini"></span> 🟡 Alerta / Erro de Senha';
            badge.title = 'Servidor ativo com alertas ou erros de autenticação nas máquinas';
        } else {
            const activePort = window.location.port || '5050';
            badge.className = 'backend-status-badge offline';
            badge.innerHTML = '<span class="status-dot-mini"></span> 🔴 Servidor Offline/Pausado';
            badge.title = `Conexão perdida com o backend na porta ${activePort}`;
        }
    }

    // Heartbeat periódico a cada 8s para monitorar o status do backend em tempo real
    setInterval(async () => {
        try {
            const res = await fetch(`${API_BASE_URL}/api/metadata`, { method: 'HEAD', cache: 'no-store' });
            updateBackendLiveStatus(res.ok);
        } catch (e) {
            updateBackendLiveStatus(false);
        }
    }, 8000);

    function renderDynamicActionMenu(metadata) {
        if (!customOptionsContent || !actionSelect) return;
        
        console.log("renderDynamicActionMenu: Iniciando renderização com metadata:", metadata); // DEBUG
        customOptionsContent.innerHTML = ''; // Limpa menu atual
        actionSelect.innerHTML = ''; // Limpa o select nativo para evitar duplicatas ao carregar metadados
        const categories = {};
        
        // Agrupa por categorias definidas no backend
        Object.entries(metadata).forEach(([key, meta]) => {
            const cat = meta.category || 'Outros';
            if (!categories[cat]) categories[cat] = [];
            categories[cat].push({ key, ...meta });
        });
        console.log("renderDynamicActionMenu: Categorias agrupadas:", categories); // DEBUG

        Object.keys(categories).forEach(catName => {
            const groupDiv = document.createElement('div');
            groupDiv.className = `custom-option-group group-${catName.toLowerCase().replace(/\s/g, '-')}`;
            
            const title = document.createElement('div');
            console.log(`renderDynamicActionMenu: Adicionando grupo: ${catName}`); // DEBUG
            title.className = 'custom-option-group-title';
            title.textContent = catName;
            groupDiv.appendChild(title);

            categories[catName].forEach(action => {
                const item = document.createElement('div');
                item.className = 'checkbox-item';
                console.log(`renderDynamicActionMenu: Adicionando ação: ${action.key} (${action.label})`); // DEBUG
            
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.id = `custom-action-${action.key}`;
                checkbox.value = action.key;

                const label = document.createElement('label');
                label.htmlFor = `custom-action-${action.key}`;
                label.classList.add(getCategoryClass(action.key)); // Adiciona a classe de categoria ao label
                
                const labelContent = document.createElement('div');
                labelContent.className = 'option-label-content';
                
                const titleSpan = document.createElement('span');
                titleSpan.className = 'option-title';
                if (action.icon) {
                    const icon = document.createElement('i');
                    icon.setAttribute('data-feather', action.icon);
                    titleSpan.appendChild(icon);
                }
                titleSpan.appendChild(document.createTextNode(action.label));
                labelContent.appendChild(titleSpan);

                const desc = ACTION_DESCRIPTIONS[action.key] || action.description;
                if (desc) {
                    const descSpan = document.createElement('span');
                    descSpan.className = 'option-desc';
                    descSpan.textContent = desc;
                    labelContent.appendChild(descSpan);
                }

                label.appendChild(labelContent);
                item.append(checkbox, label);
                
                // Adiciona a opção ao select oculto para manter compatibilidade com o form submit
                const opt = new Option(action.label, action.key);
                actionSelect.add(opt);

                // Sincronização e tratamento de conflitos
                checkbox.addEventListener('change', (e) => {
                    const isChecked = e.target.checked;
                    if (isChecked) {
                        customSelectContainer.classList.remove('open');
                        const conflictingAction = CONFLICTING_ACTIONS[action.key];
                        if (conflictingAction) {
                            const conflictingCheckbox = customOptionsContent.querySelector(`#custom-action-${conflictingAction}`);
                            if (conflictingCheckbox && conflictingCheckbox.checked) {
                                conflictingCheckbox.checked = false;
                                const conflictingOriginalOption = actionSelect.querySelector(`option[value="${conflictingAction}"]`);
                                if (conflictingOriginalOption) conflictingOriginalOption.selected = false;
                            }
                        }
                    }
                    opt.selected = isChecked;
                    actionSelect.dispatchEvent(new Event('change', { bubbles: true }));
                });

                groupDiv.appendChild(item);
            });
            customOptionsContent.appendChild(groupDiv);
        });
        // Re-gera o grupo de ações frequentes e botões de acesso rápido
        createFrequentActionsGroup();
        renderQuickAccessButtons();
        if (window.feather) feather.replace();

        // Aplica o filtro de categoria atual às novas opções renderizadas
        if (typeof filterActionOptions === 'function') filterActionOptions();
    }

    // --- Lógica de Filtro por Categoria e Faixa de Opções (Estilo Ribbon Microsoft Office) ---
    const officeRibbonBar = document.getElementById('office-ribbon-bar');
    const ribbonToolsContent = document.getElementById('ribbon-tools-content');
    const actionSearchInput = document.getElementById('action-search-input');

    const CATEGORY_MAP = {
        'all': [],
        'shortcuts-interface': ['shortcuts', 'interface', 'atalhos', 'gerenciamento-de-atalhos', 'controle-da-interface', 'perifericos', 'controle-de-periféricos', 'desktop'],
        'system-software': ['system', 'sistema', 'gerenciamento-do-sistema', 'gerenciamento-de-processos', 'processos', 'softwares'],
        'network-browser': ['network', 'browser', 'rede', 'navegador', 'configurações-do-navegador', 'configurações-de-rede'],
        'monitoring': ['monitoring', 'monitoramento'],
        'remote': ['remote', 'remotas', 'ações-remotas']
    };

    function renderRibbonActionTools(categoryKey) {
        if (!ribbonToolsContent) return;
        ribbonToolsContent.innerHTML = '';

        const queryText = actionSearchInput ? actionSearchInput.value.toLowerCase().trim() : '';
        const allowedTerms = CATEGORY_MAP[categoryKey] || [];
        const optionGroups = document.querySelectorAll('.custom-option-group, optgroup');

        optionGroups.forEach(group => {
            const groupClass = (group.className || '').toLowerCase();
            const groupLabelText = group.label || group.querySelector('.custom-option-group-title')?.textContent || '';
            const groupLabelLower = groupLabelText.toLowerCase();

            // Verifica se o grupo corresponde ao filtro de categoria
            const matchesCategory = (categoryKey === 'all') || allowedTerms.some(term => 
                groupClass.includes(term) || groupLabelLower.includes(term)
            );

            if (!matchesCategory) return;

            const items = group.querySelectorAll('.checkbox-item, option');
            const matchingButtons = [];

            items.forEach(item => {
                const value = item.value || item.querySelector('input')?.value;
                if (!value) return;

                // Para option ou checkbox-item, obtemos o texto de exibição correto
                let labelText = '';
                const titleEl = item.querySelector('.option-title');
                if (titleEl) {
                    labelText = titleEl.textContent;
                } else {
                    labelText = item.textContent || item.querySelector('label')?.textContent || value;
                }
                labelText = labelText.trim();

                // Aplica o filtro de busca aos botões da Ribbon
                const matchesSearch = !queryText || labelText.toLowerCase().includes(queryText) || value.toLowerCase().includes(queryText);
                if (!matchesSearch) return;

                const nativeOption = actionSelect ? actionSelect.querySelector(`option[value="${value}"]`) : null;
                const isSelected = nativeOption ? nativeOption.selected : false;

                const toolBtn = document.createElement('button');
                toolBtn.type = 'button';
                toolBtn.className = `ribbon-action-btn ${isSelected ? 'selected' : ''}`;
                toolBtn.dataset.value = value;

                // Busca o ícone dinâmico nos metadados
                const meta = ACTION_METADATA[value];
                let iconName = (meta && meta.icon) ? meta.icon : null;
                if (!iconName && meta && meta.category) {
                    iconName = CATEGORY_DEFAULT_ICONS[meta.category];
                }
                if (!iconName) {
                    iconName = 'zap';
                }

                toolBtn.innerHTML = `
                    <i data-feather="${iconName}" class="btn-icon"></i>
                    <span class="btn-label">${labelText}</span>
                `;

                toolBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    if (nativeOption) {
                        nativeOption.selected = !nativeOption.selected;
                        
                        // Sincroniza os checkboxes no menu dropdown
                        const allCheckboxes = document.querySelectorAll(`.custom-options-content input[value="${value}"], .custom-option-group input[value="${value}"]`);
                        allCheckboxes.forEach(cb => cb.checked = nativeOption.selected);

                        // Dispara evento para atualizar tags, contador, campos condicionais, etc.
                        actionSelect.dispatchEvent(new Event('change', { bubbles: true }));

                        if (typeof playConfirmSound === 'function') playConfirmSound();
                    }
                });

                matchingButtons.push(toolBtn);
            });

            // Se existirem botões visíveis, cria o contêiner de Grupo Ribbon (Estilo Office)
            if (matchingButtons.length > 0) {
                const groupPanel = document.createElement('div');
                groupPanel.className = `ribbon-group ${groupClass}`;

                const buttonsContainer = document.createElement('div');
                buttonsContainer.className = 'ribbon-group-buttons';
                matchingButtons.forEach(btn => buttonsContainer.appendChild(btn));

                const titleEl = document.createElement('div');
                titleEl.className = 'ribbon-group-title';
                // Remove emojis/símbolos do rótulo para ficar limpo
                titleEl.textContent = groupLabelText.replace(/[^\w\sÀ-ÿ]/g, '').trim();

                groupPanel.appendChild(buttonsContainer);
                groupPanel.appendChild(titleEl);
                ribbonToolsContent.appendChild(groupPanel);
            }
        });

        if (typeof feather !== 'undefined') feather.replace();
    }

    // Função para varrer a rede/máquinas e verificar o status real da Proteção Infantil
    let isProtectionScanning = false;
    let scanProtectionTimeout = null;

    async function scanChildProtectionStatus(explicitIps = null) {
        const masterChildProtectionBtn = document.getElementById('master-child-protection-btn');
        if (!masterChildProtectionBtn || isProtectionScanning) return;

        const checkedIps = explicitIps || Array.from(document.querySelectorAll('input[name="ip"]:checked, .ip-checkbox:checked')).map(cb => cb.value);
        const onlineIps = Array.from(document.querySelectorAll('.ip-item.status-online, .ip-item:not(.status-offline)')).map(el => el.dataset.ip).filter(Boolean);
        const targetIps = checkedIps.length > 0 ? checkedIps : onlineIps;

        if (targetIps.length === 0) return;

        isProtectionScanning = true;
        const textSpan = masterChildProtectionBtn.querySelector('span');
        const originalText = textSpan ? textSpan.textContent : 'Proteção';
        if (textSpan) textSpan.textContent = 'Varendo...';

        try {
            const pwd = typeof getActivePassword === 'function' ? getActivePassword() : 'qwe123';

            const response = await fetch('/api/check-child-protection', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ips: targetIps, password: pwd })
            });

            const data = await response.json();
            if (data && data.success) {
                updateChildProtectionButtonVisuals(data.is_protected, targetIps.length);
            } else {
                updateChildProtectionButtonVisuals(false, targetIps.length);
            }
        } catch (err) {
            console.warn('Erro ao varrer status de proteção infantil:', err);
            if (textSpan) textSpan.textContent = originalText;
        } finally {
            isProtectionScanning = false;
        }
    }

    function scheduleProtectionScan() {
        if (scanProtectionTimeout) clearTimeout(scanProtectionTimeout);
        scanProtectionTimeout = setTimeout(() => {
            scanChildProtectionStatus();
        }, 600);
    }
    window.scanChildProtectionStatus = scanChildProtectionStatus;

    // Função para atualizar visualmente o estado do Botão Inteligente de Proteção Infantil
    function updateChildProtectionButtonVisuals(isActive, selectedCount = 0) {
        const masterChildProtectionBtn = document.getElementById('master-child-protection-btn');
        if (!masterChildProtectionBtn) return;

        masterChildProtectionBtn.dataset.active = isActive ? 'true' : 'false';

        if (isActive) {
            masterChildProtectionBtn.classList.remove('child-protection-master-btn');
            masterChildProtectionBtn.classList.add('child-protection-remove-btn');
            masterChildProtectionBtn.innerHTML = '<i data-feather="shield-off"></i> <span>Remover</span>';
            masterChildProtectionBtn.title = selectedCount > 0 
                ? `Clique para Remover a Proteção Total Infantil das ${selectedCount} máquinas selecionadas` 
                : 'Clique para Remover a Proteção Total Infantil';
        } else {
            masterChildProtectionBtn.classList.remove('child-protection-remove-btn');
            masterChildProtectionBtn.classList.add('child-protection-master-btn');
            masterChildProtectionBtn.innerHTML = '<i data-feather="shield"></i> <span>Proteção</span>';
            masterChildProtectionBtn.title = selectedCount > 0 
                ? `Clique para Ativar a Proteção Total Infantil nas ${selectedCount} máquinas selecionadas` 
                : 'Clique para Ativar a Proteção Total Infantil';
        }

        if (typeof feather !== 'undefined' && feather.replace) {
            feather.replace();
        }
    }

    // Botão Master Inteligente de Proteção Total Infantil (Toggle Ativar/Remover)
    const masterChildProtectionBtn = document.getElementById('master-child-protection-btn');
    if (masterChildProtectionBtn) {
        masterChildProtectionBtn.addEventListener('click', (e) => {
            e.preventDefault();

            const checkedIPs = document.querySelectorAll('.ip-checkbox:checked, input[name="ip"]:checked');
            const selectedCount = checkedIPs.length;

            if (selectedCount === 0) {
                alert('Por favor, selecione ao menos um computador na lista para alternar a Proteção Infantil.');
                return;
            }

            const isCurrentlyActive = masterChildProtectionBtn.dataset.active === 'true';

            if (!isCurrentlyActive) {
                // CLIQUE 1: ATIVAR PROTEÇÃO TOTAL INFANTIL
                if (actionSelect) {
                    Array.from(actionSelect.options).forEach(opt => opt.selected = false);
                    const masterOption = actionSelect.querySelector('option[value="ativar_protecao_total_infantil"]');
                    if (masterOption) masterOption.selected = true;

                    const customCheckboxes = document.querySelectorAll('.custom-options input[type="checkbox"]');
                    customCheckboxes.forEach(cb => cb.checked = false);
                    const masterCustomCb = document.getElementById('custom-action-ativar_protecao_total_infantil');
                    if (masterCustomCb) masterCustomCb.checked = true;

                    actionSelect.dispatchEvent(new Event('change', { bubbles: true }));
                }

                const confirmRun = confirm(`🛡️ Ativar Proteção Total Infantil nas ${selectedCount} máquinas selecionadas?\n\nIsso aplicará DNS Familiar, SafeSearch, Bloqueio de Redes Sociais/IA, Proxies/VPNs, DoH e Modo Kiosk de uma só vez.`);
                if (confirmRun && actionForm) {
                    updateChildProtectionButtonVisuals(true, selectedCount);
                    actionForm.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
                }
            } else {
                // CLIQUE 2: REMOVER PROTEÇÃO TOTAL INFANTIL
                if (actionSelect) {
                    Array.from(actionSelect.options).forEach(opt => opt.selected = false);
                    const removeOption = actionSelect.querySelector('option[value="desativar_protecao_total_infantil"]');
                    if (removeOption) removeOption.selected = true;

                    const customCheckboxes = document.querySelectorAll('.custom-options input[type="checkbox"]');
                    customCheckboxes.forEach(cb => cb.checked = false);
                    const removeCustomCb = document.getElementById('custom-action-desativar_protecao_total_infantil');
                    if (removeCustomCb) removeCustomCb.checked = true;

                    actionSelect.dispatchEvent(new Event('change', { bubbles: true }));
                }

                const confirmRun = confirm(`🔓 Remover Proteção Total Infantil das ${selectedCount} máquinas selecionadas?\n\nIsso desativará o Modo Kiosk, removerá o bloqueio de redes sociais/IA/proxies e restaurará os navegadores para o modo normal.`);
                if (confirmRun && actionForm) {
                    updateChildProtectionButtonVisuals(false, selectedCount);
                    actionForm.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
                }
            }
        });
    }

    function filterActionOptions() {
        let selectedCat = 'all';
        if (officeRibbonBar) {
            const activeTab = officeRibbonBar.querySelector('.ribbon-tab.active');
            if (activeTab) selectedCat = activeTab.dataset.category;
        }
        const queryText = actionSearchInput ? actionSearchInput.value.toLowerCase().trim() : '';

        const allowedTerms = CATEGORY_MAP[selectedCat] || [];

        const optionGroups = document.querySelectorAll('.custom-option-group, optgroup');
        optionGroups.forEach(group => {
            let groupMatchesCategory = (selectedCat === 'all');
            const groupClass = (group.className || '').toLowerCase();
            const groupLabel = (group.label || group.querySelector('.custom-option-group-title')?.textContent || '').toLowerCase();

            if (!groupMatchesCategory) {
                groupMatchesCategory = allowedTerms.some(term => 
                    groupClass.includes(term) || groupLabel.includes(term)
                );
            }

            let hasVisibleChild = false;
            const items = group.querySelectorAll('.checkbox-item, option');
            items.forEach(item => {
                const itemText = (item.textContent || '').toLowerCase();
                const itemVal = (item.value || item.querySelector('input')?.value || '').toLowerCase();
                
                const matchesText = !queryText || itemText.includes(queryText) || itemVal.includes(queryText);
                const matchesCategory = groupMatchesCategory || (selectedCat === 'all');

                if (matchesText && matchesCategory) {
                    item.style.display = '';
                    hasVisibleChild = true;
                } else {
                    item.style.display = 'none';
                }
            });

            group.style.display = (hasVisibleChild || (selectedCat === 'all' && !queryText)) ? '' : 'none';
        });

        renderRibbonActionTools(selectedCat);
    }

    const officeRibbonPanel = document.getElementById('office-ribbon-panel');
    const ribbonToggleBtn = document.getElementById('ribbon-toggle-btn');

    function toggleRibbonPanel(forceState) {
        if (!officeRibbonPanel) return;
        const isCollapsed = (typeof forceState === 'boolean') ? forceState : !officeRibbonPanel.classList.contains('collapsed');
        
        officeRibbonPanel.classList.toggle('collapsed', isCollapsed);
        if (ribbonToggleBtn) ribbonToggleBtn.classList.toggle('collapsed', isCollapsed);
    }

    // --- Modo Esconder Barra Superior (Ribbon) ---
    const hideMenuBtn = document.getElementById('hide-menu-btn');
    const floatingMenuToggle = document.getElementById('floating-menu-toggle');
    let isTopMenuHidden = false;
    try {
        localStorage.removeItem('topMenuHiddenActive');
    } catch(e) {}

    function setTopMenuHiddenState(hidden, notify = false) {
        document.body.classList.toggle('hide-top-menu', hidden);
        if (notify && typeof showToast === 'function') {
            showToast(hidden ? 'Barra de ferramentas recolhida.' : 'Barra de ferramentas visível.', 'details');
        }
    }

    if (hideMenuBtn) {
        hideMenuBtn.addEventListener('click', () => {
            isTopMenuHidden = !isTopMenuHidden;
            setTopMenuHiddenState(isTopMenuHidden, true);
        });
    }

    if (floatingMenuToggle) {
        floatingMenuToggle.addEventListener('click', () => {
            isTopMenuHidden = false;
            setTopMenuHiddenState(false, true);
        });
    }

    if (ribbonToggleBtn) {
        ribbonToggleBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            toggleRibbonPanel();
            if (typeof playConfirmSound === 'function') playConfirmSound();
        });
    }

    if (officeRibbonBar) {
        officeRibbonBar.addEventListener('click', (e) => {
            const tab = e.target.closest('.ribbon-tab');
            if (!tab) return;

            const wasActive = tab.classList.contains('active');
            const category = tab.dataset.category;

            officeRibbonBar.querySelectorAll('.ribbon-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            // Se clicou na aba que já estava ativa, alterna fechar/abrir o painel
            if (wasActive) {
                toggleRibbonPanel();
            } else {
                // Se clicou em "Todas", recolhe automaticamente para não poluir a tela.
                // Se clicou em qualquer outra categoria, expande o painel com as poucas opções da categoria!
                if (category === 'all') {
                    toggleRibbonPanel(true); // recolhe
                } else {
                    toggleRibbonPanel(false); // expande
                }
            }

            filterActionOptions();
            if (typeof playConfirmSound === 'function') playConfirmSound();
        });

        // Inicialmente na aba "Todas", mantemos recolhido para tela 100% limpa
        setTimeout(() => {
            filterActionOptions();
            toggleRibbonPanel(true);
        }, 250);
    }

    const clearSearchBtn = document.getElementById('clear-search-btn');

    if (actionSearchInput) {
        actionSearchInput.addEventListener('input', (e) => {
            const start = e.target.selectionStart;
            const end = e.target.selectionEnd;
            if (e.target.value) {
                e.target.value = e.target.value.toUpperCase();
                try { e.target.setSelectionRange(start, end); } catch (err) {}
            }
        });

        actionSearchInput.addEventListener('input', debounce(() => {
            if (clearSearchBtn) {
                clearSearchBtn.style.display = actionSearchInput.value ? 'inline-flex' : 'none';
            }
            filterActionOptions();
        }, 150));
    }

    if (clearSearchBtn && actionSearchInput) {
        clearSearchBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            actionSearchInput.value = '';
            clearSearchBtn.style.display = 'none';
            filterActionOptions();
            actionSearchInput.focus();
        });
    }

    const AUTO_REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutos

    // Define o número máximo de ações remotas a serem executadas simultaneamente.
    // Um valor maior pode acelerar o processo, mas consome mais recursos do servidor.
    // Um valor entre 5 e 10 é geralmente um bom equilíbrio.
    const MAX_CONCURRENT_TASKS = 10;

    const ipListContainer = document.getElementById('ip-list');
    const ipCountElement = document.getElementById('ip-count');
    const ipSearchInput = document.getElementById('ip-search-input');
    const selectAllCheckbox = document.getElementById('select-all');
    const actionForm = document.getElementById('action-form');
    const systemLogBox = document.getElementById('system-log');
    const submitBtn = document.getElementById('submit-btn');
    const refreshBtn = document.getElementById('refresh-btn');
    const resetBtn = document.getElementById('reset-btn');
    const fixKeysBtn = document.getElementById('fix-keys-btn');
    const passwordInput = document.getElementById('password'); // Continua sendo usado
    const passwordGroup = passwordInput.parentElement;
    const refreshBtnText = refreshBtn.querySelector('.btn-text');
    const submitBtnText = submitBtn.querySelector('.btn-text');

    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');
    const progressContainer = document.getElementById('progress-section');
    const themeToggle = document.getElementById('theme-toggle');
    const themeLabel = document.querySelector('.theme-label');
    const messageGroup = document.getElementById('message-group');
    const messageText = document.getElementById('message-text');
    const wallpaperGroup = document.getElementById('wallpaper-group');
    const wallpaperFile = document.getElementById('wallpaper-file');
    const processNameGroup = document.getElementById('process-name-group'); // Continua sendo usado
    const processNameText = document.getElementById('process-name-text'); // Continua sendo usado
    const bandwidthGroup = document.getElementById('bandwidth-group');
    const downloadLimitText = document.getElementById('download-limit');
    const uploadLimitText = document.getElementById('upload-limit');
    const devicePathGroup = document.getElementById('device-path-group');

    // Aplica máscara de validação (Sempre permitindo ponto decimal para Mbps)
    [downloadLimitText, uploadLimitText].forEach(input => {
        if (input) {
            input.addEventListener('input', (e) => {
                e.target.value = e.target.value.replace(/[^0-9.]/g, '');
            });
        }
    });

    const devicePathText = document.getElementById('device-path-text');
    // Elementos do novo dropdown personalizado
    const actionSelect = document.querySelector('select[multiple]'); // O select original, agora escondido
    const customSelectContainer = document.getElementById('custom-action-select-container');
    const customSelectTrigger = customSelectContainer ? customSelectContainer.querySelector('.custom-select-trigger') : null;
    const customOptions = customSelectContainer ? customSelectContainer.querySelector('.custom-options') : null;
    const customOptionsContent = customSelectContainer ? customSelectContainer.querySelector('.custom-options-content') : null;
    const hideOfflineToggle = document.getElementById('hide-offline-toggle');
    const showDesyncOnlyToggle = document.getElementById('show-desync-only-toggle');
    const autoRefreshToggle = document.getElementById('auto-refresh-toggle');    
    const modalConfirmBtn = document.getElementById('modal-confirm-btn');
    const modalCancelBtn = document.getElementById('modal-cancel-btn');
    const confirmationModal = document.getElementById('confirmation-modal');
    const modalDescription = document.getElementById('modal-description');
    // Elementos do Modal de Backup
    const backupModal = document.getElementById('backup-modal');
    const backupListContainer = document.getElementById('backup-list');
    const backupConfirmBtn = document.getElementById('backup-modal-confirm-btn');
    const backupCancelBtn = document.getElementById('backup-modal-cancel-btn');
    // Elementos do Modal de Backup da Aplicação
    const appBackupModal = document.getElementById('app-backup-modal');
    const appBackupListContainer = document.getElementById('app-backup-list');
    const appBackupConfirmBtn = document.getElementById('app-backup-modal-confirm-btn');
    const appBackupCancelBtn = document.getElementById('app-backup-modal-cancel-btn');
    // Elementos do Modal de Blocklist
    const manageBlocklistBtn = document.getElementById('manage-blocklist-btn');
    const blocklistModal = document.getElementById('blocklist-modal');
    const blocklistList = document.getElementById('blocklist-list');
    const blocklistModalCloseBtn = document.getElementById('blocklist-modal-close-btn');
    const logGroupTemplate = document.getElementById('log-group-template');
    const exportIpsBtn = document.getElementById('export-ips-btn');
    const importMacsBtn = document.getElementById('import-macs-btn');
    const importMacsInput = document.getElementById('import-macs-input');
    
    // --- Elementos do Modal Multiseat (Agora no HTML) ---
    const multiseatModal = document.getElementById('multiseat-modal');
    const msListSeat0 = document.getElementById('ms-list-seat0');
    const msListSeat1 = document.getElementById('ms-list-seat1');
    const msCloseBtn = document.getElementById('ms-close-btn');
    const msRefreshBtn = document.getElementById('ms-refresh-btn');
    const msSearchInput = document.getElementById('ms-search-input');
    
    // Cria o container de Toasts se não existir
    let toastContainer = document.getElementById('toast-container');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'toast-container';
        document.body.appendChild(toastContainer);
    }

    // Elementos re-adicionados
    const logFiltersContainer = document.querySelector('.log-filters');
    const retryConnectionBtn = document.getElementById('retry-connection-btn');
    const togglePasswordBtn = document.getElementById('toggle-password-btn') || document.getElementById('toggle-password-visibility-btn');
    const passwordToggleIcon = document.getElementById('password-toggle-icon') || togglePasswordBtn;

    let autoRefreshTimer = null;
    let statusMonitorTimer = null;
    let sessionPassword = null;
    // Initial state for submit button text
    if (submitBtnText) submitBtnText.textContent = 'Executar Ação';

    // --- Contador de Seleção Dinâmico & Recursos do Dock ---
    const toggleDockBtn = document.getElementById('toggle-dock-btn');
    const bottomActionsDock = document.getElementById('bottom-actions-dock');
    const selectionCounterBadge = document.getElementById('selection-counter-badge');

    function updateSelectionCounter() {
        const selectedIPsCount = document.querySelectorAll('.ip-checkbox:checked').length;
        const selectedActionsCount = actionSelect ? Array.from(actionSelect.selectedOptions).length : 0;
        
        if (selectionCounterBadge) {
            if (selectedIPsCount > 0 || selectedActionsCount > 0) {
                const ipLabel = selectedIPsCount === 1 ? '1 IP' : `${selectedIPsCount} IPs`;
                const actionLabel = selectedActionsCount === 1 ? '1 Ação' : `${selectedActionsCount} Ações`;
                selectionCounterBadge.textContent = `${ipLabel} • ${actionLabel}`;
                selectionCounterBadge.classList.remove('hidden');
                if (submitBtn) submitBtn.classList.add('has-selection');
            } else {
                selectionCounterBadge.classList.add('hidden');
                if (submitBtn) submitBtn.classList.remove('has-selection');
            }
        }
        if (typeof checkFormValidity === 'function') checkFormValidity();
    }

    if (actionSelect) {
        actionSelect.addEventListener('change', updateSelectionCounter);
    }
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', updateSelectionCounter);
    }
    if (ipListContainer) {
        ipListContainer.addEventListener('change', (e) => {
            if (e.target && e.target.classList.contains('ip-checkbox')) {
                updateSelectionCounter();
            }
        });
    }

    // Toggle Dock Minimizável
    if (toggleDockBtn && bottomActionsDock) {
        toggleDockBtn.addEventListener('click', () => {
            bottomActionsDock.classList.toggle('dock-collapsed');
        });
    }

    // Atalhos Rápidos de Teclado (Keyboard Shortcuts)
    document.addEventListener('keydown', (e) => {
        const activeTag = document.activeElement ? document.activeElement.tagName : '';
        const isTyping = ['INPUT', 'TEXTAREA', 'SELECT'].includes(activeTag);
        
        // Ctrl + Enter: Executar Ação
        if (e.ctrlKey && e.key === 'Enter') {
            e.preventDefault();
            if (submitBtn && !submitBtn.disabled) submitBtn.click();
        }
        
        // Esc: Limpar Tudo (se não houver modal aberto)
        if (e.key === 'Escape' && !isTyping) {
            const hasOpenModal = document.querySelector('.modal-overlay:not(.hidden)');
            if (!hasOpenModal && resetBtn) {
                resetBtn.click();
                updateSelectionCounter();
            }
        }
        
        // Alt + R: Atualizar Lista
        if (e.altKey && (e.key === 'r' || e.key === 'R')) {
            e.preventDefault();
            if (refreshBtn && !refreshBtn.disabled) refreshBtn.click();
        }
        
        // Alt + D: Alternar Dock
        if (e.altKey && (e.key === 'd' || e.key === 'D')) {
            e.preventDefault();
            if (toggleDockBtn) toggleDockBtn.click();
        }
    });

    // Mapeamento de categorias para ícones padrão (Feather Icons)
    const CATEGORY_DEFAULT_ICONS = {
        'Gerenciamento de Atalhos': 'bookmark',
        'Gerenciamento do Sistema': 'settings',
        'Controle da Interface': 'layout',
        'Configurações do Navegador': 'globe',
        'Controle de Periféricos': 'mouse-pointer',
        'Ações Remotas': 'zap',
        'Desktop': 'monitor',
        'Gerenciamento de Processos': 'cpu',
        'Monitoramento': 'activity',
        'Multiseat': 'users',
        'Configurações de Rede': 'wifi',
        'Outros': 'help-circle' // Fallback para categorias não mapeadas
    };
    /**
     * Obtém a senha ativa da sessão, do input ou a padrão qwe123.
     */
    function getActivePassword() {
        const storedPwd = sessionStorage.getItem('app_ssh_password') || localStorage.getItem('app_ssh_password');
        if (storedPwd) return storedPwd;
        if (typeof sessionPassword !== 'undefined' && sessionPassword) return sessionPassword;
        if (typeof passwordInput !== 'undefined' && passwordInput && passwordInput.value) return passwordInput.value;
        return "qwe123";
    }
    window.getActivePassword = getActivePassword;

    // Função de validação que habilita/desabilita o botão de submit e o botão master de proteção infantil
    function checkFormValidity() {
        const hasSelectedActions = Array.from(actionSelect.selectedOptions).length > 0;

        // O botão agora permanece habilitado se houver uma ação selecionada.
        submitBtn.disabled = !hasSelectedActions;

        // Atualiza a disponibilidade do Botão Master Inteligente de Proteção Infantil no Cabeçalho
        const masterChildProtectionBtn = document.getElementById('master-child-protection-btn');
        const selectedIPsCount = document.querySelectorAll('.ip-checkbox:checked, input[name="ip"]:checked').length;

        if (masterChildProtectionBtn) {
            const isActive = masterChildProtectionBtn.dataset.active === 'true';
            if (selectedIPsCount > 0) {
                masterChildProtectionBtn.disabled = false;
                masterChildProtectionBtn.removeAttribute('disabled');
                masterChildProtectionBtn.classList.remove('disabled');
                masterChildProtectionBtn.title = isActive 
                    ? `Clique para Remover a Proteção Total Infantil das ${selectedIPsCount} máquinas selecionadas`
                    : `Clique para Ativar a Proteção Total Infantil nas ${selectedIPsCount} máquinas selecionadas`;
            } else {
                masterChildProtectionBtn.disabled = true;
                masterChildProtectionBtn.setAttribute('disabled', 'disabled');
                masterChildProtectionBtn.classList.add('disabled');
                masterChildProtectionBtn.title = 'Selecione ao menos 1 computador na lista para alternar a Proteção Infantil';
            }
        }

        if (typeof scheduleProtectionScan === 'function') {
            scheduleProtectionScan();
        }
    }

    // --- Lógica do Seletor de Tema ---
    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        
        const capsule = document.getElementById('theme-switch-btn') || document.querySelector('.theme-toggle-capsule');
        if (capsule) {
            capsule.setAttribute('data-theme-state', theme);
            capsule.setAttribute('aria-checked', theme === 'dark' ? 'true' : 'false');
            const titles = {
                'light': 'Tema Atual: Claro (Clique para alternar)',
                'dark': 'Tema Atual: Escuro (Clique para alternar)',
                'high-contrast': 'Tema Atual: Alto Contraste (Clique para alternar)'
            };
            capsule.setAttribute('title', titles[theme] || 'Alternar tema');
        }

        // Sincroniza o estado visual do checkbox e o ícone
        if (themeToggle) {
            themeToggle.checked = (theme === 'dark' || theme === 'high-contrast');
        }

        // Suporte a label legada se não for a cápsula
        if (themeLabel && !themeLabel.classList.contains('theme-toggle-capsule')) {
            if (theme === 'dark') {
                themeLabel.textContent = '☀️';
            } else if (theme === 'high-contrast') {
                themeLabel.textContent = '👁️';
            } else {
                themeLabel.textContent = '🌙';
            }
        }
    }

    // Lista de temas disponíveis para rotação
    const availableThemes = ['light', 'dark', 'high-contrast'];

    if (themeLabel) {
        themeLabel.addEventListener('click', (e) => {
            e.preventDefault(); // Impede o comportamento padrão do checkbox
            e.stopPropagation();
            const currentTheme = localStorage.getItem('theme') || 'dark';
            const nextIndex = (availableThemes.indexOf(currentTheme) + 1) % availableThemes.length;
            const newTheme = availableThemes[nextIndex];

            localStorage.setItem('theme', newTheme);
            applyTheme(newTheme);
            playConfirmSound();
        });
    }

    // Aplica o tema salvo no carregamento da página
    const currentTheme = localStorage.getItem('theme') || 'dark'; // Padrão para 'dark'
    applyTheme(currentTheme);



    // --- Lógica do Botão de Visualizar Senha ---
    if (togglePasswordBtn && passwordInput) {
        togglePasswordBtn.addEventListener('click', () => {
            const isPassword = passwordInput.type === 'password';
            passwordInput.type = isPassword ? 'text' : 'password';
            togglePasswordBtn.innerHTML = isPassword ? '<i data-feather="eye-off"></i>' : '<i data-feather="eye"></i>';
            if (window.feather) feather.replace({ width: '1em', height: '1em' });
        });
    }

    // --- Lógica para garantir que os menus comecem recolhidos na primeira visita ---
    // Esta flag garante que a limpeza do estado dos menus só ocorra uma vez por sessão.
    // --- Lógica para todas as Seções Retráteis ---
    const allCollapsibles = document.querySelectorAll('.collapsible-section, .collapsible-fieldset');
    allCollapsibles.forEach(collapsible => {
        // O ID é crucial para salvar/carregar o estado individualmente.
        const id = collapsible.id;
        if (!id) return;

        const indicator = collapsible.querySelector('.collapsible-indicator');
        if (!indicator) return;

        // No carregamento da página, verifica o estado salvo e o aplica.
        // Se não houver estado salvo, respeita o atributo 'open' do HTML.
        const savedState = localStorage.getItem(`collapsible-state-${id}`);
        if (savedState === 'open') {
            collapsible.open = true;
        } else if (savedState === 'closed') {
            collapsible.open = false;
        }

        // Define o indicador inicial com base no estado atual (salvo ou padrão do HTML).
        indicator.textContent = collapsible.open ? '[-]' : '[+]';

        collapsible.addEventListener('toggle', () => {
            // Altera o texto do indicador e salva o novo estado no localStorage.
            indicator.textContent = collapsible.open ? '[-]' : '[+]';
            localStorage.setItem(`collapsible-state-${id}`, collapsible.open ? 'open' : 'closed');
        });
    });

    /**
     * Atualiza a contagem de uso de cada ação no localStorage.
     * @param {string[]} actions - Um array com os valores das ações executadas.
     */
    function updateActionUsage(actions) {
        try {
            const counts = JSON.parse(localStorage.getItem('actionUsageCounts')) || {};
            actions.forEach(action => {
                counts[action] = (counts[action] || 0) + 1;
            });
            localStorage.setItem('actionUsageCounts', JSON.stringify(counts));
        } catch (e) {
            console.error("Falha ao atualizar contagem de uso das ações:", e);
        }
    }

    /**
     * Reordena as ações no <select> original, movendo as mais frequentes para um novo grupo no topo.
     */
    function createFrequentActionsGroup() {
        const counts = JSON.parse(localStorage.getItem('actionUsageCounts')) || {};
        const allOptions = Array.from(actionSelect.querySelectorAll('option'));

        // Ordena as opções pela contagem de uso, em ordem decrescente.
        allOptions.sort((a, b) => {
            const countA = counts[a.value] || 0;
            const countB = counts[b.value] || 0;
            return countB - countA;
        });

        // Pega as 5 ações mais usadas que têm pelo menos uma execução.
        const frequentOptions = allOptions.filter(opt => (counts[opt.value] || 0) > 0).slice(0, 5);

        if (frequentOptions.length > 0) {
            const frequentActionsGroup = document.createElement('optgroup');
            frequentActionsGroup.label = '⭐ Ações Frequentes';
            frequentActionsGroup.classList.add('group-frequent'); // Adiciona classe para estilização

            frequentOptions.forEach(option => {
                frequentActionsGroup.appendChild(option.cloneNode(true)); // Clona a opção para não removê-la do grupo original
            });
            actionSelect.prepend(frequentActionsGroup);
        }
    }

    // --- Lógica dos Botões de Acesso Rápido ---
    const quickActionsContainer = document.createElement('div');
    quickActionsContainer.className = 'quick-actions-container hidden';

    // Movemos os botões "Mais Acessados" para o rodapé (bottom-actions)
    const bottomActionsContainer = document.querySelector('.bottom-actions');
    if (bottomActionsContainer) {
        bottomActionsContainer.prepend(quickActionsContainer);
    }

    const DEFAULT_POPULAR_ACTIONS = ['desativar', 'ativar', 'desligar'];

    const SHORT_ACTION_LABELS = {
        // Gerenciamento de Atalhos & Desktop
        'desativar': 'Ocultar Atalhos',
        'ativar': 'Restaurar Atalhos',
        'mostrar_sistema': 'Mostrar Ícones',
        'ocultar_sistema': 'Ocultar Ícones',
        'limpar_imagens': 'Limpar Imagens',
        'atualizar_sistema': 'Atualizar Linux',
        'definir_papel_de_parede': 'Papel de Parede',

        // Ações Remotas & Energia
        'desligar': 'Desligar PCs',
        'reiniciar': 'Reiniciar PCs',
        'wake_on_lan': 'Ligar (WoL)',
        'enviar_mensagem': 'Enviar Mensagem',
        'deslogar_todos': 'Deslogar Todos',
        'logar_aluno': 'Reiniciar Login',
        'shutdown_server': 'Desligar Servidor',
        'remover_todos_bloqueios': 'Reset Bloqueios',

        // Controle da Interface
        'desativar_barra_tarefas': 'Ocultar Barra',
        'ativar_barra_tarefas': 'Restaurar Barra',
        'bloquear_barra_tarefas': 'Bloquear Barra',
        'desbloquear_barra_tarefas': 'Liberar Barra',
        'disable_sleep_button': 'Desativar Sleep',
        'enable_sleep_button': 'Ativar Sleep',
        'ativar_protecao_tela': 'Ativar Protetor',
        'desativar_protecao_tela': 'Remover Protetor',
        'ativar_deep_lock': 'Deep Lock (Freeze)',
        'desativar_deep_lock': 'Desativar Lock',
        'bloquear_terminal': 'Bloq. Terminal',
        'desbloquear_terminal': 'Liberar Terminal',
        'bloquear_dconf': 'Bloq. Dconf',
        'desbloquear_dconf': 'Liberar Dconf',
        'bloquear_combinacoes_teclas': 'Bloq. Teclas (Alt+Tab)',
        'desbloquear_combinacoes_teclas': 'Liberar Teclas',

        // Periféricos & Tela
        'bloquear_tela_mensagem': 'Bloquear Tela',
        'desbloquear_tela_mensagem': 'Desbloquear Tela',
        'desativar_perifericos': 'Bloq. Teclado/Mouse',
        'ativar_perifericos': 'Liberar Teclado/Mouse',
        'desativar_botao_direito': 'Bloq. Clique Dir.',
        'ativar_botao_direito': 'Liberar Clique Dir.',

        // Modo Aula & Veyon
        'iniciar_modo_demo': 'Transmitir Aula',
        'parar_modo_demo': 'Parar Aula',

        // Filtros, Navegador & Elefante Letrado
        'bloquear_stickers': 'Bloq. Stickers',
        'desbloquear_stickers': 'Liberar Stickers',
        'ativar_protecao_total_infantil': 'Proteção Total',
        'desativar_protecao_total_infantil': 'Remover Proteção',
        'ativar_modo_kiosk_infantil': 'Modo Kiosk',
        'desativar_modo_kiosk_infantil': 'Sair do Kiosk',
        'obter_navegador_padrao': 'Navegador Padrão',
        'definir_firefox_padrao': 'Firefox Padrão',
        'definir_chrome_padrao': 'Chrome Padrão',
        'ativar_filtro_conteudo': 'Filtro Conteúdo',
        'desativar_filtro_conteudo': 'Desat. Filtro',
        'desativar_doh_navegadores': 'Bloq. DoH',
        'ativar_doh_navegadores': 'Liberar DoH',

        // Rede & Bloqueios
        'ativar_dns_familia': 'DNS Família',
        'desativar_dns_familia': 'Remover DNS',
        'verificar_dns_familia': 'Testar DNS',
        'ativar_safesearch': 'SafeSearch',
        'desativar_safesearch': 'Desat. SafeSearch',
        'verificar_safesearch': 'Testar SafeSearch',
        'bloquear_config_rede': 'Bloq. Config Rede',
        'desbloquear_config_rede': 'Liberar Rede',
        'ativar_whitelist_sites': 'Whitelist Sites',
        'desativar_whitelist_sites': 'Desat. Whitelist',
        'verificar_whitelist_sites': 'Verificar Whitelist',
        'bloquear_sites': 'Bloquear Sites',
        'desbloquear_sites': 'Liberar Sites',
        'bloquear_redes_sociais_e_ia': 'Bloq. Redes/IA',
        'desbloquear_redes_sociais_e_ia': 'Liberar Redes/IA',
        'bloquear_proxies_e_vpns': 'Bloq. VPN/Proxy',
        'desbloquear_proxies_e_vpns': 'Liberar VPN/Proxy',
        'definir_limite_banda': 'Limitar Banda',
        'remover_limite_banda': 'Liberar Banda',

        // Processos & Monitoramento
        'encerrar_apps_ia': 'Fechar Apps IA',
        'kill_process': 'Encerrar Processo',
        'view_vnc': 'Ver Tela (VNC)',
        'instalar_monitor_tools': 'Instalar VNC',
        'get_system_info': 'Info do Sistema',
        'monitorar_rede': 'Monitorar Tráfego',
        'testar_velocidade': 'Teste Velocidade',
        'backup_aplicacao': 'Backup App',
        'restaurar_backup_aplicacao': 'Restaurar App',

        // Aplicativos
        'desinstalar_scratchjr': 'Desinstalar Scratch',
        'instalar_scratchjr': 'Instalar Scratch',
        'desinstalar_gcompris': 'Desinstalar GCompris',
        'instalar_gcompris': 'Instalar GCompris',
        'desinstalar_tuxpaint': 'Desinstalar Tux Paint',
        'instalar_tuxpaint': 'Instalar Tux Paint',
        'desinstalar_libreoffice': 'Desinstalar LibreOffice',
        'instalar_libreoffice': 'Instalar LibreOffice',
        'desinstalar_calculadora': 'Desinstalar Calculadora',
        'instalar_calculadora': 'Instalar Calculadora'
    };

    function renderQuickAccessButtons() {
        const counts = JSON.parse(localStorage.getItem('actionUsageCounts')) || {};
        // Pega as ações executadas pelo usuário em ordem de uso
        let sortedActions = Object.entries(counts)
            .sort((a, b) => b[1] - a[1])
            .map(entry => entry[0]);

        // Se houver menos de 3 ações no histórico, preenche com as ações padrão mais populares
        DEFAULT_POPULAR_ACTIONS.forEach(defaultAction => {
            if (sortedActions.length < 3 && !sortedActions.includes(defaultAction)) {
                sortedActions.push(defaultAction);
            }
        });

        sortedActions = sortedActions.slice(0, 3);

        if (sortedActions.length === 0) {
            quickActionsContainer.classList.add('hidden');
            return;
        }

        quickActionsContainer.innerHTML = '';
        quickActionsContainer.classList.remove('hidden');

        const label = document.createElement('div');
        label.className = 'quick-actions-label';
        label.innerHTML = '<span class="quick-actions-badge-icon">⚡</span><span class="quick-actions-badge-text">Recentes</span>';
        label.title = 'Ações Mais Recentes / Frequentes';
        label.setAttribute('aria-label', 'Mais Recentes');
        quickActionsContainer.appendChild(label);

        const buttonsWrapper = document.createElement('div');
        buttonsWrapper.className = 'quick-actions-wrapper';

        sortedActions.forEach(action => {
            const option = actionSelect.querySelector(`option[value="${action}"]`);
            if (!option) return;

            const btn = document.createElement('button');
            btn.type = 'button';
            const catClass = getCategoryClass(action);
            btn.className = `quick-action-btn ${catClass}`;

            const meta = ACTION_METADATA[action];
            let iconName = (meta && meta.icon) ? meta.icon : null;
            if (!iconName && meta && meta.category) {
                iconName = CATEGORY_DEFAULT_ICONS[meta.category] || 'tool';
            }
            if (iconName) {
                const icon = document.createElement('i');
                icon.setAttribute('data-feather', iconName);
                btn.appendChild(icon);
            }

            const span = document.createElement('span');
            // Formata rótulo limpo sem emojis duplicados ou sufixos longos em parênteses
            const cleanOptionText = option.textContent.trim()
                .replace(/^[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{FE00}-\u{FE0F}\u{1FA00}-\u{1FAFF}]+\s*/u, '')
                .replace(/\s*\([^)]*\)$/, '')
                .trim();
            const labelText = SHORT_ACTION_LABELS[action] || cleanOptionText || option.textContent.trim();
            span.textContent = labelText;
            btn.appendChild(span);

            // Usa a descrição amigável se disponível, senão usa o texto original completo
            btn.setAttribute('data-tooltip', ACTION_DESCRIPTIONS[action] || `Ação: ${option.textContent.trim()}`);
            
            btn.addEventListener('click', () => {
                // Desmarca todas as opções no select nativo e checkboxes customizados
                Array.from(actionSelect.options).forEach(opt => opt.selected = false);
                const allCheckboxes = document.querySelectorAll('.custom-options input[type="checkbox"]');
                allCheckboxes.forEach(cb => cb.checked = false);

                // Seleciona a opção desejada
                option.selected = true;
                
                // Sincroniza o checkbox correspondente no menu customizado
                const customCheckbox = document.getElementById(`custom-action-${action}`);
                if (customCheckbox) customCheckbox.checked = true;

                // Dispara evento de mudança para atualizar a UI (tags, validação)
                actionSelect.dispatchEvent(new Event('change', { bubbles: true }));
                
                // Feedback visual de clique
                btn.classList.add('active');
                setTimeout(() => btn.classList.remove('active'), 200);

                // Nova lógica: executa imediatamente se houver IPs selecionados
                const selectedIps = document.querySelectorAll('input[name="ip"]:checked');
                if (selectedIps.length > 0) {
                    // Garante que a validação seja executada antes de clicar
                    checkFormValidity(); 
                    if (!submitBtn.disabled) {
                        submitBtn.click();
                    }
                }
            });

            buttonsWrapper.appendChild(btn);
        });

        quickActionsContainer.appendChild(buttonsWrapper);
        if (window.feather) feather.replace();
    }

    // --- Lógica do Novo Menu de Ações Customizado ---
    if (customSelectContainer && customSelectTrigger && actionSelect) {
        // ETAPA 1: Criar o grupo de ações frequentes ANTES de popular o menu customizado.
        // Isso garante que o novo grupo seja incluído na renderização.
        createFrequentActionsGroup();
        
        // Renderiza os botões de acesso rápido iniciais
        renderQuickAccessButtons();

        // 1. Povoar o menu customizado a partir do select original
        const originalOptgroups = actionSelect.querySelectorAll('optgroup');
        originalOptgroups.forEach(optgroup => {
            const groupLabel = optgroup.label;
            const options = optgroup.querySelectorAll('option');

            const groupDiv = document.createElement('div');
            const cleanSlug = (groupLabel || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, '-');
            groupDiv.className = `custom-option-group ${optgroup.className || ''} group-${cleanSlug}`.trim();

            const groupTitle = document.createElement('div');
            groupTitle.className = 'custom-option-group-title';
            groupTitle.textContent = groupLabel;
            groupDiv.appendChild(groupTitle);

            options.forEach(option => {
                const itemDiv = document.createElement('div');
                itemDiv.className = 'checkbox-item';
                
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.id = `custom-action-${option.value}`;
                checkbox.value = option.value;

                const label = document.createElement('label');
                label.htmlFor = `custom-action-${option.value}`;
                label.textContent = option.textContent;

                itemDiv.append(checkbox, label);
                groupDiv.appendChild(itemDiv);

                // Lógica executada quando um checkbox de ação é alterado
                checkbox.addEventListener('change', () => {
                    const actionValue = checkbox.value;
                    const isChecked = checkbox.checked;

                    // Se a ação foi marcada, verifica se há um conflito
                    if (isChecked) {
                        const conflictingAction = CONFLICTING_ACTIONS[actionValue];
                        if (conflictingAction) {
                            const conflictingCheckbox = customOptions.querySelector(`#custom-action-${conflictingAction}`);
                            const conflictingOriginalOption = actionSelect.querySelector(`option[value="${conflictingAction}"]`);
                            // Se o conflitante estiver marcado, desmarca-o
                            if (conflictingCheckbox && conflictingCheckbox.checked) {
                                conflictingCheckbox.checked = false;
                                if (conflictingOriginalOption) conflictingOriginalOption.selected = false;
                            }
                        }
                    }

                    // Sincroniza o select original com o estado atual do checkbox
                    const originalOption = actionSelect.querySelector(`option[value="${actionValue}"]`);
                    if (originalOption) originalOption.selected = isChecked;
                    
                    // Dispara o evento 'change' no select original para atualizar a UI (tags, etc.)
                    actionSelect.dispatchEvent(new Event('change', { bubbles: true }));
                });
            });
            customOptionsContent.appendChild(groupDiv);
        });

        // Função universal para abrir a seleção de ações e mover o cursor do teclado direto para o campo de busca
        function focusActionSearchInput() {
            if (customSelectContainer) {
                customSelectContainer.classList.add('open');
            }
            if (!actionSearchInput) return;

            const applyFocus = () => {
                try {
                    actionSearchInput.focus();
                    if (actionSearchInput.value) {
                        actionSearchInput.select();
                    } else {
                        const len = actionSearchInput.value ? actionSearchInput.value.length : 0;
                        actionSearchInput.setSelectionRange(len, len);
                    }
                } catch (err) {}
            };

            applyFocus();
            requestAnimationFrame(applyFocus);
            setTimeout(applyFocus, 30);
            setTimeout(applyFocus, 100);
        }

        // 2. Lógica para abrir/fechar o menu e colocar foco na busca ao clicar na seleção de ações
        customSelectTrigger.addEventListener('mousedown', (e) => {
            if (e.target.closest('.tag-close-btn')) return;
            // Previne que o botão capture o foco e roube do input
            e.preventDefault();
            focusActionSearchInput();
        });

        customSelectTrigger.addEventListener('click', (e) => {
            if (e.target.closest('.tag-close-btn')) return;
            e.preventDefault();
            focusActionSearchInput();
        });

        // Intercepta clique no label "Ação a Executar:" para focar na busca
        const actionLabel = document.querySelector('label[for="action-select"], .action-group label');
        if (actionLabel) {
            actionLabel.addEventListener('click', (e) => {
                e.preventDefault();
                focusActionSearchInput();
            });
        }

        // Fecha o menu se clicar fora dele
        window.addEventListener('click', (e) => {
            if (!customSelectContainer.contains(e.target)) {
                customSelectContainer.classList.remove('open');
            }
        });

        // Garante que o menu abra ao focar ou clicar na busca
        if (actionSearchInput) {
            actionSearchInput.addEventListener('focus', () => {
                customSelectContainer.classList.add('open');
            });
            actionSearchInput.addEventListener('click', (e) => {
                e.stopPropagation();
            });
        }

    function syncRibbonButtonsState() {
        if (!ribbonToolsContent) return;
        const buttons = ribbonToolsContent.querySelectorAll('.ribbon-action-btn');
        buttons.forEach(btn => {
            const value = btn.dataset.value;
            const nativeOption = actionSelect ? actionSelect.querySelector(`option[value="${value}"]`) : null;
            const isSelected = nativeOption ? nativeOption.selected : false;
            btn.classList.toggle('selected', isSelected);
        });
    }

    /**
     * Resolve dinamicamente conflitos de ações mutuamente exclusivas.
     * Se uma nova ação for selecionada, desmarca imediatamente a ação oposta/conflitante previamente marcada.
     */
    function resolveActionConflicts() {
        if (!actionSelect) return;
        const selectedOptions = Array.from(actionSelect.selectedOptions);
        if (selectedOptions.length <= 1) return;

        selectedOptions.forEach(opt => {
            const val = opt.value;
            const conflictingVal = CONFLICTING_ACTIONS[val];
            if (conflictingVal) {
                const conflictingOpt = actionSelect.querySelector(`option[value="${conflictingVal}"]`);
                if (conflictingOpt && conflictingOpt.selected) {
                    // Desmarca a ação conflitante anterior
                    conflictingOpt.selected = false;

                    // Desmarca os checkboxes correspondentes na UI
                    const customCheckboxes = document.querySelectorAll(`input[value="${conflictingVal}"]`);
                    customCheckboxes.forEach(cb => cb.checked = false);

                    // Desmarca botões na barra Ribbon se existirem
                    const ribbonBtns = document.querySelectorAll(`.ribbon-action-btn[data-value="${conflictingVal}"]`);
                    ribbonBtns.forEach(btn => btn.classList.remove('selected'));
                }
            }
        });
    }

    /**
     * Sincroniza o estado visual selecionado dos botões da Ribbon com o select nativo.
     */
    function updateRibbonButtonSelection() {
        if (!actionSelect) return;
        const selectedValues = new Set(Array.from(actionSelect.selectedOptions).map(o => o.value));
        const ribbonBtns = document.querySelectorAll('.ribbon-action-btn');
        ribbonBtns.forEach(btn => {
            const val = btn.dataset.value;
            btn.classList.toggle('selected', selectedValues.has(val));
        });
    }

    // Lógica para atualizar o texto do botão e os campos condicionais
    actionSelect.addEventListener('change', () => {
            resolveActionConflicts();
            updateRibbonButtonSelection();
            const selectedOptions = Array.from(actionSelect.selectedOptions);
            const triggerContainer = customSelectTrigger.querySelector('.trigger-text-container');
            const placeholder = triggerContainer.querySelector('.trigger-placeholder');

            // Limpa as tags existentes e o badge de extras
            triggerContainer.querySelectorAll('.selected-action-tag, .more-actions-badge').forEach(tag => tag.remove());

            if (selectedOptions.length === 0) {
                placeholder.style.display = 'inline';
            } else {
                placeholder.style.display = 'none';

                const maxVisibleTags = 2;
                const visibleOptions = selectedOptions.slice(0, maxVisibleTags);
                const hiddenCount = selectedOptions.length - maxVisibleTags;

                visibleOptions.forEach(option => {
                    const tag = document.createElement('div');
                    const catClass = getCategoryClass(option.value);
                    tag.className = `selected-action-tag ${catClass}`;

                    const meta = ACTION_METADATA[option.value];
                    if (meta && meta.icon) {
                        const icon = document.createElement('i');
                        icon.setAttribute('data-feather', meta.icon);
                        tag.appendChild(icon);
                    }
                    
                    const textSpan = document.createElement('span');
                    textSpan.textContent = option.textContent;
                    tag.appendChild(textSpan);

                    const closeBtn = document.createElement('button');
                    closeBtn.type = 'button';
                    closeBtn.className = 'tag-close-btn';
                    closeBtn.innerHTML = '&times;';
                    closeBtn.title = `Remover "${option.textContent}"`;

                    closeBtn.addEventListener('click', (e) => {
                        e.stopPropagation(); // Impede que o menu abra/feche
                        option.selected = false;
                        // Sincroniza o checkbox no menu suspenso
                        const correspondingCheckbox = customOptions.querySelector(`#custom-action-${option.value}`);
                        if (correspondingCheckbox) {
                            correspondingCheckbox.checked = false;
                        }
                        // Dispara o evento de mudança para atualizar tudo
                        actionSelect.dispatchEvent(new Event('change', { bubbles: true }));
                    });

                    tag.appendChild(closeBtn);
                    triggerContainer.appendChild(tag);
                });

                if (hiddenCount > 0) {
                    const moreBadge = document.createElement('div');
                    moreBadge.className = 'more-actions-badge';
                    moreBadge.textContent = `+${hiddenCount} outra${hiddenCount > 1 ? 's' : ''}`;
                    
                    const hiddenTitles = selectedOptions.slice(maxVisibleTags).map(o => o.textContent).join(', ');
                    moreBadge.title = hiddenTitles;
                    triggerContainer.appendChild(moreBadge);
                }
            }
            if (window.feather) feather.replace();

            // Sincroniza os estados ativos dos botões da Ribbon
            syncRibbonButtonsState();

            const selectedActions = selectedOptions.map(opt => opt.value);

            // Esconde todos os grupos condicionais por padrão
            messageGroup.classList.add('hidden');
            wallpaperGroup.classList.add('hidden');
            processNameGroup.classList.add('hidden');
            if (bandwidthGroup) bandwidthGroup.classList.add('hidden');
            const sitesGroup = document.getElementById('sites-group');
            const whitelistSitesGroup = document.getElementById('whitelist-sites-group');

            if (sitesGroup) sitesGroup.classList.add('hidden');
            devicePathGroup.classList.add('hidden');

            // Mostra agendamento apenas para Wake-on-LAN
            const scheduleGroup = document.getElementById('schedule-group');
            if (scheduleGroup) {
                // Permite agendar se houver uma ação selecionada que não seja local
                if (selectedActions.length > 0 && !selectedActions.every(a => LOCAL_ACTIONS.has(a))) {
                    scheduleGroup.classList.remove('hidden');
                } else {
                    scheduleGroup.classList.add('hidden');
                }
            }

            // Mostra o grupo se QUALQUER uma das ações selecionadas o exigir
            if (selectedActions.includes(ACTIONS.SEND_MESSAGE) || selectedActions.includes('bloquear_tela_mensagem')) {
                messageGroup.classList.remove('hidden');
            } if (selectedActions.includes(ACTIONS.SET_WALLPAPER)) { // Usamos 'if' em vez de 'else if'
                wallpaperGroup.classList.remove('hidden');
            } if (selectedActions.includes(ACTIONS.KILL_PROCESS)) {
                processNameGroup.classList.remove('hidden');
            } if (selectedActions.includes(ACTIONS.SET_BANDWIDTH_LIMIT)) {
                if (bandwidthGroup) bandwidthGroup.classList.remove('hidden');
            } if (selectedActions.includes('bloquear_sites')) {
                if (sitesGroup) sitesGroup.classList.remove('hidden');
            } if (selectedActions.includes('ativar_whitelist_sites') || 
                   selectedActions.includes('incluir_whitelist') || 
                   selectedActions.includes('remover_whitelist') ||
                   selectedActions.includes('ativar_modo_kiosk_infantil')) {
                if (whitelistSitesGroup) whitelistSitesGroup.classList.remove('hidden');
                setupWhitelistMaintenance(); // Configura os botões de ajuda
            } if (selectedActions.includes(ACTIONS.ATTACH_SEAT_DEVICE)) {
                devicePathGroup.classList.remove('hidden');
            }
            checkFormValidity();
        });
    }
    
    /**
     * Adiciona botões de "Carregar" e "Limpar" ao grupo de whitelist para facilitar a manutenção.
     */
    function setupWhitelistMaintenance() {
        const group = document.getElementById('whitelist-sites-group');
        const textarea = document.getElementById('whitelist-sites-text');
        if (!group || !textarea || group.querySelector('.whitelist-helper-actions')) return;

        const container = document.createElement('div');
        container.className = 'whitelist-helper-actions';
        container.style.display = 'flex';
        container.style.gap = '10px';
        container.style.marginBottom = '8px';

        const loadBtn = document.createElement('button');
        loadBtn.type = 'button';
        loadBtn.className = 'small-btn';
        loadBtn.innerHTML = '<i data-feather="download-cloud"></i> Carregar da Máquina';
        
        const clearBtn = document.createElement('button');
        clearBtn.type = 'button';
        clearBtn.className = 'small-btn';
        clearBtn.style.backgroundImage = 'none';
        clearBtn.style.backgroundColor = 'var(--error-color)';
        clearBtn.innerHTML = '<i data-feather="trash-2"></i> Limpar';

        container.append(loadBtn, clearBtn);
        textarea.parentNode.insertBefore(container, textarea);
        if (window.feather) feather.replace({ 'container': container });

        loadBtn.onclick = async () => {
            const selectedIps = Array.from(document.querySelectorAll('input[name="ip"]:checked'));
            if (selectedIps.length === 0) {
                showToast("Selecione uma máquina para carregar a lista", "error");
                return;
            }
            
            loadBtn.disabled = true;
            const ip = selectedIps[0].value;
            showToast(`Buscando whitelist de ${ip}...`);

            const result = await executeRemoteAction(ip, { 
                action: 'obter_whitelist_raw', 
                password: getActivePassword() 
            });

            if (result.success) {
                // Limpa cabeçalhos e preenche o textarea
                textarea.value = result.message.replace('--- COPIE A LISTA ABAIXO ---', '').trim();
                showToast("Lista carregada com sucesso", "success");
            }
            loadBtn.disabled = false;
        };

        clearBtn.onclick = () => { textarea.value = ''; textarea.focus(); };
    }

    // --- Lógica para mudar o texto do botão "Executar Ação" para "Agendar Ação" ---
    const scheduleTimeInput = document.getElementById('schedule-time');
    if (scheduleTimeInput) {
        scheduleTimeInput.addEventListener('input', () => {
            if (scheduleTimeInput.value) {
                submitBtnText.textContent = 'Agendar Ação';
            } else {
                submitBtnText.textContent = 'Executar Ação'; // Reverte para o padrão se o tempo for limpo
            }
        });
    }

    // Listener para o botão "Tentar Novamente" na sobreposição de erro
    if (retryBackendConnectionBtn) {
        retryBackendConnectionBtn.addEventListener('click', () => {
            backendErrorOverlay.classList.add('hidden'); // Esconde o overlay temporariamente
            loadMetadata(); // Tenta carregar os metadados novamente
        });
    }

    function getStatusIconElement(ipStr) {
        if (!ipStr) return null;
        const safeSlug = String(ipStr).replace(/[\/\.:]/g, '-');
        return document.getElementById(`status-${safeSlug}`) || document.getElementById(`status-${ipStr}`);
    }

    function isHostnameConsistentWithIp(hostname, ip) {
        if (!hostname || !ip) return false;
        const clean = String(hostname).trim();
        if (!clean || clean === ip || clean.toLowerCase() === 'localhost') return false;
        return true;
    }

    function createIpItemElement(itemObj, index, targetUser = null, seatIndex = null, previouslySelectedIps = new Set()) {
        const ip = typeof itemObj === 'string' ? itemObj : itemObj.ip;
        const connectionType = (typeof itemObj === 'object' && itemObj.type) ? itemObj.type : 'ssh';
        const cardIpValue = targetUser ? `${ip}/${targetUser}` : ip;
        const safeIdSlug = cardIpValue.replace(/[\/\.:]/g, '-');

        const item = document.createElement('div');
        item.className = 'ip-item';
        item.dataset.ip = cardIpValue;
        item.dataset.baseIp = ip;
        if (targetUser) item.dataset.targetUser = targetUser;
        item.style.animationDelay = `${index * 0.05}s`;

        const lastOctet = ip.split('.').pop();
        const displaySub = targetUser ? `${lastOctet} (${targetUser})` : lastOctet;

        const statusDot = document.createElement('span');
        statusDot.className = `ip-pulse-dot ${connectionType === 'offline' ? 'offline' : 'online'}`;
        statusDot.title = connectionType === 'offline' ? 'Dispositivo Offline' : 'Dispositivo Online';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.id = `ip-${safeIdSlug}`;
        checkbox.name = 'ip';
        checkbox.value = cardIpValue;
        checkbox.className = 'ip-checkbox';

        const label = document.createElement('label');
        label.htmlFor = `ip-${safeIdSlug}`;
        
        const alias = (typeof itemObj === 'object' && itemObj.alias) || deviceAliases[ip] || "";
        const rawHostname = (typeof itemObj === 'object' && itemObj.hostname) || deviceHostnames[ip] || "";
        const hostname = isHostnameConsistentWithIp(rawHostname, ip) ? rawHostname : "";
        const baseName = alias || hostname || ip;
        const seatLabelStr = targetUser ? ` • ${targetUser}` : '';
        const computerName = `${baseName}${seatLabelStr}`;

        const dMeta = deviceMetadataMap[ip] || {};
        const groupName = (typeof itemObj === 'object' && itemObj.group_name) || deviceGroupsMap[ip] || dMeta.group_name || '';
        if (groupName) {
            item.dataset.group = groupName;
        } else {
            delete item.dataset.group;
        }
        if (hostname) item.dataset.hostname = hostname;
        if (alias) item.dataset.alias = alias;
        const mac = (typeof itemObj === 'object' && itemObj.mac) || deviceMacs[ip] || dMeta.mac || '';
        if (mac) item.dataset.mac = mac;

        if (targetUser) {
            const mainTitle = alias || hostname || lastOctet;
            label.innerHTML = `<span class="alias-text">${mainTitle} <small style="opacity:.8;font-size:.8em">(${targetUser})</small></span><span class="ip-subtext">IP: ${ip} • ${targetUser}</span>`;
            label.classList.add('has-alias');
            item.style.borderLeft = "5px solid var(--group-color-3)";
        } else if (alias) {
            label.innerHTML = `<span class="alias-text">${alias}</span><span class="ip-subtext">IP: ${ip}</span>`;
            label.classList.add('has-alias');
        } else if (hostname) {
            label.innerHTML = `<span class="alias-text">${hostname}</span><span class="ip-subtext">IP: ${ip}</span>`;
            label.classList.add('has-hostname');
        } else {
            label.innerHTML = `<span class="alias-text">${lastOctet}</span><span class="ip-subtext">IP: ${ip}</span>`;
        }

        const tooltipText = groupName ? `${computerName} • [${groupName}]` : computerName;
        item.setAttribute('data-tooltip', tooltipText);
        label.setAttribute('title', tooltipText);

        if (connectionType === 'offline') {
            item.classList.add('status-offline');
        } else {
            item.classList.add('status-online');
        }

        const blockBtn = document.createElement('button');
        blockBtn.type = 'button';
        blockBtn.className = 'block-ip-btn';
        blockBtn.setAttribute('data-tooltip', 'Bloquear este IP');
        blockBtn.innerHTML = getIconSvg('x-circle');
        blockBtn.dataset.ip = ip;

        const sshBtn = document.createElement('button');
        sshBtn.type = 'button';
        sshBtn.className = 'btn-ssh-terminal';
        sshBtn.setAttribute('data-tooltip', targetUser ? `SSH (${targetUser})` : 'Abrir Terminal SSH Web');
        sshBtn.innerHTML = `${getIconSvg('terminal')} <span>SSH</span>`;
        sshBtn.dataset.ip = cardIpValue;
        sshBtn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            window.openWebSSHTerminal(ip, targetUser || '');
        };

        const vncBtn = document.createElement('button');
        vncBtn.type = 'button';
        vncBtn.className = 'btn-vnc-desktop';
        vncBtn.setAttribute('data-tooltip', targetUser ? `VNC (${targetUser})` : 'Abrir Área de Trabalho Remota (noVNC)');
        vncBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg> <span>VNC</span>`;
        vncBtn.dataset.ip = cardIpValue;
        vncBtn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            window.openWebVNC(ip, targetUser || (seatIndex !== null ? `:${seatIndex}` : null));
        };

        const userToggleBtn = document.createElement('button');
        userToggleBtn.type = 'button';
        userToggleBtn.className = 'user-toggle-btn';
        userToggleBtn.innerHTML = '👥';
        userToggleBtn.setAttribute('data-tooltip', 'Alvo: Todos');
        userToggleBtn.dataset.target = '';
        userToggleBtn.style.display = 'none';

        const statusIcon = document.createElement('span');
        statusIcon.className = 'status-icon';
        statusIcon.id = `status-${safeIdSlug}`;

        if (previouslySelectedIps.has(cardIpValue) || previouslySelectedIps.has(ip)) {
            checkbox.checked = true;
            item.classList.add('selected');
        }

        checkbox.addEventListener('change', () => {
            item.classList.toggle('selected', checkbox.checked);
        });

        const thumbWrapper = document.createElement('div');
        thumbWrapper.className = 'ip-thumbnail-wrapper';
        thumbWrapper.setAttribute('title', 'Clique para abrir Área de Trabalho Remota (noVNC)');

        const thumbImg = document.createElement('img');
        thumbImg.alt = 'Thumbnail da Tela';
        thumbImg.className = 'ip-thumbnail-img';
        thumbImg.style.display = 'none';

        const placeholder = document.createElement('div');
        placeholder.className = 'ip-thumbnail-placeholder';
        placeholder.innerHTML = `<i data-feather="monitor"></i><span>Sem Sinal</span>`;

        const thumbOverlay = document.createElement('span');
        thumbOverlay.className = 'thumb-overlay';
        thumbOverlay.textContent = 'VNC';

        thumbWrapper.append(thumbImg, placeholder, thumbOverlay);
        thumbWrapper.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            window.openWebVNC(ip, targetUser || (seatIndex !== null ? `:${seatIndex}` : null));
        };

        if (localStorage.getItem('thumbnailModeActive') === 'true') {
            item.classList.add('show-thumbnails');
        }

        const cardHeader = document.createElement('div');
        cardHeader.className = 'ip-card-header';

        const cardIdentity = document.createElement('div');
        cardIdentity.className = 'ip-card-identity';
        cardIdentity.append(statusDot, checkbox, label);

        const cardStatusBadge = document.createElement('div');
        cardStatusBadge.className = 'ip-card-status-badge';
        cardStatusBadge.append(userToggleBtn, statusIcon);

        cardHeader.append(cardIdentity, cardStatusBadge);

        const cardActions = document.createElement('div');
        cardActions.className = 'ip-card-actions';
        cardActions.append(sshBtn, vncBtn, blockBtn);

        item.append(cardHeader, cardActions, thumbWrapper);

        return item;
    }

    async function fetchAliases() {
        try {
            const response = await fetch(`${API_BASE_URL}/get-aliases`);
            const data = await response.json();
            if (data.success) {
                deviceAliases = Object.assign({}, deviceAliases, data.aliases || {});
                if (data.hostnames) {
                    deviceHostnames = Object.assign({}, deviceHostnames, data.hostnames || {});
                }
                syncDeviceMetadataGlobals();
            }
        } catch (e) {
            console.error("Erro ao buscar apelidos:", e);
        }
    }

    // Função para buscar e exibir os IPs
    async function fetchAndDisplayIps(options = {}) {
        console.log("[fetchAndDisplayIps] Iniciando busca e exibição de IPs.");
        
        const logo = document.querySelector('.app-logo, .logo-fallback-icon');
        if (logo) {
            logo.classList.add('spinning-logo');
            logo.classList.remove('logo-error-glow'); // Remove brilho de erro ao tentar novamente
        }

        refreshBtn.disabled = true;
        refreshBtn.classList.add('loading');
        refreshBtnText.textContent = 'Buscando IPs...';

        // Constrói a string de faixa a partir do parser inteligente
        const start = document.getElementById('network-range-start')?.value.trim();
        const end = document.getElementById('network-range-end')?.value.trim();
        const customRange = typeof getComputedCustomRange === 'function' ? getComputedCustomRange() : ((start && end) ? `${start} a ${end}` : (start || ""));

        // Grava automaticamente a faixa de IP pesquisada nas mais usadas
        if (customRange) {
            saveFrequentIpRange(start, end, customRange);
        }

        // Mantém os IPs selecionados para reaplicar a seleção após a atualização.
        const previouslySelectedIps = new Set(Array.from(document.querySelectorAll('input[name="ip"]:checked')).map(cb => cb.value));

        // Helper para conversão de IP em inteiro de 32 bits (ordenação numérica real)
        const ipToNum = (ipStr) => {
            if (!ipStr) return 0;
            const parts = String(ipStr).split('.').map(Number);
            if (parts.length !== 4 || parts.some(isNaN)) return 0;
            return ((parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]) >>> 0;
        };

        // Carrega a ordem salva dos IPs, se existir.
        const savedIpOrder = JSON.parse(localStorage.getItem('ipOrder'));

        // Função para ordenar os IPs com base na ordem salva
        const sortIps = (backendIps) => {
            if (!backendIps) return [];
            if (!savedIpOrder || savedIpOrder.length === 0) {
                return [...backendIps].sort((a, b) => ipToNum(a.ip) - ipToNum(b.ip));
            }

            // Otimização: Usa um Map para lookup O(1) em vez de find/some O(N)
            const backendMap = new Map(backendIps.map(item => [item.ip, item]));
            const savedIpSet = new Set(savedIpOrder);

            // IPs que já têm ordem salva (drag and drop)
            const orderedPart = savedIpOrder
                .filter(ipStr => backendMap.has(ipStr))
                .map(ipStr => backendMap.get(ipStr));

            // Novos IPs (não salvos anteriormente): ordenados numericamente por IP
            const newPart = backendIps
                .filter(item => !savedIpSet.has(item.ip))
                .sort((a, b) => ipToNum(a.ip) - ipToNum(b.ip));

            return [...orderedPart, ...newPart];
        };

        // Limpa o container e adiciona o skeleton com fragmento
        while (ipListContainer.firstChild) {
            ipListContainer.removeChild(ipListContainer.firstChild);
        }
        const skeletonCount = 12; // Número de placeholders a serem exibidos.
        const skeletonFragment = document.createDocumentFragment();
        for (let i = 0; i < skeletonCount; i++) {
            const skeletonItem = document.createElement('div');
            skeletonItem.className = 'skeleton-item';
            skeletonFragment.appendChild(skeletonItem);
        }
        ipListContainer.appendChild(skeletonFragment);

        // REMOVIDO: ipListContainer.innerHTML = ''; <- Isso apagava o skeleton antes da busca começar
        if (ipCountElement) ipCountElement.textContent = ''; // Limpa a contagem
        submitBtn.disabled = true;
        selectAllCheckbox.checked = false;

        try {
            const isFastScanPreferred = localStorage.getItem('useFastSavedClientsScan') !== 'false';
            const shouldRunQuickScan = (options && options.forceQuickScan) ? true : (isFastScanPreferred && !customRange);

            const scanPromise = shouldRunQuickScan
                ? fetch(`${API_BASE_URL}/api/devices/quick-scan`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                })
                : fetch(`${API_BASE_URL}/discover-ips`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ custom_range: customRange })
                });

            // Dispara a busca de apelidos e a varredura de rede em paralelo para ganhar velocidade
            const [aliasRes, scanRes] = await Promise.all([
                fetchAliases(),
                scanPromise
            ]);
            let data = await scanRes.json();

            // Fallback automático: se não há máquinas cadastradas ainda no banco, faz varredura completa da sub-rede
            if (shouldRunQuickScan && data.success && (!data.ips || data.ips.length === 0) && (data.total_saved === 0 || data.total_saved === undefined)) {
                console.log("[fetchAndDisplayIps] Nenhum cliente cadastrado no banco ainda. Executando varredura completa de rede...");
                const fallbackRes = await fetch(`${API_BASE_URL}/discover-ips`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ custom_range: customRange })
                });
                data = await fallbackRes.json();
            }

            if (data.success) {
                if (logo && logo.classList.contains('logo-error-glow')) {
                    logo.classList.remove('logo-error-glow');
                }
                // Ordena os IPs ativos com base na ordem salva antes de exibi-los
                const activeIps = sortIps(data.ips);
                // Limpa o esqueleto de carregamento antes de adicionar os IPs reais.
                ipListContainer.innerHTML = '';

                const onlineCount = activeIps.filter(i => (typeof i === 'object' ? i.type : '') !== 'offline').length;
                if (ipCountElement) {
                    ipCountElement.textContent = `${onlineCount} ativa(s) de ${activeIps.length} encontrada(s) (${data.range || 'Rede'})`;
                }

                const fragment = document.createDocumentFragment();
                activeIps.forEach((itemObj, index) => {
                    if (typeof itemObj === 'object' && itemObj.ip && itemObj.hostname) {
                        if (isHostnameConsistentWithIp(itemObj.hostname, itemObj.ip)) {
                            deviceHostnames[itemObj.ip] = itemObj.hostname;
                        }
                    }
                    if (typeof itemObj === 'object' && itemObj.ip && itemObj.alias) {
                        deviceAliases[itemObj.ip] = itemObj.alias;
                    }
                    const item = createIpItemElement(itemObj, index, null, null, previouslySelectedIps);
                    fragment.appendChild(item);

                    
                    // Inicia a observação de visibilidade para este item
                    statusObserver.observe(item);
                });

                syncDeviceMetadataGlobals();

                if (activeIps.length > 0) {
                    ipListContainer.appendChild(fragment);
                    if (exportIpsBtn) exportIpsBtn.disabled = false;
                    if (typeof renderGroupPills === 'function') renderGroupPills();
                    if (typeof applyIpFilters === 'function') applyIpFilters();
                    logStatusMessage(`Busca de IPs concluída: ${activeIps.length} dispositivo(s) encontrado(s) na faixa ${data.range || 'local'}.`, 'success');
                } else {
                    // Mensagem clara quando nenhum IP é encontrado na faixa configurada.
                    if (data.detection_failed && !customRange) {
                        const manualRange = prompt(
                            "Não conseguimos detectar sua rede automaticamente e nenhum dispositivo foi encontrado na faixa padrão (192.168.50.x).\n\n" +
                            "Por favor, digite a faixa da sua rede (ex: 192.168.1.x):", 
                            localStorage.getItem('customNetworkRange') || ""
                        );
                        if (manualRange) {
                            const rangeInput = document.getElementById('network-range-input');
                            if (rangeInput) rangeInput.value = manualRange;
                            fetchAndDisplayIps(); // Tenta novamente com a nova faixa
                            return;
                        }
                    }
                    if (exportIpsBtn) exportIpsBtn.disabled = true;
                    logStatusMessage(`Nenhum dispositivo encontrado na faixa ${data.range}.`, 'info');
                }
            } else {
                ipListContainer.innerHTML = ''; // Limpa o esqueleto em caso de erro
                logStatusMessage(`Erro ao descobrir IPs: ${data.message}`, 'error');
                // statusBox.innerHTML = `<p class="error-text">Erro ao descobrir IPs: ${data.message}</p>`;
                if (exportIpsBtn) exportIpsBtn.disabled = true;
            }
        } catch (error) {
            ipListContainer.innerHTML = ''; // Limpa o esqueleto em caso de erro de conexão
            if (logo) logo.classList.add('logo-error-glow');
            playAlertSound();
            logStatusMessage(`Erro de conexão com o servidor ao buscar IPs: ${error.message}`, 'error');
            if (exportIpsBtn) exportIpsBtn.disabled = true;
        } finally {
            const logo = document.querySelector('.app-logo, .logo-fallback-icon');
            if (logo) logo.classList.remove('spinning-logo');

            refreshBtn.disabled = false; // Garante que o botão de refresh seja reativado
            refreshBtn.classList.remove('loading');
            refreshBtnText.textContent = 'Recarregar Lista';
            checkFormValidity();
            startStatusMonitor(); // Inicia o monitor de status após a busca de IPs.
        }
    }

    // Listener para o botão de atualização
    // --- Lógica do Monitor de Status ---
    const STATUS_MONITOR_INTERVAL = 30 * 1000; // 30 segundos

    function stopStatusMonitor() {
        if (statusMonitorTimer) {
            clearInterval(statusMonitorTimer);
            statusMonitorTimer = null;
        }
    }

    // --- Otimização de Monitoramento: Intersection Observer ---
    const visibleIps = new Set();
    const statusObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            const ip = entry.target.dataset.ip;
            if (entry.isIntersecting) {
                visibleIps.add(ip);
            } else {
                visibleIps.delete(ip);
            }
        });
    }, { threshold: 0.1 });

    async function checkIpStatuses() {
        const password = getActivePassword();
        if (!password || visibleIps.size === 0) return;

        // Prioriza os IPs que o usuário está realmente vendo no momento
        const ipsToPoll = Array.from(visibleIps);

        try {
            const response = await fetch(`${API_BASE_URL}/check-status`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    ips: ipsToPoll, 
                    password,
                    skip_ssh: false // Desativamos o skip para capturar sinal e usuários
                }),
            });
            const data = await response.json();
            if (data.success) {
                updateIpItemsStatus(data.statuses);
            }
        } catch (error) {
            // Não loga erros para não poluir o log, a falha será silenciosa
            // e tentará novamente no próximo ciclo.
        }
    }

    function updateIpItemsStatus(statuses) {
        requestAnimationFrame(() => {
            const ipItemMap = new Map();
            ipListContainer.querySelectorAll('.ip-item').forEach(item => {
                ipItemMap.set(item.dataset.ip, item);
            });

            for (const ip in statuses) {
                const statusData = statuses[ip];
                const status = (typeof statusData === 'object') ? statusData.status : statusData;
                const userCount = (typeof statusData === 'object' && statusData.user_count) ? statusData.user_count : 0;
                const usersRaw = (typeof statusData === 'object' && statusData.users) ? statusData.users : "";
                const usersList = usersRaw ? usersRaw.split(',').map(u => u.trim()).filter(Boolean) : [];

                if (typeof statusData === 'object') {
                    if (statusData.hostname && isHostnameConsistentWithIp(statusData.hostname, ip)) {
                        deviceHostnames[ip] = statusData.hostname;
                        const cardItem = ipItemMap.get(ip);
                        if (cardItem) {
                            const label = cardItem.querySelector('label');
                            const alias = deviceAliases[ip];
                            if (label && !alias) {
                                const aliasSpan = label.querySelector('.alias-text');
                                if (aliasSpan && aliasSpan.textContent !== statusData.hostname) {
                                    aliasSpan.textContent = statusData.hostname;
                                    label.classList.remove('has-alias');
                                    label.classList.add('has-hostname');
                                    cardItem.setAttribute('data-tooltip', statusData.hostname);
                                    label.setAttribute('title', statusData.hostname);
                                }
                            }
                        }
                    }
                    if (statusData.users) deviceUsers[ip] = statusData.users;
                }

                if (usersList.length >= 2 || userCount >= 2) {
                    const rawSeatList = usersList.length > 0 ? usersList : Array.from({length: userCount}, (_, i) => `seat${i}`);
                    
                    // Ordenação alfanumérica natural (ex: aluno1, aluno2, aluno3... em vez de aluno1, aluno10, aluno2)
                    const seatList = [...rawSeatList].sort((a, b) => 
                        a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' })
                    );

                    const mainItem = ipItemMap.get(ip);
                    let lastNode = mainItem;

                    seatList.forEach((u, sIdx) => {
                        const seatKey = `${ip}/${u}`;
                        let seatItem = ipListContainer.querySelector(`.ip-item[data-ip="${seatKey}"]`);
                        if (!seatItem) {
                            seatItem = createIpItemElement({ ip, hostname: deviceHostnames[ip] }, 0, u, sIdx);
                            if (lastNode && lastNode.parentNode) {
                                lastNode.parentNode.insertBefore(seatItem, lastNode.nextSibling);
                            } else if (mainItem && mainItem.parentNode) {
                                mainItem.parentNode.insertBefore(seatItem, mainItem.nextSibling);
                            } else {
                                ipListContainer.appendChild(seatItem);
                            }
                            if (typeof statusObserver !== 'undefined' && statusObserver) {
                                statusObserver.observe(seatItem);
                            }
                        }
                        lastNode = seatItem;

                        seatItem.classList.remove('status-online', 'status-offline', 'status-auth-error');
                        seatItem.classList.add('ping-checked');
                        if (status === 'offline') seatItem.classList.add('status-offline');
                        else if (status === 'auth_error') seatItem.classList.add('status-auth-error');
                        else seatItem.classList.add('status-online');
                    });

                    if (mainItem) {
                        mainItem.dataset.multiseatParent = "true";
                        mainItem.classList.add('multiseat-parent-hidden');
                        mainItem.style.display = 'none';
                    }
                } else {
                    const item = ipItemMap.get(ip);
                    if (item && item.dataset.multiseatParent !== "true") {
                        item.classList.remove('status-online', 'status-offline', 'status-auth-error');
                        item.classList.add('ping-checked');
                        if (status === 'offline') item.classList.add('status-offline');
                        else if (status === 'auth_error') item.classList.add('status-auth-error');
                        else item.classList.add('status-online');
                    }
                }
            }
            applyIpFilters();
        });
    }

    // --- Monitor de Miniaturas em Tempo Real (Thumbnails VNC) ---
    let isThumbnailModeActive = localStorage.getItem('thumbnailModeActive') === 'true';
    let thumbnailTimer = null;
    let isRefreshingThumbnails = false;

    function stopThumbnailMonitor() {
        if (thumbnailTimer) {
            clearInterval(thumbnailTimer);
            thumbnailTimer = null;
        }
    }

    function fetchItemThumbnail(item, password) {
        return new Promise((resolve) => {
            const cardIpValue = item.dataset.ip;
            const thumbImg = item.querySelector('.ip-thumbnail-img');
            const wrapper = item.querySelector('.ip-thumbnail-wrapper');
            const placeholder = item.querySelector('.ip-thumbnail-placeholder');
            if (!thumbImg || !cardIpValue) return resolve();

            if (wrapper) wrapper.classList.add('loading');
            const srcUrl = `${API_BASE_URL}/api/thumbnail/${cardIpValue}?t=${Date.now()}&password=${encodeURIComponent(password)}`;
            const tempImg = new Image();

            const timer = setTimeout(() => {
                tempImg.onload = null;
                tempImg.onerror = null;
                if (wrapper) wrapper.classList.remove('loading');
                resolve();
            }, 7000);

            tempImg.onload = () => {
                clearTimeout(timer);
                thumbImg.src = srcUrl;
                thumbImg.style.display = 'block';
                if (placeholder) placeholder.style.display = 'none';
                if (wrapper) wrapper.classList.remove('loading');
                resolve();
            };
            tempImg.onerror = () => {
                clearTimeout(timer);
                if (wrapper) wrapper.classList.remove('loading');
                if (thumbImg.style.display !== 'block') {
                    if (placeholder) placeholder.style.display = 'flex';
                }
                resolve();
            };
            tempImg.src = srcUrl;
        });
    }

    async function refreshThumbnails() {
        if (!isThumbnailModeActive || !ipListContainer || isRefreshingThumbnails) return;
        isRefreshingThumbnails = true;

        try {
            const allItems = Array.from(ipListContainer.querySelectorAll('.ip-item'));
            allItems.forEach(item => item.classList.toggle('show-thumbnails', isThumbnailModeActive));

            const validItems = allItems.filter(item => {
                if (item.style.display === 'none' || item.dataset.multiseatParent === 'true') return false;
                // Ignora somente se já passou por verificação de ping E foi confirmado status-offline
                if (item.classList.contains('status-offline') && item.classList.contains('ping-checked')) return false;
                return true;
            });

            const password = getActivePassword();

            // Fila com concorrência otimizada de 4 requisições por vez para atualização rápida e suave
            const CONCURRENCY = 4;
            for (let i = 0; i < validItems.length; i += CONCURRENCY) {
                if (!isThumbnailModeActive) break;
                const chunk = validItems.slice(i, i + CONCURRENCY);
                await Promise.all(chunk.map(item => fetchItemThumbnail(item, password)));
            }
        } catch (err) {
            console.warn("Erro ao atualizar miniaturas:", err);
        } finally {
            isRefreshingThumbnails = false;
        }
    }

    function startThumbnailMonitor() {
        stopThumbnailMonitor();
        if (isThumbnailModeActive) {
            refreshThumbnails();
            thumbnailTimer = setInterval(refreshThumbnails, 14000); // Atualiza suavemente a cada 14s
        }
    }

    const toggleThumbnailsBtn = document.getElementById('toggle-thumbnails-btn');
    if (toggleThumbnailsBtn) {
        if (isThumbnailModeActive) {
            toggleThumbnailsBtn.classList.add('active');
        }
        toggleThumbnailsBtn.addEventListener('click', () => {
            isThumbnailModeActive = !isThumbnailModeActive;
            localStorage.setItem('thumbnailModeActive', isThumbnailModeActive ? 'true' : 'false');
            toggleThumbnailsBtn.classList.toggle('active', isThumbnailModeActive);

            const allIpItems = document.querySelectorAll('.ip-item');
            allIpItems.forEach(item => {
                item.classList.toggle('show-thumbnails', isThumbnailModeActive);
            });

            if (isThumbnailModeActive) {
                startThumbnailMonitor();
                showToast('Modo Miniaturas ativado.', 'details');
            } else {
                stopThumbnailMonitor();
                showToast('Modo Miniaturas desativado.', 'details');
            }
        });
    }

    function startStatusMonitor() {
        stopStatusMonitor(); // Garante que não haja timers duplicados
        statusMonitorTimer = setInterval(checkIpStatuses, STATUS_MONITOR_INTERVAL);
        startThumbnailMonitor();
    }

    // --- Gerenciamento de Visibilidade da Página ---
    // Pausa o monitoramento se a aba estiver oculta para economizar recursos
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            stopStatusMonitor();
            if (autoRefreshToggle.checked && autoRefreshTimer) {
                 // Opcional: Pausar também o refresh completo se desejado, 
                 // mas o status monitor é o mais frequente.
            }
        } else {
            // Retoma o monitoramento se o auto-refresh estiver ligado ou se a página acabou de carregar
            // ou simplesmente reinicia o ciclo de status para feedback imediato
            checkIpStatuses(); // Executa um check imediato ao voltar
            startStatusMonitor();
        }
    });

    refreshBtn.addEventListener('click', () => {
        fetchAndDisplayIps();
    });

    // --- Lógica de Drag and Drop para a Lista de IPs ---
    if (ipListContainer) {
        let draggedItem = null;

        // Evento quando um item começa a ser arrastado
        ipListContainer.addEventListener('dragstart', (e) => {
            draggedItem = e.target.closest('.ip-item');
            if (draggedItem) {
                // Adiciona um estilo para indicar visualmente qual item está sendo arrastado
                setTimeout(() => {
                    draggedItem.classList.add('dragging');
                }, 0);
            }
        });

        // Evento quando o item arrastado está sobre outro item
        ipListContainer.addEventListener('dragover', (e) => {
            e.preventDefault(); // Necessário para permitir o 'drop'
            const targetItem = e.target.closest('.ip-item');
            if (targetItem && draggedItem && targetItem !== draggedItem) {
                // Determina se o item arrastado deve ser inserido antes ou depois do alvo
                const rect = targetItem.getBoundingClientRect();
                // Pega a posição do mouse em relação ao centro do elemento alvo
                const offset = e.clientY - rect.top - rect.height / 2;

                if (offset < 0) {
                    // Insere antes do alvo
                    ipListContainer.insertBefore(draggedItem, targetItem);
                } else {
                    // Insere depois do alvo
                    ipListContainer.insertBefore(draggedItem, targetItem.nextSibling);
                }
            }
        });

        // Evento quando o item é solto
        ipListContainer.addEventListener('drop', (e) => {
            e.preventDefault();
            if (draggedItem) {
                draggedItem.classList.remove('dragging');
                draggedItem = null;

                // Debounce para evitar múltiplas escritas no localStorage durante reorganizações rápidas
                clearTimeout(window.saveOrderTimeout);
                window.saveOrderTimeout = setTimeout(() => {
                    const currentIpOrder = Array.from(ipListContainer.querySelectorAll('.ip-item')).map(item => item.dataset.ip);
                    localStorage.setItem('ipOrder', JSON.stringify(currentIpOrder));
                    logStatusMessage('Ordem dos IPs salva.', 'details');
                }, 1000);
            }
        });

        // Evento que ocorre ao final da operação de arrastar (seja soltando ou cancelando)
        ipListContainer.addEventListener('dragend', () => {
            if (draggedItem) {
                // Garante que a classe 'dragging' seja removida
                draggedItem.classList.remove('dragging');
                draggedItem = null;
            }
        });
    }

    // --- Lógica para Bloqueio de IP ---
    ipListContainer.addEventListener('click', async (event) => {
        const blockBtn = event.target.closest('.block-ip-btn');
        if (blockBtn) {
            const ip = blockBtn.dataset.ip;
            const ipItem = blockBtn.closest('.ip-item');

            const confirmed = await showConfirmationModal(`Tem certeza que deseja bloquear permanentemente o IP ${ip}?\n\nEste dispositivo não aparecerá mais nas buscas e será removido do cache.`);
            if (!confirmed) {
                logStatusMessage(`Bloqueio do IP ${ip} cancelado.`, 'details');
                return;
            }

            try {
                const response = await fetch(`${API_BASE_URL}/block-ip`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ip: ip }),
                });
                const data = await response.json();

                if (data.success) {
                    logStatusMessage(data.message, 'success');
                    // Animação de saída suave
                    ipItem.style.transition = 'opacity 0.3s ease-out, transform 0.3s ease-out, height 0.3s ease-out, padding 0.3s ease-out, margin 0.3s ease-out';
                    ipItem.style.opacity = '0';
                    ipItem.style.transform = 'scale(0.9)';
                    ipItem.style.height = '0px';
                    ipItem.style.padding = '0';
                    ipItem.style.margin = '0';
                    setTimeout(() => ipItem.remove(), 300);
                } else {
                    logStatusMessage(`Falha ao bloquear IP ${ip}: ${data.message}`, 'error');
                }
            } catch (error) {
                logStatusMessage(`Erro de conexão ao tentar bloquear IP ${ip}: ${error.message}`, 'error');
            }
            return;
        }

    });

    // Função para limpar a seleção e redefinir a interface
    function resetUI() {
        // 1. Desmarcar todos os checkboxes de IP e remover classe selected
        document.querySelectorAll('input[name="ip"]').forEach(checkbox => {
            checkbox.checked = false;
            const item = checkbox.closest('.ip-item');
            if (item) item.classList.remove('selected');
        });
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = false;

        // 1.b. Redefine o menu de ações e dispara a atualização da UI (esconde tags e campos condicionais)
        Array.from(actionSelect.options).forEach(option => option.selected = false);
        actionSelect.dispatchEvent(new Event('change', { bubbles: true }));

        // 1.c. Desmarcar e parar a atualização automática se estiver ativa
        if (autoRefreshToggle.checked) {
            autoRefreshToggle.checked = false;
            autoRefreshToggle.dispatchEvent(new Event('change'));
        }

        // Limpa campos de texto que podem ter sido preenchidos
        messageText.value = '';
        processNameText.value = '';
        devicePathText.value = '';
        wallpaperFile.value = ''; // Limpa a seleção de arquivo

        // 4. Redefinir a barra de progresso
        progressBar.style.width = '0%';
        progressText.textContent = 'Pronto para executar.';
        fixKeysBtn.classList.add('hidden'); // Esconde o botão de corrigir chaves
        submitBtnText.textContent = 'Executar Ação'; // Reseta o texto do botão de submissão

        // Revalidar o formulário e atualizar dock
        checkFormValidity();
        if (typeof updateSelectionCounter === 'function') updateSelectionCounter();
        logStatusMessage('Interface limpa.', 'details');
    }

    // Listener para o botão de limpar/resetar
    resetBtn.addEventListener('click', resetUI);

    // Listener para o checkbox "Selecionar Todos"
    selectAllCheckbox.addEventListener('change', (event) => {
        const isChecked = event.target.checked;
        document.querySelectorAll('input[name="ip"]').forEach(checkbox => {
            checkbox.checked = isChecked;
            const item = checkbox.closest('.ip-item');
            if (item) item.classList.toggle('selected', isChecked);
        });
        checkFormValidity();
        if (typeof updateSelectionCounter === 'function') updateSelectionCounter();
    });

    // --- Botão para Selecionar Apenas Online ---
    const selectOnlineBtn = document.getElementById('select-online-btn');
    
    if (selectOnlineBtn) {
        selectOnlineBtn.addEventListener('click', () => {
            const ipItems = document.querySelectorAll('.ip-item');
            let count = 0;
            
            ipItems.forEach(item => {
                if (item.style.display !== 'none') {
                    const checkbox = item.querySelector('input[name="ip"]');
                    if (checkbox) {
                        const isOnline = item.classList.contains('status-online');
                        checkbox.checked = isOnline;
                        item.classList.toggle('selected', isOnline);
                        if (isOnline) count++;
                    }
                }
            });
            
            const visibleItems = Array.from(ipItems).filter(item => item.style.display !== 'none');
            const total = visibleItems.length;
            
            selectAllCheckbox.checked = (count === total && total > 0);
            selectAllCheckbox.indeterminate = (count > 0 && count < total);
            
            checkFormValidity();
            if (typeof updateSelectionCounter === 'function') updateSelectionCounter();
            logStatusMessage(`${count} dispositivo(s) online selecionado(s).`, 'details');
        });
    }

    // --- Estado dos Grupos e Filtros ---
    let activeStatusFilter = 'all';
    let activeGroupFilter = 'all';
    let currentBatchState = {
        total: 0,
        success: 0,
        failed: 0,
        pending: 0,
        failedIps: [],
        payload: null,
        actionText: ''
    };

    function syncCardsMetadataAndGroups() {
        const allCards = document.querySelectorAll('#ip-list .ip-item');
        allCards.forEach(card => {
            const ip = card.dataset.baseIp || card.dataset.ip || '';
            if (!ip) return;
            const targetUser = card.dataset.targetUser || null;
            const lastOctet = ip.split('.').pop();
            const dMeta = deviceMetadataMap[ip] || {};
            const groupName = deviceGroupsMap[ip] || dMeta.group_name || '';
            const alias = deviceAliases[ip] || dMeta.alias || '';
            const rawHostname = deviceHostnames[ip] || dMeta.hostname || '';
            const hostname = isHostnameConsistentWithIp(rawHostname, ip) ? rawHostname : '';
            const mac = deviceMacs[ip] || dMeta.mac || '';

            if (groupName) {
                card.dataset.group = groupName;
            } else {
                delete card.dataset.group;
            }

            if (hostname) card.dataset.hostname = hostname;
            if (alias) card.dataset.alias = alias;
            if (mac) card.dataset.mac = mac;

            const baseName = alias || hostname || ip;
            const seatLabelStr = targetUser ? ` • ${targetUser}` : '';
            const computerName = `${baseName}${seatLabelStr}`;
            const tooltipText = groupName ? `${computerName} • [${groupName}]` : computerName;
            card.setAttribute('data-tooltip', tooltipText);

            const label = card.querySelector('label');
            if (label) {
                label.setAttribute('title', tooltipText);
                if (targetUser) {
                    const mainTitle = alias || hostname || lastOctet;
                    label.innerHTML = `<span class="alias-text">${mainTitle} <small style="opacity:.8;font-size:.8em">(${targetUser})</small></span><span class="ip-subtext">IP: ${ip} • ${targetUser}</span>`;
                    label.classList.add('has-alias');
                } else if (alias) {
                    label.innerHTML = `<span class="alias-text">${alias}</span><span class="ip-subtext">IP: ${ip}</span>`;
                    label.classList.add('has-alias');
                } else if (hostname) {
                    label.innerHTML = `<span class="alias-text">${hostname}</span><span class="ip-subtext">IP: ${ip}</span>`;
                    label.classList.add('has-hostname');
                } else {
                    label.innerHTML = `<span class="alias-text">${lastOctet}</span><span class="ip-subtext">IP: ${ip}</span>`;
                }
            }
        });
    }

    async function loadGroupAndDeviceMetadata() {
        try {
            const [devRes, grpRes] = await Promise.all([
                fetch(`${API_BASE_URL}/api/devices`),
                fetch(`${API_BASE_URL}/api/groups`)
            ]);
            const devData = await devRes.json();
            const grpData = await grpRes.json();

            if (devData.success) {
                const list = devData.list || (devData.devices ? Object.values(devData.devices) : []);
                if (Array.isArray(list)) {
                    list.forEach(d => {
                        if (d.ip) {
                            deviceMetadataMap[d.ip] = d;
                            if (d.mac) deviceMacs[d.ip] = d.mac;
                            if (d.hostname) deviceHostnames[d.ip] = d.hostname;
                            if (d.alias) deviceAliases[d.ip] = d.alias;
                            if (d.group_name) {
                                deviceGroupsMap[d.ip] = d.group_name;
                            } else {
                                delete deviceGroupsMap[d.ip];
                            }
                        }
                    });
                }
            }

            syncCardsMetadataAndGroups();

            if (grpData.success && grpData.groups) {
                renderGroupPills(grpData.groups);
                updateGroupDatalist(Object.keys(grpData.groups));
            } else {
                renderGroupPills({});
            }
        } catch (e) {
            console.warn("Metadados de grupos indisponíveis ou inicializando:", e);
        }
    }

    let latestGroupsData = {};

    function renderGroupPills(groups = null) {
        if (groups && typeof groups === 'object') {
            latestGroupsData = groups;
        } else {
            groups = latestGroupsData || {};
        }

        const dynamicContainer = document.getElementById('dynamic-group-pills');
        if (!dynamicContainer) return;
        dynamicContainer.innerHTML = '';

        const allItems = Array.from(document.querySelectorAll('.ip-item'));
        const totalCards = allItems.length;

        // 1. Pílula "Todos"
        const allPill = document.createElement('div');
        allPill.className = `group-pill group-pill-all ${activeGroupFilter === 'all' ? 'active' : ''}`;
        allPill.dataset.group = 'all';
        allPill.title = 'Mostrar todos os computadores (Clique para filtrar ou no botão para selecionar/desmarcar todos)';
        allPill.innerHTML = `
            <span class="group-pill-name"><i data-feather="grid" style="width:12px;height:12px;"></i> Todos</span>
            <span class="pill-count" id="group-pill-count-all">${totalCards}</span>
            <button type="button" class="group-pill-select-btn" title="Alternar seleção de todas as máquinas">
                <i data-feather="check-square" style="width:11px;height:11px;"></i>
            </button>
        `;

        const allSelectBtn = allPill.querySelector('.group-pill-select-btn');
        if (allSelectBtn) {
            allSelectBtn.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                const allCbs = allItems.map(item => item.querySelector('input[name="ip"]')).filter(Boolean);
                if (allCbs.length === 0) return;
                const allChecked = allCbs.every(cb => cb.checked);
                const newState = !allChecked;
                allCbs.forEach(cb => {
                    cb.checked = newState;
                    const card = cb.closest('.ip-item');
                    if (card) card.classList.toggle('selected', newState);
                });
                checkFormValidity();
                if (typeof updateSelectionCounter === 'function') updateSelectionCounter();
                if (typeof showToast === 'function') {
                    showToast(newState ? `✅ Todos os ${allCbs.length} computadores selecionados.` : `⚪ Seleção limpa.`, 'info', 2000);
                }
            };
        }

        allPill.onclick = (e) => {
            if (e.target.closest('.group-pill-select-btn')) return;
            activeGroupFilter = 'all';
            dynamicContainer.querySelectorAll('.group-pill').forEach(p => p.classList.remove('active'));
            allPill.classList.add('active');
            applyIpFilters();
        };
        dynamicContainer.appendChild(allPill);

        const groupNames = Object.keys(groups || {}).sort();
        let assignedIpsSet = new Set();

        groupNames.forEach(groupName => {
            const groupIps = groups[groupName] || [];
            groupIps.forEach(ip => assignedIpsSet.add(ip));

            // Conta máquinas no DOM associadas a este grupo
            const countInDom = allItems.filter(item => {
                const baseIp = item.dataset.baseIp || item.dataset.ip || '';
                const itemGroup = item.dataset.group || deviceGroupsMap[baseIp] || (deviceMetadataMap[baseIp] && deviceMetadataMap[baseIp].group_name) || '';
                return itemGroup.toLowerCase() === groupName.toLowerCase() || groupIps.includes(baseIp);
            }).length;

            const displayCount = countInDom > 0 ? countInDom : groupIps.length;

            const pill = document.createElement('div');
            pill.className = `group-pill ${activeGroupFilter === groupName ? 'active' : ''}`;
            pill.dataset.group = groupName;
            pill.title = `Grupo "${groupName}" • ${displayCount} computador(es)\n• Clique para filtrar\n• Clique no ícone de check para selecionar/desmarcar o grupo`;

            pill.innerHTML = `
                <span class="group-pill-name"><i data-feather="monitor" style="width:12px;height:12px;"></i> ${groupName}</span>
                <span class="pill-count">${displayCount}</span>
                <button type="button" class="group-pill-select-btn" title="Selecionar / Desmarcar todos os computadores de ${groupName}">
                    <i data-feather="check" style="width:11px;height:11px;"></i>
                </button>
            `;

            // Botão de Seleção Rápida em Lote do Grupo
            const selectBtn = pill.querySelector('.group-pill-select-btn');
            if (selectBtn) {
                selectBtn.onclick = (e) => {
                    e.preventDefault();
                    e.stopPropagation();

                    const groupCheckboxes = [];
                    allItems.forEach(item => {
                        const baseIp = item.dataset.baseIp || item.dataset.ip || '';
                        const itemGroup = item.dataset.group || deviceGroupsMap[baseIp] || (deviceMetadataMap[baseIp] && deviceMetadataMap[baseIp].group_name) || '';
                        if (itemGroup.toLowerCase() === groupName.toLowerCase() || groupIps.includes(baseIp)) {
                            const cb = item.querySelector('input[name="ip"]');
                            if (cb) groupCheckboxes.push(cb);
                        }
                    });

                    if (groupCheckboxes.length === 0) {
                        if (typeof showToast === 'function') {
                            showToast(`Nenhuma máquina de "${groupName}" encontrada na grade.`, 'warning');
                        }
                        return;
                    }

                    const allChecked = groupCheckboxes.every(cb => cb.checked);
                    const newCheckedState = !allChecked;

                    groupCheckboxes.forEach(cb => {
                        cb.checked = newCheckedState;
                        const card = cb.closest('.ip-item');
                        if (card) card.classList.toggle('selected', newCheckedState);
                    });

                    checkFormValidity();
                    if (typeof updateSelectionCounter === 'function') updateSelectionCounter();

                    if (typeof showToast === 'function') {
                        showToast(
                            newCheckedState 
                                ? `✅ ${groupCheckboxes.length} máquina(s) do grupo "${groupName}" selecionadas.` 
                                : `⚪ Seleção do grupo "${groupName}" desmarcada.`,
                            newCheckedState ? 'success' : 'info',
                            2500
                        );
                    }
                };
            }

            // Clique no corpo do chip para filtrar
            pill.onclick = (e) => {
                if (e.target.closest('.group-pill-select-btn')) return;

                if (activeGroupFilter === groupName) {
                    activeGroupFilter = 'all';
                    dynamicContainer.querySelectorAll('.group-pill').forEach(p => p.classList.remove('active'));
                    allPill.classList.add('active');
                } else {
                    activeGroupFilter = groupName;
                    dynamicContainer.querySelectorAll('.group-pill').forEach(p => p.classList.remove('active'));
                    pill.classList.add('active');
                }
                applyIpFilters();
            };

            dynamicContainer.appendChild(pill);
        });

        // 3. Pílula "Sem Grupo" se houver computadores não associados a nenhum grupo
        const unassignedItems = allItems.filter(item => {
            const baseIp = item.dataset.baseIp || item.dataset.ip || '';
            const itemGroup = item.dataset.group || deviceGroupsMap[baseIp] || (deviceMetadataMap[baseIp] && deviceMetadataMap[baseIp].group_name) || '';
            return !itemGroup && !assignedIpsSet.has(baseIp);
        });

        if (unassignedItems.length > 0) {
            const noGroupPill = document.createElement('div');
            noGroupPill.className = `group-pill group-pill-unassigned ${activeGroupFilter === '__no_group__' ? 'active' : ''}`;
            noGroupPill.dataset.group = '__no_group__';
            noGroupPill.title = `${unassignedItems.length} computadores sem grupo cadastrado\n• Clique para filtrar\n• Clique no check para selecionar todos`;

            noGroupPill.innerHTML = `
                <span class="group-pill-name"><i data-feather="help-circle" style="width:12px;height:12px;"></i> Sem Grupo</span>
                <span class="pill-count">${unassignedItems.length}</span>
                <button type="button" class="group-pill-select-btn" title="Selecionar / Desmarcar máquinas sem grupo">
                    <i data-feather="check" style="width:11px;height:11px;"></i>
                </button>
            `;

            const selectNoGroupBtn = noGroupPill.querySelector('.group-pill-select-btn');
            if (selectNoGroupBtn) {
                selectNoGroupBtn.onclick = (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const cbs = unassignedItems.map(item => item.querySelector('input[name="ip"]')).filter(Boolean);
                    if (cbs.length === 0) return;
                    const allChecked = cbs.every(cb => cb.checked);
                    const newState = !allChecked;
                    cbs.forEach(cb => {
                        cb.checked = newState;
                        const card = cb.closest('.ip-item');
                        if (card) card.classList.toggle('selected', newState);
                    });
                    checkFormValidity();
                    if (typeof updateSelectionCounter === 'function') updateSelectionCounter();
                    if (typeof showToast === 'function') {
                        showToast(newState ? `✅ ${cbs.length} máquina(s) sem grupo selecionadas.` : `⚪ Seleção limpa.`, 'info');
                    }
                };
            }

            noGroupPill.onclick = (e) => {
                if (e.target.closest('.group-pill-select-btn')) return;
                if (activeGroupFilter === '__no_group__') {
                    activeGroupFilter = 'all';
                    dynamicContainer.querySelectorAll('.group-pill').forEach(p => p.classList.remove('active'));
                    allPill.classList.add('active');
                } else {
                    activeGroupFilter = '__no_group__';
                    dynamicContainer.querySelectorAll('.group-pill').forEach(p => p.classList.remove('active'));
                    noGroupPill.classList.add('active');
                }
                applyIpFilters();
            };

            dynamicContainer.appendChild(noGroupPill);
        }

        if (window.feather) feather.replace();
    }

    function updateGroupDatalist(groupNames) {
        const datalist = document.getElementById('existing-groups-datalist');
        if (!datalist) return;
        datalist.innerHTML = '';
        groupNames.forEach(name => {
            const opt = document.createElement('option');
            opt.value = name;
            datalist.appendChild(opt);
        });
    }

    // Event Listener para Barra de Status Pills
    const statusPillsBar = document.getElementById('status-pills-bar');
    if (statusPillsBar) {
        statusPillsBar.addEventListener('click', (e) => {
            const pill = e.target.closest('.status-pill');
            if (!pill) return;
            statusPillsBar.querySelectorAll('.status-pill').forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            activeStatusFilter = pill.dataset.statusFilter || 'all';
            applyIpFilters();
        });
    }

    // Handlers para o Modal de Atribuir Grupo / Laboratório
    const openSetGroupBtn = document.getElementById('open-set-group-modal-btn');
    const setGroupModal = document.getElementById('set-group-modal');
    const confirmSetGroupBtn = document.getElementById('confirm-set-group-btn');
    const groupNameInput = document.getElementById('group-name-input');

    if (openSetGroupBtn && setGroupModal) {
        openSetGroupBtn.onclick = () => {
            const selectedIps = Array.from(document.querySelectorAll('input[name="ip"]:checked')).map(cb => cb.value);
            if (selectedIps.length === 0) {
                alert('Por favor, selecione pelo menos um computador na lista para atribuir um grupo.');
                return;
            }
            if (groupNameInput) groupNameInput.value = '';
            setGroupModal.classList.remove('hidden');
        };
    }

    if (confirmSetGroupBtn) {
        confirmSetGroupBtn.onclick = async () => {
            const selectedIps = Array.from(document.querySelectorAll('input[name="ip"]:checked')).map(cb => cb.value);
            const groupName = groupNameInput ? groupNameInput.value.trim() : '';

            try {
                const res = await fetch(`${API_BASE_URL}/api/device/group`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ips: selectedIps, group_name: groupName })
                });
                const data = await res.json();
                if (data.success) {
                    logStatusMessage(data.message, 'success');
                    setGroupModal.classList.add('hidden');
                    await loadGroupAndDeviceMetadata();
                    if (typeof window.refreshSavedClientsData === 'function') window.refreshSavedClientsData();
                    if (typeof fetchAndDisplayIps === 'function') fetchAndDisplayIps();
                } else {
                    logStatusMessage(`Erro ao atribuir grupo: ${data.message}`, 'error');
                }
            } catch (e) {
                logStatusMessage(`Erro de rede ao salvar grupo: ${e.message}`, 'error');
            }
        };
    }

    // --- Função Centralizada de Filtragem (Pesquisa + Status + Grupo) ---
    let lastDesyncTotal = null;
    function applyIpFilters() {
        const searchTerm = ipSearchInput.value.toLowerCase().trim();
        const hideOffline = hideOfflineToggle ? hideOfflineToggle.checked : false;
        const showDesyncOnly = showDesyncOnlyToggle ? showDesyncOnlyToggle.checked : false;
        const ipItems = document.querySelectorAll('.ip-item');
        let visibleCount = 0;
        let desyncTotal = 0;
        let totalItemsCount = 0;
        let onlineCount = 0;
        let offlineCount = 0;
        let blockedCount = 0;

        ipItems.forEach(item => {
            if (item.dataset.multiseatParent === "true" || item.classList.contains('multiseat-parent-hidden')) {
                item.style.display = 'none';
                return;
            }

            totalItemsCount++;

            if (item.classList.contains('status-sync-error')) desyncTotal++;
            const isOnline = item.classList.contains('status-online');
            const isOffline = item.classList.contains('status-offline');
            const isBlocked = item.classList.contains('status-blocked') || item.querySelector('.unblock-ip-btn') !== null;

            if (isOnline) {
                onlineCount++;
            } else {
                offlineCount++;
            }

            if (isBlocked) blockedCount++;

            const ip = item.dataset.ip || "";
            const baseIp = item.dataset.baseIp || ip;
            const textContent = item.textContent ? item.textContent.toLowerCase() : "";
            const itemGroup = item.dataset.group || deviceGroupsMap[baseIp] || (deviceMetadataMap[baseIp] && deviceMetadataMap[baseIp].group_name) || "";
            
            const matchesSearch = !searchTerm || 
                ip.toLowerCase().includes(searchTerm) || 
                textContent.includes(searchTerm) || 
                itemGroup.toLowerCase().includes(searchTerm);
            
            let matchesStatusFilter = true;
            if (activeStatusFilter === 'online') matchesStatusFilter = isOnline;
            else if (activeStatusFilter === 'offline') matchesStatusFilter = isOffline;
            else if (activeStatusFilter === 'blocked') matchesStatusFilter = isBlocked;

            let matchesGroupFilter = true;
            if (activeGroupFilter === '__no_group__' || activeGroupFilter === '__none__') {
                matchesGroupFilter = !itemGroup || itemGroup.trim() === '';
            } else if (activeGroupFilter && activeGroupFilter !== 'all') {
                matchesGroupFilter = (itemGroup.toLowerCase() === activeGroupFilter.toLowerCase());
            }

            const shouldHide = hideOffline && isOffline;
            const shouldHideSyncOk = showDesyncOnly && !item.classList.contains('status-sync-error');

            if (matchesSearch && matchesStatusFilter && matchesGroupFilter && !shouldHide && !shouldHideSyncOk) {
                if (item.style.display === 'none') {
                    item.style.display = '';
                }
                item.style.animationDelay = `${visibleCount * 0.01}s`;
                visibleCount++;
            } else {
                item.style.display = 'none';
            }
        });

        // Atualiza os contadores das pílulas de status
        const countAll = document.getElementById('count-all');
        const countOnline = document.getElementById('count-online');
        const countOffline = document.getElementById('count-offline');
        const countBlocked = document.getElementById('count-blocked');

        if (countAll) countAll.textContent = totalItemsCount;
        if (countOnline) countOnline.textContent = onlineCount;
        if (countOffline) countOffline.textContent = offlineCount;
        if (countBlocked) countBlocked.textContent = blockedCount;

        // Alerta visual no cabeçalho se o número de máquinas desincronizadas mudar
        if (lastDesyncTotal !== null && desyncTotal !== lastDesyncTotal) {
            const headerElement = document.querySelector('header');
            if (headerElement) {
                headerElement.classList.remove('header-desync-alert');
                void headerElement.offsetWidth;
                headerElement.classList.add('header-desync-alert');
                setTimeout(() => headerElement.classList.remove('header-desync-alert'), 3000);
            }
        }
        lastDesyncTotal = desyncTotal;

        if (ipCountElement) {
            ipCountElement.textContent = '';
        }

        const badgeContainer = document.getElementById('desync-badge-container');
        if (badgeContainer) {
            badgeContainer.innerHTML = desyncTotal > 0 
                ? `<span class="error-text" style="font-size: 0.7em; margin-left: 10px; background: color-mix(in srgb, var(--error-color) 15%, transparent); padding: 2px 8px; border-radius: 10px; border: 1px solid var(--error-color); white-space: nowrap;">⚠️ ${desyncTotal} com hora errada</span>` 
                : '';
        }

        const statsOnline = document.getElementById('stats-online');
        const statsOffline = document.getElementById('stats-offline');
        if (statsOnline) statsOnline.textContent = onlineCount;
        if (statsOffline) statsOffline.textContent = offlineCount;

        const totalActive = onlineCount + offlineCount;
        const healthPercent = totalActive > 0 ? Math.round((onlineCount / totalActive) * 100) : 100;
        const statsHealthPercent = document.getElementById('stats-health-percent');
        const statsHealthFill = document.getElementById('stats-health-fill');
        if (statsHealthPercent) statsHealthPercent.textContent = `${healthPercent}%`;
        if (statsHealthFill) {
            statsHealthFill.style.width = `${healthPercent}%`;
            if (healthPercent >= 80) {
                statsHealthFill.style.background = 'linear-gradient(90deg, #10b981, #34d399)';
            } else if (healthPercent >= 50) {
                statsHealthFill.style.background = 'linear-gradient(90deg, #f59e0b, #fbbf24)';
            } else {
                statsHealthFill.style.background = 'linear-gradient(90deg, #ef4444, #f87171)';
            }
        }
    }

    if (hideOfflineToggle) {
        hideOfflineToggle.addEventListener('change', applyIpFilters);
    }

    if (showDesyncOnlyToggle) {
        showDesyncOnlyToggle.addEventListener('change', applyIpFilters);
    }

    // Função de Debounce para otimizar a pesquisa
    function debounce(func, wait) {
        let timeout;
        return function(...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    // Listener para o campo de pesquisa de IPs
    ipSearchInput.addEventListener('input', debounce(applyIpFilters, 300)); // Aguarda 300ms após a última tecla antes de filtrar

    // Centraliza a validação do formulário para todos os inputs e checkboxes
    actionForm.addEventListener('input', checkFormValidity); // Para campos de texto, como senha e mensagem

    // Usa delegação de eventos para os checkboxes de IP, que são adicionados dinamicamente.
    // O listener é adicionado ao container que sempre existe.
    ipListContainer.addEventListener('change', (event) => {
        if (event.target.matches('input[name="ip"]')) {
            checkFormValidity();
        }
    });

    // Adiciona o listener para o select de ações e outros checkboxes (como 'Selecionar Todos')
    // O listener de 'change' no formulário cobre o select de ações e os checkboxes.
    actionForm.addEventListener('change', checkFormValidity);

    // Listener para o botão de exportar IPs
    if (exportIpsBtn) {
        exportIpsBtn.addEventListener('click', () => {
            // Coleta apenas os IPs que estão atualmente visíveis na lista
            // (respeitando o filtro de pesquisa).
            const visibleIps = Array.from(document.querySelectorAll('.ip-item'))
                .filter(item => item.style.display !== 'none')
                .map(item => item.dataset.ip);

            if (visibleIps.length === 0) {
                logStatusMessage('Nenhum IP para exportar.', 'details');
                return;
            }

            // Junta os IPs, cada um em uma nova linha.
            const fileContent = visibleIps.join('\n');
            // Cria um objeto Blob, que representa o arquivo em memória.
            const blob = new Blob([fileContent], { type: 'text/plain;charset=utf-8' });

            // Cria um link temporário para iniciar o download.
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            
            // Formata a data e hora para incluir no nome do arquivo.
            const timestamp = new Date().toISOString().slice(0, 19).replace(/[-T:]/g, '');
            link.download = `ips_online_${timestamp}.txt`;

            // Adiciona o link ao corpo, clica nele e depois o remove.
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        });
    }

    // --- Lógica de Importação de MACs ---
    if (importMacsBtn && importMacsInput) {
        importMacsBtn.addEventListener('click', () => {
            importMacsInput.click();
        });

        importMacsInput.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;

            const reader = new FileReader();
            reader.onload = async (event) => {
                const text = event.target.result;
                const lines = text.split('\n');
                const entries = [];

                // Regex flexível para encontrar IP e MAC na mesma linha
                // Aceita formatos como:
                // 192.168.0.10 00:11:22:33:44:55
                // 192.168.0.10,00-11-22-33-44-55
                const lineRegex = /((?:\d{1,3}\.){3}\d{1,3})[\s,;]+([0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2})/i;

                lines.forEach(line => {
                    const match = line.match(lineRegex);
                    if (match) {
                        entries.push({ ip: match[1], mac: match[2] });
                    }
                });

                if (entries.length === 0) {
                    logStatusMessage("Nenhum par IP/MAC válido encontrado no arquivo.", "error");
                    return;
                }

                logStatusMessage(`Lendo arquivo... Encontrados ${entries.length} pares. Enviando...`, "details");

                try {
                    const response = await fetch(`${API_BASE_URL}/import-macs`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ entries }),
                    });
                    const data = await response.json();
                    logStatusMessage(data.message, data.success ? "success" : "error");
                } catch (error) {
                    logStatusMessage(`Erro de conexão ao importar: ${error.message}`, "error");
                } finally {
                    importMacsInput.value = ''; // Permite selecionar o mesmo arquivo novamente se necessário
                }
            };
            reader.readAsText(file);
        });
    }


    // --- Lógica de Filtragem de Log ---
    const activeLogFilters = new Set();

    function applyLogFilters() {
        systemLogBox.querySelectorAll('.log-entry').forEach(entry => {
            const entryType = entry.dataset.logType;
            // Esconde a entrada se o seu tipo estiver no conjunto de filtros ativos.
            entry.style.display = activeLogFilters.has(entryType) ? 'none' : '';
        });
    }

    if (logFiltersContainer) {
        logFiltersContainer.addEventListener('click', (e) => {
            const filterBtn = e.target.closest('.log-filter-btn');
            if (!filterBtn) return;

            const filterType = filterBtn.dataset.filter;
            filterBtn.classList.toggle('active');

            if (activeLogFilters.has(filterType)) {
                activeLogFilters.delete(filterType); // Desativa o filtro
            } else {
                activeLogFilters.add(filterType); // Ativa o filtro
            }
            applyLogFilters();
        });
    }

    // Listener para o botão de copiar log (para a IDE Antigravity)
    const copyLogBtn = document.getElementById('copy-log-btn');
    if (copyLogBtn) {
        copyLogBtn.addEventListener('click', () => {
            const logEntries = systemLogBox.querySelectorAll('.log-entry, .log-group');
            if (logEntries.length === 0) {
                showToast('Nenhum log disponível para copiar.', 'details');
                return;
            }

            const formattedLogs = [];
            formattedLogs.push('=== LOG DO SISTEMA (Copiado para IDE Antigravity) ===');

            logEntries.forEach(entry => {
                if (entry.style.display !== 'none') {
                    let text = entry.innerText || entry.textContent || '';
                    text = text.trim().replace(/\s+/g, ' ');
                    if (text) {
                        formattedLogs.push(text);
                    }
                }
            });

            if (formattedLogs.length <= 1) {
                showToast('Nenhum log visível com os filtros atuais.', 'details');
                return;
            }

            const logContent = formattedLogs.join('\n');

            const copyToClipboard = (str) => {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    return navigator.clipboard.writeText(str);
                } else {
                    return new Promise((resolve, reject) => {
                        try {
                            const textarea = document.createElement('textarea');
                            textarea.value = str;
                            textarea.style.position = 'fixed';
                            textarea.style.opacity = '0';
                            document.body.appendChild(textarea);
                            textarea.select();
                            document.execCommand('copy');
                            document.body.removeChild(textarea);
                            resolve();
                        } catch (err) {
                            reject(err);
                        }
                    });
                }
            };

            copyToClipboard(logContent)
                .then(() => {
                    const originalHtml = copyLogBtn.innerHTML;
                    copyLogBtn.innerHTML = '<i data-feather="check"></i> Copiado!';
                    if (typeof feather !== 'undefined') feather.replace();
                    showToast('Logs copiados com sucesso! Pronto para colar na IDE Antigravity.', 'success');
                    setTimeout(() => {
                        copyLogBtn.innerHTML = originalHtml;
                        if (typeof feather !== 'undefined') feather.replace();
                    }, 2000);
                })
                .catch(err => {
                    showToast(`Erro ao copiar logs: ${err.message}`, 'error');
                });
        });
    }

    // Listener para o botão de limpar log
    const clearLogBtn = document.getElementById('clear-log-btn');
    if (clearLogBtn) {
        clearLogBtn.addEventListener('click', () => {
            systemLogBox.innerHTML = '';
        });
    }

    /**
     * Exibe uma notificação flutuante (Toast).
     * @param {string} message - Mensagem.
     * @param {string} type - 'success', 'error', ou 'details' (info).
     */
    /**
     * Exibe uma notificação flutuante Glassmorphic (Toast).
     * @param {string} message - Mensagem.
     * @param {string} type - 'success', 'error', 'warning', ou 'details' (info).
     */
    function showToast(message, type = 'details') {
        const toastType = (type === 'details' || type === 'info') ? 'info' : type;
        if (typeof window.showAppToast === 'function') {
            window.showAppToast(message, toastType, 4000);
            return;
        }

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        
        let icon = '';
        if (type === 'success') icon = '<i data-feather="check-circle"></i> ';
        else if (type === 'error') icon = '<i data-feather="alert-circle"></i> ';
        else icon = '<i data-feather="info"></i> ';

        toast.innerHTML = `${icon}<span>${message}</span>`;
        if (toastContainer) toastContainer.appendChild(toast);
        if (typeof feather !== 'undefined') feather.replace();

        setTimeout(() => {
            toast.classList.add('fade-out');
            toast.addEventListener('animationend', () => {
                toast.remove();
            });
        }, 4000);
    }

    /**
     * Exibe um modal com uma lista de texto (usado para sites bloqueados).
     */
    function showTextListModal(title, content) {
        let modal = document.getElementById('text-list-modal');
        
        // Cria o modal dinamicamente se não existir no HTML
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'text-list-modal';
            modal.className = 'modal-overlay hidden';
            modal.innerHTML = `
                <div class="modal-content">
                    <h2 class="modal-title"></h2>
                    <div class="text-list-container"></div>
                    <div class="modal-actions" style="margin-top: 1.5rem;">
                        <button class="modal-btn-cancel" onclick="this.closest('.modal-overlay').classList.add('hidden')">Fechar</button>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);

            // Fecha ao clicar fora do conteúdo (no overlay)
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    modal.classList.add('hidden');
                }
            });
        }

        const titleEl = modal.querySelector('.modal-title');
        const containerEl = modal.querySelector('.text-list-container');

        titleEl.textContent = title;
        
        // Limpa cabeçalhos repetitivos vindos do backend para o modal ficar limpo
        const cleanContent = content.replace(/--- SITES BLOQUEADOS .* ---/g, '').trim();
        containerEl.textContent = cleanContent || "Nenhum site bloqueado encontrado.";

        modal.classList.remove('hidden');
        
        // Fecha ao apertar ESC
        const escHandler = (e) => {
            if (e.key === 'Escape') {
                modal.classList.add('hidden');
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);
    }

    /**
     * Função auxiliar para logar mensagens na caixa de status.
     * @param {string} message - A mensagem a ser exibida (pode conter HTML).
     * @param {string} groupId - O ID do grupo de log ao qual a mensagem pertence.
     */

    function logStatusMessage(message, type = 'info') {
        logBuffer.push({ message, type, timestamp: new Date().toLocaleTimeString() });

        if (!isLogUpdatePending) {
            isLogUpdatePending = true;
            requestAnimationFrame(processLogBuffer);
        }

        if (type === 'success' || type === 'error') {
            showToast(message.replace(/<[^>]*>?/gm, ''), type);
        }
    }

    function processLogBuffer() {
        if (!systemLogBox || logBuffer.length === 0) {
            isLogUpdatePending = false;
            return;
        }

        const fragment = document.createDocumentFragment();
        const icons = { success: '✅', error: '❌', details: 'ℹ️', info: '➡️' };

        logBuffer.forEach(({ message, type, timestamp }) => {
            const logEntry = document.createElement('div');
            logEntry.className = `log-entry ${type}-text`;
            logEntry.dataset.logType = type;
            logEntry.style.display = activeLogFilters.has(type) ? 'none' : '';

            const icon = icons[type] || '➡️';
            logEntry.innerHTML = `<span>[${timestamp}] ${icon} </span><span>${message}</span>`;
            fragment.appendChild(logEntry);
        });

        logBuffer = [];
        const isNearBottom = systemLogBox.scrollHeight - systemLogBox.scrollTop - systemLogBox.clientHeight < 100;
        
        systemLogBox.appendChild(fragment);

        // Manutenção do limite de logs
        const MAX_LOG_ENTRIES = 100;
        while (systemLogBox.children.length > MAX_LOG_ENTRIES) {
            systemLogBox.removeChild(systemLogBox.firstChild);
        }

        if (isNearBottom) {
            systemLogBox.scrollTop = systemLogBox.scrollHeight;
        }

        isLogUpdatePending = false;
    }


    /**
     * Lida com o clique no botão de informação de um IP específico.
     * @param {Event} event - O evento de clique.
     */
    async function handleInfoButtonClick(event) {
        const target = event.target;
        if (!target.matches('.info-btn')) return;

        // Lê o IP diretamente do atributo 'data-ip' do botão clicado.
        // A abordagem anterior (target.closest('.ip-item').dataset.ip) também funcionaria,
        // mas esta é mais direta, pois o botão agora tem a informação.
        const ip = target.dataset.ip;
        if (!ip) return; // Segurança extra

        const password = getActivePassword();
        if (!password) {
            logStatusMessage('Por favor, digite a senha para obter as informações.', 'error');
            passwordInput.focus();
            return;
        }

        const iconElement = getStatusIconElement(ip);
        if (iconElement) {
            iconElement.innerHTML = '🔄'; // Feedback visual imediato
            iconElement.className = 'status-icon processing';
        }
        target.disabled = true;

        const payload = {
            password: password, // A senha é adicionada aqui
            action: 'get_system_info', // Ação específica para esta função
        };

        try {
            const result = await executeRemoteAction(ip, payload);
            // A função updateIpStatus já lida com a exibição dos dados e do ícone de status
            updateIpStatus(ip, result);
        } catch (error) {
            // Em caso de erro na execução, reverte o ícone para um estado de erro
            updateIpStatus(ip, { success: false, message: "Falha ao obter informações.", details: error.message });
        } finally {
            // Reabilita o botão após a conclusão
            target.disabled = false;
        }
    }

    /**
     * Atualiza a barra de progresso.
     * @param {number} processed - Número de IPs processados.
     * @param {number} total - Número total de IPs.
     * @param {string} [actionText=''] - O texto da ação atual (opcional).
     */
    function updateProgressBar(processed, total, actionText = '') {
        const progress = total > 0 ? Math.round((processed / total) * 100) : 0;
        const actionPrefix = actionText ? `[${actionText}] ` : '';
        progressBar.style.width = `${progress}%`;
        progressText.textContent = `${actionPrefix}Processando ${processed} de ${total} (${progress}%)`;
        // Atualiza o atributo ARIA para leitores de tela
        if (progressContainer) progressContainer.setAttribute('aria-valuenow', progress);
    }

    /**
     * Prepara a UI para o início do processamento das ações.
     */
    function prepareUIForProcessing() {
        submitBtn.disabled = true;
        submitBtn.classList.add('processing');
        fixKeysBtn.classList.add('hidden');
        submitBtn.querySelector('.btn-text').textContent = 'Processando...';
        // Não limpa o log, apenas adiciona novas entradas
        document.querySelectorAll('.status-icon').forEach(icon => (icon.className = 'status-icon'));
    }

    /**
     * Exibe um modal de confirmação e retorna uma promessa.
     * @param {string} message - A mensagem a ser exibida no modal.
     * @returns {Promise<boolean>} - Resolve com `true` se confirmado, `false` se cancelado.
     */
    function showConfirmationModal(message) {
        // Usa \n como delimitador e cria parágrafos para melhor formatação no modal.
        const formattedMessage = message.split('\n').map(line => `<p>${line}</p>`).join('');

        const previouslyFocusedElement = document.activeElement;

        return new Promise((resolve) => {
            modalDescription.innerHTML = formattedMessage;
            confirmationModal.classList.remove('hidden');
            confirmationModal.setAttribute('aria-hidden', 'false');

            const focusableElements = confirmationModal.querySelectorAll('button');
            const firstElement = focusableElements[0];
            const lastElement = focusableElements[focusableElements.length - 1];

            const cleanupAndResolve = (value) => {
                confirmationModal.classList.add('hidden');
                confirmationModal.setAttribute('aria-hidden', 'true');
                document.removeEventListener('keydown', keydownHandler);
                confirmationModal.removeEventListener('click', overlayClickHandler);
                previouslyFocusedElement?.focus(); // Retorna o foco ao elemento original
                resolve(value);
            };
            
            const confirmHandler = () => {
                cleanupAndResolve(true);
            };

            const cancelHandler = () => {
                cleanupAndResolve(false);
            };

            const overlayClickHandler = (e) => {
                if (e.target === confirmationModal) cancelHandler();
            };

            const keydownHandler = (e) => {
                if (e.key === 'Escape') {
                    cancelHandler();
                }
                if (e.key === 'Tab' && firstElement) { // Garante que há elementos focáveis
                    if (e.shiftKey && document.activeElement === firstElement) {
                        e.preventDefault();
                        lastElement.focus();
                    } else if (!e.shiftKey && document.activeElement === lastElement) {
                        e.preventDefault();
                        firstElement.focus();
                    }
                }
            };

            document.addEventListener('keydown', keydownHandler);
            confirmationModal.addEventListener('click', overlayClickHandler);

            modalConfirmBtn.addEventListener('click', confirmHandler, { once: true });
            modalCancelBtn.addEventListener('click', cancelHandler, { once: true });

            firstElement?.focus(); // Foco inicial no modal
        });
    }

    /**
     * Exibe um modal para o usuário selecionar quais backups de atalhos restaurar.
     * @param {string} ip - O IP do dispositivo para verificar os backups.
     * @param {string} password - A senha SSH.
     * @returns {Promise<string[]|null>} - Resolve com um array de diretórios selecionados, ou `null` se cancelado.
     */
    function showBackupSelectionModal(ip, password) {
        const previouslyFocusedElement = document.activeElement;

        return new Promise(async (resolve) => {
            // Mostra um estado de carregamento no modal
            backupListContainer.innerHTML = '<p>Buscando backups...</p>';
            backupConfirmBtn.disabled = true;
            backupModal.classList.remove('hidden');
            backupModal.setAttribute('aria-hidden', 'false');

            const cleanupAndResolve = (value) => {
                backupModal.classList.add('hidden');
                backupModal.setAttribute('aria-hidden', 'true');
                document.removeEventListener('keydown', keydownHandler);
                backupModal.removeEventListener('click', overlayClickHandler);
                previouslyFocusedElement?.focus();
                resolve(value);
            };

            const confirmHandler = () => {
                // Seleciona diretamente os checkboxes de arquivos individuais que estão marcados,
                // ignorando o checkbox "Restaurar Todos". A lógica de sincronização garante que,
                // se "Restaurar Todos" estiver marcado, todos os individuais também estarão.
                const selectedFiles = Array.from(backupListContainer.querySelectorAll('input[name="backup-file"]:not(#backup-__ALL__):checked'))
                    .map(cb => cb.value);
                cleanupAndResolve(selectedFiles);
            };

            const cancelHandler = () => {
                cleanupAndResolve(null); // Resolve com null no cancelamento
            };

            const overlayClickHandler = (e) => {
                if (e.target === backupModal) cancelHandler();
            };

            const keydownHandler = (e) => {
                if (e.key === 'Escape') {
                    cancelHandler();
                }
                if (e.key === 'Tab') {
                    const focusableElements = Array.from(backupModal.querySelectorAll('button, input[type="checkbox"]')).filter(el => !el.disabled);
                    if (focusableElements.length === 0) return;
                    const firstElement = focusableElements[0];
                    const lastElement = focusableElements[focusableElements.length - 1];

                    if (e.shiftKey && document.activeElement === firstElement) {
                        e.preventDefault();
                        lastElement.focus();
                    } else if (!e.shiftKey && document.activeElement === lastElement) {
                        e.preventDefault();
                        firstElement.focus();
                    }
                }
            };

            // Adiciona os listeners uma única vez
            backupConfirmBtn.addEventListener('click', confirmHandler, { once: true }); // O {once: true} já remove o listener
            backupCancelBtn.addEventListener('click', cancelHandler, { once: true });
            document.addEventListener('keydown', keydownHandler);
            backupModal.addEventListener('click', overlayClickHandler);

            try {
                const response = await fetch(`${API_BASE_URL}/list-backups`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ip, password }),
                });
                const data = await response.json();

                if (!data.success || Object.keys(data.backups).length === 0) {
                    backupListContainer.innerHTML = `<p class="error-text">${data.message || 'Nenhum backup encontrado.'}</p>`;
                } else {
                    // Popula o modal com os checkboxes dos backups encontrados
                    backupListContainer.innerHTML = `
                        <div class="checkbox-item">
                            <input type="checkbox" id="backup-__ALL__" name="backup-file" value="__ALL__">
                            <label for="backup-__ALL__"><strong>Restaurar Todos</strong></label>
                        </div>
                        <hr style="border-color: var(--border-color-light); margin: 0.5rem 0;">
                    `;
                    const fragment = document.createDocumentFragment();
                    let backupCounter = 0;
                    // Itera sobre os diretórios e seus arquivos
                    for (const directory in data.backups) {
                        const fieldset = document.createElement('fieldset');
                        const legend = document.createElement('legend');
                        legend.textContent = directory;
                        fieldset.appendChild(legend);

                        data.backups[directory].forEach(filename => {
                            const fullPath = `${directory}/${filename}`;
                            // Cria um ID seguro e único para o elemento usando um contador para evitar colisões.
                            const safeId = `backup-item-${backupCounter++}`;

                            // Constrói os elementos do DOM programaticamente para maior segurança e robustez,
                            // evitando problemas com caracteres especiais em nomes de arquivos ao usar innerHTML.
                            const div = document.createElement('div');
                            div.className = 'checkbox-item';

                            const input = document.createElement('input');
                            input.type = 'checkbox';
                            input.id = safeId;
                            input.name = 'backup-file';
                            // O valor enviado para o backend deve ser o caminho original. O backend é responsável pela normalização.
                            input.value = fullPath;

                            const label = document.createElement('label');
                            label.htmlFor = safeId;
                            // Exibe o nome de arquivo original para o usuário.
                            label.textContent = filename;

                            div.appendChild(input);
                            div.appendChild(label);
                            fieldset.appendChild(div);
                        });
                        fragment.appendChild(fieldset);
                    }
                    backupListContainer.appendChild(fragment);

                    // Adiciona lógica para o checkbox "Restaurar Todos"
                    const allCheckbox = document.getElementById('backup-__ALL__');
                    const otherCheckboxes = Array.from(backupListContainer.querySelectorAll('input[name="backup-file"]:not(#backup-__ALL__)'));

                    // Ação ao clicar no checkbox "Restaurar Todos"
                    allCheckbox.addEventListener('change', () => {
                        otherCheckboxes.forEach(cb => {
                            cb.checked = allCheckbox.checked;
                        });
                    });

                    // Ação ao clicar em qualquer outro checkbox individual
                    otherCheckboxes.forEach(cb => {
                        cb.addEventListener('change', () => {
                            // Se todos os individuais estiverem marcados, marca o "Restaurar Todos". Caso contrário, desmarca.
                            const allAreChecked = otherCheckboxes.every(item => item.checked);
                            allCheckbox.checked = allAreChecked;
                        });
                    });

                    backupConfirmBtn.disabled = false;
                    backupConfirmBtn.focus(); // Foca no botão de confirmar após o conteúdo carregar
                }
            } catch (error) {
                backupListContainer.innerHTML = `<p class="error-text">Erro ao conectar para listar backups.</p>`;
                cleanupAndResolve(null); // Garante que a promise seja resolvida em caso de erro
            }
        });
    }

    /**
     * Exibe um modal para o usuário selecionar qual backup da aplicação restaurar.
     * @returns {Promise<string|null>} - Resolve com o nome do arquivo de backup selecionado, ou `null` se cancelado.
     */
    function showAppBackupSelectionModal() {
        const previouslyFocusedElement = document.activeElement;

        return new Promise(async (resolve) => {
            // Mostra um estado de carregamento no modal
            appBackupListContainer.innerHTML = '<p>Buscando backups da aplicação...</p>';
            appBackupConfirmBtn.disabled = true;
            appBackupModal.classList.remove('hidden');
            appBackupModal.setAttribute('aria-hidden', 'false');

            const cleanupAndResolve = (value) => {
                appBackupModal.classList.add('hidden');
                appBackupModal.setAttribute('aria-hidden', 'true');
                document.removeEventListener('keydown', keydownHandler);
                appBackupModal.removeEventListener('click', overlayClickHandler);
                previouslyFocusedElement?.focus();
                resolve(value);
            };

            const confirmHandler = () => {
                const selectedRadio = appBackupListContainer.querySelector('input[name="app-backup-file"]:checked');
                cleanupAndResolve(selectedRadio ? selectedRadio.value : null);
            };

            const cancelHandler = () => {
                cleanupAndResolve(null);
            };

            const overlayClickHandler = (e) => {
                if (e.target === appBackupModal) cancelHandler();
            };

            const keydownHandler = (e) => {
                if (e.key === 'Escape') {
                    cancelHandler();
                }
            };

            appBackupConfirmBtn.addEventListener('click', confirmHandler, { once: true });
            appBackupCancelBtn.addEventListener('click', cancelHandler, { once: true });
            document.addEventListener('keydown', keydownHandler);
            appBackupModal.addEventListener('click', overlayClickHandler);

            // Delegação de eventos para os botões de exclusão
            appBackupListContainer.addEventListener('click', async (e) => {
                const deleteBtn = e.target.closest('.delete-backup-btn');
                if (!deleteBtn) return;

                e.stopPropagation(); // Impede que o clique no botão selecione o item

                const backupItemDiv = deleteBtn.closest('.backup-item');
                const filename = backupItemDiv.dataset.filename;

                const confirmed = await showConfirmationModal(`Tem certeza que deseja excluir o backup:\n\n${filename}\n\nEsta ação não pode ser desfeita.`);
                if (!confirmed) return;

                try {
                    const response = await fetch(`${API_BASE_URL}/delete-application-backup`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ backup_file: filename }),
                    });
                    const result = await response.json();

                    if (result.success) {
                        logStatusMessage(`Backup "${filename}" excluído com sucesso.`, 'success');
                        backupItemDiv.remove(); // Remove o item da lista na UI
                    } else {
                        logStatusMessage(`Falha ao excluir backup: ${result.message}`, 'error');
                    }
                } catch (error) {
                    logStatusMessage(`Erro de conexão ao tentar excluir backup: ${error.message}`, 'error');
                }
            });

            try {
                // Assumindo que a nova rota no backend será /list-application-backups
                const response = await fetch(`${API_BASE_URL}/list-application-backups`, {
                    method: 'GET', // GET é mais apropriado para listar recursos
                });
                const data = await response.json();

                if (!data.success || data.backups.length === 0) {
                    appBackupListContainer.innerHTML = `<p class="error-text">${data.message || 'Nenhum backup da aplicação encontrado.'}</p>`;
                } else {
                    
                    const fragment = document.createDocumentFragment();
                    // O backend deve retornar a lista já ordenada do mais recente para o mais antigo
                    data.backups.forEach((filename, index) => {
                        // Extrai a data do nome do arquivo para uma exibição mais amigável
                        // Extrai a data do nome do arquivo para uma exibição mais amigável.
                        let displayDate = filename; // Valor padrão caso o regex não encontre.
                        const match = filename.match(/backup_app_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.zip/);
                        let labelText = filename;
                        if (match) {
                            const [, year, month, day, hour, minute, second] = match;
                            labelText = `Data: ${day}/${month}/${year} às ${hour}:${minute}:${second}`;
                            displayDate = `Data: ${day}/${month}/${year} às ${hour}:${minute}:${second}`;
                        }

                        const itemDiv = document.createElement('div');
                        itemDiv.className = 'backup-item';
                        itemDiv.dataset.filename = filename;

                        const input = document.createElement('input');
                        input.type = 'radio'; // Radio buttons para seleção única
                        input.id = `app-backup-${index}`;
                        input.name = 'app-backup-file';
                        input.value = filename;
                        if (index === 0) {
                            input.checked = true; // Pré-seleciona o primeiro (mais recente)
                            itemDiv.classList.add('selected');
                        }

                        const detailsDiv = document.createElement('div');
                        detailsDiv.className = 'backup-details';
                        detailsDiv.innerHTML = `${displayDate} <small style="display: block; color: var(--subtle-text-color);">${filename}</small>`;

                        const deleteBtn = document.createElement('button');
                        deleteBtn.type = 'button';
                        deleteBtn.className = 'delete-backup-btn';
                        deleteBtn.innerHTML = '🗑️';
                        deleteBtn.title = `Excluir este backup`;

                        itemDiv.append(input, detailsDiv, deleteBtn);
                        fragment.appendChild(itemDiv);
                    });
                    appBackupListContainer.innerHTML = ''; // Limpa o "carregando"
                    appBackupListContainer.appendChild(fragment);

                    // Adiciona lógica para destacar o item selecionado
                    appBackupListContainer.addEventListener('click', (e) => {
                        const targetItem = e.target.closest('.backup-item');
                        if (!targetItem) return;
                        appBackupListContainer.querySelectorAll('.backup-item').forEach(item => item.classList.remove('selected'));
                        targetItem.classList.add('selected');
                        targetItem.querySelector('input[type="radio"]').checked = true;
                    });

                    appBackupConfirmBtn.disabled = false;
                    appBackupConfirmBtn.focus();
                }
            } catch (error) {
                appBackupListContainer.innerHTML = `<p class="error-text">Erro ao conectar para listar backups da aplicação.</p>`;
            }
        });
    }

    /**
     * Executa uma única ação em um único IP, encapsulando a lógica de fetch e timeout.
     * @param {string} ip - O IP alvo.
     * @param {object} payload - O corpo da requisição para a API.
     * @param {boolean} [isLongRunning=false] - Indica se a ação pode demorar, ajustando o timeout.
     * @returns {Promise<object>} - Um objeto com o resultado da operação.
     */
    async function executeRemoteAction(ip, payload, isLongRunning = false) {
        const controller = new AbortController();
        // Ações de streaming podem demorar muito (ex: Atualizar Sistema), então o timeout é de 30 minutos (1.800.000ms).
        const isStreaming = STREAMING_ACTIONS.includes(payload.action);
        const timeoutDuration = isStreaming ? 1800000 : 30000; // 30 minutos para streaming, 30s para o resto.
        const timeoutId = setTimeout(() => controller.abort(), timeoutDuration);

        // Para ações de streaming, gera um ID único para o log. O backend usará isso
        // para criar um logger específico para esta requisição, resolvendo o erro
        // "ssh_connect() missing 1 required positional argument: 'logger'".
        const requestBody = isStreaming
            ? { ...payload, ip, log_id: `log-group-${ip.replace(/[^a-zA-Z0-9_-]/g, '-')}-${Date.now()}` }
            : { ...payload, ip };

        try {
            const response = await fetch(`${API_BASE_URL}/${isStreaming ? 'stream-action' : 'gerenciar_atalhos_ip'}`, {
                method: 'POST',
                // Garante que os cabeçalhos sejam sempre um objeto literal, pois a API fetch
                // não aceita um objeto Headers quando a opção 'keepalive' é usada.
                // Isso corrige o erro "TypeError: The provided value is not of type..."
                headers: { 'Content-Type': 'application/json' }, 
                body: JSON.stringify(requestBody),
                // keepalive removido para evitar limites de buffer em payloads grandes
                signal: controller.signal,
            });

            clearTimeout(timeoutId); // Limpa o timeout assim que a resposta chega

            if (isStreaming) {
                return processStreamResponse(ip, payload, response, requestBody.log_id);
            }

            if (!response.ok) {
                let errorMessage = `Erro do servidor (HTTP ${response.status})`;
                let errorDetails = response.statusText;
                try {
                    // Tenta extrair uma mensagem de erro mais detalhada do corpo da resposta.
                    const errorData = await response.json();
                    errorMessage = errorData.message || errorMessage;
                    errorDetails = errorData.details || errorDetails;
                } catch (e) {
                    // O corpo não era JSON ou estava vazio. Mantém a mensagem de erro HTTP padrão.
                }
                return { success: false, message: errorMessage, details: errorDetails };
            }

            return await response.json();
        } catch (error) {
            clearTimeout(timeoutId); // Garante que o timeout seja limpo em caso de erro

            // Retorna um objeto de erro padronizado para erros de rede/timeout
            const isTimeout = error.name === 'AbortError';
            const message = isTimeout ? `Ação expirou (timeout de ${timeoutDuration / 1000}s).` : 'Erro de comunicação com o servidor.';
            const details = isTimeout
                ? `A ação excedeu o limite de tempo. O dispositivo pode estar lento ou offline.`
                : `Não foi possível conectar ao backend. Verifique se ele está em execução e se não há um firewall bloqueando a conexão.`;
            return {
                success: false, message, details
            };
        } finally {
            // O clearTimeout foi movido para dentro do try/catch para ser mais preciso.
        }
    }

    /**
     * Processa a resposta de uma ação de streaming, atualizando a UI em tempo real.
     * @param {string} ip - O IP alvo.
     * @param {object} payload - O payload original enviado na requisição.
     * @param {Response} response - O objeto de resposta do fetch.
     * @returns {Promise<object>} - Um objeto com o resultado final da operação.
     */
    async function processStreamResponse(ip, payload, response, logGroupId) {
        
        // Cria a entrada de log agrupada ANTES de começar a receber o stream
        const logGroupClone = logGroupTemplate.content.cloneNode(true);
        const logGroupElement = logGroupClone.querySelector('.log-group');
        logGroupElement.id = logGroupId;
        logGroupElement.dataset.logType = 'details'; // Começa como 'details'
        logGroupElement.open = true; // Começa aberto para o usuário ver o progresso

        const actionText = Array.from(actionSelect.options).find(opt => opt.value === payload.action)?.text || payload.action;
        logGroupElement.querySelector('.log-group-icon').textContent = '⏳';
        logGroupElement.querySelector('.log-group-title').textContent = `${ip}: ${actionText}`;
        logGroupElement.querySelector('.log-group-timestamp').textContent = new Date().toLocaleTimeString();
        const logContentElement = logGroupElement.querySelector('.log-group-content');
        const copyBtn = logGroupElement.querySelector('.copy-log-btn');

        copyBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            navigator.clipboard.writeText(logContentElement.textContent)
                .then(() => {                    
                    copyBtn.innerHTML = '<i data-feather="check"></i>';
                    setTimeout(() => { copyBtn.innerHTML = '<i data-feather="copy"></i>'; feather.replace(); }, 2000);
                });
        });

        systemLogBox.appendChild(logGroupElement);
        
        // Smart Scroll também para grupos de log
        systemLogBox.scrollTop = systemLogBox.scrollHeight;

        if (!response.ok || !response.body) {
            const errorText = await response.text();
            return { success: false, message: `Erro do servidor (HTTP ${response.status})`, details: errorText };
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let finalResult = { success: false, message: "Ação de streaming finalizada sem uma conclusão clara." };
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // Guarda a última linha parcial no buffer

            for (const line of lines) {
                if (line.startsWith('__STREAM_END__:')) {
                    const exitCode = parseInt(line.split(':')[1], 10);
                    finalResult.success = exitCode === 0;
                    finalResult.message = exitCode === 0 ? "Ação concluída com sucesso." : `Ação falhou com código de saída ${exitCode}.`;
                } else if (line.startsWith('__STREAM_ERROR__:')) {
                    finalResult.success = false;
                    finalResult.message = "Erro durante o streaming.";
                    finalResult.details = line.substring('__STREAM_ERROR__:'.length);
                    logGroupElement.dataset.logType = 'error';
                    logGroupElement.querySelector('.log-group-icon').textContent = '❌';
                } else if (line.trim()) { // Garante que a linha não esteja vazia
                    // Loga a linha de progresso na caixa de status
                    if (logContentElement) {
                        logContentElement.appendChild(document.createTextNode(line + '\n'));
                    }
                }
            }
        }
        // Atualiza o ícone final com base no resultado
        logGroupElement.querySelector('.log-group-icon').textContent = finalResult.success ? '✅' : '❌';
        logGroupElement.dataset.logType = finalResult.success ? 'success' : 'error';
        return finalResult;
    }

    /**
     * Atualiza o ícone de status e a mensagem de log para um IP específico.
     * @param {string} ip - O IP alvo.
     * @param {object} result - O objeto de resultado da função executeRemoteAction.
     */
    function updateIpStatus(ip, result, actionText = 'Ação', payload = {}) {
        const ipItem = ipListContainer.querySelector(`.ip-item[data-ip="${ip}"]`);
        if (ipItem) {
            ipItem.classList.remove('processing');

            // Se a ação de sincronização de horário foi bem-sucedida, removemos o alerta visual do card
            if (payload.action === ACTIONS.SYNC_TIME && result.success) {
                const warnIcon = ipItem.querySelector('.time-warning-icon');
                if (warnIcon) warnIcon.remove();
                ipItem.classList.remove('status-sync-error');
            }
        }
        const iconElement = getStatusIconElement(ip);
        const logGroupId = `log-group-${ip.replace(/[^a-zA-Z0-9_-]/g, '-')}-${Date.now()}`;

        // Intercepta o comando de listagem para exibir no modal
        if (payload.action === 'listar_sites_bloqueados' && result.success) {
            showTextListModal(`Sites Bloqueados - ${ip}`, result.message);
        }

        // Se a ação for de Informações do Sistema, formatamos de forma especial
        if (payload.action === 'get_system_info' && result.success && result.data) {
            const data = result.data;
            const cpuVal = parseFloat(data.cpu) || 0;
            const memVal = data.memory ? (parseFloat(data.memory.split('/')[0]) / parseFloat(data.memory.split('/')[1]) * 100) : 0;
            
            const getBarColor = (val) => val > 80 ? 'fill-high' : (val > 50 ? 'fill-mid' : 'fill-low');
            
            const isDesync = Math.abs(data.offset || 0) > 15;
            const timeClass = isDesync ? 'error-text' : 'success-text';
            
            // Adiciona alerta visual no card da máquina
            const ipItem = document.querySelector(`.ip-item[data-ip="${ip}"]`);
            if (ipItem && isDesync) {
                // Aplica a cor amarela ao card
                ipItem.classList.add('status-sync-error');

                let warnIcon = ipItem.querySelector('.time-warning-icon');
                if (!warnIcon) {
                    warnIcon = document.createElement('span');
                    warnIcon.className = 'time-warning-icon';
                    warnIcon.innerHTML = ' <i data-feather="clock"></i>';
                    ipItem.querySelector('label').appendChild(warnIcon);
                    if (window.feather) feather.replace({ 'container': ipItem });
                }
                warnIcon.setAttribute('data-tooltip', `Hora incorreta! Diferença: ${data.offset_readable}`);
            } else if (ipItem) {
                ipItem.classList.remove('status-sync-error');
            }

            const infoHtml = `
                <div class="log-details-grid">
                    <div class="log-details-item">
                        <span class="${timeClass}">🕒 Hora: ${data.remote_time}</span>
                        <small>Offset: ${data.offset_readable}</small>
                    </div>
                    <div class="log-details-item">
                        <span>💻 CPU: ${data.cpu}</span>
                        <div class="resource-mini-bar"><div class="resource-mini-fill ${getBarColor(cpuVal)}" style="width: ${cpuVal}%"></div></div>
                    </div>
                    <div class="log-details-item">
                        <span>🧠 RAM: ${data.memory}</span>
                        <div class="resource-mini-bar"><div class="resource-mini-fill ${getBarColor(memVal)}" style="width: ${memVal}%"></div></div>
                    </div>
                    <div class="log-details-item">
                        <span>💾 Disco: ${data.disk}</span>
                    </div>
                </div>
            `;
            logStatusMessage(`[${ip}] Informações coletadas:${infoHtml}`, 'success');
        } else {
            // Log padrão para outras ações
            const logType = result.success ? 'success' : 'error';
            logStatusMessage(`${ip}: ${result.message}`, logType);
        }

        // Atualiza o ícone de status
        if (iconElement) {
            const icon = result.success ? '✅' : '❌';
            const cssClass = result.success ? 'success' : 'error';
            iconElement.textContent = icon;
            iconElement.className = `status-icon ${cssClass}`;
        }
    }

    // --- Lógica para Categorias Pré-definidas de Sites ---
    /**
     * Completa automaticamente domínios simples (ex: "facebook" para "facebook.com")
     * quando o usuário digita um separador ou sai do campo.
     * @param {HTMLTextAreaElement} textarea - O elemento textarea a ser processado.
     */
    function autoCompleteDomains(textarea) {
        const currentVal = textarea.value.trim();
        if (!currentVal) return;

        const domains = currentVal.split(/[,\s\n]+/).filter(s => s.length > 0);
        const completedDomains = domains.map(domain => {
            // Se o domínio já contém um ponto, assume que já tem um TLD ou é um subdomínio.
            if (domain.includes('.')) {
                return domain;
            }
            // Heurística simples: se é uma palavra sem ponto, adiciona .com
            // Pode ser expandido para .net, .org, .br, etc., se necessário.
            if (/^[a-zA-Z0-9-]+$/.test(domain)) {
                return `${domain}.com`;
            }
            return domain; // Retorna como está se não se encaixa no padrão
        });

        const newText = completedDomains.join('\n'); // Junta com novas linhas para melhor legibilidade
        if (newText !== currentVal) {
            textarea.value = newText;
            // Dispara um evento de input para garantir que outros listeners (como validação) sejam acionados
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
        }
    }

    const setupCategoryButtons = (containerId, textareaId) => {
        const container = document.getElementById(containerId);
        const textarea = document.getElementById(textareaId);
        if (!container || !textarea) return;

        container.addEventListener('click', (e) => {
            const btn = e.target.closest('.category-btn');
            if (!btn) return;
            
            const sitesToAdd = btn.dataset.sites;
            const currentVal = textarea.value.trim();
            if (currentVal) {
                const existing = new Set(currentVal.split(/[,\s\n]+/));
                const news = sitesToAdd.split(' ').filter(s => !existing.has(s));
                if (news.length > 0) {
                    textarea.value = currentVal + '\n' + news.join('\n');
                }
            } else {
                textarea.value = sitesToAdd.split(' ').join('\n');
            }
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
        });

        // Adiciona listener para autocompletar ao digitar um separador
        textarea.addEventListener('input', (e) => {
            const lastChar = e.data;
            if (lastChar === ' ' || lastChar === ',' || lastChar === '\n') {
                autoCompleteDomains(textarea);
            }
        });
        // Adiciona listener para autocompletar ao sair do campo
        textarea.addEventListener('blur', () => {
            autoCompleteDomains(textarea);
        });
    };

    const setupBandwidthPresetButtons = () => {
        const bandwidthGroup = document.getElementById('bandwidth-group');
        const downloadInput = document.getElementById('download-limit');
        const uploadInput = document.getElementById('upload-limit');
        if (!bandwidthGroup || !downloadInput || !uploadInput) return;

        bandwidthGroup.addEventListener('click', (e) => {
            const btn = e.target.closest('.bandwidth-preset-btn');
            if (!btn) return;

            const dl = btn.dataset.download;
            const ul = btn.dataset.upload;
            if (dl) downloadInput.value = dl;
            if (ul) uploadInput.value = ul;

            // Animação visual nos campos de input para destacar a alteração
            downloadInput.classList.add('input-highlight-flash');
            uploadInput.classList.add('input-highlight-flash');
            setTimeout(() => {
                downloadInput.classList.remove('input-highlight-flash');
                uploadInput.classList.remove('input-highlight-flash');
            }, 600);

            downloadInput.dispatchEvent(new Event('input', { bubbles: true }));
            uploadInput.dispatchEvent(new Event('input', { bubbles: true }));
            if (typeof playConfirmSound === 'function') playConfirmSound();
        });
    };

    setupCategoryButtons('sites-group', 'sites-text');
    setupCategoryButtons('whitelist-sites-group', 'whitelist-sites-text');
    setupBandwidthPresetButtons();

    // --- Lógica do Modal Multiseat ---
    async function openMultiseatModal(ip, password) {
        multiseatModal.classList.remove('hidden');
        
        // Reseta e configura o filtro de busca
        if (msSearchInput) {
            msSearchInput.value = '';
            msSearchInput.oninput = () => {
                const term = msSearchInput.value.toLowerCase();
                const items = multiseatModal.querySelectorAll('.ms-device-item');
                items.forEach(item => {
                    const text = item.textContent.toLowerCase();
                    item.style.display = text.includes(term) ? '' : 'none';
                });
            };
        }
        
        // Função auxiliar para gerar cores baseadas no grupo (pai) do dispositivo
        const getGroupColor = (id) => {
            let parentId = 'root';
            if (id) {
                // Se tem ponto, o pai é tudo antes do último ponto (ex: 1-1.2 -> 1-1)
                if (id.includes('.')) parentId = id.substring(0, id.lastIndexOf('.'));
                // Se não tem ponto mas tem hífen (ex: 1-1), agrupa pelo barramento
                else if (id.includes('-')) parentId = id.split('-')[0];
                // Para PCI (ex: 00:02.0), agrupa pelo slot
                else if (id.includes(':')) parentId = id.substring(0, id.lastIndexOf('.'));
            }
            let hash = 0;
            for (let i = 0; i < parentId.length; i++) hash = parentId.charCodeAt(i) + ((hash << 5) - hash);
            const palette = ['#3b82f6', '#22c55e', '#a855f7', '#f97316', '#14b8a6', '#ef4444', '#eab308', '#6366f1', '#ec4899', '#64748b'];
            return palette[Math.abs(hash) % palette.length];
        };

        // Funções de manipulação do DOM do Multiseat
        const createDeviceItem = (dev) => {
            if (!dev) return document.createElement('div');
            const el = document.createElement('div');
            el.className = 'ms-device-item';
            el.draggable = true;
            el.dataset.path = dev.path;
            el.dataset.seat = dev.seat;
            el.dataset.devInfo = JSON.stringify(dev); // Armazena toda a info

            let icon = '🔌'; // Padrão para USB genérico
            const type = dev.type || '';
            if (type.includes('GPU') || type.includes('VGA') || type.includes('Display')) icon = '🖥️';
            if (type.includes('Teclado')) icon = '⌨️';
            if (type.includes('Mouse')) icon = '🖱️';
            if (type.includes('Áudio')) icon = '🔊';
            if (type.includes('Hub')) icon = '🔀';
            
            el.innerHTML = `<strong>${icon} ${dev.name || 'Desconhecido'}</strong><br><small>${dev.id || 'N/A'}</small>`;
            
            // Aplica a cor do grupo como uma borda lateral
            const groupColor = getGroupColor(dev.id);
            el.style.borderLeft = `5px solid ${groupColor}`;

            el.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('application/json', e.target.dataset.devInfo);
                setTimeout(() => el.classList.add('dragging'), 0);
            });
            el.addEventListener('dragend', () => el.classList.remove('dragging'));
            return el;
        };

        const loadMultiseatData = async () => {
            msListSeat0.innerHTML = '<div class="loading-placeholder">Carregando dispositivos...</div>';
            msListSeat1.innerHTML = '<div class="loading-placeholder">Carregando dispositivos...</div>';
            msRefreshBtn.classList.add('loading');
            msRefreshBtn.disabled = true;

            const result = await executeRemoteAction(ip, { password, action: ACTIONS.SCAN_MULTISEAT });
            
            msRefreshBtn.classList.remove('loading');
            msRefreshBtn.disabled = false;

            if (result.success) {
                try {
                    const jsonStart = result.message.indexOf('[');
                    const jsonEnd = result.message.lastIndexOf(']') + 1;
                    const jsonStr = (jsonStart > -1 && jsonEnd > jsonStart) 
                        ? result.message.substring(jsonStart, jsonEnd) 
                        : result.message;

                    const devices = JSON.parse(jsonStr);

                    // Ordena dispositivos pela topologia (ID físico), ex: 1-1 antes de 1-2, 1-2.1 antes de 1-2.2
                    devices.sort((a, b) => {
                        if (!a.id || !b.id) return 0;
                        return a.id.localeCompare(b.id, undefined, { numeric: true, sensitivity: 'base' });
                    });

                    msListSeat0.innerHTML = '';
                    msListSeat1.innerHTML = '';
                    if (devices.length === 0) {
                        msListSeat0.innerHTML = '<div class="loading-placeholder">Nenhum dispositivo compatível encontrado.</div>';
                    }
                    devices.forEach(dev => {
                        if (!dev) return;
                        const item = createDeviceItem(dev);
                        if (dev.seat === 'seat1') msListSeat1.appendChild(item);
                        else msListSeat0.appendChild(item);
                    });
                } catch (e) {
                    logStatusMessage(`Erro ao processar dados JSON do Multiseat: ${e.message}`, 'error');
                    msListSeat0.innerHTML = '<div class="error-placeholder">Erro ao ler dados do dispositivo.</div>';
                }
            } else {
                logStatusMessage(`Erro ao escanear multiseat: ${result.message}`, 'error');
                msListSeat0.innerHTML = '<div class="error-placeholder">Falha ao conectar ou escanear.</div>';
                msListSeat1.innerHTML = '';
            }
        };

        // Configura os listeners de Drop nas listas
        [msListSeat0, msListSeat1].forEach(list => {
            list.ondragover = e => {
                e.preventDefault();
                list.classList.add('drag-over');
            };
            list.ondragleave = () => list.classList.remove('drag-over');
            list.ondrop = async (e) => {
                e.preventDefault();
                list.classList.remove('drag-over');
                const rawData = e.dataTransfer.getData('application/json');
                if (!rawData) return;

                const dev = JSON.parse(rawData);
                if (!dev) return;
                const targetSeat = list.dataset.seat;

                if (dev.seat !== targetSeat) {
                    logStatusMessage(`Movendo ${dev.name || 'Dispositivo'} para ${targetSeat}...`, 'details');
                    
                    // Feedback visual: coloca o ícone do IP em modo processando
                    const statusIcon = getStatusIconElement(ip);
                    if (statusIcon) {
                        statusIcon.textContent = '🔄';
                        statusIcon.className = 'status-icon processing';
                    }

                    const result = await executeRemoteAction(ip, { password, action: ACTIONS.ATTACH_SEAT_DEVICE, device_path: dev.path, target_seat: targetSeat });
                    if (result.success) {
                        logStatusMessage(result.message, 'success');
                        if (statusIcon) statusIcon.textContent = '✅';
                        // Aumentado para 3.5 segundos para garantir que o kernel atualize a DB do udev
                        setTimeout(async () => { await loadMultiseatData(); }, 3500);
                    } else {
                        logStatusMessage(`Erro ao mover dispositivo: ${result.message}`, 'error');
                        if (statusIcon) { statusIcon.textContent = '❌'; statusIcon.className = 'status-icon error'; }
                        if (result.details) logStatusMessage(`Detalhes: ${result.details}`, 'details');
                    }
                }
            };
        });

        // Listeners dos botões do modal
        msCloseBtn.onclick = () => multiseatModal.classList.add('hidden');
        multiseatModal.addEventListener('click', (e) => {
            if (e.target === multiseatModal) {
                multiseatModal.classList.add('hidden');
            }
        });
        msRefreshBtn.onclick = loadMultiseatData;
        
        // Carrega os dados iniciais
        await loadMultiseatData();
    }

    // Função auxiliar para ler um arquivo como Data URL (base64)
    function readFileAsDataURL(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    // Função para construir o payload de uma ação, lidando com casos assíncronos como a leitura de arquivos.
    async function buildActionPayload(action, password) {
        // O payload base sempre deve conter a senha e a ação.
        const payload = { password: password, action: action };

        if (action === ACTIONS.SEND_MESSAGE) {
            payload.message = messageText.value;
        } else if (action === ACTIONS.KILL_PROCESS) {
            payload.process_name = processNameText.value;
        } else if (action === 'bloquear_sites') {
            const sitesText = document.getElementById('sites-text');
            payload.sites = sitesText ? sitesText.value : '';
        } else if (action === 'ativar_whitelist_sites') {
            const whitelistSitesText = document.getElementById('whitelist-sites-text');
            payload.sites = whitelistSitesText ? whitelistSitesText.value : '';
        } else if (action === ACTIONS.SET_BANDWIDTH_LIMIT) {
            let dlRaw = downloadLimitText ? downloadLimitText.value.trim() : '';
            let ulRaw = uploadLimitText ? uploadLimitText.value.trim() : '1'; // Padrão 1 Mbps

            // Converte Mbps para kbps (o backend espera kbps)
            let dlValue = dlRaw ? Math.round(parseFloat(dlRaw) * 1000).toString() : '';
            let ulValue = Math.round(parseFloat(ulRaw) * 1000).toString();

            payload.download_limit = dlValue;
            payload.upload_limit = ulValue;

            // Validação visual e bloqueio se o download estiver vazio
            if (!dlValue) {
                downloadLimitText.classList.add('invalid', 'shake-animation');
                downloadLimitText.focus();
                logStatusMessage('O limite de Download é obrigatório para esta ação.', 'error');
                
                downloadLimitText.addEventListener('animationend', () => {
                    downloadLimitText.classList.remove('shake-animation');
                }, { once: true });

                playAlertSound();
                return null; // Cancela o envio
            }

            // Validação de limite mínimo (ex: 100 kbps para manter conectividade básica)
            const MIN_BANDWIDTH_KBPS = 100; // 0.1 Mbps
            if (parseFloat(dlValue) < MIN_BANDWIDTH_KBPS || parseFloat(ulValue) < MIN_BANDWIDTH_KBPS) {
                downloadLimitText.classList.add('invalid', 'shake-animation');
                uploadLimitText.classList.add('invalid', 'shake-animation');
                downloadLimitText.focus();
                logStatusMessage(`O limite de banda não pode ser inferior a ${MIN_BANDWIDTH_KBPS} kbps (0.1 Mbps) para garantir a conectividade.`, 'error');
                
                downloadLimitText.addEventListener('animationend', () => {
                    downloadLimitText.classList.remove('shake-animation');
                    uploadLimitText.classList.remove('shake-animation');
                }, { once: true });

                playAlertSound();
                return null; // Cancela o envio
            }

            // Validação de limite máximo (1000 Mbps = 1.000.000 kbps)
            const MAX_BANDWIDTH_KBPS = 1000000; // 1000 Mbps
            if (parseFloat(dlValue) > MAX_BANDWIDTH_KBPS || parseFloat(ulValue) > MAX_BANDWIDTH_KBPS) {
                downloadLimitText.classList.add('invalid', 'shake-animation');
                uploadLimitText.classList.add('invalid', 'shake-animation');
                downloadLimitText.focus();
                logStatusMessage(`O limite de banda não pode exceder ${MAX_BANDWIDTH_KBPS / 1000} Mbps.`, 'error');
                
                downloadLimitText.addEventListener('animationend', () => {
                    downloadLimitText.classList.remove('shake-animation');
                    uploadLimitText.classList.remove('shake-animation');
                }, { once: true });

                playAlertSound();
                return null; // Cancela o envio
            }
        } else if (action === ACTIONS.ATTACH_SEAT_DEVICE) {
            payload.device_path = devicePathText.value.trim();
        } else if (action === ACTIONS.SET_WALLPAPER) {
            if (wallpaperFile.files.length === 0) {
                logStatusMessage('Por favor, selecione um arquivo de imagem para o papel de parede.', 'error');
                return null; // Retorna nulo para indicar falha na construção
            }
            const file = wallpaperFile.files[0];
            if (!file) {
                logStatusMessage('Arquivo não encontrado.', 'error');
                return null;
            }
            try {
                payload.wallpaper_data = await readFileAsDataURL(file);
                payload.wallpaper_filename = file.name;
            } catch (error) {
                logStatusMessage(`Erro ao ler o arquivo de imagem: ${error.message}`, 'error');
                return null;
            }
        }
        return payload;
    }

    function getSelectedIps() {
        return Array.from(document.querySelectorAll('input[name="ip"]:checked')).map(checkbox => {
            const toggleBtn = checkbox.closest('.ip-item').querySelector('.user-toggle-btn');
            const targetUser = toggleBtn ? toggleBtn.dataset.target : '';
            return targetUser ? `${checkbox.value}/${targetUser}` : checkbox.value;
        });
    }

    async function processBatch(payload, actionText, customTargetIps = null) {
        logStatusMessage(`--- Iniciando ação: "${actionText}" ---`, 'details');
        let targetIps = customTargetIps || getSelectedIps();
        if (!targetIps || targetIps.length === 0) return false;

        const PER_USER_ACTIONS = [
            'desativar', 'ativar', 'mostrar_sistema', 'ocultar_sistema', 'limpar_imagens',
            'desativar_barra_tarefas', 'ativar_barra_tarefas', 'bloquear_barra_tarefas', 'desbloquear_barra_tarefas',
            'bloquear_combinacoes_teclas', 'desbloquear_combinacoes_teclas', 'bloquear_terminal', 'desbloquear_terminal',
            'bloquear_dconf', 'desbloquear_dconf', 'definir_firefox_padrao', 'definir_chrome_padrao',
            'desativar_perifericos', 'ativar_perifericos', 'bloquear_tela_mensagem', 'desbloquear_tela_mensagem',
            'iniciar_modo_demo', 'parar_modo_demo', 'desativar_botao_direito', 'ativar_botao_direito',
            'enviar_mensagem', 'definir_papel_de_parede', 'instalar_scratchjr', 'remover_todos_bloqueios'
        ];

        // Se a ação é de nível de sistema/máquina, desduplica os IPs base (ex: 192.168.0.101/aluno1 -> 192.168.0.101)
        if (payload && payload.action && !PER_USER_ACTIONS.includes(payload.action)) {
            targetIps = Array.from(new Set(targetIps.map(ipSpec => {
                const baseIp = String(ipSpec).split('/')[0].trim();
                return baseIp.split(':')[0].trim();
            })));
        }

        let batchSuccess = false;
        const totalIPs = targetIps.length;
        let processedIPs = 0;
        updateProgressBar(0, totalIPs, actionText);

        if (totalIPs >= 2 || customTargetIps) {
            openBatchProgressModal(actionText, targetIps);
        }

        // Marca todos os itens como processando visualmente
        targetIps.forEach(targetIp => {
            const ipItem = ipListContainer.querySelector(`.ip-item[data-ip="${targetIp}"]`);
            if (ipItem) ipItem.classList.add('processing');
            const iconElement = getStatusIconElement(targetIp);
            if (iconElement) {
                iconElement.textContent = '🔄';
                iconElement.className = 'status-icon processing';
            }
        });

        const sock = getDashboardSocket();
        // Se Socket.IO estiver disponível e conectado, usa o executor paralelo do backend (ignora limite de 6 do browser!)
        if (sock && sock.connected) {
            const batchId = `batch_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
            if (typeof currentBatchState !== 'undefined' && currentBatchState) {
                currentBatchState.batchId = batchId;
            }

            const streamingLogGroups = new Map();

            return new Promise((resolve) => {
                const onStreamLine = (data) => {
                    if (!data || data.batch_id !== batchId) return;
                    const ip = data.ip;
                    let logGroup = streamingLogGroups.get(ip);
                    if (!logGroup && logGroupTemplate) {
                        const logGroupClone = logGroupTemplate.content.cloneNode(true);
                        const el = logGroupClone.querySelector('.log-group');
                        el.id = `log-group-${String(ip).replace(/[^a-zA-Z0-9_-]/g, '-')}-${Date.now()}`;
                        el.dataset.logType = 'details';
                        el.open = true;
                        el.querySelector('.log-group-icon').textContent = '⏳';
                        el.querySelector('.log-group-title').textContent = `${ip}: ${actionText}`;
                        el.querySelector('.log-group-timestamp').textContent = new Date().toLocaleTimeString();
                        
                        const copyBtn = el.querySelector('.copy-log-btn');
                        if (copyBtn) {
                            copyBtn.addEventListener('click', (e) => {
                                e.stopPropagation();
                                const contentEl = el.querySelector('.log-group-content');
                                if (contentEl) {
                                    navigator.clipboard.writeText(contentEl.textContent).then(() => {
                                        copyBtn.innerHTML = '<i data-feather="check"></i>';
                                        setTimeout(() => { copyBtn.innerHTML = '<i data-feather="copy"></i>'; if (window.feather) feather.replace(); }, 2000);
                                    });
                                }
                            });
                        }

                        systemLogBox.appendChild(el);
                        systemLogBox.scrollTop = systemLogBox.scrollHeight;
                        logGroup = { el, content: el.querySelector('.log-group-content') };
                        streamingLogGroups.set(ip, logGroup);
                    }

                    if (logGroup && logGroup.content && data.line && data.line.trim()) {
                        logGroup.content.appendChild(document.createTextNode(data.line));
                        systemLogBox.scrollTop = systemLogBox.scrollHeight;
                    }
                };

                const onItemResult = (data) => {
                    if (!data || data.batch_id !== batchId) return;
                    const targetIp = data.ip;
                    const result = data.result || { success: false, message: 'Erro desconhecido.' };

                    if (result.success) batchSuccess = true;

                    const logGroup = streamingLogGroups.get(targetIp);
                    if (logGroup && logGroup.el) {
                        const icon = logGroup.el.querySelector('.log-group-icon');
                        if (icon) icon.textContent = result.success ? '✅' : '❌';
                        logGroup.el.dataset.logType = result.success ? 'success' : 'error';
                    }

                    updateIpStatus(targetIp, result, actionText, payload);
                    processedIPs++;
                    updateProgressBar(processedIPs, totalIPs, actionText);
                    updateBatchProgressItem(targetIp, result.success, result.message, payload, actionText);
                };

                const onCompleted = (data) => {
                    if (data && data.batch_id && data.batch_id !== batchId) return;
                    cleanup();
                    resolve(batchSuccess);
                };

                const onError = (data) => {
                    if (data && data.batch_id && data.batch_id !== batchId) return;
                    logStatusMessage(`[Lote] Erro no backend: ${data?.message || 'Erro desconhecido'}`, 'error');
                    cleanup();
                    resolve(batchSuccess);
                };

                const cleanup = () => {
                    sock.off('batch_stream_line', onStreamLine);
                    sock.off('batch_item_result', onItemResult);
                    sock.off('batch_completed', onCompleted);
                    sock.off('batch_error', onError);
                };

                sock.on('batch_stream_line', onStreamLine);
                sock.on('batch_item_result', onItemResult);
                sock.on('batch_completed', onCompleted);
                sock.on('batch_error', onError);

                // Dispara lote em paralelo real no backend
                sock.emit('start_batch_action', {
                    batch_id: batchId,
                    action: payload.action,
                    ips: targetIps,
                    password: payload.password || getActivePassword(),
                    payload: payload
                });
            });
        }

        // Fallback: modo tradicional via HTTP
        const tasks = targetIps.map(targetIp => async () => {
            const result = await executeRemoteAction(targetIp, payload);
            if (result.success) batchSuccess = true;                    
            updateIpStatus(targetIp, result, actionText, payload);
            processedIPs++;
            updateProgressBar(processedIPs, totalIPs, actionText);
            updateBatchProgressItem(targetIp, result.success, result.message, payload, actionText);
        });
        await runPromisesInParallel(tasks, 25);
        return batchSuccess;
    }

    function openBatchProgressModal(actionText, ips) {
        const modal = document.getElementById('batch-progress-modal');
        if (!modal) return;

        currentBatchState = {
            total: ips.length,
            success: 0,
            failed: 0,
            pending: ips.length,
            failedIps: [],
            payload: null,
            actionText: actionText
        };

        const titleEl = document.getElementById('batch-progress-title');
        const subTitleEl = document.getElementById('batch-progress-subtitle');
        const progressBar = document.getElementById('batch-progress-bar');
        const statTotal = document.getElementById('batch-stat-total');
        const statSuccess = document.getElementById('batch-stat-success');
        const statFailed = document.getElementById('batch-stat-failed');
        const statPending = document.getElementById('batch-stat-pending');
        const liveStatusText = document.getElementById('batch-live-status-text');
        const retryBtn = document.getElementById('batch-retry-failed-btn');
        const streamList = document.getElementById('batch-device-stream-list');

        if (titleEl) titleEl.textContent = `Executando: ${actionText}`;
        if (subTitleEl) subTitleEl.textContent = `Processando ${ips.length} computador(es)...`;
        if (progressBar) progressBar.style.width = '0%';
        if (statTotal) statTotal.textContent = ips.length;
        if (statSuccess) statSuccess.textContent = '0';
        if (statFailed) statFailed.textContent = '0';
        if (statPending) statPending.textContent = ips.length;
        if (liveStatusText) liveStatusText.textContent = 'Em execução...';
        if (retryBtn) retryBtn.classList.add('hidden');

        if (streamList) {
            streamList.innerHTML = '';
            ips.forEach(ip => {
                const item = document.createElement('div');
                item.className = 'stream-item pending';
                item.id = `stream-item-${ip.replace(/[\/\.:]/g, '-')}`;
                item.innerHTML = `<span><strong>${ip}</strong></span><span class="status-msg">⏳ Processando...</span>`;
                streamList.appendChild(item);
            });
        }

        modal.classList.remove('hidden');
    }

    function updateBatchProgressItem(ip, success, message, payload, actionText) {
        currentBatchState.pending = Math.max(0, currentBatchState.pending - 1);
        if (success) {
            currentBatchState.success++;
        } else {
            currentBatchState.failed++;
            if (!currentBatchState.failedIps.includes(ip)) {
                currentBatchState.failedIps.push(ip);
            }
            currentBatchState.payload = payload;
            currentBatchState.actionText = actionText;
        }

        const processed = currentBatchState.success + currentBatchState.failed;
        const pct = Math.round((processed / currentBatchState.total) * 100);

        const progressBar = document.getElementById('batch-progress-bar');
        if (progressBar) progressBar.style.width = `${pct}%`;

        const statSuccess = document.getElementById('batch-stat-success');
        const statFailed = document.getElementById('batch-stat-failed');
        const statPending = document.getElementById('batch-stat-pending');

        if (statSuccess) statSuccess.textContent = currentBatchState.success;
        if (statFailed) statFailed.textContent = currentBatchState.failed;
        if (statPending) statPending.textContent = currentBatchState.pending;

        const itemEl = document.getElementById(`stream-item-${ip.replace(/[\/\.:]/g, '-')}`);
        if (itemEl) {
            itemEl.className = `stream-item ${success ? 'success' : 'failed'}`;
            const icon = success ? '✓' : '✗';
            itemEl.innerHTML = `<span><strong>${ip}</strong></span><span class="status-msg">${icon} ${message || (success ? 'Sucesso' : 'Falha')}</span>`;
        }

        if (processed >= currentBatchState.total) {
            const liveStatusText = document.getElementById('batch-live-status-text');
            if (liveStatusText) liveStatusText.textContent = 'Concluído';
            if (currentBatchState.failed > 0) {
                const retryBtn = document.getElementById('batch-retry-failed-btn');
                const failedBadge = document.getElementById('failed-count-badge');
                if (retryBtn) retryBtn.classList.remove('hidden');
                if (failedBadge) failedBadge.textContent = currentBatchState.failed;
            }
        }
    }

    /**
     * Executa tarefas em paralelo com limite de concorrência e política de re-tentativa.
     */
    async function runPromisesInParallel(taskFunctions, concurrency = 25, retries = 1) {
        const limit = (typeof concurrency === 'number' && !isNaN(concurrency) && concurrency > 0) ? concurrency : 25;
        const executeWithRetry = async (taskFn, attempt = 0) => {
            try {
                await taskFn();
            } catch (err) {
                if (attempt < retries) {
                    console.warn(`Retrying task... Attempt ${attempt + 1}`);
                    await new Promise(r => setTimeout(r, 1000)); // Backoff de 1s
                    return executeWithRetry(taskFn, attempt + 1);
                }
                throw err;
            }
        };

        const queue = [...taskFunctions];
        const numWorkers = Math.min(limit, queue.length);
        if (numWorkers === 0) return;

        const workers = Array(numWorkers).fill(null).map(async () => {
            while (queue.length > 0) {
                const task = queue.shift();
                if (task) await executeWithRetry(task);
            }
        });
        await Promise.all(workers);
    }

    // Listener para o evento de submit do formulário
    actionForm.addEventListener('submit', async (event) => {
        event.preventDefault(); // Impede o recarregamento da página

        let password = getActivePassword();
        let selectedActions = Array.from(actionSelect.selectedOptions).map(opt => opt.value);
        
        // Coleta os IPs, anexando a flag de usuário se estiver definida no botão de toggle
        const selectedIps = getSelectedIps();

        // Verifica se há ações que exigem um IP selecionado.
        const hasRemoteActions = selectedActions.some(action => !LOCAL_ACTIONS.has(action));

        if (hasRemoteActions && selectedIps.length === 0) {
            // Aplica a animação de shake, o som e o destaque na lista de IPs
            playAlertSound();
            submitBtn.classList.add('btn-shake');
            ipListSection.classList.add('section-flash-error');
            
            setTimeout(() => {
                submitBtn.classList.remove('btn-shake');
                ipListSection.classList.remove('section-flash-error');
            }, 400);
            
            logStatusMessage('Por favor, selecione pelo menos um IP.', 'error');
            return; // Aborta se ações remotas foram selecionadas sem um IP.
        }

        if (!password) {
            logStatusMessage('Por favor, digite a senha.', 'error');
            return;
        }

        if (selectedActions.length === 0) {
            logStatusMessage('Por favor, selecione pelo menos uma ação no menu suspenso.', 'error');
            return;
        }

        // --- ETAPA 1: Construir o Payload Completo ---
        const actionPayload = await buildActionPayload(selectedActions[0], password);
        if (!actionPayload) return;

        // --- Fluxo de Agendamento ---
        const scheduleTimeInput = document.getElementById('schedule-time');
        const executionTime = (scheduleTimeInput && !scheduleTimeInput.parentElement.classList.contains('hidden')) ? scheduleTimeInput.value : null;

        if (executionTime) {
            try {
                // Enviamos o actionPayload (com mensagens/files) junto com os dados de agendamento
                const scheduleData = { ...actionPayload, ips: selectedIps, execution_time: executionTime };
                const res = await fetch(`${API_BASE_URL}/api/schedule`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(scheduleData)
                });
                const data = await res.json();
                if (data.success) {
                    showToast(data.message, 'success');
                    fetchScheduledTasks();
                    resetUI();
                }
            } catch (e) { showToast("Erro ao agendar", "error"); }
            return;
        }

        // --- Confirmação para Ações Perigosas ---
        if (selectedActions.some(action => DANGEROUS_ACTIONS.includes(action))) {
            // Obtém o texto da primeira ação perigosa para exibir no modal
            // Obtém o texto da ação a partir da opção selecionada no dropdown
            const actionLabel = actionSelect.options[actionSelect.selectedIndex].text;


            const confirmationMessage = `Você está prestes a executar uma ação disruptiva:\n\n• ${actionLabel}\n\nTem certeza que deseja continuar?`;

            const confirmed = await showConfirmationModal(confirmationMessage);
            if (!confirmed) {
                logStatusMessage('Operação cancelada pelo usuário.', 'details');
                return; // Aborta a execução
            }
        }

        // Desabilita o botão e prepara a UI antes de qualquer coisa.
        stopStatusMonitor();
        prepareUIForProcessing();

        try {
            const actionHandlers = {
                [ACTIONS.SHUTDOWN_SERVER]: async () => {
                    logStatusMessage('Enviando comando para desligar o servidor backend...', 'details');
                    const response = await fetch(`${API_BASE_URL}/shutdown`, { method: 'POST' });
                    const data = await response.json();
                    if (data.success) {
                        logStatusMessage('Comando de desligamento aceito. O servidor será encerrado.', 'success');
                        submitBtn.textContent = 'Servidor Desligando...';
                    } else {
                        logStatusMessage(`Falha ao desligar o servidor: ${data.message}`, 'error');
                    }
                    return { success: data.success, skipFurtherProcessing: true };
                },
                [ACTIONS.BACKUP_APLICACAO]: async () => {
                    logStatusMessage('Iniciando backup da aplicação...', 'details');
                    const response = await fetch(`${API_BASE_URL}/backup-application`, { method: 'POST' });
                    const data = await response.json();
                    logStatusMessage(data.success ? `Backup da aplicação criado com sucesso: ${data.path}` : `Falha ao criar backup da aplicação: ${data.message}`, data.success ? 'success' : 'error');
                    return { success: data.success, skipFurtherProcessing: true };
                },
                [ACTIONS.RESTAURAR_BACKUP_APLICACAO]: async () => {
                    const backupFile = await showAppBackupSelectionModal();
                    if (!backupFile) {
                        logStatusMessage('Restauração de backup da aplicação cancelada.', 'details');
                        return { success: false, skipFurtherProcessing: true };
                    }
                    logStatusMessage(`Iniciando restauração do backup "${backupFile}"...`, 'details');

                    // Dispara a requisição de restauração sem esperar pela resposta,
                    // pois o servidor será reiniciado.
                    fetch(`${API_BASE_URL}/restore-application-backup`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ backup_file: backupFile }),
                    }).catch(() => {}); // Ignora o erro de fetch esperado.

                    // Exibe uma mensagem e começa a verificar se o servidor voltou.
                    logStatusMessage('Comando de restauração enviado. Aguardando o servidor reiniciar...', 'success');

                    // Define a função de verificação dentro do handler para garantir que ela só exista neste escopo.
                    function checkAndReload() {
                        const checkInterval = setInterval(async () => {
                            try {
                                // Usa a rota /check-status que é mais leve que /discover-ips
                                const response = await fetch(`${API_BASE_URL}/check-status`, {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ ips: [] }), // Envia um corpo vazio
                                    signal: AbortSignal.timeout(2000)
                                });
                                if (response.ok) {
                                    clearInterval(checkInterval);
                                    logStatusMessage('Servidor online. Recarregando a página...', 'success');
                                    setTimeout(() => window.location.reload(), 1500);
                                }
                            } catch (e) { /* Ignora erros de conexão, que são esperados */ }
                        }, 3000); // Tenta a cada 3 segundos.
                    }
                    checkAndReload(); // Inicia a verificação
                    return { success: true, skipFurtherProcessing: true };
                },
                [ACTIONS.ENABLE_SHORTCUTS]: async () => {
                    let backupFiles = null;
                    let sourceIp = null;

                    // Tenta buscar a lista de backups a partir do primeiro IP online na seleção.
                    for (const ip of selectedIps) {
                        logStatusMessage(`Tentando buscar lista de backups de ${ip}...`, 'details');
                        const files = await showBackupSelectionModal(ip, password);
                        // Se a busca for bem-sucedida (não nula) e o usuário selecionar arquivos, interrompe o loop.
                        if (files !== null) {
                            backupFiles = files;
                            sourceIp = ip;
                            break;
                        }
                        logStatusMessage(`Falha ao buscar backups de ${ip}. Tentando o próximo...`, 'details');
                    }

                    if (backupFiles === null) {
                        logStatusMessage('Restauração de atalhos cancelada pelo usuário.', 'details');
                        return { success: false, skipFurtherProcessing: true };
                    }

                    if (backupFiles.length === 0) {
                        logStatusMessage('Nenhum atalho selecionado para restauração. Pulando a ação.', 'details');
                        return { success: false, skipFurtherProcessing: true };
                    }
                    const restorePayload = { password, action: ACTIONS.ENABLE_SHORTCUTS, backup_files: backupFiles };
                    return { success: await processBatch(restorePayload, 'Restaurar Atalhos'), skipFurtherProcessing: true };
                },
                [ACTIONS.SCAN_MULTISEAT]: async () => {
                    // A ação agora só pode ser disparada para um único IP.
                    if (hasRemoteActions && selectedIps.length !== 1) {
                        logStatusMessage('Por favor, selecione exatamente UM dispositivo para gerenciar o Multiseat.', 'error');
                        return { success: false, skipFurtherProcessing: true };
                    }
                    const ip = selectedIps[0];
                    await openMultiseatModal(ip, password);
                    return { success: true, skipFurtherProcessing: true };
                },
            };

            let anySuccess = false;
            ipsWithKeyErrors.clear();

            // Itera sobre cada ação selecionada
            // ETAPA 1: Construir todos os payloads necessários ANTES da execução.
            // Isso garante que operações assíncronas como a leitura de arquivos sejam concluídas.
            const executionQueue = [];
            for (const action of selectedActions) {
                const handler = actionHandlers[action];
                if (handler) {
                    // Adiciona o handler especial à fila de execução.
                    executionQueue.push({ type: 'handler', handler, action });
                } else {
                    // Constrói o payload para ações padrão.
                    const payload = await buildActionPayload(action, password);
                    if (payload) { // Adiciona à fila apenas se o payload for válido.
                        const actionText = Array.from(actionSelect.options).find(opt => opt.value === action)?.text || action;
                        executionQueue.push({ type: 'batch', payload, actionText });
                    }
                }
            }

            // ETAPA 2: Executar as ações da fila em sequência.
            for (const task of executionQueue) {
                let success = false;
                if (task.type === 'handler') {
                    const result = await task.handler();
                    success = result?.success || false;
                } else if (task.type === 'batch') {
                    success = await processBatch(task.payload, task.actionText);
                }
                if (success) anySuccess = true;
            }

            // Atualiza a contagem de uso para TODAS as ações que estavam na fila de execução.
            // Isso garante que tanto ações em lote (batch) quanto ações especiais (handler) sejam contadas.
            const allExecutedActions = executionQueue.map(task => {
                return task.type === 'batch' ? task.payload.action : task.action;
            }).filter(Boolean); // O .filter(Boolean) remove quaisquer valores nulos ou indefinidos.

            if (allExecutedActions.length > 0) {
                updateActionUsage(allExecutedActions);
                renderQuickAccessButtons(); // Atualiza os botões de acesso rápido
            }

            if (anySuccess) {
                if (sessionPassword === null) {
                    sessionPassword = password;
                    passwordGroup.style.display = 'none';
                    logStatusMessage('Senha salva para esta sessão. Para alterar, recarregue a página.', 'details');
                }
                try {
                    sessionStorage.setItem('app_ssh_password', password);
                    localStorage.setItem('app_ssh_password', password);
                } catch(e){}
            }

            logStatusMessage('--- Processamento concluído! ---', 'details');
        } catch (error) { // Captura qualquer erro inesperado que não foi tratado internamente
            console.error("Erro inesperado durante a execução das ações:", error);
            logStatusMessage(`Ocorreu um erro inesperado: ${error.message}`, 'error');
        } finally {
            // --- Finalização da UI (executado sempre) ---
            progressBar.style.width = '0%';
            progressText.textContent = 'Pronto para executar.';

            if (ipsWithKeyErrors.size > 0) {
                fixKeysBtn.classList.remove('hidden');
            }

            submitBtn.disabled = false;
            submitBtn.classList.remove('processing');
            submitBtn.querySelector('.btn-text').textContent = 'Executar Ação';

            if (autoRefreshToggle.checked) {
                startStatusMonitor();
            }
        }
    });

    // --- Atalho de Teclado (Ctrl + Enter) para Executar ---
    document.addEventListener('keydown', (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
            // Verifica se o botão de execução está visível e habilitado
            if (submitBtn && !submitBtn.disabled && submitBtn.offsetParent !== null) {
                event.preventDefault(); // Evita comportamento padrão se houver
                submitBtn.click();
            }
        }
    });

    // --- Função para Gerenciar Blocklist ---
    async function showBlocklistModal() {
        blocklistModal.classList.remove('hidden');
        blocklistList.innerHTML = '<p>Carregando lista de bloqueios...</p>';
        
        try {
            const response = await fetch(`${API_BASE_URL}/get-blocklist`);
            const data = await response.json();
            
            if (data.success && data.blocklist && data.blocklist.length > 0) {
                blocklistList.innerHTML = '';
                data.blocklist.forEach(ip => {
                    const item = document.createElement('div');
                    item.className = 'backup-item'; // Reutiliza estilo de layout de lista
                    item.style.justifyContent = 'space-between';
                    item.innerHTML = `
                        <div class="backup-details"><strong>${ip}</strong></div>
                        <button type="button" class="modal-btn modal-btn-cancel small-btn unblock-btn" data-ip="${ip}" style="margin:0; padding:4px 8px;">Desbloquear</button>
                    `;
                    blocklistList.appendChild(item);
                });

                // Adiciona listeners para os botões de desbloqueio criados
                blocklistList.querySelectorAll('.unblock-btn').forEach(btn => {
                    btn.onclick = async () => {
                        const ip = btn.dataset.ip;
                        const res = await fetch(`${API_BASE_URL}/unblock-ip`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ ip })
                        });
                        const result = await res.json();
                        if (result.success) {
                            showToast(result.message, 'success');
                            showBlocklistModal(); // Atualiza a lista no modal
                        }
                    };
                });
            } else {
                blocklistList.innerHTML = '<p>Nenhum IP bloqueado no momento.</p>';
            }
        } catch (e) {
            blocklistList.innerHTML = '<p class="error-text">Erro ao conectar com o servidor.</p>';
        }
    }

    if (blocklistModalCloseBtn) {
        blocklistModalCloseBtn.onclick = () => blocklistModal.classList.add('hidden');
    }
    if (blocklistModal) {
        blocklistModal.addEventListener('click', (e) => {
            if (e.target === blocklistModal) {
                blocklistModal.classList.add('hidden');
            }
        });
    }

    // Listener para o botão "Corrigir Chaves SSH"
    fixKeysBtn.addEventListener('click', async () => {
        const ipsToFix = Array.from(ipsWithKeyErrors);
        if (ipsToFix.length === 0) return;

        fixKeysBtn.disabled = true;
        fixKeysBtn.querySelector('.btn-text').textContent = 'Corrigindo...';
        logStatusMessage(`--- Tentando corrigir chaves SSH para ${ipsToFix.length} dispositivo(s)... ---`, 'details');

        try {
            const response = await fetch(`${API_BASE_URL}/fix-ssh-keys`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ips: ipsToFix }),
            });
            const data = await response.json();

            for (const ip in data.results) {
                const result = data.results[ip];
                const logType = result.success ? 'success' : 'error';
                logStatusMessage(`[${ip}] ${result.message}`, logType);
            }
            logStatusMessage('Correção de chaves concluída. Tente executar a ação novamente.', 'details');
        } catch (error) {
            logStatusMessage('Erro de conexão ao tentar corrigir chaves SSH.', 'error');
        } finally {
            fixKeysBtn.disabled = false;
            fixKeysBtn.querySelector('.btn-text').textContent = 'Corrigir Chaves SSH';
            fixKeysBtn.classList.add('hidden'); // Esconde o botão após a tentativa
        }
    });

    // Listener para o botão de gerenciar blocklist
    if (manageBlocklistBtn) {
        manageBlocklistBtn.addEventListener('click', showBlocklistModal);
    }

    // Listener para o toggle de atualização automática (colocado no final para garantir que todas as funções estejam definidas)
    if (autoRefreshToggle) {
        autoRefreshToggle.addEventListener('change', () => {
            // Sempre limpa o timer existente para evitar múltiplos timers rodando.
            if (autoRefreshTimer) {
                clearInterval(autoRefreshTimer);
                autoRefreshTimer = null;
            }
            stopStatusMonitor(); // Também para o monitor de status

            if (autoRefreshToggle.checked) {
                autoRefreshTimer = setInterval(fetchAndDisplayIps, AUTO_REFRESH_INTERVAL);
                startStatusMonitor(); // Inicia o monitor de status junto
                logStatusMessage(`Atualização automática ativada (a cada ${AUTO_REFRESH_INTERVAL / 60000} minutos).`, 'details');
            } else {
                // A mensagem de "pausado" já é emitida por stopStatusMonitor
                logStatusMessage('Atualização automática desativada.', 'details');
            }
        });
    }

    // --- Lógica de Drag and Drop para os Botões de Ação ---
    const bottomFixedActions = document.getElementById('bottom-fixed-actions');
    if (bottomFixedActions) {
        let draggedButton = null;

        bottomFixedActions.addEventListener('dragstart', (e) => {
            // Garante que estamos arrastando um botão direto do container
            if (e.target.matches('.bottom-fixed-actions > button')) {
                draggedButton = e.target;
                setTimeout(() => {
                    draggedButton.classList.add('dragging');
                }, 0);
            }
        });

        bottomFixedActions.addEventListener('dragover', (e) => {
            e.preventDefault();
            const targetButton = e.target.closest('.bottom-fixed-actions > button');
            if (targetButton && draggedButton && targetButton !== draggedButton) {
                const rect = targetButton.getBoundingClientRect();
                // Usa a posição X do mouse para determinar a ordem
                const offsetX = e.clientX - rect.left - rect.width / 2;

                if (offsetX < 0) {
                    bottomFixedActions.insertBefore(draggedButton, targetButton);
                } else {
                    bottomFixedActions.insertBefore(draggedButton, targetButton.nextSibling);
                }
            }
        });

        bottomFixedActions.addEventListener('drop', (e) => {
            e.preventDefault();
            if (draggedButton) {
                draggedButton.classList.remove('dragging');
                draggedButton = null;

                // Salva a nova ordem dos botões no localStorage
                const currentButtonOrder = Array.from(bottomFixedActions.querySelectorAll('button')).map(btn => btn.id);
                localStorage.setItem('buttonOrder', JSON.stringify(currentButtonOrder));
                logStatusMessage('Ordem dos botões salva.', 'details');
            }
        });

        bottomActionsContainer.addEventListener('dragend', () => {
            if (draggedButton) {
                draggedButton.classList.remove('dragging');
                draggedButton = null;
            }
        });
    }

    // --- Lógica para Restaurar a Ordem dos Botões no Carregamento ---
    const savedButtonOrder = JSON.parse(localStorage.getItem('buttonOrder'));
    if (savedButtonOrder && bottomFixedActions) {
        const fragment = document.createDocumentFragment();
        // Adiciona os botões ao fragmento na ordem salva
        savedButtonOrder.forEach(buttonId => {
            const button = document.getElementById(buttonId);
            if (button) fragment.appendChild(button);
        });
        // Limpa o container e adiciona os botões ordenados
        bottomFixedActions.innerHTML = '';
        bottomFixedActions.appendChild(fragment);
    }

    // --- Configuração de Tooltips para Botões Estáticos ---
    const staticTooltips = [
        { id: 'refresh-btn', text: 'Recarregar lista de dispositivos' },
        { id: 'reset-btn', text: 'Limpar seleções e campos' },
        { id: 'submit-btn', text: 'Executar ação selecionada (Ctrl+Enter)' },
        { id: 'toggle-tasks-btn', text: 'Mostrar/Ocultar tarefas agendadas' },
        { id: 'export-ips-btn', text: 'Baixar lista de IPs (.txt)' },
        { id: 'import-macs-btn', text: 'Importar lista de MACs' },
        { id: 'clear-log-btn', text: 'Limpar histórico de log' },
        { id: 'fix-keys-btn', text: 'Corrigir erros de chave SSH' },
        { id: 'select-online-btn', text: 'Selecionar apenas Online' },
        { id: 'manage-blocklist-btn', text: 'Gerenciar IPs bloqueados' }
    ];
    staticTooltips.forEach(t => {
        const el = document.getElementById(t.id);
        if (el) el.setAttribute('data-tooltip', t.text);
    });

    // --- Lógica do Terminal Web SSH (xterm.js + Socket.IO) ---
    function setupWebSSHTerminal() {
        const sshModal = document.getElementById('ssh-terminal-modal');
        const sshTargetSpan = document.getElementById('ssh-terminal-target');
        const sshStatusBadge = document.getElementById('ssh-terminal-status');
        const sshLoginForm = document.getElementById('ssh-login-form');
        const sshUsernameInput = document.getElementById('ssh-username-input');
        const sshPasswordInput = document.getElementById('ssh-password-input');
        const sshConnectBtn = document.getElementById('ssh-connect-btn');
        const sshContainer = document.getElementById('ssh-terminal-container');
        const sshClearBtn = document.getElementById('ssh-terminal-clear-btn');
        const sshFullscreenBtn = document.getElementById('ssh-terminal-fullscreen-btn');
        const sshCloseBtn = document.getElementById('ssh-terminal-close-btn');

        if (!sshModal || !sshContainer) return;

        let socket = null;
        let term = null;
        let fitAddon = null;
        let currentIp = '';
        let isConnected = false;

        function updateStatus(status, text) {
            sshStatusBadge.className = `ssh-status-badge ${status}`;
            sshStatusBadge.textContent = text;
        }

        function initXterm() {
            if (term) return;

            term = new Terminal({
                cursorBlink: true,
                cursorStyle: 'block',
                theme: {
                    background: '#090d16',
                    foreground: '#f8fafc',
                    cursor: '#3b82f6',
                    selectionBackground: 'rgba(59, 130, 246, 0.3)',
                    black: '#1e293b',
                    red: '#ef4444',
                    green: '#10b981',
                    yellow: '#f59e0b',
                    blue: '#3b82f6',
                    magenta: '#a855f7',
                    cyan: '#06b6d4',
                    white: '#f8fafc'
                },
                fontSize: 14,
                fontFamily: "'JetBrains Mono', 'Consolas', 'Courier New', monospace",
                allowProposedApi: true
            });

            if (window.FitAddon) {
                fitAddon = new window.FitAddon.FitAddon();
                term.loadAddon(fitAddon);
            }

            if (window.WebLinksAddon) {
                term.loadAddon(new window.WebLinksAddon.WebLinksAddon());
            }

            term.open(sshContainer);

            term.onData(data => {
                if (socket && isConnected) {
                    socket.emit('ssh_input', { data });
                }
            });

            term.onResize(size => {
                if (socket && isConnected) {
                    socket.emit('ssh_resize', { cols: size.cols, rows: size.rows });
                }
            });
        }

        function initSocket() {
            if (socket) return;

            socket = io({
                transports: ['websocket', 'polling'],
                reconnection: true
            });

            socket.on('ssh_output', data => {
                if (term) term.write(data);
            });

            socket.on('ssh_connected', () => {
                isConnected = true;
                updateStatus('connected', 'Conectado');
                sshLoginForm.classList.add('hidden');
                if (fitAddon) {
                    setTimeout(() => fitAddon.fit(), 100);
                }
            });

            socket.on('ssh_disconnected', () => {
                isConnected = false;
                updateStatus('disconnected', 'Desconectado');
            });

            socket.on('disconnect', () => {
                isConnected = false;
                updateStatus('disconnected', 'Desconectado');
            });
        }

        function connectSSH(ip, username, password) {
            currentIp = ip;
            sshTargetSpan.textContent = ip;
            updateStatus('connecting', 'Conectando...');
            initSocket();
            initXterm();

            term.clear();
            term.focus();

            if (fitAddon) {
                fitAddon.fit();
            }

            socket.emit('connect_ssh', {
                ip,
                username,
                password,
                cols: term ? term.cols : 80,
                rows: term ? term.rows : 24
            });
        }

        window.openWebSSHTerminal = (ip, username = '') => {
            currentIp = ip;
            sshTargetSpan.textContent = ip;
            sshModal.classList.remove('hidden');

            if (window.feather) {
                setTimeout(() => feather.replace(), 50);
            }

            const activePassword = typeof getActivePassword === 'function' ? getActivePassword() : '';

            if (username && activePassword) {
                sshLoginForm.classList.add('hidden');
                connectSSH(ip, username, activePassword);
            } else {
                sshLoginForm.classList.remove('hidden');
                sshUsernameInput.value = username || 'aluno';
                sshPasswordInput.value = activePassword || '';
                sshUsernameInput.focus();
            }
        };


        if (sshConnectBtn) {
            sshConnectBtn.onclick = () => {
                const username = sshUsernameInput.value.trim();
                const password = sshPasswordInput.value;
                if (!username) {
                    alert('Por favor, informe o usuário SSH.');
                    return;
                }
                connectSSH(currentIp, username, password);
            };
        }

        if (sshClearBtn) {
            sshClearBtn.onclick = () => {
                if (term) term.clear();
            };
        }

        if (sshFullscreenBtn) {
            sshFullscreenBtn.onclick = () => {
                const modalContent = sshModal.querySelector('.ssh-terminal-content');
                if (modalContent) {
                    modalContent.classList.toggle('fullscreen');
                    if (fitAddon) {
                        setTimeout(() => fitAddon.fit(), 150);
                    }
                }
            };
        }

        const closeTerminal = (e) => {
            if (e) {
                e.preventDefault();
                e.stopPropagation();
            }

            if (socket) {
                try {
                    socket.emit('disconnect_ssh');
                    socket.disconnect();
                } catch (err) {
                    console.warn("Erro ao desconectar socket SSH:", err);
                }
                socket = null;
            }

            isConnected = false;
            sshModal.classList.add('hidden');

            const modalContent = sshModal.querySelector('.ssh-terminal-content');
            if (modalContent) {
                modalContent.classList.remove('fullscreen');
            }

            updateStatus('disconnected', 'Desconectado');

            if (term) {
                try {
                    term.clear();
                } catch (err) {}
            }
        };

        if (sshCloseBtn) {
            sshCloseBtn.addEventListener('click', closeTerminal);
        }

        sshModal.addEventListener('click', (e) => {
            if (e.target === sshModal || e.target.closest('#ssh-terminal-close-btn')) {
                closeTerminal(e);
            }
        });


        window.addEventListener('resize', () => {
            if (!sshModal.classList.contains('hidden') && fitAddon && term) {
                fitAddon.fit();
                if (socket && isConnected) {
                    socket.emit('ssh_resize', { cols: term.cols, rows: term.rows });
                }
            }
        });

        document.addEventListener('click', (e) => {
            const btn = e.target.closest('.btn-ssh-terminal, [data-action="ssh-terminal"]');
            if (btn) {
                e.stopPropagation();
                e.preventDefault();
                const ip = btn.dataset.ip || (btn.closest('.ip-item') ? btn.closest('.ip-item').dataset.ip : '');
                if (ip) {
                    window.openWebSSHTerminal(ip);
                }
            }
        });
    }

    function setupWebVNC() {
        const vncModal = document.getElementById('vnc-desktop-modal');
        if (!vncModal) return;

        const vncTargetSpan = document.getElementById('vnc-desktop-target');
        const vncStatusBadge = document.getElementById('vnc-desktop-status');
        const vncContainer = document.getElementById('vnc-canvas-container');
        const vncCtrlAltDelBtn = document.getElementById('vnc-ctrlaltdel-btn');
        const vncScaleBtn = document.getElementById('vnc-scale-btn');
        const vncFullscreenBtn = document.getElementById('vnc-fullscreen-btn');
        const vncCloseBtn = document.getElementById('vnc-close-btn');

        let rfb = null;
        let activeWsPort = null;
        let isScaled = true;

        function updateVNCStatus(status, text) {
            if (!vncStatusBadge) return;
            vncStatusBadge.className = `vnc-status-badge ${status}`;
            vncStatusBadge.textContent = text;
        }

        const closeVNC = async (e) => {
            if (e) {
                e.preventDefault();
                e.stopPropagation();
            }

            if (rfb) {
                try {
                    rfb.disconnect();
                } catch (err) {}
                rfb = null;
            }

            if (activeWsPort) {
                try {
                    fetch(`${API_BASE_URL}/api/stop-vnc`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ ws_port: activeWsPort })
                    }).catch(() => {});
                } catch (err) {}
                activeWsPort = null;
            }

            vncModal.classList.add('hidden');
            const modalContent = vncModal.querySelector('.vnc-desktop-content');
            if (modalContent) modalContent.classList.remove('fullscreen');
            if (vncContainer) vncContainer.innerHTML = '';
            updateVNCStatus('disconnected', 'Desconectado');
        };

        window.openWebVNC = async (ip, display = null) => {
            // Se houver uma sessão VNC ativa prévia, encerra graciosamente
            if (rfb || activeWsPort) {
                await closeVNC();
            }

            if (vncTargetSpan) vncTargetSpan.textContent = ip;
            vncModal.classList.remove('hidden');
            if (vncContainer) vncContainer.innerHTML = '';
            updateVNCStatus('connecting', `Iniciando VNC em ${ip}...`);

            const activePassword = typeof getActivePassword === 'function' ? getActivePassword() : '';

            let wsPort = 6080;
            try {
                const bodyData = { ip, username: 'aluno', password: activePassword };
                if (display) bodyData.display = display;

                const prepRes = await fetch(`${API_BASE_URL}/api/start-vnc`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(bodyData)
                });
                const prepData = await prepRes.json();
                
                if (prepData.multiseat) {
                    vncModal.classList.add('hidden');
                    const msModal = document.getElementById('vnc-multiseat-modal');
                    const msButtons = document.getElementById('vnc-multiseat-buttons');
                    if (msButtons) {
                        msButtons.innerHTML = '';
                        prepData.displays.forEach(d => {
                            const btn = document.createElement('button');
                            btn.className = 'modal-btn modal-btn-confirm';
                            btn.textContent = d.label;
                            btn.onclick = () => {
                                msModal.classList.add('hidden');
                                window.openWebVNC(ip, d.display);
                            };
                            msButtons.appendChild(btn);
                        });
                    }
                    if (msModal) msModal.classList.remove('hidden');
                    return;
                }

                if (prepData.success && prepData.ws_port) {
                    wsPort = prepData.ws_port;
                    activeWsPort = wsPort;
                    updateVNCStatus('connecting', `Conectando ao display remoto (${prepData.display || ':0'})...`);
                } else if (!prepData.success) {
                    updateVNCStatus('disconnected', `Erro: ${prepData.message}`);
                    logStatusMessage(`VNC: ${prepData.message}`, 'error');
                    return;
                }
            } catch (err) {
                updateVNCStatus('disconnected', 'Erro ao contatar o backend');
                console.error('Erro ao preparar VNC:', err);
                return;
            }

            const wsHost = window.location.hostname || '127.0.0.1';
            const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
            const wsUrl = `${protocol}://${wsHost}:${wsPort}/websockify`;

            try {
                if (typeof window.RFB !== 'function') {
                    throw new Error("Biblioteca noVNC (RFB) não carregada no navegador.");
                }

                rfb = new window.RFB(vncContainer, wsUrl);
                rfb.scaleViewport = isScaled;
                rfb.resizeSession = false;
                rfb.showDotCursor = false;
                rfb.qualityLevel = 8;       // Modo Focado / Tela Cheia: 15-30 FPS alta qualidade
                rfb.compressionLevel = 2;   // Baixa latência
                rfb.targetFps = 30;         // Fluido 30 FPS para inspeção direta do professor

                rfb.addEventListener('connect', () => {
                    updateVNCStatus('connected', `Conectado → ${ip}`);
                    logStatusMessage(`VNC Conectado a ${ip}`, 'success');
                });

                rfb.addEventListener('disconnect', (e) => {
                    const clean = e.detail?.clean;
                    updateVNCStatus('disconnected', clean ? `Desconectado de ${ip}` : `Conexão perdida com ${ip}`);
                    rfb = null;
                });

                rfb.addEventListener('credentialsrequired', () => {
                    const pwd = prompt('Senha VNC:') || '';
                    rfb.sendCredentials({ password: pwd });
                });

                rfb.addEventListener('securityfailure', (e) => {
                    updateVNCStatus('disconnected', `Falha de autenticação: ${e.detail?.reason || 'senha incorreta'}`);
                });

            } catch (err) {
                updateVNCStatus('disconnected', `Erro noVNC: ${err.message}`);
                console.error('Erro ao instanciar noVNC RFB:', err);
            }
        };

        if (vncCtrlAltDelBtn) {
            vncCtrlAltDelBtn.onclick = () => {
                if (rfb) {
                    try { rfb.sendCtrlAltDel(); } catch (err) {}
                }
            };
        }

        if (vncScaleBtn) {
            vncScaleBtn.onclick = () => {
                isScaled = !isScaled;
                if (rfb) {
                    try { rfb.scaleViewport = isScaled; } catch (err) {}
                }
                logStatusMessage(`Escala VNC: ${isScaled ? 'Ajustada à janela' : 'Tamanho Original'}`, 'info');
            };
        }

        if (vncFullscreenBtn) {
            vncFullscreenBtn.onclick = () => {
                const modalContent = vncModal.querySelector('.vnc-desktop-content');
                if (modalContent) modalContent.classList.toggle('fullscreen');
            };
        }

        if (vncCloseBtn) {
            vncCloseBtn.addEventListener('click', closeVNC);
        }

        vncModal.addEventListener('click', (e) => {
            if (e.target === vncModal || e.target.closest('#vnc-close-btn')) {
                closeVNC(e);
            }
        });
        const openGridBtn = document.getElementById('open-vnc-grid-btn');
        if (openGridBtn) {
            openGridBtn.onclick = () => {
                if (typeof window.openVNCGrid === 'function') {
                    window.openVNCGrid();
                }
            };
        }
    }

    setupWebSSHTerminal();
    setupWebVNC();

    // Event listeners para o Modal de Progresso em Lote
    const closeBatchModalBtn = document.getElementById('close-batch-modal-btn');
    const batchCloseModalBtn = document.getElementById('batch-close-modal-btn');
    const batchRetryFailedBtn = document.getElementById('batch-retry-failed-btn');
    const batchModal = document.getElementById('batch-progress-modal');

    if (closeBatchModalBtn && batchModal) closeBatchModalBtn.onclick = () => batchModal.classList.add('hidden');
    if (batchCloseModalBtn && batchModal) batchCloseModalBtn.onclick = () => batchModal.classList.add('hidden');

    if (batchRetryFailedBtn) {
        batchRetryFailedBtn.onclick = async () => {
            if (currentBatchState.failedIps.length > 0 && currentBatchState.payload) {
                const retryIps = [...currentBatchState.failedIps];
                const payload = currentBatchState.payload;
                const actionText = currentBatchState.actionText;
                logStatusMessage(`Re-tentando ação "${actionText}" em ${retryIps.length} máquina(s)...`, 'info');
                
                const submitFormBtn = document.getElementById('submit-btn');
                if (submitFormBtn) {
                    submitFormBtn.disabled = true;
                    submitFormBtn.classList.add('processing');
                }
                try {
                    // Executa a ação do lote com os IPs que falharam
                    const passwordGroup = document.getElementById('password');
                    const pwd = passwordGroup ? passwordGroup.value : (sessionPassword || '');
                    const refreshedPayload = await buildActionPayload(payload.action, pwd);
                    await processBatch(refreshedPayload || payload, actionText, retryIps);
                } finally {
                    if (submitFormBtn) {
                        submitFormBtn.disabled = false;
                        submitFormBtn.classList.remove('processing');
                    }
                }
            }
        };
    }

    // --- Lógica do Modal de Alertas de Fim de Aula (Horário Escolar) ---
    const openScheduleModalBtn = document.getElementById('open-schedule-alert-btn');
    const scheduleModal = document.getElementById('schedule-alert-modal');
    const closeScheduleModalBtn = document.getElementById('close-schedule-modal-btn');
    const cancelScheduleModalBtn = document.getElementById('cancel-schedule-modal-btn');
    const saveScheduleConfigBtn = document.getElementById('save-schedule-config-btn');
    const syncScheduleWebBtn = document.getElementById('sync-schedule-web-btn');
    const testScheduleAlertBtn = document.getElementById('test-schedule-alert-btn');
    const testScheduleEndBtn = document.getElementById('test-schedule-end-btn');
    const testScheduleUnlockBtn = document.getElementById('test-schedule-unlock-btn');

    const scheduleEnabledToggle = document.getElementById('schedule-enabled-toggle');
    const scheduleEnableAllBtn = document.getElementById('schedule-enable-all-btn');
    const scheduleDisableAllBtn = document.getElementById('schedule-disable-all-btn');
    const scheduleMinutesSelect = document.getElementById('schedule-minutes-select');
    const scheduleMessageInput = document.getElementById('schedule-message-input');
    const scheduleAutoCleanToggle = document.getElementById('schedule-auto-clean-toggle');
    const scheduleAutoLockToggle = document.getElementById('schedule-auto-lock-toggle');
    const scheduleAutoUnlockToggle = document.getElementById('schedule-auto-unlock-toggle');
    const scheduleUnlockMinutesSelect = document.getElementById('schedule-unlock-minutes-select');
    const scheduleLockMessageInput = document.getElementById('schedule-lock-message-input');

    const scheduleStatusBadge = document.getElementById('schedule-status-badge');
    const scheduleUpcomingList = document.getElementById('schedule-upcoming-list');

    let scheduleCountdownInterval = null;
    let upcomingAlertsData = [];

    function updateNextAlertCountdown() {
        const titleEl = document.getElementById('schedule-next-title');
        const timerEl = document.getElementById('schedule-next-timer');
        if (!titleEl || !timerEl) return;

        if (scheduleEnabledToggle && !scheduleEnabledToggle.checked) {
            titleEl.textContent = 'Alertas automáticos desativados.';
            timerEl.textContent = 'PAUSADO';
            timerEl.style.color = '#ef4444';
            return;
        }

        if (!upcomingAlertsData || upcomingAlertsData.length === 0) {
            titleEl.textContent = 'Nenhum horário cadastrado para hoje.';
            timerEl.textContent = '--:--';
            return;
        }

        const now = new Date();
        const nowMinutes = now.getHours() * 60 + now.getMinutes();
        const nowSeconds = now.getSeconds();

        // Filtra alertas do dia que ainda não dispararam e são futuros (ignora recreios/intervalos sem alerta)
        const futureAlerts = upcomingAlertsData.filter(a => {
            if (a.fired_today) return false;
            if (a.type === 'recreio' || !a.alert_time || a.alert_time === '--:--') return false;
            const parts = a.alert_time.split(':').map(Number);
            if (isNaN(parts[0]) || isNaN(parts[1])) return false;
            const alertMin = parts[0] * 60 + parts[1];
            return alertMin >= nowMinutes;
        });

        if (futureAlerts.length === 0) {
            titleEl.textContent = 'Todos os alertas de hoje foram concluídos! 🎉';
            timerEl.textContent = '00:00';
            timerEl.style.color = '#10b981';
            return;
        }

        const next = futureAlerts[0];
        const parts = next.alert_time.split(':').map(Number);
        const targetSec = (parts[0] * 60 + parts[1]) * 60;
        const currentSec = nowMinutes * 60 + nowSeconds;
        const diffSec = targetSec - currentSec;

        if (diffSec <= 0) {
            titleEl.textContent = `${next.period_name} (Alerta às ${next.alert_time})`;
            timerEl.textContent = 'DISPARANDO...';
            timerEl.style.color = '#ef4444';
            return;
        }

        const m = Math.floor(diffSec / 60);
        const s = diffSec % 60;
        const formatted = `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;

        titleEl.textContent = `${next.period_name} (Alerta às ${next.alert_time}) — Término da Aula: ${next.class_end}`;
        timerEl.textContent = `em ${formatted}`;
        timerEl.style.color = '#fbbf24';

        const headerBadge = document.getElementById('header-schedule-badge');
        if (headerBadge) {
            if (scheduleEnabledToggle && !scheduleEnabledToggle.checked) {
                headerBadge.style.display = 'none';
            } else if (diffSec > 0) {
                headerBadge.textContent = `${next.alert_time} (${formatted})`;
                headerBadge.style.display = 'inline-block';
            } else {
                headerBadge.style.display = 'none';
            }
        }
    }

    let currentShiftFilter = 'all';

    const scheduleSchoolSelect = document.getElementById('schedule-school-select');
    const scheduleActiveSchoolBadge = document.getElementById('schedule-active-school-badge');
    const toggleEditSchedulePeriodsBtn = document.getElementById('toggle-edit-schedule-periods-btn');
    const schedulePeriodsEditorPanel = document.getElementById('schedule-periods-editor-panel');
    const editorSchoolTitle = document.getElementById('editor-school-title');
    const addSchedulePeriodBtn = document.getElementById('add-schedule-period-btn');
    const resetSchedulePeriodBtn = document.getElementById('reset-schedule-period-btn');
    const schedulePeriodsTableContainer = document.getElementById('schedule-periods-table-container');

    // Inputs Rápidos de Entrada e Recreios
    const quickEntM = document.getElementById('quick-ent-m');
    const quickRec1MStart = document.getElementById('quick-rec1-m-start');
    const quickRec1MEnd = document.getElementById('quick-rec1-m-end');
    const quickRec2MStart = document.getElementById('quick-rec2-m-start');
    const quickRec2MEnd = document.getElementById('quick-rec2-m-end');

    const quickEntT = document.getElementById('quick-ent-t');
    const quickRec1TStart = document.getElementById('quick-rec1-t-start');
    const quickRec1TEnd = document.getElementById('quick-rec1-t-end');
    const quickRec2TStart = document.getElementById('quick-rec2-t-start');
    const quickRec2TEnd = document.getElementById('quick-rec2-t-end');
    const scheduleRecreioMessageInput = document.getElementById('schedule-recreio-message-input');

    let scheduleSchoolsData = {};
    let currentSelectedSchool = 'escola_1';
    let currentPeriodsData = [];

    function updateActiveSchoolBadge() {
        if (!scheduleActiveSchoolBadge) return;
        const school = scheduleSchoolsData[currentSelectedSchool];
        const schoolName = school ? school.name : (currentSelectedSchool === 'escola_2' ? 'Escola 2 (EMEB Padre Benito)' : 'Escola 1 (EMEB Profª Anna Bonagura)');
        scheduleActiveSchoolBadge.textContent = schoolName;
        if (editorSchoolTitle) editorSchoolTitle.textContent = schoolName;
    }

    function populateQuickTimeInputs() {
        if (!currentPeriodsData) return;
        
        const entM = currentPeriodsData.find(p => (p.type === 'entrada' || (p.name && p.name.toLowerCase().includes('entrada'))) && p.shift === 'Manhã');
        const recsM = currentPeriodsData.filter(p => (p.type === 'recreio' || (p.name && p.name.toLowerCase().includes('recreio'))) && p.shift === 'Manhã');
        const entT = currentPeriodsData.find(p => (p.type === 'entrada' || (p.name && p.name.toLowerCase().includes('entrada'))) && p.shift === 'Tarde');
        const recsT = currentPeriodsData.filter(p => (p.type === 'recreio' || (p.name && p.name.toLowerCase().includes('recreio'))) && p.shift === 'Tarde');

        if (quickEntM && entM) quickEntM.value = entM.start || '';
        if (quickRec1MStart && recsM[0]) quickRec1MStart.value = recsM[0].start || '';
        if (quickRec1MEnd && recsM[0]) quickRec1MEnd.value = recsM[0].end || '';
        if (quickRec2MStart && recsM[1]) quickRec2MStart.value = recsM[1].start || '';
        if (quickRec2MEnd && recsM[1]) quickRec2MEnd.value = recsM[1].end || '';

        if (quickEntT && entT) quickEntT.value = entT.start || '';
        if (quickRec1TStart && recsT[0]) quickRec1TStart.value = recsT[0].start || '';
        if (quickRec1TEnd && recsT[0]) quickRec1TEnd.value = recsT[0].end || '';
        if (quickRec2TStart && recsT[1]) quickRec2TStart.value = recsT[1].start || '';
        if (quickRec2TEnd && recsT[1]) quickRec2TEnd.value = recsT[1].end || '';
    }

    function syncQuickInputToPeriods(periodType, shift, indexInShift, field, value) {
        if (!value) return;
        let matched = currentPeriodsData.filter(p => (p.type === periodType || (p.name && p.name.toLowerCase().includes(periodType))) && p.shift === shift);
        let target = matched[indexInShift];
        
        if (target) {
            target[field] = value;
            if (periodType === 'entrada') target.end = value;
        } else {
            const prefix = currentSelectedSchool === 'escola_2' ? 'e2' : 'e1';
            const sCode = shift === 'Manhã' ? 'm' : 't';
            const newId = `${prefix}_${periodType}_${sCode}_${Date.now()}`;
            const label = periodType === 'entrada' ? `Entrada (${shift})` : `${indexInShift + 1}º Recreio (${shift})`;
            const newP = {
                id: newId,
                name: label,
                type: periodType,
                shift: shift,
                start: field === 'start' ? value : '00:00',
                end: field === 'end' ? value : value
            };
            currentPeriodsData.push(newP);
        }

        if (schedulePeriodsEditorPanel && schedulePeriodsEditorPanel.style.display !== 'none') {
            renderSchedulePeriodsEditor();
        }
    }

    // Configurar listeners dos campos rápidos
    if (quickEntM) quickEntM.oninput = (e) => syncQuickInputToPeriods('entrada', 'Manhã', 0, 'start', e.target.value);
    if (quickRec1MStart) quickRec1MStart.oninput = (e) => syncQuickInputToPeriods('recreio', 'Manhã', 0, 'start', e.target.value);
    if (quickRec1MEnd) quickRec1MEnd.oninput = (e) => syncQuickInputToPeriods('recreio', 'Manhã', 0, 'end', e.target.value);
    if (quickRec2MStart) quickRec2MStart.oninput = (e) => syncQuickInputToPeriods('recreio', 'Manhã', 1, 'start', e.target.value);
    if (quickRec2MEnd) quickRec2MEnd.oninput = (e) => syncQuickInputToPeriods('recreio', 'Manhã', 1, 'end', e.target.value);

    if (quickEntT) quickEntT.oninput = (e) => syncQuickInputToPeriods('entrada', 'Tarde', 0, 'start', e.target.value);
    if (quickRec1TStart) quickRec1TStart.oninput = (e) => syncQuickInputToPeriods('recreio', 'Tarde', 0, 'start', e.target.value);
    if (quickRec1TEnd) quickRec1TEnd.oninput = (e) => syncQuickInputToPeriods('recreio', 'Tarde', 0, 'end', e.target.value);
    if (quickRec2TStart) quickRec2TStart.oninput = (e) => syncQuickInputToPeriods('recreio', 'Tarde', 1, 'start', e.target.value);
    if (quickRec2TEnd) quickRec2TEnd.oninput = (e) => syncQuickInputToPeriods('recreio', 'Tarde', 1, 'end', e.target.value);

    function renderSchedulePeriodsEditor() {
        if (!schedulePeriodsTableContainer) return;
        if (!currentPeriodsData || currentPeriodsData.length === 0) {
            schedulePeriodsTableContainer.innerHTML = '<p style="font-size:0.75rem; color:#94a3b8; text-align:center; padding:10px;">Nenhum horário cadastrado. Clique em "+ Adicionar Aula".</p>';
            return;
        }

        const filteredPeriods = currentShiftFilter === 'all'
            ? currentPeriodsData.map((p, idx) => ({ period: p, originalIdx: idx }))
            : currentPeriodsData.map((p, idx) => ({ period: p, originalIdx: idx })).filter(item => item.period.shift === currentShiftFilter);

        let html = `
            <table style="width:100%; min-width:440px; border-collapse:collapse; font-size:0.75rem; color:#cbd5e1;">
                <thead>
                    <tr style="border-bottom:1px solid #334155; color:#94a3b8; text-align:left;">
                        <th style="padding:4px 6px;">Nome / Evento</th>
                        <th style="padding:4px 6px; width:80px;">Tipo</th>
                        <th style="padding:4px 6px; width:75px;">Turno</th>
                        <th style="padding:4px 6px; width:65px;">Início</th>
                        <th style="padding:4px 6px; width:65px;">Fim</th>
                        <th style="padding:4px 6px; width:30px; text-align:center;"></th>
                    </tr>
                </thead>
                <tbody>
        `;

        filteredPeriods.forEach(({ period: p, originalIdx: idx }) => {
            const pType = p.type || (p.name && p.name.toLowerCase().includes('recreio') ? 'recreio' : (p.name && p.name.toLowerCase().includes('entrada') ? 'entrada' : 'aula'));
            const typeColor = pType === 'entrada' ? '#34d399' : (pType === 'recreio' ? '#fbbf24' : '#818cf8');
            html += `
                <tr style="border-bottom:1px solid rgba(255,255,255,0.05);" data-idx="${idx}">
                    <td style="padding:4px 6px;">
                        <input type="text" class="period-name-input" data-idx="${idx}" value="${p.name || ''}"
                            style="width:100%; background:#1e293b; border:1px solid #475569; color:#f8fafc; padding:3px 6px; border-radius:4px; font-size:0.75rem; box-sizing:border-box;">
                    </td>
                    <td style="padding:4px 6px;">
                        <select class="period-type-input" data-idx="${idx}"
                            style="width:100%; background:#1e293b; border:1px solid ${typeColor}; color:${typeColor}; font-weight:600; padding:3px 4px; border-radius:4px; font-size:0.72rem; box-sizing:border-box;">
                            <option value="aula" ${pType === 'aula' ? 'selected' : ''}>⏰ Aula</option>
                            <option value="recreio" ${pType === 'recreio' ? 'selected' : ''}>🍎 Recreio</option>
                            <option value="entrada" ${pType === 'entrada' ? 'selected' : ''}>🚪 Entrada</option>
                        </select>
                    </td>
                    <td style="padding:4px 6px;">
                        <select class="period-shift-input" data-idx="${idx}"
                            style="width:100%; background:#1e293b; border:1px solid #475569; color:#f8fafc; padding:3px 4px; border-radius:4px; font-size:0.72rem; box-sizing:border-box;">
                            <option value="Manhã" ${p.shift === 'Manhã' ? 'selected' : ''}>Manhã</option>
                            <option value="Tarde" ${p.shift === 'Tarde' ? 'selected' : ''}>Tarde</option>
                        </select>
                    </td>
                    <td style="padding:4px 6px;">
                        <input type="text" class="period-start-input" data-idx="${idx}" value="${p.start || ''}" placeholder="07:00"
                            style="width:100%; background:#1e293b; border:1px solid #475569; color:#f8fafc; padding:3px 4px; border-radius:4px; font-size:0.75rem; text-align:center; box-sizing:border-box;">
                    </td>
                    <td style="padding:4px 6px;">
                        <input type="text" class="period-end-input" data-idx="${idx}" value="${p.end || ''}" placeholder="07:50"
                            style="width:100%; background:#1e293b; border:1px solid #475569; color:#38bdf8; font-weight:700; padding:3px 4px; border-radius:4px; font-size:0.75rem; text-align:center; box-sizing:border-box;">
                    </td>
                    <td style="padding:4px 6px; text-align:center;">
                        <button type="button" class="delete-period-btn" data-idx="${idx}"
                            style="background:transparent; border:none; color:#ef4444; cursor:pointer; font-size:0.85rem; padding:2px;"
                            title="Remover este item">🗑️</button>
                    </td>
                </tr>
            `;
        });

        html += '</tbody></table>';
        schedulePeriodsTableContainer.innerHTML = html;

        // Conectar listeners dos campos do editor
        schedulePeriodsTableContainer.querySelectorAll('.period-name-input').forEach(input => {
            input.addEventListener('input', (e) => {
                const idx = parseInt(e.target.dataset.idx);
                if (currentPeriodsData[idx]) currentPeriodsData[idx].name = e.target.value;
                populateQuickTimeInputs();
            });
        });
        schedulePeriodsTableContainer.querySelectorAll('.period-type-input').forEach(input => {
            input.addEventListener('change', (e) => {
                const idx = parseInt(e.target.dataset.idx);
                if (currentPeriodsData[idx]) currentPeriodsData[idx].type = e.target.value;
                renderSchedulePeriodsEditor();
                populateQuickTimeInputs();
            });
        });
        schedulePeriodsTableContainer.querySelectorAll('.period-shift-input').forEach(input => {
            input.addEventListener('change', (e) => {
                const idx = parseInt(e.target.dataset.idx);
                if (currentPeriodsData[idx]) currentPeriodsData[idx].shift = e.target.value;
                populateQuickTimeInputs();
            });
        });
        schedulePeriodsTableContainer.querySelectorAll('.period-start-input').forEach(input => {
            input.addEventListener('input', (e) => {
                const idx = parseInt(e.target.dataset.idx);
                if (currentPeriodsData[idx]) currentPeriodsData[idx].start = e.target.value;
                populateQuickTimeInputs();
            });
        });
        schedulePeriodsTableContainer.querySelectorAll('.period-end-input').forEach(input => {
            input.addEventListener('input', (e) => {
                const idx = parseInt(e.target.dataset.idx);
                if (currentPeriodsData[idx]) currentPeriodsData[idx].end = e.target.value;
                populateQuickTimeInputs();
            });
        });
        schedulePeriodsTableContainer.querySelectorAll('.delete-period-btn').forEach(btn => {
            btn.onclick = (e) => {
                const idx = parseInt(e.currentTarget.dataset.idx);
                currentPeriodsData.splice(idx, 1);
                renderSchedulePeriodsEditor();
                populateQuickTimeInputs();
            };
        });
    }

    if (toggleEditSchedulePeriodsBtn && schedulePeriodsEditorPanel) {
        toggleEditSchedulePeriodsBtn.onclick = () => {
            const isHidden = schedulePeriodsEditorPanel.style.display === 'none' || !schedulePeriodsEditorPanel.style.display;
            schedulePeriodsEditorPanel.style.display = isHidden ? 'block' : 'none';
            toggleEditSchedulePeriodsBtn.style.background = isHidden ? '#4f46e5' : '#334155';
            toggleEditSchedulePeriodsBtn.style.color = isHidden ? '#ffffff' : '#cbd5e1';
            if (isHidden) {
                renderSchedulePeriodsEditor();
            }
        };
    }

    if (addSchedulePeriodBtn) {
        addSchedulePeriodBtn.onclick = () => {
            const count = currentPeriodsData.length + 1;
            const isAfternoon = count > 8;
            currentPeriodsData.push({
                id: `${currentSelectedSchool}_p${Date.now()}`,
                name: `${count}ª Aula (${isAfternoon ? 'Tarde' : 'Manhã'})`,
                type: 'aula',
                shift: isAfternoon ? 'Tarde' : 'Manhã',
                start: isAfternoon ? '13:00' : '08:00',
                end: isAfternoon ? '13:55' : '08:55'
            });
            renderSchedulePeriodsEditor();
            populateQuickTimeInputs();
        };
    }

    if (resetSchedulePeriodBtn) {
        resetSchedulePeriodBtn.onclick = () => {
            if (confirm(`Deseja restaurar a grade de horários padrão (com Entrada e Recreios) para ${scheduleActiveSchoolBadge ? scheduleActiveSchoolBadge.textContent : 'esta escola'}?`)) {
                if (currentSelectedSchool === 'escola_1') {
                    currentPeriodsData = [
                        {"id": "e1_ent_m", "name": "Entrada da Manhã", "type": "entrada", "shift": "Manhã", "start": "07:05", "end": "07:05"},
                        {"id": "e1_m1", "name": "1ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "07:05", "end": "08:00"},
                        {"id": "e1_m2", "name": "2ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "08:00", "end": "08:55"},
                        {"id": "e1_m3", "name": "3ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "08:55", "end": "09:50"},
                        {"id": "e1_rec1_m", "name": "1º Recreio (Manhã)", "type": "recreio", "shift": "Manhã", "start": "10:15", "end": "10:35"},
                        {"id": "e1_m4", "name": "4ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "09:50", "end": "10:45"},
                        {"id": "e1_rec2_m", "name": "2º Recreio (Manhã)", "type": "recreio", "shift": "Manhã", "start": "10:45", "end": "11:05"},
                        {"id": "e1_m5", "name": "5ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "11:05", "end": "12:00"},
                        {"id": "e1_ent_t", "name": "Entrada da Tarde", "type": "entrada", "shift": "Tarde", "start": "12:35", "end": "12:35"},
                        {"id": "e1_t1", "name": "1ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "12:35", "end": "13:30"},
                        {"id": "e1_t2", "name": "2ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "13:30", "end": "14:25"},
                        {"id": "e1_t3", "name": "3ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "14:25", "end": "15:20"},
                        {"id": "e1_rec1_t", "name": "1º Recreio (Tarde)", "type": "recreio", "shift": "Tarde", "start": "14:50", "end": "15:10"},
                        {"id": "e1_rec2_t", "name": "2º Recreio (Tarde)", "type": "recreio", "shift": "Tarde", "start": "15:20", "end": "15:40"},
                        {"id": "e1_t4", "name": "4ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "15:40", "end": "16:35"},
                        {"id": "e1_t5", "name": "5ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "16:35", "end": "17:30"}
                    ];
                } else {
                    currentPeriodsData = [
                        {"id": "e2_ent_m", "name": "Entrada da Manhã", "type": "entrada", "shift": "Manhã", "start": "07:00", "end": "07:00"},
                        {"id": "e2_m1", "name": "1ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "07:00", "end": "07:55"},
                        {"id": "e2_m2", "name": "2ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "07:55", "end": "08:50"},
                        {"id": "e2_m3", "name": "3ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "08:50", "end": "09:45"},
                        {"id": "e2_rec1_m", "name": "1º Recreio (Manhã)", "type": "recreio", "shift": "Manhã", "start": "09:45", "end": "10:05"},
                        {"id": "e2_rec2_m", "name": "2º Recreio (Manhã)", "type": "recreio", "shift": "Manhã", "start": "09:50", "end": "10:10"},
                        {"id": "e2_m4", "name": "4ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "10:10", "end": "11:05"},
                        {"id": "e2_m5", "name": "5ª Aula (Manhã)", "type": "aula", "shift": "Manhã", "start": "11:05", "end": "12:00"},
                        {"id": "e2_ent_t", "name": "Entrada da Tarde", "type": "entrada", "shift": "Tarde", "start": "12:30", "end": "12:30"},
                        {"id": "e2_t1", "name": "1ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "12:30", "end": "13:25"},
                        {"id": "e2_t2", "name": "2ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "13:25", "end": "14:20"},
                        {"id": "e2_t3", "name": "3ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "14:20", "end": "15:15"},
                        {"id": "e2_rec1_t", "name": "1º Recreio (Tarde)", "type": "recreio", "shift": "Tarde", "start": "15:15", "end": "15:35"},
                        {"id": "e2_rec2_t", "name": "2º Recreio (Tarde)", "type": "recreio", "shift": "Tarde", "start": "15:20", "end": "15:40"},
                        {"id": "e2_t4", "name": "4ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "15:40", "end": "16:35"},
                        {"id": "e2_t5", "name": "5ª Aula (Tarde)", "type": "aula", "shift": "Tarde", "start": "16:35", "end": "17:30"}
                    ];
                }
                renderSchedulePeriodsEditor();
                populateQuickTimeInputs();
                showToast('Grade restaurada com Entrada e Recreios padrão!', 'info');
            }
        };
    }

    if (scheduleSchoolSelect) {
        scheduleSchoolSelect.addEventListener('change', async () => {
            const selectedVal = scheduleSchoolSelect.value;
            currentSelectedSchool = selectedVal;
            updateActiveSchoolBadge();

            try {
                // Notifica backend para alternar escola e atualizar alertas instantaneamente
                const resp = await fetch('/api/schedule/config', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ selected_school: selectedVal })
                });
                const data = await resp.json();
                if (data.success) {
                    if (data.schools) scheduleSchoolsData = data.schools;
                    if (data.periods) currentPeriodsData = JSON.parse(JSON.stringify(data.periods));
                    populateQuickTimeInputs();
                    if (data.upcoming_alerts) {
                        upcomingAlertsData = data.upcoming_alerts;
                        renderUpcomingAlerts(data.upcoming_alerts);
                        startScheduleCountdownTimer();
                    }
                    if (schedulePeriodsEditorPanel && schedulePeriodsEditorPanel.style.display !== 'none') {
                        renderSchedulePeriodsEditor();
                    }
                    const schoolName = (data.schools && data.schools[selectedVal]) ? data.schools[selectedVal].name : selectedVal;
                    showToast(`Horários ativados: ${schoolName}`, 'info', 2500);
                }
            } catch (err) {
                console.error('[ScheduleUI] Erro ao alternar escola:', err);
                showToast('Erro ao alternar escola.', 'error');
            }
        });
    }

    function startScheduleCountdownTimer() {
        if (scheduleCountdownInterval) clearInterval(scheduleCountdownInterval);
        updateNextAlertCountdown();
        scheduleCountdownInterval = setInterval(updateNextAlertCountdown, 1000);
    }

    async function loadScheduleConfig() {
        try {
            const resp = await fetch('/api/schedule/config');
            const data = await resp.json();
            if (data.success) {
                if (scheduleEnabledToggle) scheduleEnabledToggle.checked = data.enabled;
                if (scheduleMinutesSelect) scheduleMinutesSelect.value = data.minutes_before || 5;
                if (scheduleMessageInput) scheduleMessageInput.value = data.custom_message || '';
                const schedulePlaySoundToggle = document.getElementById('schedule-play-sound-toggle');
                if (schedulePlaySoundToggle) schedulePlaySoundToggle.checked = data.play_sound !== false;
                
                if (scheduleAutoCleanToggle) scheduleAutoCleanToggle.checked = data.auto_clean_screen !== false;
                if (scheduleAutoLockToggle) scheduleAutoLockToggle.checked = data.auto_lock_screen !== false;
                if (scheduleAutoUnlockToggle) scheduleAutoUnlockToggle.checked = data.auto_unlock_screen !== false;
                if (scheduleUnlockMinutesSelect) scheduleUnlockMinutesSelect.value = data.auto_unlock_minutes || 2;

                const scheduleAutoWolToggle = document.getElementById('schedule-auto-wol-toggle');
                if (scheduleAutoWolToggle) scheduleAutoWolToggle.checked = data.auto_wol_enabled !== false;
                const scheduleAutoShutdownToggle = document.getElementById('schedule-auto-shutdown-toggle');
                if (scheduleAutoShutdownToggle) scheduleAutoShutdownToggle.checked = data.auto_shutdown_enabled !== false;

                if (scheduleLockMessageInput) scheduleLockMessageInput.value = data.lock_message || '';
                if (scheduleRecreioMessageInput) scheduleRecreioMessageInput.value = data.recreio_message || '';

                if (data.popup_theme) {
                    applyPopupTheme(data.popup_theme);
                }

                if (data.schools) scheduleSchoolsData = data.schools;
                if (data.selected_school) {
                    currentSelectedSchool = data.selected_school;
                    if (scheduleSchoolSelect) scheduleSchoolSelect.value = data.selected_school;
                }
                if (data.periods) {
                    currentPeriodsData = JSON.parse(JSON.stringify(data.periods));
                    if (typeof window.checkAutoResetOnClassStart === 'function') {
                        window.checkAutoResetOnClassStart();
                    }
                }
                updateActiveSchoolBadge();
                populateQuickTimeInputs();

                if (schedulePeriodsEditorPanel && schedulePeriodsEditorPanel.style.display !== 'none') {
                    renderSchedulePeriodsEditor();
                }

                if (scheduleStatusBadge) {
                    scheduleStatusBadge.innerHTML = data.enabled 
                        ? '🟢 Ativado' 
                        : '🔴 Pausado';
                    scheduleStatusBadge.style.color = data.enabled ? '#10b981' : '#ef4444';
                }

                const countdownBox = document.getElementById('schedule-next-countdown-box');
                if (countdownBox) {
                    countdownBox.style.opacity = data.enabled ? '1' : '0.6';
                }

                if (data.upcoming_alerts) {
                    upcomingAlertsData = data.upcoming_alerts;
                    if (scheduleUpcomingList) renderUpcomingAlerts(data.upcoming_alerts);
                    startScheduleCountdownTimer();
                }
            }
        } catch (e) {
            console.warn('[ScheduleUI] Erro ao carregar configs:', e);
        }
    }

    let currentPopupTheme = 'dark';

    function applyPopupTheme(theme) {
        currentPopupTheme = theme || 'dark';
        const mockupBox = document.getElementById('schedule-mockup-box');
        if (mockupBox) {
            mockupBox.classList.remove('theme-dark', 'theme-blue', 'theme-yellow', 'theme-green');
            mockupBox.classList.add(`theme-${currentPopupTheme}`);
        }
        const previewCard = document.getElementById('popup-preview-card');
        if (previewCard) {
            previewCard.classList.remove('theme-dark', 'theme-blue', 'theme-yellow', 'theme-green');
            previewCard.classList.add(`theme-${currentPopupTheme}`);
        }
        document.querySelectorAll('.schedule-theme-pill').forEach(pill => {
            const isMatch = pill.getAttribute('data-popup-theme') === currentPopupTheme;
            pill.classList.toggle('active', isMatch);
            pill.style.borderColor = isMatch ? '#38bdf8' : '#334155';
            pill.style.color = isMatch ? '#38bdf8' : '#94a3b8';
            pill.style.fontWeight = isMatch ? '700' : '600';
        });
    }

    document.querySelectorAll('.schedule-theme-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            const selectedTheme = pill.getAttribute('data-popup-theme') || 'dark';
            applyPopupTheme(selectedTheme);
            autoSaveScheduleConfig(`Tema "${pill.textContent.trim()}" aplicado!`, true);
        });
    });

    function renderUpcomingAlerts(alerts) {
        if (!scheduleUpcomingList) return;
        const list = alerts || upcomingAlertsData;
        if (!list || list.length === 0) {
            scheduleUpcomingList.innerHTML = '<span style="font-size:0.78rem; color:#64748b;">Nenhum horário cadastrado.</span>';
            return;
        }

        const filtered = currentShiftFilter === 'all'
            ? list
            : list.filter(a => !a.shift || a.shift === currentShiftFilter);

        if (filtered.length === 0) {
            scheduleUpcomingList.innerHTML = `<span style="font-size:0.75rem; color:#64748b;">Nenhum horário para o turno da ${currentShiftFilter}.</span>`;
            return;
        }

        scheduleUpcomingList.innerHTML = filtered.map(a => {
            let bg, border, icon, badgeColor, timeDisplay;
            
            if (a.type === 'shift_wol') {
                icon = '⚡';
                bg = a.fired_today ? '#1e293b' : 'rgba(56,189,248,0.18)';
                border = a.fired_today ? '1px solid #334155' : '1px solid rgba(56,189,248,0.5)';
                badgeColor = '#38bdf8';
                timeDisplay = `<strong style="color:#38bdf8;">${a.alert_time}</strong> <span style="color:#7dd3fc; font-weight:600;">(Ligar Lab 5 min antes)</span>`;
            } else if (a.type === 'shift_shutdown') {
                icon = '🌙';
                bg = a.fired_today ? '#1e293b' : 'rgba(239,68,68,0.18)';
                border = a.fired_today ? '1px solid #334155' : '1px solid rgba(239,68,68,0.5)';
                badgeColor = '#f87171';
                timeDisplay = `<strong style="color:#f87171;">${a.alert_time}</strong> <span style="color:#fca5a5; font-weight:600;">(Desligar Turno)</span>`;
            } else if (a.type === 'entrada') {
                icon = '🚪';
                bg = a.fired_today ? '#1e293b' : 'rgba(16,185,129,0.15)';
                border = a.fired_today ? '1px solid #334155' : '1px solid rgba(16,185,129,0.5)';
                badgeColor = '#34d399';
                timeDisplay = `<strong style="color:#34d399;">${a.alert_time}</strong> <span style="color:#cbd5e1;">(Entrada)</span>`;
            } else if (a.type === 'recreio') {
                icon = '🍎';
                bg = a.fired_today ? '#1e293b' : 'rgba(245,158,11,0.15)';
                border = a.fired_today ? '1px solid #334155' : '1px solid rgba(245,158,11,0.5)';
                badgeColor = '#fbbf24';
                timeDisplay = `<strong style="color:#fbbf24;">${a.class_start} às ${a.class_end}</strong> <span style="color:#fcd34d; font-size:0.7rem; font-weight:600;">(🍎 Recreio - Sem Alerta)</span>`;
            } else {
                icon = a.fired_today ? '✓' : (a.is_future ? '⏰' : '⏳');
                bg = a.fired_today ? '#334155' : (a.is_future ? 'rgba(99,102,241,0.2)' : '#1e293b');
                border = a.fired_today ? '1px solid #475569' : (a.is_future ? '1px solid rgba(99,102,241,0.5)' : '1px solid #334155');
                badgeColor = a.fired_today ? '#94a3b8' : (a.is_future ? '#38bdf8' : '#64748b');
                timeDisplay = `<strong style="color:#f8fafc;">${a.alert_time}</strong> <span style="color:#a5b4fc;">(Fim: ${a.class_end})</span>`;
            }

            return `
                <div style="background:${bg}; border:${border}; padding:4px 8px; border-radius:5px; font-size:0.74rem; display:inline-flex; align-items:center; gap:5px; box-sizing:border-box; max-width:100%;">
                    <span>${icon}</span>
                    <span>${timeDisplay}</span>
                    <span style="color:${badgeColor}; font-size:0.68rem; font-weight:700;">${a.shift}</span>
                    <span style="color:#94a3b8; font-size:0.66rem;">${a.period_name}</span>
                </div>
            `;
        }).join('');
    }

    function applyShiftFilter(filter) {
        currentShiftFilter = filter;
        const morningBlock = document.getElementById('quick-shift-morning-block');
        const afternoonBlock = document.getElementById('quick-shift-afternoon-block');
        const grid = document.getElementById('quick-shifts-grid');

        if (morningBlock && afternoonBlock && grid) {
            if (filter === 'Manhã') {
                morningBlock.style.display = 'flex';
                afternoonBlock.style.display = 'none';
                grid.style.gridTemplateColumns = '1fr';
            } else if (filter === 'Tarde') {
                morningBlock.style.display = 'none';
                afternoonBlock.style.display = 'flex';
                grid.style.gridTemplateColumns = '1fr';
            } else {
                morningBlock.style.display = 'flex';
                afternoonBlock.style.display = 'flex';
                grid.style.gridTemplateColumns = '1fr 1fr';
            }
        }

        renderUpcomingAlerts(upcomingAlertsData);
        if (schedulePeriodsEditorPanel && schedulePeriodsEditorPanel.style.display !== 'none') {
            renderSchedulePeriodsEditor();
        }
    }

    document.querySelectorAll('.schedule-shift-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            document.querySelectorAll('.schedule-shift-pill').forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            applyShiftFilter(pill.getAttribute('data-shift-filter') || 'all');
        });
    });

    // Configura evento de clique dos Chips de Frases Rápidas
    document.querySelectorAll('.schedule-preset-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            const msg = chip.getAttribute('data-msg');
            if (scheduleMessageInput && msg) {
                scheduleMessageInput.value = msg;
                showToast('Frase modelo aplicada!', 'info', 2000);
            }
        });
    });

    async function autoSaveScheduleConfig(customToastMsg = null, isSuccessToast = true) {
        try {
            const schedulePlaySoundToggle = document.getElementById('schedule-play-sound-toggle');
            const scheduleAutoWolToggle = document.getElementById('schedule-auto-wol-toggle');
            const scheduleAutoShutdownToggle = document.getElementById('schedule-auto-shutdown-toggle');
            const payload = {
                enabled: scheduleEnabledToggle ? scheduleEnabledToggle.checked : true,
                minutes_before: scheduleMinutesSelect ? parseInt(scheduleMinutesSelect.value) : 5,
                custom_message: scheduleMessageInput ? scheduleMessageInput.value.trim() : '',
                popup_theme: currentPopupTheme || 'dark',
                play_sound: schedulePlaySoundToggle ? schedulePlaySoundToggle.checked : true,
                auto_clean_screen: scheduleAutoCleanToggle ? scheduleAutoCleanToggle.checked : true,
                auto_lock_screen: scheduleAutoLockToggle ? scheduleAutoLockToggle.checked : true,
                auto_unlock_screen: scheduleAutoUnlockToggle ? scheduleAutoUnlockToggle.checked : true,
                auto_unlock_minutes: scheduleUnlockMinutesSelect ? parseInt(scheduleUnlockMinutesSelect.value) : 2,
                auto_wol_enabled: scheduleAutoWolToggle ? scheduleAutoWolToggle.checked : true,
                auto_shutdown_enabled: scheduleAutoShutdownToggle ? scheduleAutoShutdownToggle.checked : true,
                lock_message: scheduleLockMessageInput ? scheduleLockMessageInput.value.trim() : '',
                recreio_message: scheduleRecreioMessageInput ? scheduleRecreioMessageInput.value.trim() : '',
                selected_school: currentSelectedSchool,
                periods: currentPeriodsData
            };
            const resp = await fetch('/api/schedule/config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            const res = await resp.json();
            if (res.success && customToastMsg && typeof showToast === 'function') {
                showToast(customToastMsg, isSuccessToast ? 'success' : 'warning', 2500);
            }
            return res;
        } catch (e) {
            console.error('[ScheduleConfig] Erro ao salvar automaticamente:', e);
            if (typeof showToast === 'function') {
                showToast('Erro ao salvar alterações de alerta.', 'error', 3000);
            }
        }
    }

    async function setAllScheduleAlerts(enabled) {
        if (scheduleEnabledToggle) scheduleEnabledToggle.checked = enabled;
        const schedulePlaySoundToggle = document.getElementById('schedule-play-sound-toggle');
        if (schedulePlaySoundToggle) schedulePlaySoundToggle.checked = enabled;
        if (scheduleAutoCleanToggle) scheduleAutoCleanToggle.checked = enabled;
        if (scheduleAutoLockToggle) scheduleAutoLockToggle.checked = enabled;
        if (scheduleAutoUnlockToggle) scheduleAutoUnlockToggle.checked = enabled;
        const scheduleAutoWolToggle = document.getElementById('schedule-auto-wol-toggle');
        if (scheduleAutoWolToggle) scheduleAutoWolToggle.checked = enabled;
        const scheduleAutoShutdownToggle = document.getElementById('schedule-auto-shutdown-toggle');
        if (scheduleAutoShutdownToggle) scheduleAutoShutdownToggle.checked = enabled;

        if (scheduleStatusBadge) {
            scheduleStatusBadge.innerHTML = enabled 
                ? '🟢 Ativado' 
                : '🔴 Pausado';
            scheduleStatusBadge.style.color = enabled ? '#10b981' : '#ef4444';
        }

        const countdownBox = document.getElementById('schedule-next-countdown-box');
        if (countdownBox) {
            countdownBox.style.opacity = enabled ? '1' : '0.6';
        }

        updateNextAlertCountdown();

        // Salva imediatamente no backend sem necessidade de apertar botão de salvar
        await autoSaveScheduleConfig(
            enabled ? '🔔 Todos os alertas foram ATIVADOS e salvos!' : '🔕 Todos os alertas foram DESATIVADOS e salvos!',
            enabled
        );
    }

    if (scheduleEnableAllBtn) {
        scheduleEnableAllBtn.onclick = () => setAllScheduleAlerts(true);
    }
    if (scheduleDisableAllBtn) {
        scheduleDisableAllBtn.onclick = () => setAllScheduleAlerts(false);
    }

    if (scheduleEnabledToggle) {
        scheduleEnabledToggle.addEventListener('change', async () => {
            const isEnabled = scheduleEnabledToggle.checked;
            if (scheduleStatusBadge) {
                scheduleStatusBadge.innerHTML = isEnabled 
                    ? '🟢 Ativado' 
                    : '🔴 Pausado';
                scheduleStatusBadge.style.color = isEnabled ? '#10b981' : '#ef4444';
            }
            const countdownBox = document.getElementById('schedule-next-countdown-box');
            if (countdownBox) {
                countdownBox.style.opacity = isEnabled ? '1' : '0.6';
            }
            updateNextAlertCountdown();

            // Salva imediatamente no backend
            await autoSaveScheduleConfig(
                isEnabled ? '🟢 Disparo de alertas ATIVADO e salvo!' : '🔴 Disparo de alertas DESATIVADO e salvo!',
                isEnabled
            );
        });
    }

    // Auto-salvar ao alternar opções individuais de alerta ou seletores
    [
        'schedule-play-sound-toggle',
        'schedule-auto-clean-toggle',
        'schedule-auto-lock-toggle',
        'schedule-auto-unlock-toggle',
        'schedule-auto-wol-toggle',
        'schedule-auto-shutdown-toggle',
        'schedule-minutes-select',
        'schedule-unlock-minutes-select'
    ].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('change', () => {
                autoSaveScheduleConfig();
            });
        }
    });

    // Alternância de Abas no Modal de Alertas (Horário Escolar)
    function switchScheduleTab(targetTabId) {
        const tabBtns = document.querySelectorAll('.schedule-tab-btn');
        tabBtns.forEach(b => {
            const isMatch = b.dataset.tab === targetTabId;
            b.classList.toggle('active', isMatch);
            if (isMatch) {
                b.style.setProperty('background', 'linear-gradient(135deg, #4f46e5 0%, #3b82f6 100%)', 'important');
                b.style.setProperty('color', '#ffffff', 'important');
                b.style.setProperty('border-color', 'rgba(99, 102, 241, 0.6)', 'important');
                b.style.setProperty('box-shadow', '0 2px 10px rgba(79, 70, 229, 0.4)', 'important');
                b.style.setProperty('font-weight', '700', 'important');
            } else {
                b.style.setProperty('background', 'transparent', 'important');
                b.style.setProperty('color', '#94a3b8', 'important');
                b.style.setProperty('border-color', 'transparent', 'important');
                b.style.setProperty('box-shadow', 'none', 'important');
                b.style.setProperty('font-weight', '600', 'important');
            }
        });

        document.querySelectorAll('.schedule-tab-content').forEach(content => {
            content.classList.toggle('hidden', content.id !== targetTabId);
        });
    }

    const scheduleTabBtns = document.querySelectorAll('.schedule-tab-btn');
    scheduleTabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTabId = btn.dataset.tab;
            if (targetTabId) switchScheduleTab(targetTabId);
        });
    });

    if (openScheduleModalBtn && scheduleModal) {
        openScheduleModalBtn.onclick = () => {
            scheduleModal.classList.remove('hidden');
            switchScheduleTab('schedule-tab-alerts');
            loadScheduleConfig();
        };
    }

    if (closeScheduleModalBtn && scheduleModal) {
        closeScheduleModalBtn.onclick = () => {
            if (scheduleCountdownInterval) clearInterval(scheduleCountdownInterval);
            scheduleModal.classList.add('hidden');
        };
    }
    if (cancelScheduleModalBtn && scheduleModal) {
        cancelScheduleModalBtn.onclick = () => {
            if (scheduleCountdownInterval) clearInterval(scheduleCountdownInterval);
            scheduleModal.classList.add('hidden');
        };
    }

    if (saveScheduleConfigBtn) {
        saveScheduleConfigBtn.onclick = async () => {
            saveScheduleConfigBtn.disabled = true;
            saveScheduleConfigBtn.innerText = 'Salvando...';
            try {
                const schedulePlaySoundToggle = document.getElementById('schedule-play-sound-toggle');
                const scheduleAutoWolToggle = document.getElementById('schedule-auto-wol-toggle');
                const scheduleAutoShutdownToggle = document.getElementById('schedule-auto-shutdown-toggle');
                const payload = {
                    enabled: scheduleEnabledToggle ? scheduleEnabledToggle.checked : true,
                    minutes_before: scheduleMinutesSelect ? parseInt(scheduleMinutesSelect.value) : 5,
                    custom_message: scheduleMessageInput ? scheduleMessageInput.value.trim() : '',
                    play_sound: schedulePlaySoundToggle ? schedulePlaySoundToggle.checked : true,
                    auto_clean_screen: scheduleAutoCleanToggle ? scheduleAutoCleanToggle.checked : true,
                    auto_lock_screen: scheduleAutoLockToggle ? scheduleAutoLockToggle.checked : true,
                    auto_unlock_screen: scheduleAutoUnlockToggle ? scheduleAutoUnlockToggle.checked : true,
                    auto_unlock_minutes: scheduleUnlockMinutesSelect ? parseInt(scheduleUnlockMinutesSelect.value) : 2,
                    auto_wol_enabled: scheduleAutoWolToggle ? scheduleAutoWolToggle.checked : true,
                    auto_shutdown_enabled: scheduleAutoShutdownToggle ? scheduleAutoShutdownToggle.checked : true,
                    lock_message: scheduleLockMessageInput ? scheduleLockMessageInput.value.trim() : '',
                    recreio_message: scheduleRecreioMessageInput ? scheduleRecreioMessageInput.value.trim() : '',
                    selected_school: currentSelectedSchool,
                    periods: currentPeriodsData
                };
                const resp = await fetch('/api/schedule/config', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                const res = await resp.json();
                if (res.success) {
                    showToast('Configurações de Alertas, Turnos e Horários Salvas!', 'success');
                    if (scheduleModal) scheduleModal.classList.add('hidden');
                } else {
                    showToast('Erro ao salvar: ' + (res.message || 'Falha desconhecida'), 'error');
                }
            } catch (e) {
                showToast('Erro de rede ao salvar configurações.', 'error');
            } finally {
                saveScheduleConfigBtn.disabled = false;
                saveScheduleConfigBtn.innerText = 'Salvar Alterações';
            }
        };
    }

    // Botões de Teste dos Turnos (WoL e Desligamento)
    const testShiftWolBtn = document.getElementById('test-schedule-shift-wol-btn');
    if (testShiftWolBtn) {
        testShiftWolBtn.onclick = async () => {
            testShiftWolBtn.disabled = true;
            testShiftWolBtn.innerText = 'Enviando WoL...';
            try {
                const resp = await fetch('/api/schedule/test-shift-wol', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ shift: 'Manhã' })
                });
                const res = await resp.json();
                if (res.success) {
                    showToast('⚡ Sinal Wake-on-LAN enviado para todas as máquinas do laboratório!', 'success', 4000);
                } else {
                    showToast('Falha no teste de WoL: ' + (res.message || 'Erro'), 'error');
                }
            } catch (e) {
                showToast('Erro de comunicação no teste de WoL.', 'error');
            } finally {
                testShiftWolBtn.disabled = false;
                testShiftWolBtn.innerText = '⚡ Testar WoL (Ligar Agora)';
            }
        };
    }

    const testShiftShutdownBtn = document.getElementById('test-schedule-shift-shutdown-btn');
    if (testShiftShutdownBtn) {
        testShiftShutdownBtn.onclick = async () => {
            if (!confirm('Tem certeza que deseja enviar o sinal de desligamento para os computadores do laboratório agora?')) return;
            testShiftShutdownBtn.disabled = true;
            testShiftShutdownBtn.innerText = 'Desligando...';
            try {
                const resp = await fetch('/api/schedule/test-shift-shutdown', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ shift: 'Manhã' })
                });
                const res = await resp.json();
                if (res.success) {
                    showToast(`🌙 Sinal de desligamento enviado para ${res.count || 0} computadores!`, 'success', 5000);
                } else {
                    showToast('Falha no desligamento: ' + (res.message || 'Erro'), 'error');
                }
            } catch (e) {
                showToast('Erro ao disparar desligamento.', 'error');
            } finally {
                testShiftShutdownBtn.disabled = false;
                testShiftShutdownBtn.innerText = '🌙 Testar Desligar Turno';
            }
        };
    }

    if (syncScheduleWebBtn) {
        syncScheduleWebBtn.onclick = async () => {
            syncScheduleWebBtn.disabled = true;
            syncScheduleWebBtn.innerText = 'Sincronizando...';
            try {
                const resp = await fetch('/api/schedule/sync', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ school_id: currentSelectedSchool })
                });
                const res = await resp.json();
                if (res.success) {
                    showToast(`Sincronizados ${res.count} horários da web com sucesso!`, 'success');
                    loadScheduleConfig();
                } else {
                    showToast('Aviso: ' + (res.message || 'Falha na sincronização'), 'warning');
                }
            } catch (e) {
                showToast('Erro ao conectar com a web.', 'error');
            } finally {
                syncScheduleWebBtn.disabled = false;
                syncScheduleWebBtn.innerText = '🔄 Sincronizar com Web';
            }
        };
    }

    // --- Lógica de Pré-visualização do Pop-up da Tela do Aluno (Delegação Global) ---
    document.addEventListener('click', (e) => {
        const previewBtn = e.target.closest('#preview-schedule-popup-btn');
        if (previewBtn) {
            e.preventDefault();
            e.stopPropagation();

            const modal = document.getElementById('popup-preview-modal');
            const textBody = document.getElementById('popup-preview-text-body');
            const msgInput = document.getElementById('schedule-message-input');
            const minsSelect = document.getElementById('schedule-minutes-select');

            if (modal && textBody) {
                const rawMsg = msgInput ? msgInput.value.trim() : '';
                const mins = minsSelect ? minsSelect.value : '5';
                
                let formatted = rawMsg || "📢 ATENÇÃO: Faltam {minutos} minutos para encerrar a aula! Por favor, salvem seus arquivos e organizem os computadores.";
                formatted = formatted.replace(/{minutos}/g, mins)
                                     .replace(/{minuto}/g, mins)
                                     .replace(/{min}/g, mins)
                                     .replace(/{minutes}/g, mins);
                
                textBody.innerText = formatted;
                applyPopupTheme(currentPopupTheme);
                modal.classList.remove('hidden');
            }
        }

        const closeBtn = e.target.closest('#close-popup-preview-btn, #cancel-popup-preview-modal-btn, #popup-preview-mock-ok-btn');
        if (closeBtn) {
            e.preventDefault();
            const modal = document.getElementById('popup-preview-modal');
            if (modal) modal.classList.add('hidden');
        }
    });

    // --- Atualização Automática das Caixas de Pré-visualização em Tempo Real ---
    function updateLivePreviews() {
        const scheduleMsgInput = document.getElementById('schedule-message-input');
        const scheduleMinsSelect = document.getElementById('schedule-minutes-select');
        const scheduleLiveText = document.getElementById('schedule-live-preview-text');
        
        if (scheduleLiveText) {
            const rawMsg = scheduleMsgInput ? scheduleMsgInput.value.trim() : '';
            const mins = scheduleMinsSelect ? scheduleMinsSelect.value : '5';
            let formatted = rawMsg || "📢 ATENÇÃO: Faltam {minutos} minutos para encerrar a aula! Por favor, salvem seus arquivos e organizem os computadores.";
            formatted = formatted.replace(/{minutos}/g, mins)
                                 .replace(/{minuto}/g, mins)
                                 .replace(/{min}/g, mins)
                                 .replace(/{minutes}/g, mins);
            scheduleLiveText.innerText = formatted;
        }

        const powerMsgInput = document.getElementById('power-schedule-msg-input');
        const powerLiveText = document.getElementById('power-schedule-live-preview-text');
        if (powerLiveText && powerMsgInput) {
            powerLiveText.innerText = powerMsgInput.value.trim() || 'O computador será desligado em instantes pelo administrador.';
        }
    }

    document.addEventListener('input', updateLivePreviews);
    document.addEventListener('change', updateLivePreviews);
    setTimeout(updateLivePreviews, 500);

    if (testScheduleAlertBtn) {
        testScheduleAlertBtn.onclick = async () => {
            const isCurrentlyAlerting = testScheduleAlertBtn.dataset.alerting === 'true';
            const checkedIps = Array.from(document.querySelectorAll('input[name="ip"]:checked')).map(cb => cb.value);

            testScheduleAlertBtn.disabled = true;

            if (!isCurrentlyAlerting) {
                // CLIQUE 1: Disparar Pop-up de Aviso
                testScheduleAlertBtn.innerText = 'Enviando...';
                try {
                    const msg = scheduleMessageInput ? scheduleMessageInput.value : '';
                    const resp = await fetch('/api/schedule/test', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ ips: checkedIps, message: msg })
                    });
                    const res = await resp.json();
                    if (res.success) {
                        showToast('📢 Pop-up de aviso enviado! Clique novamente no botão verde para fechar o aviso.', 'info', 7000);
                        testScheduleAlertBtn.dataset.alerting = 'true';
                        testScheduleAlertBtn.style.background = 'linear-gradient(135deg, #059669, #10b981)';
                        testScheduleAlertBtn.style.boxShadow = '0 2px 6px rgba(16,185,129,0.3)';
                        testScheduleAlertBtn.innerText = '❌ Fechar Pop-up';
                    } else {
                        showToast('Falha no alerta de teste: ' + res.message, 'error');
                        testScheduleAlertBtn.innerText = '📢 Pop-up';
                    }
                } catch (e) {
                    showToast('Erro de comunicação ao disparar teste.', 'error');
                    testScheduleAlertBtn.innerText = '📢 Pop-up';
                } finally {
                    testScheduleAlertBtn.disabled = false;
                }
            } else {
                // CLIQUE 2: Fechar Pop-up de Aviso
                testScheduleAlertBtn.innerText = 'Fechando...';
                try {
                    const resp = await fetch('/api/schedule/test-close-alert', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ ips: checkedIps })
                    });
                    const res = await resp.json();
                    if (res.success) {
                        showToast('❌ Pop-up de aviso fechado com sucesso!', 'success');
                        testScheduleAlertBtn.dataset.alerting = 'false';
                        testScheduleAlertBtn.style.background = 'linear-gradient(135deg, #6366f1, #4f46e5)';
                        testScheduleAlertBtn.style.boxShadow = '0 2px 6px rgba(99,102,241,0.25)';
                        testScheduleAlertBtn.innerText = '📢 Pop-up';
                    } else {
                        showToast('Falha ao fechar pop-up de aviso: ' + res.message, 'error');
                        testScheduleAlertBtn.innerText = '❌ Fechar Pop-up';
                    }
                } catch (e) {
                    showToast('Erro de comunicação ao fechar pop-up.', 'error');
                    testScheduleAlertBtn.innerText = '❌ Fechar Pop-up';
                } finally {
                    testScheduleAlertBtn.disabled = false;
                }
            }
        };
    }

    if (testScheduleEndBtn) {
        testScheduleEndBtn.onclick = async () => {
            const isCurrentlyTesting = testScheduleEndBtn.dataset.testing === 'true';
            const checkedIps = Array.from(document.querySelectorAll('input[name="ip"]:checked')).map(cb => cb.value);

            testScheduleEndBtn.disabled = true;

            if (!isCurrentlyTesting) {
                // CLIQUE 1: Iniciar o Teste de Fim de Aula (Limpar + Bloquear)
                testScheduleEndBtn.innerText = 'Executando...';
                try {
                    const resp = await fetch('/api/schedule/test-end', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ ips: checkedIps })
                    });
                    const res = await resp.json();
                    if (res.success) {
                        showToast('🔒 Fim de aula acionado! Clique novamente no botão verde para encerrar o teste.', 'warning', 7000);
                        testScheduleEndBtn.dataset.testing = 'true';
                        testScheduleEndBtn.style.background = 'linear-gradient(135deg, #059669, #10b981)';
                        testScheduleEndBtn.style.boxShadow = '0 2px 6px rgba(16,185,129,0.3)';
                        testScheduleEndBtn.innerText = '🔓 Encerrar Teste';
                    } else {
                        showToast('Falha ao disparar teste de término: ' + res.message, 'error');
                        testScheduleEndBtn.innerText = '🔒 Testar Fim de Aula';
                    }
                } catch (e) {
                    showToast('Erro de comunicação ao disparar teste de término.', 'error');
                    testScheduleEndBtn.innerText = '🔒 Testar Fim de Aula';
                } finally {
                    testScheduleEndBtn.disabled = false;
                }
            } else {
                // CLIQUE 2: Encerrar o Teste de Fim de Aula (Desbloquear)
                testScheduleEndBtn.innerText = 'Desbloqueando...';
                try {
                    const resp = await fetch('/api/schedule/test-unlock', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ ips: checkedIps })
                    });
                    const res = await resp.json();
                    if (res.success) {
                        showToast('🔓 Teste encerrado com sucesso! Computadores desbloqueados.', 'success');
                        testScheduleEndBtn.dataset.testing = 'false';
                        testScheduleEndBtn.style.background = 'linear-gradient(135deg, #dc2626, #b91c1c)';
                        testScheduleEndBtn.style.boxShadow = '0 2px 6px rgba(220,38,38,0.3)';
                        testScheduleEndBtn.innerText = '🔒 Testar Fim de Aula';
                    } else {
                        showToast('Falha ao desbloquear computadores: ' + res.message, 'error');
                        testScheduleEndBtn.innerText = '🔓 Encerrar Teste';
                    }
                } catch (e) {
                    showToast('Erro de comunicação ao encerrar teste.', 'error');
                    testScheduleEndBtn.innerText = '🔓 Encerrar Teste';
                } finally {
                    testScheduleEndBtn.disabled = false;
                }
            }
        };
    }

    if (window.socket) {
        window.socket.on('class_end_warning_triggered', (data) => {
            showToast(`⏰ ALERTA DISPARADO (${data.timestamp}): "${data.message}"`, 'info', 10000);
        });
        window.socket.on('class_ended_actions_triggered', (data) => {
            showToast(`🏁 TÉRMINO DE AULA (${data.timestamp}): Executada Limpeza=${data.clean} e Bloqueio=${data.lock}`, 'warning', 10000);
        });
    }

    // --- Lógica do Modal de Gerenciamento de Energia (Linux Mint 22.1 Cinnamon) ---
    const openPowerModalBtn = document.getElementById('open-power-modal-btn');
    const powerModal = document.getElementById('power-management-modal');
    const closePowerModalBtn = document.getElementById('close-power-modal-btn');
    const cancelPowerModalBtn = document.getElementById('cancel-power-modal-btn');
    const savePowerConfigBtn = document.getElementById('save-power-config-btn');
    const powerSelectedTargetsLabel = document.getElementById('power-selected-targets-label');

    // Elementos da Aba 1 - Configurações GSettings
    const powerDisplaySleepSelect = document.getElementById('power-display-sleep-select');
    const powerSuspendTimeoutSelect = document.getElementById('power-suspend-timeout-select');
    const powerButtonActionSelect = document.getElementById('power-button-action-select');
    const powerLidCloseSelect = document.getElementById('power-lid-close-select');
    const powerLockOnSuspendToggle = document.getElementById('power-lock-on-suspend-toggle');
    const powerLockEnabledToggle = document.getElementById('power-lock-enabled-toggle');

    // Botões de Presets
    const powerPresetLab = document.getElementById('power-preset-lab');
    const powerPresetEco = document.getElementById('power-preset-eco');
    const powerPresetSecurity = document.getElementById('power-preset-security');

    // Elementos da Aba 2 - Ações Instantâneas
    const powerActionShutdownBtn = document.getElementById('power-action-shutdown-btn');
    const powerActionRebootBtn = document.getElementById('power-action-reboot-btn');
    const powerActionSuspendBtn = document.getElementById('power-action-suspend-btn');
    const powerActionLockBtn = document.getElementById('power-action-lock-btn');
    const powerActionLogoutBtn = document.getElementById('power-action-logout-btn');

    // Elementos da Aba - Proteção de Tela
    const powerScreensaverEnableBtn = document.getElementById('power-screensaver-enable-btn');
    const powerScreensaverDisableBtn = document.getElementById('power-screensaver-disable-btn');
    const powerScreensaverConfigBtn = document.getElementById('power-screensaver-config-btn');
    const screensaverDelaySelect = document.getElementById('screensaver-delay-select');
    const screensaverLockDelaySelect = document.getElementById('screensaver-lock-delay-select');
    const screensaverLockEnabledChk = document.getElementById('screensaver-lock-enabled-chk');
    const screensaverIdleActivationChk = document.getElementById('screensaver-idle-activation-chk');

    // Elementos da Aba 4 - Agendamento
    const powerScheduleMinutesInput = document.getElementById('power-schedule-minutes-input');
    const powerScheduleMsgInput = document.getElementById('power-schedule-msg-input');
    const powerScheduleApplyBtn = document.getElementById('power-schedule-apply-btn');
    const powerScheduleCancelBtn = document.getElementById('power-schedule-cancel-btn');

    // Função de atualização das metas selecionadas
    function updatePowerTargetsLabel() {
        if (!powerSelectedTargetsLabel) return;
        const checkedIps = Array.from(document.querySelectorAll('input[name="ip"]:checked')).map(cb => cb.value);
        if (checkedIps.length > 0) {
            powerSelectedTargetsLabel.innerHTML = `🎯 <b>Alvo:</b> ${checkedIps.length} máquina(s) selecionada(s)`;
            powerSelectedTargetsLabel.style.color = '#38bdf8';
        } else {
            powerSelectedTargetsLabel.innerHTML = `🌐 <b>Alvo:</b> Todas as máquinas online da rede`;
            powerSelectedTargetsLabel.style.color = '#fbbf24';
        }
    }

    if (openPowerModalBtn && powerModal) {
        openPowerModalBtn.onclick = () => {
            updatePowerTargetsLabel();
            powerModal.classList.remove('hidden');
        };
    }

    if (closePowerModalBtn && powerModal) closePowerModalBtn.onclick = () => powerModal.classList.add('hidden');
    if (cancelPowerModalBtn && powerModal) cancelPowerModalBtn.onclick = () => powerModal.classList.add('hidden');

    // Alternância de Abas no Modal de Energia
    const powerTabBtns = document.querySelectorAll('.power-tab-btn');
    powerTabBtns.forEach(btn => {
        btn.onclick = () => {
            powerTabBtns.forEach(b => {
                b.classList.remove('active');
                b.style.background = '#0f172a';
                b.style.color = '#94a3b8';
                b.style.borderColor = 'transparent';
            });
            btn.classList.add('active');
            btn.style.background = '#1e293b';
            btn.style.color = '#fbbf24';
            btn.style.borderColor = 'rgba(251,191,36,0.4)';

            const targetTabId = btn.dataset.tab;
            document.querySelectorAll('.power-tab-content').forEach(tab => tab.classList.add('hidden'));
            const activeTab = document.getElementById(targetTabId);
            if (activeTab) activeTab.classList.remove('hidden');
        };
    });

    // Presets Rápidos
    if (powerPresetLab) {
        powerPresetLab.onclick = () => {
            if (powerDisplaySleepSelect) powerDisplaySleepSelect.value = '0';
            if (powerSuspendTimeoutSelect) powerSuspendTimeoutSelect.value = '0';
            if (powerButtonActionSelect) powerButtonActionSelect.value = 'interactive';
            if (powerLidCloseSelect) powerLidCloseSelect.value = 'nothing';
            if (powerLockOnSuspendToggle) powerLockOnSuspendToggle.checked = false;
            if (powerLockEnabledToggle) powerLockEnabledToggle.checked = false;
            showToast('⚡ Perfil "Modo Laboratório" aplicado aos campos.', 'info');
        };
    }

    if (powerPresetEco) {
        powerPresetEco.onclick = () => {
            if (powerDisplaySleepSelect) powerDisplaySleepSelect.value = '10';
            if (powerSuspendTimeoutSelect) powerSuspendTimeoutSelect.value = '30';
            if (powerButtonActionSelect) powerButtonActionSelect.value = 'suspend';
            if (powerLidCloseSelect) powerLidCloseSelect.value = 'suspend';
            if (powerLockOnSuspendToggle) powerLockOnSuspendToggle.checked = true;
            if (powerLockEnabledToggle) powerLockEnabledToggle.checked = true;
            showToast('🍃 Perfil "Modo Econômico" aplicado aos campos.', 'info');
        };
    }

    if (powerPresetSecurity) {
        powerPresetSecurity.onclick = () => {
            if (powerDisplaySleepSelect) powerDisplaySleepSelect.value = '10';
            if (powerSuspendTimeoutSelect) powerSuspendTimeoutSelect.value = '15';
            if (powerButtonActionSelect) powerButtonActionSelect.value = 'interactive';
            if (powerLidCloseSelect) powerLidCloseSelect.value = 'suspend';
            if (powerLockOnSuspendToggle) powerLockOnSuspendToggle.checked = true;
            if (powerLockEnabledToggle) powerLockEnabledToggle.checked = true;
            showToast('🔐 Perfil "Modo Segurança" aplicado aos campos.', 'info');
        };
    }

    // Auxiliar para obter alvos e disparar ações via processBatch
    async function dispatchPowerAction(actionName, actionText, extraData = {}) {
        const checkedIps = Array.from(document.querySelectorAll('input[name="ip"]:checked')).map(cb => cb.value);
        const onlineIps = Array.from(document.querySelectorAll('.ip-item.status-online, .ip-item:not(.status-offline)')).map(el => el.dataset.ip).filter(Boolean);
        const targetIps = checkedIps.length > 0 ? checkedIps : onlineIps;

        if (!targetIps || targetIps.length === 0) {
            showToast('Nenhum computador online encontrado para executar a ação.', 'warning');
            return;
        }

        const pwdEl = document.getElementById('password');
        const pwd = pwdEl ? pwdEl.value : (sessionPassword || '');

        const payload = {
            action: actionName,
            password: pwd,
            target_ips: targetIps,
            ...extraData
        };

        if (powerModal) powerModal.classList.add('hidden');

        if (typeof processBatch === 'function') {
            await processBatch(payload, actionText, targetIps);
        } else {
            try {
                const resp = await fetch('/execute-action', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const res = await resp.json();
                if (res.success) {
                    showToast(`Ação "${actionText}" iniciada em ${targetIps.length} máquina(s).`, 'success');
                } else {
                    showToast(`Erro ao executar "${actionText}": ${res.message}`, 'error');
                }
            } catch (err) {
                showToast(`Falha de rede ao disparar "${actionText}".`, 'error');
            }
        }
    }

    // Salvar Configurações GSettings
    if (savePowerConfigBtn) {
        savePowerConfigBtn.onclick = async () => {
            const data = {
                display_sleep: parseInt(powerDisplaySleepSelect ? powerDisplaySleepSelect.value : '10', 10),
                suspend_timeout: parseInt(powerSuspendTimeoutSelect ? powerSuspendTimeoutSelect.value : '0', 10),
                power_button_action: powerButtonActionSelect ? powerButtonActionSelect.value : 'interactive',
                lid_close_action: powerLidCloseSelect ? powerLidCloseSelect.value : 'suspend',
                lock_on_suspend: powerLockOnSuspendToggle ? powerLockOnSuspendToggle.checked : true,
                lock_enabled: powerLockEnabledToggle ? powerLockEnabledToggle.checked : true
            };
            await dispatchPowerAction('configurar_energia_cinnamon', 'Configuração de Energia Cinnamon', data);
        };
    }

    // Ações Instantâneas
    if (powerActionShutdownBtn) {
        powerActionShutdownBtn.onclick = async () => {
            if (confirm('⚠️ Tem certeza que deseja DESLIGAR IMEDIATAMENTE os computadores selecionados?')) {
                await dispatchPowerAction('desligar_maquinas', 'Desligar Computadores');
            }
        };
    }

    if (powerActionRebootBtn) {
        powerActionRebootBtn.onclick = async () => {
            if (confirm('🔄 Tem certeza que deseja REINICIAR os computadores selecionados?')) {
                await dispatchPowerAction('reiniciar_maquinas', 'Reiniciar Computadores');
            }
        };
    }

    if (powerActionSuspendBtn) {
        powerActionSuspendBtn.onclick = async () => {
            await dispatchPowerAction('suspender_maquinas', 'Suspender Computadores (Sleep)');
        };
    }

    if (powerActionLockBtn) {
        powerActionLockBtn.onclick = async () => {
            await dispatchPowerAction('bloquear_tela_cinnamon', 'Bloquear Sessão de Usuário');
        };
    }

    if (powerActionLogoutBtn) {
        powerActionLogoutBtn.onclick = async () => {
            if (confirm('🚪 Deseja encerrar a sessão (logoff) dos usuários nas máquinas selecionadas?')) {
                await dispatchPowerAction('logout_cinnamon', 'Encerrar Sessão (Logoff)');
            }
        };
    }

    // Ações de Proteção de Tela
    if (powerScreensaverEnableBtn) {
        powerScreensaverEnableBtn.onclick = async () => {
            await dispatchPowerAction('ativar_protecao_tela', 'Ativar Proteção de Tela');
        };
    }

    if (powerScreensaverDisableBtn) {
        powerScreensaverDisableBtn.onclick = async () => {
            await dispatchPowerAction('desativar_protecao_tela', 'Desativar Proteção de Tela');
        };
    }

    if (powerScreensaverConfigBtn) {
        powerScreensaverConfigBtn.onclick = async () => {
            const idleDelay = parseInt(screensaverDelaySelect ? screensaverDelaySelect.value : '300', 10);
            const lockDelay = parseInt(screensaverLockDelaySelect ? screensaverLockDelaySelect.value : '0', 10);
            const lockEnabled = screensaverLockEnabledChk ? screensaverLockEnabledChk.checked : true;
            const idleActivation = screensaverIdleActivationChk ? screensaverIdleActivationChk.checked : true;
            await dispatchPowerAction('configurar_protecao_tela', 'Configurar Proteção de Tela', {
                idle_delay: idleDelay,
                lock_delay: lockDelay,
                lock_enabled: lockEnabled,
                idle_activation_enabled: idleActivation
            });
        };
    }

    // Agendamento por Timer
    if (powerScheduleApplyBtn) {
        powerScheduleApplyBtn.onclick = async () => {
            const mins = parseInt(powerScheduleMinutesInput ? powerScheduleMinutesInput.value : '15', 10);
            const msg = powerScheduleMsgInput ? powerScheduleMsgInput.value : 'O computador será desligado em instantes.';
            if (isNaN(mins) || mins < 1) {
                showToast('Por favor, informe um tempo válido de pelo menos 1 minuto.', 'warning');
                return;
            }
            await dispatchPowerAction('agendar_desligamento', `Agendar Desligamento em ${mins}m`, { minutes: mins, message: msg });
        };
    }

    if (powerScheduleCancelBtn) {
        powerScheduleCancelBtn.onclick = async () => {
            await dispatchPowerAction('cancelar_desligamento_agendado', 'Cancelar Desligamento Agendado');
        };
    }

    // ─── Menu de Contexto do Card de IP ──────────────────────────────────────

    // ─── Menu de Contexto do Card de IP ──────────────────────────────────────

    function _ctxHide() {
        const m = document.getElementById('ip-card-context-menu');
        if (!m) return;
        m.classList.add('ip-context-menu--hidden');
        m.classList.add('hidden');
        m.style.setProperty('display', 'none', 'important');
    }

    function _ctxShow(x, y) {
        const m = document.getElementById('ip-card-context-menu');
        if (!m) return;

        m.classList.remove('ip-context-menu--hidden');
        m.classList.remove('hidden');
        m.style.setProperty('display', 'block', 'important');
        m.style.setProperty('visibility', 'visible', 'important');
        m.style.setProperty('opacity', '1', 'important');
        m.style.setProperty('z-index', '2147483647', 'important');

        const mw = m.offsetWidth || 260;
        const mh = m.offsetHeight || 380;
        const posX = typeof x === 'number' && !isNaN(x) && x > 0 ? x : (window.innerWidth / 2);
        const posY = typeof y === 'number' && !isNaN(y) && y > 0 ? y : (window.innerHeight / 2);

        const safeX = Math.min(posX, window.innerWidth  - mw - 12);
        const safeY = Math.min(posY, window.innerHeight - mh - 12);

        m.style.setProperty('left', `${Math.max(12, safeX)}px`, 'important');
        m.style.setProperty('top', `${Math.max(12, safeY)}px`, 'important');
        m.dataset.openedAt = String(Date.now());
    }

    function showIpCardContextMenu(e, cardIpValue, baseIp, targetUser, computerName) {
        const menu = document.getElementById('ip-card-context-menu');
        if (!menu) return;

        // Atualiza o cabeçalho do menu
        const titleEl   = document.getElementById('ip-ctx-title');
        const badgeIpEl = document.getElementById('ip-ctx-badge-ip');
        const dotEl     = document.getElementById('ip-ctx-status-dot');

        if (titleEl)   titleEl.textContent   = computerName || baseIp;
        if (badgeIpEl) badgeIpEl.textContent = cardIpValue;

        // Detecta se está offline para colorir o indicador
        let isOffline = false;
        try {
            const targetItem = document.querySelector(`.ip-item[data-ip="${cardIpValue}"], .ip-item[data-base-ip="${baseIp}"]`);
            if (targetItem && targetItem.classList.contains('status-offline')) isOffline = true;
        } catch (_) {}
        if (dotEl) dotEl.className = `status-dot-mini ${isOffline ? 'offline' : 'online'}`;

        // Posiciona e exibe o menu
        const posX = (e && typeof e.clientX === 'number') ? e.clientX : (window.innerWidth / 2);
        const posY = (e && typeof e.clientY === 'number') ? e.clientY : (window.innerHeight / 2);
        _ctxShow(posX, posY);

        // Associa cada botão do menu a sua ação
        const bindItem = (id, handler) => {
            const btn = document.getElementById(id);
            if (!btn) return;
            btn.onclick = (evt) => {
                evt.preventDefault();
                evt.stopPropagation();
                _ctxHide();
                handler();
            };
        };

        bindItem('ip-ctx-vnc', () => {
            if (typeof window.openWebVNC === 'function') {
                window.openWebVNC(baseIp, targetUser || null);
            } else {
                const port = 5900;
                window.open(`/novnc/vnc.html?host=${baseIp}&port=${port}&autoconnect=true&resize=remote`, '_blank');
            }
        });

        bindItem('ip-ctx-ssh', () => {
            if (typeof window.openWebSSHTerminal === 'function') {
                window.openWebSSHTerminal(baseIp, targetUser || '');
            } else {
                const userParam = targetUser ? `&user=${encodeURIComponent(targetUser)}` : '';
                window.open(`/ssh-terminal?host=${baseIp}${userParam}`, '_blank');
            }
        });

        bindItem('ip-ctx-msg', () => {
            const msg = prompt(`Digite a mensagem para exibir na tela do computador ${computerName} (${cardIpValue}):`, "📢 Mensagem do Administrador");
            if (msg && msg.trim()) {
                const pwd = typeof getActivePassword === 'function' ? getActivePassword() : 'qwe123';
                const payload = {
                    action: 'enviar_mensagem',
                    password: pwd,
                    message: msg.trim()
                };
                if (typeof processBatch === 'function') {
                    processBatch(payload, `Enviar Mensagem (${baseIp})`, [cardIpValue]);
                } else {
                    fetch(`${API_BASE_URL}/gerenciar_atalhos_ip`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ ...payload, ip: cardIpValue })
                    }).then(r => r.json()).then(res => {
                        if (res.success) {
                            if (typeof showToast === 'function') showToast(`Mensagem enviada para ${computerName}`, 'success');
                        } else {
                            if (typeof showToast === 'function') showToast(`Erro ao enviar mensagem: ${res.message}`, 'error');
                        }
                    });
                }
            }
        });

        bindItem('ip-ctx-protection', async () => {
            const pwd = typeof getActivePassword === 'function' ? getActivePassword() : 'qwe123';
            let isCurrentlyProtected = false;
            try {
                const resp = await fetch(`${API_BASE_URL}/api/check-child-protection`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ips: [baseIp], password: pwd })
                });
                const data = await resp.json();
                if (data && data.success) isCurrentlyProtected = data.is_protected;
            } catch (e) {}

            const actionToRun = isCurrentlyProtected ? 'remover_protecao_total_infantil' : 'ativar_protecao_total_infantil';
            const actionLabel = isCurrentlyProtected ? 'Remover Proteção Infantil' : 'Ativar Proteção Infantil';

            const payload = {
                action: actionToRun,
                password: pwd
            };

            if (typeof processBatch === 'function') {
                processBatch(payload, `${actionLabel} (${baseIp})`, [baseIp]);
            } else {
                fetch(`${API_BASE_URL}/gerenciar_atalhos_ip`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ...payload, ip: baseIp })
                });
                if (typeof showToast === 'function') showToast(`${actionLabel} iniciada em ${baseIp}`, 'info');
            }
        });

        bindItem('ip-ctx-alias', async () => {
            const currentAlias = (typeof deviceAliases !== 'undefined' && deviceAliases[baseIp]) || '';
            const newAlias = prompt(`Definir apelido / nome amigável para ${baseIp}:`, currentAlias);
            if (newAlias !== null) {
                try {
                    const resp = await fetch(`${API_BASE_URL}/set-alias`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ ip: baseIp, alias: newAlias.trim() })
                    });
                    const data = await resp.json();
                    if (data.success) {
                        if (typeof deviceAliases !== 'undefined') deviceAliases[baseIp] = newAlias.trim();
                        syncDeviceMetadataGlobals();
                        if (typeof fetchAndDisplayIps === 'function') fetchAndDisplayIps();
                        if (typeof showToast === 'function') showToast(`Apelido salvo para ${baseIp}`, 'success');
                    } else {
                        if (typeof showToast === 'function') showToast(`Erro ao salvar apelido: ${data.message || 'Falha no servidor'}`, 'error');
                    }
                } catch (e) {
                    if (typeof showToast === 'function') showToast(`Falha de comunicação ao salvar apelido.`, 'error');
                }
            }
        });

        bindItem('ip-ctx-group', () => {
            if (typeof openGroupModalForIps === 'function') {
                openGroupModalForIps([baseIp]);
            } else {
                const cb = document.getElementById(`ip-${cardIpValue.replace(/[\/\.:]/g, '-')}`);
                if (cb) cb.checked = true;
                if (typeof updateSelectionCounter === 'function') updateSelectionCounter();
                const groupModal = document.getElementById('set-group-modal');
                if (groupModal) groupModal.classList.remove('hidden');
            }
        });

        bindItem('ip-ctx-sync-time', () => {
            const pwd = typeof getActivePassword === 'function' ? getActivePassword() : 'qwe123';
            const payload = {
                action: 'sync_time',
                password: pwd
            };
            if (typeof processBatch === 'function') {
                processBatch(payload, `Sincronizar Horário (${baseIp})`, [baseIp]);
            } else {
                fetch(`${API_BASE_URL}/gerenciar_atalhos_ip`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ...payload, ip: baseIp })
                });
                if (typeof showToast === 'function') showToast(`Sincronização de horário enviada para ${baseIp}`, 'info');
            }
        });

        bindItem('ip-ctx-power', () => {
            const cb = document.getElementById(`ip-${cardIpValue.replace(/[\/\.:]/g, '-')}`);
            if (cb) {
                document.querySelectorAll('.ip-checkbox').forEach(c => c.checked = false);
                cb.checked = true;
                if (typeof updateSelectionCounter === 'function') updateSelectionCounter();
            }
            const powerModalLabel = document.getElementById('power-selected-targets-label');
            if (powerModalLabel) {
                powerModalLabel.textContent = `Máquina Alvo: ${computerName} (${cardIpValue})`;
            }
            const powerModal = document.getElementById('power-management-modal');
            if (powerModal) powerModal.classList.remove('hidden');
        });

        bindItem('ip-ctx-block', () => {
            if (typeof blockIp === 'function') {
                blockIp(baseIp);
            } else {
                const itemEl = Array.from(document.querySelectorAll('.ip-item')).find(el => el.dataset.ip === cardIpValue || el.dataset.baseIp === baseIp);
                if (itemEl) itemEl.style.display = 'none';
                if (typeof showToast === 'function') showToast(`IP ${baseIp} bloqueado da visualização.`, 'info');
            }
        });
    }

    window.showIpCardContextMenu = showIpCardContextMenu;

    // ─── Interceptação Delegada para Botão de Opções do Computador (.btn-ip-options) ──
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.btn-ip-options');
        if (btn) {
            e.preventDefault();
            e.stopPropagation();
            const ipItem = btn.closest('.ip-item, [data-ip]');
            if (ipItem) {
                const cardIpValue  = ipItem.dataset.ip  || '';
                const baseIp       = ipItem.dataset.baseIp || cardIpValue.split('/')[0];
                const targetUser   = ipItem.dataset.targetUser || (cardIpValue.includes('/') ? cardIpValue.split('/')[1] : null);
                const computerName = ipItem.getAttribute('data-tooltip') || ipItem.getAttribute('title') || baseIp;

                const rect = btn.getBoundingClientRect();
                const fakeEvent = { clientX: rect.right, clientY: rect.bottom };
                showIpCardContextMenu(fakeEvent, cardIpValue, baseIp, targetUser, computerName);
            }
        }
    }, true);

    // ─── Interceptação Delegada de Clique Direito nos Cartões de IP ─────────────────
    const handleIpCardRightClick = (e) => {
        // Se o clique for em campos editáveis ou no modo grid, ignora
        if (e.target.closest('input:not(.ip-checkbox), textarea, select, .vnc-tile')) return;

        const ipItem = e.target.closest('.ip-item, [data-ip]');
        if (!ipItem) return;

        e.preventDefault();
        e.stopPropagation();

        const cardIpValue  = ipItem.dataset.ip  || '';
        const baseIp       = ipItem.dataset.baseIp || cardIpValue.split('/')[0];
        const targetUser   = ipItem.dataset.targetUser || (cardIpValue.includes('/') ? cardIpValue.split('/')[1] : null);
        const computerName = ipItem.getAttribute('data-tooltip') || ipItem.getAttribute('title') || baseIp;

        showIpCardContextMenu(e, cardIpValue, baseIp, targetUser, computerName);
    };

    document.addEventListener('contextmenu', handleIpCardRightClick, true);

    // Fecha o menu ao clicar com o botão ESQUERDO fora do menu de contexto
    document.addEventListener('click', (e) => {
        const menu = document.getElementById('ip-card-context-menu');
        if (!menu || menu.classList.contains('ip-context-menu--hidden') || menu.style.display === 'none') return;

        // Se o clique ocorreu dentro do próprio menu ou no botão de opções, não fecha aqui
        if (menu.contains(e.target)) return;

        if (e.target.closest('.btn-ip-options')) return;

        // Proteção de tempo para evitar fechamento imediato na abertura
        const openedAt = parseInt(menu.dataset.openedAt || '0', 10);
        if (Date.now() - openedAt < 200) return;

        _ctxHide();
    }, true);

    // Fecha o menu com Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') _ctxHide();
    });

    // --- Módulo do Medidor de Decibéis & Ruído Ambiente (Decibelímetro Web Audio) ---
    function initDecibelMeterModule() {
        const openBtn = document.getElementById('open-decibel-modal-btn');
        const modal = document.getElementById('decibel-meter-modal');
        const minimizeBtn = document.getElementById('minimize-decibel-modal-btn');
        const minimizeFooterBtn = document.getElementById('minimize-decibel-footer-btn');
        const closeBtn = document.getElementById('close-decibel-modal-btn');
        const cancelBtn = document.getElementById('cancel-decibel-modal-btn');
        const toggleMicBtn = document.getElementById('decibel-toggle-mic-btn');
        const toggleBtnLabel = document.getElementById('decibel-toggle-btn-label');
        const resetStatsBtn = document.getElementById('decibel-reset-stats-btn');
        const saveSettingsBtn = document.getElementById('decibel-save-settings-btn');
        const saveSettingsTopBtn = document.getElementById('decibel-save-settings-top-btn');

        // Floating HUD (Mini Widget Flutuante)
        const floatingHud = document.getElementById('decibel-floating-hud');
        const hudDragHandle = document.getElementById('decibel-hud-drag-handle');
        const hudExpandTrigger = document.getElementById('decibel-hud-expand-trigger');
        const hudLiveDot = document.getElementById('decibel-hud-live-dot');
        const hudCurrentVal = document.getElementById('decibel-hud-current-val');
        const hudZoneBadge = document.getElementById('decibel-hud-zone-badge');
        const hudInfractionsBadge = document.getElementById('decibel-hud-infractions-badge');
        const hudSilenceBtn = document.getElementById('decibel-hud-silence-btn');
        const hudExpandBtn = document.getElementById('decibel-hud-expand-btn');
        const hudStopBtn = document.getElementById('decibel-hud-stop-btn');

        const liveDot = document.getElementById('decibel-live-dot');
        const statusText = document.getElementById('decibel-status-text');
        const zoneBadge = document.getElementById('decibel-zone-badge');
        const currentValEl = document.getElementById('decibel-current-val');
        const heroCard = document.getElementById('decibel-hero-card');
        const meterBar = document.getElementById('decibel-meter-bar');
        const thresholdMarker = document.getElementById('decibel-threshold-marker');
        const peakMarker = document.getElementById('decibel-peak-marker');

        // Elementos do Mostrador Analógico Unificado (Canvas VU Dial)
        const analogCanvas = document.getElementById('decibel-analog-canvas');
        const analogCtx = analogCanvas ? analogCanvas.getContext('2d') : null;
        let needlePhysAngle = -Math.PI / 2 - (65 * Math.PI / 180); // -65° a partir do topo (-155° no plano)
        let peakPhysAngle = -Math.PI / 2 - (65 * Math.PI / 180);
        const digitalLimitVal = document.getElementById('decibel-digital-limit-val');

        // Barra Compacta de Micro-LEDs Digitais
        const ledLadderTrack = document.getElementById('decibel-led-ladder-track');
        const TOTAL_LED_SEGS = 24;
        const ledSegElements = [];
        if (ledLadderTrack) {
            ledLadderTrack.innerHTML = '';
            for (let i = 0; i < TOTAL_LED_SEGS; i++) {
                const seg = document.createElement('div');
                seg.className = 'decibel-led-seg';
                const segPercent = i / (TOTAL_LED_SEGS - 1);
                if (segPercent <= 0.35) {
                    seg.classList.add('zone-green');
                } else if (segPercent <= 0.60) {
                    seg.classList.add('zone-cyan');
                } else if (segPercent <= 0.80) {
                    seg.classList.add('zone-amber');
                } else {
                    seg.classList.add('zone-red');
                }
                ledLadderTrack.appendChild(seg);
                ledSegElements.push(seg);
            }
        }

        // =========================================================================
        // ⏱️ RENDERIZADOR DO MOSTRADOR ANALÓGICO VU METER (ALTA RESOLUÇÃO CANVAS)
        // =========================================================================
        function drawAnalogMeterDial(currentDb, peakDb, threshDb) {
            if (!analogCtx || !analogCanvas) return;

            const w = analogCanvas.width;   // 560
            const h = analogCanvas.height;  // 284
            const cx = w / 2;               // 280
            const cy = 250;                 // Centro do eixo
            const radius = 205;             // Raio da escala

            analogCtx.clearRect(0, 0, w, h);

            const isDark = !document.documentElement.getAttribute('data-theme') || document.documentElement.getAttribute('data-theme') === 'dark';

            // 1. Fundo do Mostrador Analógico
            analogCtx.save();
            analogCtx.beginPath();
            analogCtx.arc(cx, cy, radius + 30, Math.PI + 0.35, Math.PI * 2 - 0.35, false);
            analogCtx.lineTo(cx, cy);
            analogCtx.closePath();
            
            const bgGrad = analogCtx.createRadialGradient(cx, cy, 30, cx, cy, radius + 35);
            if (isDark) {
                bgGrad.addColorStop(0, '#1e293b');
                bgGrad.addColorStop(0.7, '#0f172a');
                bgGrad.addColorStop(1, '#090d16');
            } else {
                bgGrad.addColorStop(0, '#ffffff');
                bgGrad.addColorStop(0.7, '#f8fafc');
                bgGrad.addColorStop(1, '#e2e8f0');
            }
            analogCtx.fillStyle = bgGrad;
            analogCtx.fill();
            analogCtx.strokeStyle = isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.08)';
            analogCtx.lineWidth = 2.5;
            analogCtx.stroke();
            analogCtx.restore();

            // Conversão: dB (20..120) para Ângulo em Radianos (-65° a +65°)
            function dbToAngleRad(dbVal) {
                const clamped = Math.max(20, Math.min(120, dbVal));
                const deg = -65 + ((clamped - 20) / 100) * 130;
                return (deg * Math.PI) / 180;
            }

            // 2. Faixas Coloridas em Arco
            const zones = [
                { start: 20, end: 50, color: '#10b981' }, // Verde
                { start: 50, end: 70, color: '#38bdf8' }, // Ciano
                { start: 70, end: 85, color: '#f59e0b' }, // Âmbar
                { start: 85, end: 120, color: '#ef4444' } // Vermelho
            ];

            zones.forEach(zone => {
                const a1 = -Math.PI / 2 + dbToAngleRad(zone.start);
                const a2 = -Math.PI / 2 + dbToAngleRad(zone.end);
                analogCtx.beginPath();
                analogCtx.arc(cx, cy, radius, a1, a2, false);
                analogCtx.strokeStyle = zone.color;
                analogCtx.lineWidth = 8;
                analogCtx.lineCap = 'round';
                analogCtx.stroke();
            });

            // 3. Ticks e Números da Escala
            const majorTicks = [20, 40, 60, 80, 100, 120];
            const minorTicks = [30, 50, 70, 90, 110];

            analogCtx.textAlign = 'center';
            analogCtx.textBaseline = 'middle';
            analogCtx.font = '700 17px "JetBrains Mono", monospace, sans-serif';

            majorTicks.forEach(db => {
                const angle = -Math.PI / 2 + dbToAngleRad(db);
                const x1 = cx + (radius - 5) * Math.cos(angle);
                const y1 = cy + (radius - 5) * Math.sin(angle);
                const x2 = cx + (radius + 15) * Math.cos(angle);
                const y2 = cy + (radius + 15) * Math.sin(angle);
                const tx = cx + (radius - 26) * Math.cos(angle);
                const ty = cy + (radius - 26) * Math.sin(angle);

                analogCtx.beginPath();
                analogCtx.moveTo(x1, y1);
                analogCtx.lineTo(x2, y2);
                analogCtx.strokeStyle = db >= 85 ? '#ef4444' : (db >= 70 ? '#f59e0b' : (isDark ? '#94a3b8' : '#475569'));
                analogCtx.lineWidth = 3.5;
                analogCtx.stroke();

                analogCtx.fillStyle = db >= 85 ? '#ef4444' : (db >= 70 ? '#f59e0b' : (isDark ? '#94a3b8' : '#475569'));
                analogCtx.fillText(String(db), tx, ty);
            });

            minorTicks.forEach(db => {
                const angle = -Math.PI / 2 + dbToAngleRad(db);
                const x1 = cx + (radius - 2) * Math.cos(angle);
                const y1 = cy + (radius - 2) * Math.sin(angle);
                const x2 = cx + (radius + 10) * Math.cos(angle);
                const y2 = cy + (radius + 10) * Math.sin(angle);

                analogCtx.beginPath();
                analogCtx.moveTo(x1, y1);
                analogCtx.lineTo(x2, y2);
                analogCtx.strokeStyle = isDark ? 'rgba(255, 255, 255, 0.25)' : 'rgba(0, 0, 0, 0.25)';
                analogCtx.lineWidth = 2;
                analogCtx.stroke();
            });

            // 4. Marcador Triangular do Limite de Alerta
            const activeThresh = (threshDb !== undefined && threshDb !== null) ? threshDb : alertThreshold;
            const threshAngle = -Math.PI / 2 + dbToAngleRad(activeThresh || 75);
            const thDist = radius + 15;
            const thX = cx + thDist * Math.cos(threshAngle);
            const thY = cy + thDist * Math.sin(threshAngle);

            analogCtx.save();
            analogCtx.translate(thX, thY);
            analogCtx.rotate(threshAngle + Math.PI / 2);
            analogCtx.beginPath();
            analogCtx.moveTo(-7, -12);
            analogCtx.lineTo(7, -12);
            analogCtx.lineTo(0, 0);
            analogCtx.closePath();
            analogCtx.fillStyle = '#ffffff';
            analogCtx.fill();
            analogCtx.strokeStyle = '#0f172a';
            analogCtx.lineWidth = 1.5;
            analogCtx.stroke();
            analogCtx.restore();

            // 5. Física Balística da Agulha
            const targetRad = -Math.PI / 2 + dbToAngleRad(currentDb || 20);
            needlePhysAngle += (targetRad - needlePhysAngle) * 0.32;

            // Agulha de Pico Analógica (Peak Hold Needle)
            const targetPeakRad = -Math.PI / 2 + dbToAngleRad(peakDb || currentDb || 20);
            if (targetPeakRad > peakPhysAngle) {
                peakPhysAngle = targetPeakRad;
            } else {
                peakPhysAngle = Math.max(targetRad, peakPhysAngle - 0.008);
            }

            analogCtx.save();
            analogCtx.beginPath();
            analogCtx.setLineDash([5, 5]);
            analogCtx.moveTo(cx, cy);
            const pkTipX = cx + (radius + 10) * Math.cos(peakPhysAngle);
            const pkTipY = cy + (radius + 10) * Math.sin(peakPhysAngle);
            analogCtx.lineTo(pkTipX, pkTipY);
            analogCtx.strokeStyle = 'rgba(244, 63, 94, 0.85)';
            analogCtx.lineWidth = 3;
            analogCtx.stroke();
            analogCtx.restore();

            // 6. Agulha Analógica Principal
            analogCtx.save();
            analogCtx.translate(cx, cy);
            analogCtx.rotate(needlePhysAngle + Math.PI / 2);

            analogCtx.shadowColor = 'rgba(239, 68, 68, 0.45)';
            analogCtx.shadowBlur = 10;
            analogCtx.shadowOffsetY = 2;

            analogCtx.beginPath();
            analogCtx.moveTo(-4.5, 0);
            analogCtx.lineTo(-1.5, -(radius + 12));
            analogCtx.lineTo(1.5, -(radius + 12));
            analogCtx.lineTo(4.5, 0);
            analogCtx.lineTo(0, 16);
            analogCtx.closePath();
            analogCtx.fillStyle = '#ef4444';
            analogCtx.fill();

            // Ponta branca contrastante
            analogCtx.beginPath();
            analogCtx.moveTo(-1.8, -(radius + 1));
            analogCtx.lineTo(0, -(radius + 20));
            analogCtx.lineTo(1.8, -(radius + 1));
            analogCtx.closePath();
            analogCtx.fillStyle = '#ffffff';
            analogCtx.fill();
            analogCtx.restore();

            // 7. Pivô Central Metálico
            analogCtx.save();
            analogCtx.beginPath();
            analogCtx.arc(cx, cy, 26, 0, Math.PI * 2);
            analogCtx.fillStyle = isDark ? '#1e293b' : '#334155';
            analogCtx.strokeStyle = isDark ? '#64748b' : '#94a3b8';
            analogCtx.lineWidth = 4;
            analogCtx.shadowColor = 'rgba(0, 0, 0, 0.5)';
            analogCtx.shadowBlur = 8;
            analogCtx.fill();
            analogCtx.stroke();

            analogCtx.beginPath();
            analogCtx.arc(cx, cy, 14, 0, Math.PI * 2);
            analogCtx.fillStyle = '#0f172a';
            analogCtx.fill();

            analogCtx.beginPath();
            analogCtx.arc(cx - 4, cy - 4, 4, 0, Math.PI * 2);
            analogCtx.fillStyle = 'rgba(255, 255, 255, 0.6)';
            analogCtx.fill();
            analogCtx.restore();
        }

        const avgValEl = document.getElementById('decibel-avg-val');
        const maxValEl = document.getElementById('decibel-max-val');
        const minValEl = document.getElementById('decibel-min-val');
        const alertCountEl = document.getElementById('decibel-alert-count');

        const alertEnableToggle = document.getElementById('decibel-alert-enable-toggle');
        const thresholdInput = document.getElementById('decibel-threshold-input');
        const thresholdNumberInput = document.getElementById('decibel-threshold-number');
        const thresholdDisplay = document.getElementById('decibel-threshold-display');
        const presetChips = document.querySelectorAll('.decibel-preset-chip');
        const beepToggle = document.getElementById('decibel-beep-toggle');

        const deviceSelect = document.getElementById('decibel-device-select');
        const calibInput = document.getElementById('decibel-calibration-offset');
        const calibDisplay = document.getElementById('decibel-calib-display');
        const autoCalibBtn = document.getElementById('decibel-auto-calibrate-btn');
        const autoCalibBtnLabel = document.getElementById('decibel-autocalib-btn-label');
        const calibFeedbackBox = document.getElementById('decibel-calib-feedback-box');
        const calibFeedbackText = document.getElementById('decibel-calib-feedback-text');

        const autoActionsToggle = document.getElementById('decibel-auto-actions-toggle');
        const step1El = document.getElementById('decibel-step-1');
        const step2El = document.getElementById('decibel-step-2');
        const step3El = document.getElementById('decibel-step-3');
        const line1El = document.getElementById('decibel-line-1');
        const line2El = document.getElementById('decibel-line-2');
        const lockBanner = document.getElementById('decibel-lock-status-banner');
        const lockCalmPercentBadge = document.getElementById('decibel-calm-percent-badge');
        const lockCalmBarFill = document.getElementById('decibel-calm-bar-fill');
        const lockCalmStatusText = document.getElementById('decibel-calm-status-text');
        const lockTitle = document.getElementById('decibel-lock-title');
        const lockDesc = document.getElementById('decibel-lock-desc');
        const manualUnlockBtn = document.getElementById('decibel-manual-unlock-btn');
        const currentInfractionsLabel = document.getElementById('decibel-current-infractions-label');
        const resetClassBtn = document.getElementById('decibel-reset-class-btn');

        // 🚦 Semáforo de Ruído no Monitor do Aluno (Visual & Pedagógico)
        const studentTrafficLightToggle = document.getElementById('decibel-student-traffic-light-toggle');
        const tfDotGreen = document.getElementById('tf-prev-dot-green');
        const tfDotYellow = document.getElementById('tf-prev-dot-yellow');
        const tfDotRed = document.getElementById('tf-prev-dot-red');
        const tfStatusLabel = document.getElementById('tf-prev-status-label');
        const tfSyncBtn = document.getElementById('decibel-tf-sync-btn');

        // 🏆 Gamificação "Turma Nota 10 em Silêncio"
        const gamificationScoreBadge = document.getElementById('decibel-gamification-score-badge');
        const star1 = document.getElementById('decibel-star-1');
        const star2 = document.getElementById('decibel-star-2');
        const star3 = document.getElementById('decibel-star-3');
        const gamificationStatusText = document.getElementById('decibel-gamification-status-text');
        const sendCelebrationBtn = document.getElementById('decibel-send-celebration-btn');

        const canvas = document.getElementById('decibel-canvas');
        let ctx = canvas ? canvas.getContext('2d') : null;

        // Abas do Medidor de Ruído (Tabs UI)
        let activeDecibelTab = 'monitor';

        function switchDecibelTab(targetTab) {
            if (!targetTab) return;
            activeDecibelTab = targetTab;
            window._activeDecibelTab = targetTab;
            
            const allTabs = document.querySelectorAll('.decibel-tab-btn');
            const allPanes = document.querySelectorAll('.decibel-tab-pane');

            allTabs.forEach(t => {
                const isMatch = t.getAttribute('data-tab') === targetTab;
                if (isMatch) {
                    t.classList.add('active');
                } else {
                    t.classList.remove('active');
                }
            });

            allPanes.forEach(pane => {
                const isMatch = pane.id === `decibel-tab-${targetTab}`;
                if (isMatch) {
                    pane.classList.add('active');
                    pane.classList.remove('hidden');
                    pane.style.setProperty('display', 'flex', 'important');
                } else {
                    pane.classList.remove('active');
                    pane.classList.add('hidden');
                    pane.style.setProperty('display', 'none', 'important');
                }
            });

            if (targetTab === 'history') {
                if (typeof loadNoiseHistoryReport === 'function') {
                    loadNoiseHistoryReport();
                } else if (typeof window.loadNoiseHistoryReport === 'function') {
                    window.loadNoiseHistoryReport();
                }
            }
        }

        window.switchDecibelTab = switchDecibelTab;

        // Estado do Áudio
        let isMonitoring = false;
        let audioCtx = null;
        let analyser = null;
        let micStream = null;
        let sourceNode = null;
        let backgroundAudioInterval = null;
        let animationFrameId = null;
        let lastAudioProcessTime = 0;
        let lastUiRenderTime = 0;
        let lockdownEndTime = 0;

        // Estatísticas e Filtros
        let smoothedDb = 0;
        let peakValue = 0;
        let peakMarkerPos = 0;
        let minDb = 999;
        let maxDb = 0;
        let dbSum = 0;
        let dbSampleCount = 0;
        let alertCount = 0;
        let isCurrentlyInAlert = false;
        let lastBeepTime = 0;
        let lastDbLogTime = 0;

        // Estado do Semáforo no Monitor do Aluno
        let isStudentTrafficLightEnabled = localStorage.getItem('decibel_traffic_light_enabled') === 'true';
        let currentTrafficLevel = 'green';
        let lastSentTrafficLevel = '';
        let lastTrafficSyncTime = 0;

        // Estado da Disciplina na Sala de Aula (Automação de Rede)
        let autoNetworkActionsEnabled = localStorage.getItem('decibel_auto_actions_enabled') !== 'false';
        let autoSilenceAlertEnabled = localStorage.getItem('decibel_auto_silence_enabled') !== 'false';
        let silenceContinuousDurationSec = parseInt(localStorage.getItem('decibel_silence_duration') || '3', 10);
        let lastSilenceAlertTriggerTime = 0;
        let lastExceedTime = 0;

        let classroomInfractionCount = parseInt(localStorage.getItem('decibel_classroom_infractions') || '0', 10);
        let isCurrentlyLockedDown = false;
        let lockdownRemainingSeconds = 0;
        let calmBarScore = 0; // Gamificação Reversa: Barra de Calma Coletiva (0% a 100%)
        let lastPenaltySentTime = 0;
        let lastCalmScoreSentTime = 0;
        let lockdownInterval = null;
        let noiseExceedStartTime = 0;
        let consecutiveQuietSeconds = 0;
        let lastInfractionTriggerTime = 0;

        // Histórico para o Gráfico Canvas (últimos 120 pontos)
        const historyMaxPoints = 120;
        const historyPoints = [];

        // Carrega configurações salvas do LocalStorage
        let alertThreshold = parseInt(localStorage.getItem('decibel_alert_threshold') || '75', 10);
        let calibrationOffset = parseInt(localStorage.getItem('decibel_calib_offset') || '0', 10);
        let isAlertEnabled = localStorage.getItem('decibel_alert_enabled') !== 'false';
        let isBeepEnabled = localStorage.getItem('decibel_beep_enabled') !== 'false';
        let selectedDeviceId = localStorage.getItem('decibel_device_id') || '';

        // Helper para obter os IPs dos alunos ativos na sala (selecionados ou online)
        function getActiveTargetIps() {
            try {
                const checkedIps = Array.from(document.querySelectorAll('input[name="ip"]:checked, .ip-checkbox:checked')).map(cb => cb.value).filter(Boolean);
                if (checkedIps.length > 0) return checkedIps;
                const onlineIps = Array.from(document.querySelectorAll('.ip-item.status-online, .ip-item:not(.status-offline)')).map(el => el.dataset.ip).filter(Boolean);
                if (onlineIps.length > 0) return onlineIps;
            } catch (e) {}
            return [];
        }

        // Dispara o alerta automático "Pedir Silêncio" para todas as máquinas dos alunos
        async function triggerContinuousSilenceAlert() {
            const now = Date.now();
            // Debounce de 20s entre disparos automáticos para evitar repetição constante enquanto a sala silencia
            if (now - lastSilenceAlertTriggerTime < 20000) return;
            lastSilenceAlertTriggerTime = now;

            try {
                const pwd = typeof getActivePassword === 'function' ? getActivePassword() : 'qwe123';
                const targetIps = getActiveTargetIps();
                const resp = await fetch('/api/noise/silence', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        threshold: alertThreshold,
                        password: pwd,
                        ips: targetIps,
                        message: "🤫 ATENÇÃO: O nível de ruído na sala ultrapassou o limite! Por favor, façam silêncio e prestem atenção."
                    })
                });
                const res = await resp.json();
                if (res.success) {
                    showToast(`🤫 Alerta "Pedir Silêncio" disparado automaticamente nas máquinas dos alunos (${res.delivered_count || 'todas'} online)!`, 'warning', 7000);
                }
            } catch (e) {
                console.error('[Decibelímetro] Erro ao disparar Pedir Silêncio:', e);
            }
        }

        // =========================================================================
        // 🚦 ATUALIZAÇÃO VISUAL E SINCRONIZAÇÃO DO SEMÁFORO DE RUÍDO
        // =========================================================================
        function updateTrafficLightVisual(level, dbVal) {
            currentTrafficLevel = level;
            if (tfDotGreen && tfDotYellow && tfDotRed) {
                tfDotGreen.classList.toggle('active', level === 'green');
                tfDotYellow.classList.toggle('active', level === 'yellow');
                tfDotRed.classList.toggle('active', level === 'red');
            }
            if (tfStatusLabel) {
                if (level === 'red') {
                    tfStatusLabel.innerHTML = `<span style="color:#ef4444;">🔴 Vermelho: Limite Atingido (${dbVal.toFixed(1)} dB)</span>`;
                } else if (level === 'yellow') {
                    tfStatusLabel.innerHTML = `<span style="color:#fbbf24;">🟡 Amarelo: Atenção / Conversas (${dbVal.toFixed(1)} dB)</span>`;
                } else {
                    tfStatusLabel.innerHTML = `<span style="color:#34d399;">🟢 Verde: Silêncio Perfeito (${dbVal.toFixed(1)} dB)</span>`;
                }
            }
        }

        async function syncTrafficLightToStudents(level, dbVal, force = false) {
            if (!isStudentTrafficLightEnabled && !force) return;
            const now = Date.now();
            if (!force && level === lastSentTrafficLevel && (now - lastTrafficSyncTime < 15000)) return;
            if (!force && (now - lastTrafficSyncTime < 1800)) return;

            lastSentTrafficLevel = level;
            lastTrafficSyncTime = now;

            try {
                const pwd = typeof getActivePassword === 'function' ? getActivePassword() : 'qwe123';
                await fetch('/api/noise/traffic-light', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        level: isStudentTrafficLightEnabled ? level : 'off',
                        db: parseFloat(dbVal.toFixed(1)),
                        threshold: alertThreshold,
                        password: pwd
                    })
                });
            } catch (err) {
                console.debug('[TrafficLight] Erro ao sincronizar semáforo:', err);
            }
        }

        // =========================================================================
        // 🏆 GAMIFICAÇÃO "TURMA NOTA 10 EM SILÊNCIO"
        // =========================================================================
        function updateGamificationScore() {
            let stars = 3;
            let badgeText = '⭐⭐⭐ NOTA 10 (100%)';
            let badgeColor = '#fde047';
            let statusDesc = 'Zero infrações registradas. A turma mantém pontuação máxima!';

            if (classroomInfractionCount === 1) {
                stars = 2;
                badgeText = '⭐⭐ BOM COMPORTAMENTO (80%)';
                badgeColor = '#38bdf8';
                statusDesc = '1 aviso emitido na aula. A turma mantém bom aproveitamento!';
            } else if (classroomInfractionCount === 2) {
                stars = 1;
                badgeText = '⭐ ATENÇÃO AO RUÍDO (60%)';
                badgeColor = '#fbbf24';
                statusDesc = '2 avisos emitidos. Atenção redobrada para não bloquear as máquinas!';
            } else if (classroomInfractionCount >= 3) {
                stars = 0;
                badgeText = '⚠️ RECUPERAÇÃO DISCIPLINAR (40%)';
                badgeColor = '#ef4444';
                statusDesc = 'Travamento disciplinar ocorrido. Silêncio necessário para recuperar o foco!';
            }

            if (gamificationScoreBadge) {
                gamificationScoreBadge.textContent = badgeText;
                gamificationScoreBadge.style.color = badgeColor;
            }

            if (star1) star1.className = stars >= 1 ? 'star-on' : 'star-off';
            if (star2) star2.className = stars >= 2 ? 'star-on' : 'star-off';
            if (star3) star3.className = stars >= 3 ? 'star-on' : 'star-off';

            if (gamificationStatusText) {
                gamificationStatusText.textContent = statusDesc;
            }
        }

        async function celebrateTurmaNota10() {
            let stars = 3;
            if (classroomInfractionCount === 1) stars = 2;
            else if (classroomInfractionCount === 2) stars = 1;
            else if (classroomInfractionCount >= 3) stars = 1; // Incentivo

            if (sendCelebrationBtn) {
                sendCelebrationBtn.disabled = true;
                sendCelebrationBtn.textContent = 'Enviando...';
            }

            let periodName = 'Aula Atual';
            try {
                const pResp = await fetch('/api/schedule/current-period');
                const pData = await pResp.json();
                if (pData && pData.current_period && pData.current_period.name) {
                    periodName = pData.current_period.name;
                }
            } catch (e) {}

            try {
                const pwd = typeof getActivePassword === 'function' ? getActivePassword() : 'qwe123';
                const resp = await fetch('/api/noise/celebrate-stars', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        stars: stars,
                        period_name: periodName,
                        password: pwd,
                        message: stars >= 3
                            ? "Parabéns a toda a turma pelo silêncio exemplar e disciplina nota 10!"
                            : "Parabéns a todos pela dedicação e cooperação durante a aula!"
                    })
                });
                const res = await resp.json();
                if (res.success) {
                    showToast(`🏆 Premiação "Turma Nota 10" (${stars} ⭐) exibida com sucesso para ${res.delivered_count || 'todas as'} máquinas!`, 'success', 6000);
                } else {
                    showToast('Falha ao enviar premiação: ' + (res.message || 'Erro'), 'error');
                }
            } catch (err) {
                showToast('Erro de rede ao enviar premiação aos alunos: ' + err.message, 'error');
            } finally {
                if (sendCelebrationBtn) {
                    sendCelebrationBtn.disabled = false;
                    sendCelebrationBtn.textContent = '🏆 Enviar Premiação aos Alunos';
                }
            }
        }

        // =========================================================================
        // 👮‍♂️ REGRAS DE EXCESSO DE RUÍDO & GAMIFICAÇÃO REVERSA DA CALMA COLETIVA
        // 1º Excesso: 1º Aviso visual na tela
        // 2º Excesso: 2º Aviso visual de atenção
        // 3º Excesso: Barra de Calma Coletiva (Meta 100% de Calma para desbloqueio)
        // Regras da Barra: Silêncio = +10%/s | Barulho = -20% (Pausa de Penalidade)
        // =========================================================================

        function getLockdownDurationSeconds(infractionCount) {
            const count = parseInt(infractionCount, 10) || 3;
            if (count <= 3) return 30;
            return 30 + (count - 3) * 15;
        }

        function updateDisciplineUI() {
            if (currentInfractionsLabel) {
                if (classroomInfractionCount >= 3) {
                    currentInfractionsLabel.textContent = `${classroomInfractionCount}º excesso (Desafio 100%)`;
                } else {
                    currentInfractionsLabel.textContent = `${classroomInfractionCount} de 3`;
                }
            }

            if (lockBanner) {
                if (isCurrentlyLockedDown) {
                    lockBanner.classList.remove('hidden');
                    if (lockCalmPercentBadge) {
                        lockCalmPercentBadge.textContent = `${calmBarScore}%`;
                    }
                    if (lockCalmBarFill) {
                        lockCalmBarFill.style.width = `${calmBarScore}%`;
                    }
                    if (lockTitle) {
                        lockTitle.innerHTML = `🎮 DESAFIO DA CALMA (${classroomInfractionCount}º EXCESSO)`;
                    }
                } else {
                    lockBanner.classList.add('hidden');
                    if (lockCalmBarFill) lockCalmBarFill.style.width = '0%';
                }
            }

            if (hudInfractionsBadge) {
                if (isCurrentlyLockedDown) {
                    hudInfractionsBadge.textContent = `🎮 ${calmBarScore}%`;
                    hudInfractionsBadge.classList.add('locked');
                } else if (classroomInfractionCount >= 3) {
                    hudInfractionsBadge.textContent = `🔒 ${classroomInfractionCount}x`;
                    hudInfractionsBadge.classList.add('locked');
                } else {
                    hudInfractionsBadge.textContent = `${classroomInfractionCount}/3`;
                    hudInfractionsBadge.classList.remove('locked');
                }
            }

            if (step1El) {
                step1El.classList.toggle('triggered', classroomInfractionCount >= 1);
                step1El.classList.toggle('active', classroomInfractionCount === 0);
            }
            if (line1El) {
                line1El.classList.toggle('active', classroomInfractionCount >= 1);
            }
            if (step2El) {
                step2El.classList.toggle('triggered', classroomInfractionCount >= 2);
                step2El.classList.toggle('active', classroomInfractionCount === 1);
            }
            if (line2El) {
                line2El.classList.toggle('active', classroomInfractionCount >= 2);
            }
            if (step3El) {
                step3El.classList.toggle('triggered', classroomInfractionCount >= 3);
                step3El.classList.toggle('active', classroomInfractionCount >= 2);
            }

            updateGamificationScore();
        }

        // Dispara uma infração de ruído e executa ação na rede
        async function triggerNoiseInfraction(isForced = false) {
            const now = Date.now();
            if (!isForced && isCurrentlyLockedDown) return; // Se já está travado, o loop da barra de calma aplica as penalidades (-20%)
            
            // Intervalo pedagógico entre infrações (5s após avisos para dar tempo da turma acalmar)
            const cooldownMs = isForced ? 0 : 5000;
            if (!isForced && (now - lastInfractionTriggerTime < cooldownMs)) return;
            lastInfractionTriggerTime = now;
            noiseExceedStartTime = 0; // Reseta a contagem contínua para exigir nova medição

            classroomInfractionCount++;
            localStorage.setItem('decibel_classroom_infractions', classroomInfractionCount);
            updateDisciplineUI();
            playWarningBeep();

            if (!autoNetworkActionsEnabled && !isForced) {
                showToast(`⚠️ Ruído excedeu o limite! (${classroomInfractionCount}ª infração detectada).`, 'warning', 4000);
                return;
            }

            const pwd = typeof getActivePassword === 'function' ? getActivePassword() : 'qwe123';
            const targetIps = getActiveTargetIps();

            if (classroomInfractionCount === 1) {
                // 1º Excesso: Envia 1ª mensagem de aviso na tela (periféricos livres)
                showToast('📢 [1º Excesso] 1º Aviso de Barulho enviado às telas dos alunos!', 'warning', 5000);
                try {
                    const resp = await fetch('/api/noise/warn', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ infraction: 1, threshold: alertThreshold, password: pwd, ips: targetIps })
                    });
                    const res = await resp.json();
                    if (res && res.delivered_count > 0) {
                        showToast(`📢 1º Aviso entregue a ${res.delivered_count} máquina(s) com sucesso!`, 'success', 4000);
                    }
                } catch (e) {
                    console.error('[Decibelímetro] Erro ao enviar aviso 1:', e);
                }
            } else if (classroomInfractionCount === 2) {
                // 2º Excesso: Envia 2ª mensagem de aviso na tela (periféricos livres)
                showToast('⚠️ [2º Excesso] 2º Aviso enviado! No próximo excesso, os computadores iniciarão o Desafio da Calma.', 'warning', 6000);
                try {
                    const resp = await fetch('/api/noise/warn', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ infraction: 2, threshold: alertThreshold, password: pwd, ips: targetIps })
                    });
                    const res = await resp.json();
                    if (res && res.delivered_count > 0) {
                        showToast(`⚠️ 2º Aviso entregue a ${res.delivered_count} máquina(s) com sucesso!`, 'success', 4000);
                    }
                } catch (e) {
                    console.error('[Decibelímetro] Erro ao enviar aviso 2:', e);
                }
            } else if (classroomInfractionCount >= 3) {
                // 3º Excesso em diante: Inicia o Desafio da Calma Coletiva
                await startLockdown();
            }
        }

        // Inicia o Desafio da Calma Coletiva (Gamificação Reversa: Meta 100%)
        async function startLockdown() {
            isCurrentlyLockedDown = true;
            calmBarScore = 0; // Inicia em 0% e a turma precisa acumular 100% de calma

            updateDisciplineUI();

            const toastMsg = `🎮 Desafio da Calma Coletiva Ativado! (${classroomInfractionCount}º excesso) • Meta de 100% para liberar.`;
            showToast(toastMsg, 'error', 7000);

            try {
                const pwd = typeof getActivePassword === 'function' ? getActivePassword() : 'qwe123';
                const targetIps = getActiveTargetIps();
                const resp = await fetch('/api/noise/lock', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        infraction: classroomInfractionCount,
                        threshold: alertThreshold,
                        unlock_seconds: 0,
                        require_silence: true,
                        password: pwd,
                        ips: targetIps,
                        message: "🎮 DESAFIO DA CALMA COLETIVA ATIVADO!\nMeta da Turma: Atingir 100% na Barra de Calma.\nSilêncio = +5%/s | Barulho ou conversas = a barra recua -20%!\nAo atingir 100%, todos os computadores voltam na hora!"
                    })
                });
                const res = await resp.json();
                if (res && res.delivered_count > 0) {
                    showToast(`🔒 Telas bloqueadas com Desafio da Calma em ${res.delivered_count} máquina(s)!`, 'warning', 5000);
                }
            } catch (e) {
                console.error('[Decibelímetro] Erro ao iniciar desafio da calma:', e);
            }

            if (lockdownInterval) clearInterval(lockdownInterval);
            
            // Loop da Barra de Calma Coletiva a cada 1000ms
            lockdownInterval = setInterval(() => {
                if (!isCurrentlyLockedDown) {
                    clearInterval(lockdownInterval);
                    lockdownInterval = null;
                    return;
                }

                // Critérios da Barra de Calma Coletiva (3 Zonas Pedagógicas):
                // 1. Silêncio Real (< 10 dB do limite máximo): Ganha +5%/s (exige 20 segundos de silêncio para 100%)
                // 2. Zona de Conversa/Murmúrio (entre -10 dB e o limite): Barra PAUSADA (não ganha pontos)
                // 3. Zona de Barulho (próximo ou acima do limite): Penalidade imediata de -15%
                const quietThreshold = alertThreshold - 10;
                const noisePenaltyThreshold = Math.max(quietThreshold + 4, alertThreshold - 3);

                const isHardNoise = isCurrentlyInAlert || (smoothedDb >= noisePenaltyThreshold);
                const isTalkingOrMurmur = !isHardNoise && (smoothedDb >= quietThreshold);

                if (isHardNoise) {
                    // ⚠️ BARULHO DETECTADO: A Barra de Calma recua 15%
                    calmBarScore = Math.max(0, calmBarScore - 15);

                    // Sincroniza a penalidade de barulho com as telas dos alunos via SSH/Backend
                    const now = Date.now();
                    if (!lastPenaltySentTime || (now - lastPenaltySentTime > 1000)) {
                        lastPenaltySentTime = now;
                        lastCalmScoreSentTime = now;
                        try {
                            const pwd = typeof getActivePassword === 'function' ? getActivePassword() : 'qwe123';
                            const targetIps = getActiveTargetIps();
                            fetch('/api/noise/penalty', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ password: pwd, ips: targetIps, score: calmBarScore })
                            }).catch(() => {});
                        } catch (e) {}
                    }

                    if (lockBanner) {
                        lockBanner.classList.remove('hidden');
                        lockBanner.classList.add('noise-penalty');
                        lockBanner.classList.remove('silence-accumulating');
                    }
                    if (lockCalmBarFill) {
                        lockCalmBarFill.classList.add('penalty');
                        lockCalmBarFill.style.width = `${calmBarScore}%`;
                    }
                    if (lockCalmPercentBadge) {
                        lockCalmPercentBadge.textContent = `${calmBarScore}%`;
                        lockCalmPercentBadge.style.color = '#ef4444';
                        lockCalmPercentBadge.style.borderColor = 'rgba(239, 68, 68, 0.4)';
                        lockCalmPercentBadge.style.background = 'rgba(239, 68, 68, 0.15)';
                    }
                    if (lockTitle) {
                        lockTitle.innerHTML = `<span style="color:#ef4444;">⚠️ BARULHO DETECTADO! (-15% de Energia)</span>`;
                    }
                    if (lockCalmStatusText) {
                        lockCalmStatusText.innerHTML = `⚠️ Barulho na sala (<strong style="color:#ef4444;">${smoothedDb.toFixed(1)} dB</strong>)! A barra recuou para <strong style="color:#ef4444;">${calmBarScore}%</strong>. Façam silêncio (< ${quietThreshold} dB).`;
                    }
                    if (hudInfractionsBadge) {
                        hudInfractionsBadge.textContent = `⚠️ ${calmBarScore}%`;
                        hudInfractionsBadge.classList.add('locked');
                    }
                    updateDynamicBrowserTab(smoothedDb, true, true, calmBarScore);
                } else if (isTalkingOrMurmur) {
                    // ⏸️ CONVERSAS / MURMÚRIO: Barra PAUSADA (não ganha pontos!)
                    const now = Date.now();
                    if (!lastCalmScoreSentTime || (now - lastCalmScoreSentTime > 2000)) {
                        lastCalmScoreSentTime = now;
                        try {
                            const pwd = typeof getActivePassword === 'function' ? getActivePassword() : 'qwe123';
                            const targetIps = getActiveTargetIps();
                            fetch('/api/noise/score', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ password: pwd, ips: targetIps, score: calmBarScore, state: 'pause' })
                            }).catch(() => {});
                        } catch (e) {}
                    }

                    if (lockBanner) {
                        lockBanner.classList.remove('hidden');
                        lockBanner.classList.remove('noise-penalty');
                        lockBanner.classList.remove('silence-accumulating');
                    }
                    if (lockCalmBarFill) {
                        lockCalmBarFill.classList.remove('penalty');
                        lockCalmBarFill.style.width = `${calmBarScore}%`;
                    }
                    if (lockCalmPercentBadge) {
                        lockCalmPercentBadge.textContent = `${calmBarScore}%`;
                        lockCalmPercentBadge.style.color = '#fbbf24';
                        lockCalmPercentBadge.style.borderColor = 'rgba(245, 158, 11, 0.4)';
                        lockCalmPercentBadge.style.background = 'rgba(245, 158, 11, 0.15)';
                    }
                    if (lockTitle) {
                        lockTitle.innerHTML = `<span style="color:#fbbf24;">⏸️ CONVERSAS DETECTADAS • BARRA PAUSADA</span>`;
                    }
                    if (lockCalmStatusText) {
                        lockCalmStatusText.innerHTML = `🤫 Conversas ativas (<strong style="color:#fbbf24;">${smoothedDb.toFixed(1)} dB</strong>). Silêncio abaixo de <strong style="color:#34d399;">${quietThreshold} dB</strong> para a barra avançar.`;
                    }
                    if (hudInfractionsBadge) {
                        hudInfractionsBadge.textContent = `⏸️ ${calmBarScore}%`;
                        hudInfractionsBadge.classList.add('locked');
                    }
                    updateDynamicBrowserTab(smoothedDb, false, true, calmBarScore);
                } else {
                    // 🤫 SALA EM SILÊNCIO REAL (< quietThreshold): Cada segundo preenche +5% (20s de silêncio contínuo para 100%)
                    calmBarScore = Math.min(100, calmBarScore + 5);

                    // Sincroniza o progresso positivo a cada ~1s com as estações dos alunos
                    const now = Date.now();
                    if (!lastCalmScoreSentTime || (now - lastCalmScoreSentTime > 1000)) {
                        lastCalmScoreSentTime = now;
                        try {
                            const pwd = typeof getActivePassword === 'function' ? getActivePassword() : 'qwe123';
                            const targetIps = getActiveTargetIps();
                            fetch('/api/noise/score', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ password: pwd, ips: targetIps, score: calmBarScore, state: 'silence' })
                            }).catch(() => {});
                        } catch (e) {}
                    }

                    if (lockBanner) {
                        lockBanner.classList.remove('hidden');
                        lockBanner.classList.remove('noise-penalty');
                        lockBanner.classList.add('silence-accumulating');
                    }
                    if (lockCalmBarFill) {
                        lockCalmBarFill.classList.remove('penalty');
                        lockCalmBarFill.style.width = `${calmBarScore}%`;
                    }
                    if (lockCalmPercentBadge) {
                        lockCalmPercentBadge.textContent = `${calmBarScore}%`;
                        lockCalmPercentBadge.style.color = '#34d399';
                        lockCalmPercentBadge.style.borderColor = 'rgba(16, 185, 129, 0.4)';
                        lockCalmPercentBadge.style.background = 'rgba(16, 185, 129, 0.15)';
                    }
                    if (lockTitle) {
                        lockTitle.innerHTML = `<span style="color:#34d399;">🤫 SALA EM SILÊNCIO • ENCHENDO BARRA (+5%/s)</span>`;
                    }
                    if (lockCalmStatusText) {
                        lockCalmStatusText.innerHTML = `🤫 Silêncio na sala (<strong style="color:#34d399;">${smoothedDb.toFixed(1)} dB</strong>)! Energia em <strong style="color:#34d399;">${calmBarScore}%</strong> (Meta: 100%).`;
                    }
                    if (hudInfractionsBadge) {
                        hudInfractionsBadge.textContent = `🤫 ${calmBarScore}%`;
                        hudInfractionsBadge.classList.add('locked');
                    }
                    updateDynamicBrowserTab(smoothedDb, false, true, calmBarScore);

                    // 🎯 META DE 100% ATINGIDA: Libera automaticamente as estações dos alunos!
                    if (calmBarScore >= 100) {
                        endLockdown(false);
                    }
                }
            }, 1000);
        }

        // Finaliza o travamento e desbloqueia os computadores
        async function endLockdown(isManual = false) {
            isCurrentlyLockedDown = false;
            calmBarScore = 0;
            lastInfractionTriggerTime = Date.now();
            noiseExceedStartTime = 0;
            if (lockdownInterval) {
                clearInterval(lockdownInterval);
                lockdownInterval = null;
            }
            if (lockBanner) {
                lockBanner.classList.add('hidden');
                lockBanner.classList.remove('noise-penalty');
                lockBanner.classList.remove('silence-accumulating');
            }
            if (lockCalmBarFill) {
                lockCalmBarFill.classList.remove('penalty');
                lockCalmBarFill.style.width = '0%';
            }
            updateDisciplineUI();

            try {
                const pwd = typeof getActivePassword === 'function' ? getActivePassword() : 'qwe123';
                const targetIps = getActiveTargetIps();
                fetch('/api/noise/unlock', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password: pwd, ips: targetIps })
                });
                showToast(
                    isManual
                        ? '🔓 Computadores dos alunos desbloqueados manualmente pelo professor.'
                        : '🎉 DESAFIO CONCLUÍDO! A Barra de Calma Coletiva atingiu 100% e os computadores foram liberados com sucesso!',
                    'success',
                    6000
                );
            } catch (e) {
                console.error('[Decibelímetro] Erro ao desbloquear:', e);
            }
        }

        // =========================================================================
        // 🔄 ZERAMENTO DE INFRAÇÕES DE RUÍDO (MANUAL E AUTOMÁTICO A CADA INÍCIO DE AULA)
        // =========================================================================
        let lastTrackedClassKey = localStorage.getItem('decibel_last_class_key') || '';
        let lastTrackedClassDate = localStorage.getItem('decibel_last_class_date') || '';

        function resetClassInfractions(source = 'manual', periodName = '') {
            classroomInfractionCount = 0;
            localStorage.setItem('decibel_classroom_infractions', '0');
            lastInfractionTriggerTime = 0;
            noiseExceedStartTime = 0;
            consecutiveQuietSeconds = 0;
            if (isCurrentlyLockedDown) {
                endLockdown(true);
            }
            updateDisciplineUI();
            
            if (source === 'auto') {
                showToast(`🔔 Início de aula (${periodName || 'Nova Aula'}): infrações de ruído zeradas automaticamente!`, 'info', 4000);
            } else {
                showToast('Nova aula iniciada: histórico de infrações de ruído zerado.', 'info', 3000);
            }
        }

        window.resetClassInfractions = resetClassInfractions;

        // Checagem contínua para zerar as infrações automaticamente sempre que iniciar uma nova aula / período
        function checkAutoResetOnClassStart() {
            const now = new Date();
            const todayStr = now.toISOString().split('T')[0];
            const currentHm = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

            // Se mudou o dia, zera automaticamente
            if (lastTrackedClassDate && lastTrackedClassDate !== todayStr) {
                lastTrackedClassDate = todayStr;
                localStorage.setItem('decibel_last_class_date', todayStr);
                localStorage.removeItem('decibel_last_class_key');
                lastTrackedClassKey = '';
                resetClassInfractions('auto', 'Nova Jornada');
                return;
            }
            if (!lastTrackedClassDate) {
                lastTrackedClassDate = todayStr;
                localStorage.setItem('decibel_last_class_date', todayStr);
            }

            // Obtém os períodos da escola ativa
            const periods = (typeof currentPeriodsData !== 'undefined' && currentPeriodsData && currentPeriodsData.length > 0)
                ? currentPeriodsData
                : (window.currentPeriodsData || []);

            if (!periods || periods.length === 0) {
                if (typeof loadScheduleConfig === 'function') {
                    loadScheduleConfig();
                }
                return;
            }

            for (const p of periods) {
                if (!p.start) continue;
                const pType = (p.type || '').toLowerCase();
                const pName = (p.name || '').toLowerCase();
                if (pType === 'recreio' || pType === 'intervalo' || pName.includes('recreio') || pName.includes('intervalo') || pName.includes('lanche')) {
                    continue;
                }
                
                const pStart = p.start;
                const pEnd = p.end || pStart;
                const classKey = `${todayStr}_${p.id || p.name}_${pStart}`;

                // Se o horário atual está dentro deste período escolar de aula
                if (currentHm >= pStart && currentHm < pEnd) {
                    if (lastTrackedClassKey !== classKey) {
                        const prevKey = lastTrackedClassKey;
                        lastTrackedClassKey = classKey;
                        localStorage.setItem('decibel_last_class_key', classKey);

                        // Nova aula iniciada! Zera as infrações registradas da aula anterior
                        resetClassInfractions('auto', p.name || 'Nova Aula');
                    }
                    break;
                }
            }
        }

        window.checkAutoResetOnClassStart = checkAutoResetOnClassStart;

        // Escuta eventos em tempo real via Socket.IO emitidos pelo daemon de horários
        try {
            const ds = (typeof getDashboardSocket === 'function') ? getDashboardSocket() : null;
            if (ds) {
                ds.on('schedule_class_started', (data) => {
                    const pName = data?.period_name || 'Nova Aula';
                    const pStart = data?.start || '';
                    const todayStr = new Date().toISOString().split('T')[0];
                    const newKey = `${todayStr}_${data?.period_id || pName}_${pStart}`;
                    if (lastTrackedClassKey !== newKey) {
                        lastTrackedClassKey = newKey;
                        localStorage.setItem('decibel_last_class_key', newKey);
                    }
                    resetClassInfractions('auto', pName);
                });
                ds.on('schedule_entry_triggered', (data) => {
                    resetClassInfractions('auto', data?.period_name || 'Início das Aulas');
                });
            }
        } catch (err) {
            console.warn('[Decibelímetro] Falha ao registrar listeners SocketIO de início de aula:', err);
        }

        // Executa imediatamente e a cada 5 segundos
        checkAutoResetOnClassStart();
        setInterval(checkAutoResetOnClassStart, 5000);

        // Sincroniza valor limite de alerta
        function setThresholdValue(val) {
            let num = parseInt(val, 10);
            if (isNaN(num)) num = 75;
            num = Math.max(30, Math.min(120, num));
            alertThreshold = num;

            if (thresholdInput) thresholdInput.value = num;
            if (thresholdNumberInput) thresholdNumberInput.value = num;
            if (thresholdDisplay) thresholdDisplay.textContent = `${num} dB`;

            presetChips.forEach(chip => {
                if (parseInt(chip.dataset.db, 10) === num) {
                    chip.classList.add('active');
                } else {
                    chip.classList.remove('active');
                }
            });

            localStorage.setItem('decibel_alert_threshold', alertThreshold);
            updateThresholdPosition();
        }

        // Sincroniza controles com configurações salvas
        setThresholdValue(alertThreshold);
        updateDisciplineUI();

        if (autoActionsToggle) {
            autoActionsToggle.checked = autoNetworkActionsEnabled;
            autoActionsToggle.addEventListener('change', (e) => {
                autoNetworkActionsEnabled = e.target.checked;
                localStorage.setItem('decibel_auto_actions_enabled', autoNetworkActionsEnabled);
            });
        }
        if (manualUnlockBtn) {
            manualUnlockBtn.addEventListener('click', () => endLockdown(true));
        }
        if (resetClassBtn) {
            resetClassBtn.addEventListener('click', () => resetClassInfractions('manual'));
        }
        const testWarnBtn = document.getElementById('decibel-test-warn-btn');
        if (testWarnBtn) {
            testWarnBtn.addEventListener('click', async () => {
                testWarnBtn.disabled = true;
                const origHtml = testWarnBtn.innerHTML;
                testWarnBtn.innerText = 'Enviando...';
                try {
                    // Se já estiver travado ou em 3+ infrações, zera primeiro para voltar ao 1º aviso
                    if (isCurrentlyLockedDown || classroomInfractionCount >= 3) {
                        isCurrentlyLockedDown = false;
                        if (lockdownInterval) {
                            clearInterval(lockdownInterval);
                            lockdownInterval = null;
                        }
                        if (lockBanner) lockBanner.classList.add('hidden');
                        classroomInfractionCount = 0;
                        localStorage.setItem('decibel_classroom_infractions', '0');
                        updateDisciplineUI();
                    }

                    lastInfractionTriggerTime = 0;
                    await triggerNoiseInfraction(true);
                } catch (e) {
                    console.error('[Decibelímetro] Erro no teste de aviso:', e);
                    showToast('Erro ao disparar teste: ' + (e.message || 'Erro'), 'error');
                } finally {
                    testWarnBtn.disabled = false;
                    testWarnBtn.innerHTML = origHtml;
                }
            });
        }
        const testLockBtn = document.getElementById('decibel-test-lock-btn');
        if (testLockBtn) {
            testLockBtn.addEventListener('click', async () => {
                testLockBtn.disabled = true;
                const origHtml = testLockBtn.innerHTML;
                testLockBtn.innerText = 'Travando...';
                try {
                    classroomInfractionCount = 3;
                    localStorage.setItem('decibel_classroom_infractions', '3');
                    updateDisciplineUI();
                    await startLockdown();
                } catch (e) {
                    console.error('[Decibelímetro] Erro no teste de bloqueio:', e);
                    showToast('Erro ao disparar bloqueio: ' + (e.message || 'Erro'), 'error');
                } finally {
                    testLockBtn.disabled = false;
                    testLockBtn.innerHTML = origHtml;
                }
            });
        }
        if (calibInput) {
            calibInput.value = calibrationOffset;
            if (calibDisplay) calibDisplay.textContent = `${calibrationOffset >= 0 ? '+' : ''}${calibrationOffset} dB`;
        }
        if (alertEnableToggle) alertEnableToggle.checked = isAlertEnabled;
        if (beepToggle) beepToggle.checked = isBeepEnabled;

        // Atualização dos marcadores visuais (Analógico, Digital e Barra de LED)
        function updateThresholdPosition() {
            if (thresholdMarker) {
                const percent = Math.min(100, Math.max(0, (alertThreshold / 110) * 100));
                thresholdMarker.style.left = `${percent}%`;
            }
            if (digitalLimitVal) {
                digitalLimitVal.textContent = `Limite: ${alertThreshold}dB`;
            }
            // Redesenha o mostrador analógico com a nova posição do marcador
            drawAnalogMeterDial(smoothedDb || 20, peakMarkerPos || 20, alertThreshold);
        }

        // Toca um bipe suave de aviso (Web Audio sintetizado)
        function playWarningBeep() {
            if (!isBeepEnabled) return;
            const now = Date.now();
            if (now - lastBeepTime < 2500) return; // Limita repetição a cada 2.5s
            lastBeepTime = now;

            try {
                const context = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
                if (context.state === 'suspended') {
                    context.resume();
                }
                const osc = context.createOscillator();
                const gain = context.createGain();

                osc.type = 'sine';
                osc.frequency.setValueAtTime(880, context.currentTime);
                osc.frequency.exponentialRampToValueAtTime(440, context.currentTime + 0.22);

                gain.gain.setValueAtTime(0.12, context.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.22);

                osc.connect(gain);
                gain.connect(context.destination);

                osc.start();
                osc.stop(context.currentTime + 0.24);
            } catch (err) {
                console.warn('[Decibelímetro] Erro ao emitir aviso sonoro:', err);
            }
        }

        const micErrorBanner = document.getElementById('decibel-mic-error-banner');
        const errorTitle = document.getElementById('decibel-error-title');
        const errorMsg = document.getElementById('decibel-error-msg');

        // Popula dispositivos de microfone disponíveis
        async function populateAudioDevices() {
            if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
            try {
                const devices = await navigator.mediaDevices.enumerateDevices();
                const audioInputs = devices.filter(d => d.kind === 'audioinput');
                if (!deviceSelect) return;

                const currentVal = selectedDeviceId || deviceSelect.value;
                deviceSelect.innerHTML = '<option value="">Microfone Padrão do Sistema</option>';

                audioInputs.forEach((dev, index) => {
                    const opt = document.createElement('option');
                    opt.value = dev.deviceId;
                    opt.textContent = dev.label || `Microfone ${index + 1}`;
                    if (dev.deviceId === currentVal) {
                        opt.selected = true;
                    }
                    deviceSelect.appendChild(opt);
                });
            } catch (e) {
                console.warn('[Decibelímetro] Não foi possível listar dispositivos:', e);
            }
        }

        // Inicia captura do microfone
        async function startMonitoring() {
            if (isMonitoring) return;

            // Esconde aviso de erro anterior
            if (micErrorBanner) micErrorBanner.classList.add('hidden');

            try {
                // Checa contexto seguro (localhost / 127.0.0.1 / https)
                const isSecure = window.isSecureContext || location.hostname === 'localhost' || location.hostname === '127.0.0.1';
                if (!isSecure && !navigator.mediaDevices) {
                    if (micErrorBanner) {
                        micErrorBanner.classList.remove('hidden');
                        if (errorTitle) errorTitle.textContent = 'Bloqueio de Segurança do Navegador (HTTP)';
                        if (errorMsg) errorMsg.innerHTML = `O microfone só pode ser acessado via <strong>http://localhost:5050</strong> ou <strong>http://127.0.0.1:5050</strong> no notebook. Você está acessando via <code>${location.origin}</code>.`;
                    }
                    showToast('Acesse via http://localhost:5050 para usar o microfone.', 'error', 8000);
                    return;
                }

                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                    if (micErrorBanner) {
                        micErrorBanner.classList.remove('hidden');
                        if (errorTitle) errorTitle.textContent = 'Recurso Não Suportado';
                        if (errorMsg) errorMsg.textContent = 'Seu navegador não suporta a API de captura de microfone (navigator.mediaDevices.getUserMedia).';
                    }
                    showToast('Navegador incompatível com captura de áudio.', 'error', 6000);
                    return;
                }

                const AudioContextClass = window.AudioContext || window.webkitAudioContext;
                if (!AudioContextClass) {
                    showToast('Seu navegador não suporta a Web Audio API.', 'error');
                    return;
                }

                // Cria o AudioContext e garante que está ativo (não suspenso)
                if (!audioCtx || audioCtx.state === 'closed') {
                    audioCtx = new AudioContextClass();
                }
                if (audioCtx.state === 'suspended') {
                    await audioCtx.resume();
                }

                // Restrições de áudio flexíveis
                const audioConstraints = {
                    audio: selectedDeviceId ? { deviceId: { exact: selectedDeviceId } } : true
                };

                micStream = await navigator.mediaDevices.getUserMedia(audioConstraints);

                sourceNode = audioCtx.createMediaStreamSource(micStream);
                analyser = audioCtx.createAnalyser();
                analyser.fftSize = 512; // Otimizado para baixo uso de CPU
                analyser.smoothingTimeConstant = 0.30;

                sourceNode.connect(analyser);

                // Heartbeat / Timer de 2º plano leve (12 Hz) para manter disciplina ativa quando minimizado
                if (backgroundAudioInterval) clearInterval(backgroundAudioInterval);
                backgroundAudioInterval = setInterval(() => {
                    if (isMonitoring) {
                        processDecibelAudio(false);
                    }
                }, 80);

                isMonitoring = true;
                if (micErrorBanner) micErrorBanner.classList.add('hidden');

                if (toggleMicBtn) {
                    toggleMicBtn.classList.add('recording');
                    if (toggleBtnLabel) toggleBtnLabel.textContent = 'Parar Captação';
                    const icon = toggleMicBtn.querySelector('i');
                    if (icon) {
                        icon.setAttribute('data-feather', 'mic-off');
                        if (window.feather) feather.replace();
                    }
                }
                if (liveDot) liveDot.classList.add('active');
                if (statusText) statusText.textContent = 'Monitorando em Tempo Real';
                if (openBtn) openBtn.classList.add('is-monitoring-active');
                if (hudLiveDot) hudLiveDot.classList.add('active');

                await populateAudioDevices();
                renderDecibelFrame();
                showToast('Microfone ativo! Monitoramento em andamento.', 'success', 2500);
            } catch (err) {
                console.error('[Decibelímetro] Erro ao acessar microfone:', err);
                let title = 'Erro ao Acessar Microfone';
                let msg = err.message || 'Não foi possível iniciar a captação de áudio.';

                if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
                    title = 'Permissão do Microfone Bloqueada';
                    msg = 'O acesso ao microfone foi recusado ou está bloqueado no navegador. Clique no ícone de configurações/cadeado na barra de endereços (URL), permita o Microfone e tente novamente.';
                } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
                    title = 'Nenhum Microfone Encontrado';
                    msg = 'Nenhum dispositivo de microfone foi encontrado no notebook/computador.';
                } else if (err.name === 'NotReadableError' || err.name === 'TrackStartError') {
                    title = 'Microfone Ocupado por Outro Programa';
                    msg = 'O microfone está sendo usado exclusivamente por outro aplicativo (Teams, Zoom, Discord, etc.).';
                }

                if (micErrorBanner) {
                    micErrorBanner.classList.remove('hidden');
                    if (errorTitle) errorTitle.textContent = title;
                    if (errorMsg) errorMsg.textContent = msg;
                }

                showToast(title + ': ' + msg, 'error', 8000);
                stopMonitoring();
            }
        }

        // Para captura e libera o microfone
        function stopMonitoring() {
            isMonitoring = false;
            if (animationFrameId) {
                cancelAnimationFrame(animationFrameId);
                animationFrameId = null;
            }

            if (backgroundAudioInterval) {
                clearInterval(backgroundAudioInterval);
                backgroundAudioInterval = null;
            }

            if (micStream) {
                micStream.getTracks().forEach(track => track.stop());
                micStream = null;
            }

            if (audioCtx && audioCtx.state !== 'closed') {
                try {
                    audioCtx.close();
                } catch (e) {}
                audioCtx = null;
            }

            if (toggleMicBtn) {
                toggleMicBtn.classList.remove('recording');
                if (toggleBtnLabel) toggleBtnLabel.textContent = 'Iniciar Captação';
                const icon = toggleMicBtn.querySelector('i');
                if (icon) {
                    icon.setAttribute('data-feather', 'mic');
                    if (window.feather) feather.replace();
                }
            }
            if (liveDot) liveDot.classList.remove('active');
            if (statusText) statusText.textContent = 'Microfone Inativo';
            if (heroCard) heroCard.classList.remove('noise-alerting');
            if (zoneBadge) {
                zoneBadge.className = 'decibel-zone-badge zone-idle';
                zoneBadge.textContent = 'Parado';
            }
            if (currentValEl) currentValEl.textContent = '--.-';
            if (meterBar) meterBar.style.width = '0%';
            drawAnalogMeterDial(20, 20, alertThreshold);

            if (openBtn) openBtn.classList.remove('is-monitoring-active');
            if (floatingHud) {
                floatingHud.classList.remove('noise-alerting');
                floatingHud.classList.add('hidden');
            }
            if (hudLiveDot) hudLiveDot.classList.remove('active');
            if (hudCurrentVal) hudCurrentVal.textContent = '--.-';
            if (hudZoneBadge) {
                hudZoneBadge.className = 'decibel-hud-badge zone-idle';
                hudZoneBadge.textContent = 'Parado';
            }
            updateDynamicBrowserTab(0, false, false, 0);
        }

        // =========================================================================
        // 🏷️ INDICADOR DINÂMICO NA ABA DO NAVEGADOR (FAVICON & TÍTULO)
        // =========================================================================
        const defaultPageTitle = document.title || 'Gerenciador de Atalhos';
        const dynamicFaviconEl = document.getElementById('dynamic-app-favicon');
        const originalFaviconHref = dynamicFaviconEl ? dynamicFaviconEl.getAttribute('href') : 'logo.png';
        let faviconCanvas = null;
        let faviconCtx = null;
        let lastFaviconState = '';
        let lastTabUpdate = 0;

        function updateDynamicBrowserTab(currentDb, isExceed, isLocked, remainingSec) {
            const now = Date.now();
            if (!isMonitoring) {
                if (document.title !== defaultPageTitle) {
                    document.title = defaultPageTitle;
                }
                if (dynamicFaviconEl && dynamicFaviconEl.getAttribute('href') !== originalFaviconHref) {
                    dynamicFaviconEl.setAttribute('href', originalFaviconHref);
                }
                return;
            }

            // Limita a frequência de atualização de título (exceto na transição de alerta)
            if (now - lastTabUpdate < 400 && !isExceed && !isLocked) return;
            lastTabUpdate = now;

            // 1. Atualização do Título da Aba
            if (isLocked) {
                document.title = `[🔒 ${remainingSec}s TRAVADO] ${defaultPageTitle}`;
            } else if (isExceed) {
                document.title = `[🚨 ${currentDb.toFixed(1)} dB EXCESSO!] ${defaultPageTitle}`;
            } else if (currentDb < 45) {
                document.title = `[🤫 ${currentDb.toFixed(1)} dB] ${defaultPageTitle}`;
            } else if (currentDb < 65) {
                document.title = `[🟢 ${currentDb.toFixed(1)} dB] ${defaultPageTitle}`;
            } else if (currentDb < 78) {
                document.title = `[🟡 ${currentDb.toFixed(1)} dB] ${defaultPageTitle}`;
            } else {
                document.title = `[🟠 ${currentDb.toFixed(1)} dB] ${defaultPageTitle}`;
            }

            // 2. Atualização Leve do Ícone (Favicon apenas em mudança real de estado)
            if (!dynamicFaviconEl) return;

            const stateKey = isLocked
                ? 'locked'
                : isExceed
                ? 'alert'
                : currentDb < 45
                ? 'quiet'
                : currentDb < 65
                ? 'normal'
                : 'warn';

            if (stateKey === lastFaviconState) return;
            lastFaviconState = stateKey;

            if (!faviconCanvas) {
                faviconCanvas = document.createElement('canvas');
                faviconCanvas.width = 32;
                faviconCanvas.height = 32;
                faviconCtx = faviconCanvas.getContext('2d');
            }

            faviconCtx.clearRect(0, 0, 32, 32);

            if (isExceed || isLocked) {
                faviconCtx.beginPath();
                faviconCtx.arc(16, 16, 14, 0, Math.PI * 2);
                faviconCtx.fillStyle = '#ef4444';
                faviconCtx.fill();
                faviconCtx.strokeStyle = '#ffffff';
                faviconCtx.lineWidth = 2.5;
                faviconCtx.stroke();

                faviconCtx.fillStyle = '#ffffff';
                faviconCtx.font = 'bold 18px Arial, sans-serif';
                faviconCtx.textAlign = 'center';
                faviconCtx.textBaseline = 'middle';
                faviconCtx.fillText(isLocked ? '🔒' : '!', 16, 17);
            } else {
                let color = '#10b981';
                if (currentDb >= 65 && currentDb < 78) color = '#f59e0b';
                else if (currentDb >= 78) color = '#f97316';

                faviconCtx.beginPath();
                faviconCtx.arc(16, 16, 14, 0, Math.PI * 2);
                faviconCtx.fillStyle = '#0f172a';
                faviconCtx.fill();
                faviconCtx.strokeStyle = color;
                faviconCtx.lineWidth = 3;
                faviconCtx.stroke();

                faviconCtx.beginPath();
                faviconCtx.arc(16, 16, 6, 0, Math.PI * 2);
                faviconCtx.fillStyle = color;
                faviconCtx.fill();
            }

            try {
                dynamicFaviconEl.href = faviconCanvas.toDataURL('image/png');
            } catch (e) {}
        }

        // Processamento Central de Áudio, Decibéis e Regras Disciplinares
        function processDecibelAudio(forceUiUpdate = false) {
            if (!isMonitoring || !analyser) return;

            const now = Date.now();
            if (!forceUiUpdate && (now - lastAudioProcessTime < 30)) return;
            lastAudioProcessTime = now;

            const bufferLength = analyser.fftSize;
            const timeData = new Uint8Array(bufferLength);
            analyser.getByteTimeDomainData(timeData);

            // Calcula Root Mean Square (RMS)
            let sumSquares = 0;
            for (let i = 0; i < bufferLength; i++) {
                const sample = (timeData[i] - 128) * 0.0078125; // [-1.0, 1.0]
                sumSquares += sample * sample;
            }
            const rms = Math.sqrt(sumSquares / bufferLength);

            // Estimativa de decibéis SPL
            let currentInstantDb = 30;
            if (rms > 0.001) {
                const rawDb = 20 * Math.log10(rms);
                currentInstantDb = rawDb + 95 + calibrationOffset;
            } else {
                currentInstantDb = 30 + calibrationOffset;
            }

            currentInstantDb = Math.max(25, Math.min(125, currentInstantDb));

            // Suavização
            if (smoothedDb === 0) {
                smoothedDb = currentInstantDb;
            } else {
                smoothedDb = (smoothedDb * 0.65) + (currentInstantDb * 0.35);
            }

            // Atualiza estatísticas (Mín, Máx, Média)
            if (smoothedDb > 25) {
                minDb = Math.min(minDb, smoothedDb);
                maxDb = Math.max(maxDb, smoothedDb);
                dbSum += smoothedDb;
                dbSampleCount++;
            }

            // Categorização do Nível de Ruído (Zonas)
            let zoneClass = 'zone-quiet';
            let zoneLabel = 'Silencioso / Estudo';
            let hudZoneText = 'Silêncio';

            if (smoothedDb < 45) {
                zoneClass = 'zone-quiet';
                zoneLabel = 'Silencioso / Estudo';
                hudZoneText = 'Silêncio';
            } else if (smoothedDb < 65) {
                zoneClass = 'zone-normal';
                zoneLabel = 'Normal / Conversa';
                hudZoneText = 'Normal';
            } else if (smoothedDb < 78) {
                zoneClass = 'zone-moderate';
                zoneLabel = 'Ruído Moderado';
                hudZoneText = 'Moderado';
            } else if (smoothedDb < 88) {
                zoneClass = 'zone-loud';
                zoneLabel = 'Barulhento';
                hudZoneText = 'Alto';
            } else {
                zoneClass = 'zone-critical';
                zoneLabel = 'Barulho Excessivo';
                hudZoneText = 'Excessivo';
            }

            // Nível do Semáforo Pedagógico
            let trafficLevel = 'green';
            if (smoothedDb >= alertThreshold) {
                trafficLevel = 'red';
            } else if (smoothedDb >= (alertThreshold - 10)) {
                trafficLevel = 'yellow';
            } else {
                trafficLevel = 'green';
            }
            updateTrafficLightVisual(trafficLevel, smoothedDb);
            if (isStudentTrafficLightEnabled) {
                syncTrafficLightToStudents(trafficLevel, smoothedDb);
            }

            // Checagem de Limite de Alerta de Sala de Aula
            const isExceeding = isAlertEnabled && (smoothedDb >= alertThreshold);
            if (isExceeding) {
                zoneClass = 'zone-critical';
                zoneLabel = `⚠️ Excesso (> ${alertThreshold} dB)`;
                hudZoneText = '🚨 Excesso';

                lastExceedTime = now;
                if (!isCurrentlyInAlert || !noiseExceedStartTime) {
                    isCurrentlyInAlert = true;
                    alertCount++;
                    if (alertCountEl) alertCountEl.textContent = alertCount;
                    noiseExceedStartTime = now;
                }

                const continuousDuration = now - noiseExceedStartTime;

                if (autoSilenceAlertEnabled && continuousDuration >= (silenceContinuousDurationSec * 1000)) {
                    triggerContinuousSilenceAlert();
                }

                if (continuousDuration >= 600 || smoothedDb >= alertThreshold + 2) {
                    triggerNoiseInfraction();
                }

                if (heroCard) heroCard.classList.add('noise-alerting');
                playWarningBeep();
            } else {
                if (now - lastExceedTime >= 800) {
                    isCurrentlyInAlert = false;
                    noiseExceedStartTime = 0;
                    if (heroCard) heroCard.classList.remove('noise-alerting');
                }
            }

            // Throttling de renderização visual no DOM (máx ~30 FPS para manter fluidez sem engasgar o browser)
            const shouldRenderUi = forceUiUpdate || (now - lastUiRenderTime >= 32);
            if (shouldRenderUi) {
                lastUiRenderTime = now;
                const displayDb = smoothedDb.toFixed(1);

                if (avgValEl && dbSampleCount > 0) avgValEl.textContent = `${(dbSum / dbSampleCount).toFixed(1)} dB`;
                if (maxValEl) maxValEl.textContent = `${maxDb.toFixed(1)} dB`;
                if (minValEl && minDb < 900) minValEl.textContent = `${minDb.toFixed(1)} dB`;

                const isModalOpen = modal && !modal.classList.contains('hidden');
                if (isModalOpen) {
                    if (currentValEl) currentValEl.textContent = displayDb;

                    // 1. Atualização do Mostrador Analógico VU (Agulha, Pico e Limite)
                    if (smoothedDb > peakMarkerPos) {
                        peakMarkerPos = smoothedDb;
                    } else {
                        peakMarkerPos = Math.max(20, peakMarkerPos - 0.35);
                    }
                    drawAnalogMeterDial(smoothedDb, peakMarkerPos, alertThreshold);

                    // 2. Barra Compacta de Micro-LEDs Digitais
                    if (ledSegElements && ledSegElements.length > 0) {
                        const totalSegs = ledSegElements.length;
                        for (let i = 0; i < totalSegs; i++) {
                            const segDb = 20 + (i / (totalSegs - 1)) * 100;
                            const isLit = smoothedDb >= segDb;
                            const isPeak = Math.abs(peakMarkerPos - segDb) < (100 / totalSegs * 0.85);
                            const isThresh = Math.abs(alertThreshold - segDb) < (100 / totalSegs * 0.6);
                            
                            const seg = ledSegElements[i];
                            seg.classList.toggle('lit', isLit);
                            seg.classList.toggle('is-peak', isPeak);
                            seg.classList.toggle('is-threshold', isThresh);
                        }
                    }

                    if (zoneBadge) {
                        zoneBadge.className = `decibel-zone-badge ${zoneClass}`;
                        zoneBadge.textContent = zoneLabel;
                    }

                    // Renderiza o Gráfico Canvas apenas se o modal estiver visível E na aba Monitor
                    if (activeDecibelTab === 'monitor') {
                        drawCanvasGraph(timeData);
                    }
                }

                // Atualiza o Floating HUD quando o modal estiver minimizado
                const isHudOpen = floatingHud && !floatingHud.classList.contains('hidden');
                if (isHudOpen) {
                    if (hudCurrentVal) hudCurrentVal.textContent = displayDb;
                    if (hudZoneBadge) {
                        hudZoneBadge.className = `decibel-hud-badge ${zoneClass}`;
                        hudZoneBadge.textContent = hudZoneText;
                    }
                    if (isExceeding) {
                        floatingHud.classList.add('noise-alerting');
                    } else {
                        floatingHud.classList.remove('noise-alerting');
                    }
                }

                // Atualiza a aba do navegador
                updateDynamicBrowserTab(smoothedDb, isExceeding, isCurrentlyLockedDown, lockdownRemainingSeconds);
            }

            // Histórico para o Canvas
            historyPoints.push(smoothedDb);
            if (historyPoints.length > historyMaxPoints) {
                historyPoints.shift();
            }

            // Gravação Periódica no Banco de Dados SQLite (a cada 5 segundos)
            if (now - lastDbLogTime >= 5000) {
                lastDbLogTime = now;
                logNoiseReadingToBackend(smoothedDb, peakValue, isExceeding);
            }

            return timeData;
        }

        // Loop de processamento de áudio a 60 FPS quando o navegador está em primeiro plano
        function renderDecibelFrame() {
            if (!isMonitoring || !analyser) return;
            processDecibelAudio(true);
            animationFrameId = requestAnimationFrame(renderDecibelFrame);
        }

        // Cache de gradientes do Canvas para não alocar objetos a cada frame
        let cachedCanvasW = 0;
        let cachedCanvasH = 0;
        let cachedLineGrad = null;
        let cachedFillGrad = null;

        // Desenha o gráfico de histórico e onda de ruído no Canvas (Ultra Otimizado)
        function drawCanvasGraph(timeData) {
            if (!ctx || !canvas) return;

            const width = canvas.width;
            const height = canvas.height;

            if (cachedCanvasW !== width || cachedCanvasH !== height || !cachedLineGrad) {
                cachedCanvasW = width;
                cachedCanvasH = height;
                cachedLineGrad = ctx.createLinearGradient(0, height, 0, 0);
                cachedLineGrad.addColorStop(0, 'rgba(16, 185, 129, 0.85)');
                cachedLineGrad.addColorStop(0.5, 'rgba(56, 189, 248, 0.9)');
                cachedLineGrad.addColorStop(0.8, 'rgba(245, 158, 11, 0.9)');
                cachedLineGrad.addColorStop(1, 'rgba(239, 68, 68, 1)');

                cachedFillGrad = ctx.createLinearGradient(0, height, 0, 0);
                cachedFillGrad.addColorStop(0, 'rgba(16, 185, 129, 0.08)');
                cachedFillGrad.addColorStop(0.6, 'rgba(56, 189, 248, 0.16)');
                cachedFillGrad.addColorStop(1, 'rgba(239, 68, 68, 0.28)');
            }

            ctx.clearRect(0, 0, width, height);

            // Subamostragem da forma de onda (64 pontos para desempenho instantâneo)
            if (timeData && timeData.length > 0) {
                ctx.beginPath();
                ctx.strokeStyle = 'rgba(56, 189, 248, 0.22)';
                ctx.lineWidth = 1.5;
                const sampleSteps = 64;
                const sampleInterval = Math.floor(timeData.length / sampleSteps) || 1;
                const sliceW = width / (sampleSteps - 1);

                for (let i = 0; i < sampleSteps; i++) {
                    const sampleIdx = Math.min(timeData.length - 1, i * sampleInterval);
                    const v = timeData[sampleIdx] / 128.0;
                    const waveY = (v * height) / 2;
                    const waveX = i * sliceW;
                    if (i === 0) {
                        ctx.moveTo(waveX, waveY);
                    } else {
                        ctx.lineTo(waveX, waveY);
                    }
                }
                ctx.stroke();
            }

            // Linha de grade do Limite de Alerta (Threshold)
            if (isAlertEnabled) {
                const thresholdY = height - ((alertThreshold / 110) * height);
                ctx.save();
                ctx.setLineDash([4, 4]);
                ctx.strokeStyle = 'rgba(239, 68, 68, 0.65)';
                ctx.lineWidth = 1.2;
                ctx.beginPath();
                ctx.moveTo(0, thresholdY);
                ctx.lineTo(width, thresholdY);
                ctx.stroke();

                ctx.fillStyle = 'rgba(239, 68, 68, 0.85)';
                ctx.font = '10px JetBrains Mono, sans-serif';
                ctx.fillText(`Limite ${alertThreshold} dB`, width - 85, Math.max(12, thresholdY - 4));
                ctx.restore();
            }

            if (historyPoints.length < 2) return;

            const step = width / (historyMaxPoints - 1);

            // Traça área preenchida
            ctx.beginPath();
            ctx.moveTo(0, height);

            for (let i = 0; i < historyPoints.length; i++) {
                const x = i * step;
                const db = historyPoints[i];
                const y = height - ((db / 110) * height);
                ctx.lineTo(x, y);
            }

            const lastX = (historyPoints.length - 1) * step;
            ctx.lineTo(lastX, height);
            ctx.closePath();
            ctx.fillStyle = cachedFillGrad;
            ctx.fill();

            // Traça a linha do gráfico de histórico
            ctx.beginPath();
            for (let i = 0; i < historyPoints.length; i++) {
                const x = i * step;
                const db = historyPoints[i];
                const y = height - ((db / 110) * height);
                if (i === 0) {
                    ctx.moveTo(x, y);
                } else {
                    ctx.lineTo(x, y);
                }
            }
            ctx.strokeStyle = cachedLineGrad;
            ctx.lineWidth = 2.2;
            ctx.lineJoin = 'round';
            ctx.stroke();

            // Ponto indicador final
            const curY = height - ((smoothedDb / 110) * height);
            ctx.beginPath();
            ctx.arc(lastX, curY, 3.5, 0, Math.PI * 2);
            ctx.fillStyle = smoothedDb >= alertThreshold && isAlertEnabled ? '#ef4444' : '#10b981';
            ctx.fill();
        }

        // Resetar estatísticas
        function resetStats() {
            minDb = 999;
            maxDb = 0;
            dbSum = 0;
            dbSampleCount = 0;
            alertCount = 0;
            peakMarkerPos = 20;
            needlePhysAngle = -Math.PI / 2 - (65 * Math.PI / 180);
            peakPhysAngle = -Math.PI / 2 - (65 * Math.PI / 180);
            historyPoints.length = 0;

            if (avgValEl) avgValEl.textContent = '-- dB';
            if (maxValEl) maxValEl.textContent = '-- dB';
            if (minValEl) minValEl.textContent = '-- dB';
            if (alertCountEl) alertCountEl.textContent = '0';
            if (heroCard) heroCard.classList.remove('noise-alerting');
            drawCanvasGraph();
            drawAnalogMeterDial(20, 20, alertThreshold);
            showToast('Estatísticas do decibelímetro reiniciadas.', 'info', 2000);
        }

        // Drag and Drop do Widget Flutuante (Floating HUD)
        function initHudDragAndDrop() {
            if (!floatingHud || !hudDragHandle) return;

            let isDragging = false;
            let startX = 0;
            let startY = 0;
            let initialLeft = 0;
            let initialTop = 0;

            function onDragStart(clientX, clientY) {
                isDragging = true;
                const rect = floatingHud.getBoundingClientRect();
                startX = clientX;
                startY = clientY;
                initialLeft = rect.left;
                initialTop = rect.top;

                floatingHud.style.bottom = 'auto';
                floatingHud.style.right = 'auto';
                floatingHud.style.left = `${initialLeft}px`;
                floatingHud.style.top = `${initialTop}px`;
                floatingHud.style.transition = 'none';
            }

            function onDragMove(clientX, clientY) {
                if (!isDragging) return;
                const dx = clientX - startX;
                const dy = clientY - startY;

                let newLeft = initialLeft + dx;
                let newTop = initialTop + dy;

                const maxLeft = Math.max(10, window.innerWidth - floatingHud.offsetWidth - 10);
                const maxTop = Math.max(10, window.innerHeight - floatingHud.offsetHeight - 10);

                newLeft = Math.max(10, Math.min(maxLeft, newLeft));
                newTop = Math.max(10, Math.min(maxTop, newTop));

                floatingHud.style.left = `${newLeft}px`;
                floatingHud.style.top = `${newTop}px`;
            }

            function onDragEnd() {
                if (!isDragging) return;
                isDragging = false;
                floatingHud.style.transition = '';
                localStorage.setItem('decibel_hud_left', floatingHud.style.left);
                localStorage.setItem('decibel_hud_top', floatingHud.style.top);
            }

            // Mouse events
            hudDragHandle.addEventListener('mousedown', (e) => {
                onDragStart(e.clientX, e.clientY);
                const onMouseMove = (ev) => onDragMove(ev.clientX, ev.clientY);
                const onMouseUp = () => {
                    onDragEnd();
                    document.removeEventListener('mousemove', onMouseMove);
                    document.removeEventListener('mouseup', onMouseUp);
                };
                document.addEventListener('mousemove', onMouseMove);
                document.addEventListener('mouseup', onMouseUp);
                e.preventDefault();
            });

            // Touch events
            hudDragHandle.addEventListener('touchstart', (e) => {
                if (e.touches.length !== 1) return;
                onDragStart(e.touches[0].clientX, e.touches[0].clientY);
            }, { passive: true });

            hudDragHandle.addEventListener('touchmove', (e) => {
                if (!isDragging || e.touches.length !== 1) return;
                onDragMove(e.touches[0].clientX, e.touches[0].clientY);
                e.preventDefault();
            }, { passive: false });

            hudDragHandle.addEventListener('touchend', onDragEnd, { passive: true });
        }

        function applySavedHudPosition() {
            if (!floatingHud) return;
            const savedLeft = localStorage.getItem('decibel_hud_left');
            const savedTop = localStorage.getItem('decibel_hud_top');

            if (savedLeft && savedTop) {
                const leftNum = parseInt(savedLeft, 10);
                const topNum = parseInt(savedTop, 10);
                if (!isNaN(leftNum) && !isNaN(topNum)) {
                    const maxLeft = window.innerWidth - 220;
                    const maxTop = window.innerHeight - 80;
                    if (leftNum < maxLeft && topNum < maxTop && leftNum >= 0 && topNum >= 0) {
                        floatingHud.style.bottom = 'auto';
                        floatingHud.style.right = 'auto';
                        floatingHud.style.left = `${leftNum}px`;
                        floatingHud.style.top = `${topNum}px`;
                        return;
                    }
                }
            }
            floatingHud.style.left = '';
            floatingHud.style.top = '';
            floatingHud.style.bottom = '24px';
            floatingHud.style.right = '24px';
        }

        initHudDragAndDrop();

        function openDecibelModal() {
            if (floatingHud) floatingHud.classList.add('hidden');
            if (modal) {
                modal.classList.remove('hidden');
                populateAudioDevices();
                updateThresholdPosition();
                updateDisciplineUI();
                drawAnalogMeterDial(smoothedDb || 20, peakMarkerPos || 20, alertThreshold);
                switchDecibelTab(activeDecibelTab || 'monitor');
                if (window.feather) feather.replace();
                // Inicia monitoramento automaticamente ao abrir para conveniência
                if (!isMonitoring) {
                    startMonitoring();
                }
            }
        }

        function minimizeDecibelModal() {
            if (!isMonitoring) {
                startMonitoring();
            }
            if (modal) modal.classList.add('hidden');
            if (floatingHud) {
                floatingHud.classList.remove('hidden');
                applySavedHudPosition();
                if (window.feather) feather.replace();
            }
            if (openBtn) openBtn.classList.add('is-monitoring-active');
            showToast('🎙️ Decibelímetro minimizado! Monitoramento e regras continuam ativos em 2º plano.', 'info', 3500);
        }

        function restoreDecibelModal() {
            if (floatingHud) floatingHud.classList.add('hidden');
            if (modal) {
                modal.classList.remove('hidden');
                populateAudioDevices();
                updateThresholdPosition();
                updateDisciplineUI();
                drawAnalogMeterDial(smoothedDb || 20, peakMarkerPos || 20, alertThreshold);
                switchDecibelTab(activeDecibelTab || 'monitor');
                if (window.feather) feather.replace();
            }
        }

        function closeModal() {
            if (isMonitoring) {
                minimizeDecibelModal();
            } else {
                if (modal) modal.classList.add('hidden');
                if (floatingHud) floatingHud.classList.add('hidden');
            }
        }

        function stopAndCloseDecibel() {
            stopMonitoring();
            if (modal) modal.classList.add('hidden');
            if (floatingHud) floatingHud.classList.add('hidden');
            if (openBtn) openBtn.classList.remove('is-monitoring-active');
            showToast('⏹️ Monitoramento de decibéis encerrado.', 'info', 2500);
        }

        window.openDecibelModal = openDecibelModal;
        window.minimizeDecibelModal = minimizeDecibelModal;
        window.restoreDecibelModal = restoreDecibelModal;
        window.closeDecibelModal = closeModal;
        window.stopAndCloseDecibel = stopAndCloseDecibel;

        // Eventos dos Controles
        if (openBtn) {
            openBtn.addEventListener('click', () => {
                if (modal && !modal.classList.contains('hidden')) {
                    minimizeDecibelModal();
                } else {
                    openDecibelModal();
                }
            });
        }

        if (minimizeBtn) minimizeBtn.addEventListener('click', minimizeDecibelModal);
        if (minimizeFooterBtn) minimizeFooterBtn.addEventListener('click', minimizeDecibelModal);
        if (closeBtn) closeBtn.addEventListener('click', closeModal);
        if (cancelBtn) cancelBtn.addEventListener('click', closeModal);

        // Ações do Widget Flutuante (Floating HUD)
        if (hudExpandTrigger) hudExpandTrigger.addEventListener('click', restoreDecibelModal);
        if (hudExpandBtn) hudExpandBtn.addEventListener('click', restoreDecibelModal);
        if (hudStopBtn) hudStopBtn.addEventListener('click', stopAndCloseDecibel);
        if (hudSilenceBtn) hudSilenceBtn.addEventListener('click', () => {
            triggerContinuousSilenceAlert();
        });

        if (modal) {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) closeModal();
            });
        }

        if (toggleMicBtn) {
            toggleMicBtn.addEventListener('click', () => {
                if (isMonitoring) {
                    stopMonitoring();
                } else {
                    startMonitoring();
                }
            });
        }

        if (resetStatsBtn) {
            resetStatsBtn.addEventListener('click', resetStats);
        }

        if (thresholdInput) {
            thresholdInput.addEventListener('input', (e) => {
                setThresholdValue(e.target.value);
            });
        }

        if (thresholdNumberInput) {
            thresholdNumberInput.addEventListener('input', (e) => {
                setThresholdValue(e.target.value);
            });
            thresholdNumberInput.addEventListener('change', (e) => {
                setThresholdValue(e.target.value);
            });
        }

        presetChips.forEach(chip => {
            chip.addEventListener('click', () => {
                const dbVal = chip.dataset.db;
                if (dbVal) {
                    setThresholdValue(dbVal);
                }
            });
        });

        if (alertEnableToggle) {
            alertEnableToggle.addEventListener('change', (e) => {
                isAlertEnabled = e.target.checked;
                localStorage.setItem('decibel_alert_enabled', isAlertEnabled);
                if (!isAlertEnabled && heroCard) {
                    heroCard.classList.remove('noise-alerting');
                }
            });
        }

        if (beepToggle) {
            beepToggle.addEventListener('change', (e) => {
                isBeepEnabled = e.target.checked;
                localStorage.setItem('decibel_beep_enabled', isBeepEnabled);
            });
        }

        if (calibInput) {
            calibInput.addEventListener('input', (e) => {
                calibrationOffset = parseInt(e.target.value, 10);
                if (calibDisplay) {
                    calibDisplay.textContent = `${calibrationOffset >= 0 ? '+' : ''}${calibrationOffset} dB`;
                }
                localStorage.setItem('decibel_calib_offset', calibrationOffset);
            });
        }

        // =========================================================================
        // 🎯 AUTO-CALIBRAÇÃO INTELIGENTE DE AMBIENTE (SMART AUTO-CALIBRATION)
        // =========================================================================
        let isCalibrating = false;
        async function runSmartAutoCalibration() {
            if (isCalibrating) return;

            // Se o microfone não estiver monitorando, inicia automaticamente
            if (!isMonitoring) {
                await startMonitoring();
            }
            if (!isMonitoring) {
                showToast('Inicie a captação do microfone para calibrar o ambiente.', 'warning');
                return;
            }

            isCalibrating = true;
            if (autoCalibBtn) {
                autoCalibBtn.classList.add('calibrating');
                autoCalibBtn.disabled = true;
            }
            if (calibFeedbackBox) {
                calibFeedbackBox.classList.remove('hidden');
            }
            if (calibFeedbackText) {
                calibFeedbackText.innerHTML = '🎯 <strong>Medindo ruído ambiente da sala...</strong> Por favor, permaneçam em silêncio natural por 3 segundos.';
            }

            const samples = [];
            let remainingMs = 3000;
            const sampleInterval = setInterval(() => {
                if (smoothedDb > 20) {
                    samples.push(smoothedDb);
                }
                remainingMs -= 100;
                const remainingSec = Math.max(0, (remainingMs / 1000)).toFixed(1);
                if (autoCalibBtnLabel && remainingMs > 0) {
                    autoCalibBtnLabel.textContent = `Medindo (${remainingSec}s)...`;
                }

                if (remainingMs <= 0) {
                    clearInterval(sampleInterval);
                    finishCalibration();
                }
            }, 100);

            function finishCalibration() {
                isCalibrating = false;
                if (autoCalibBtn) {
                    autoCalibBtn.classList.remove('calibrating');
                    autoCalibBtn.disabled = false;
                }
                if (autoCalibBtnLabel) {
                    autoCalibBtnLabel.textContent = 'Calibrar Sala Agora (3s)';
                }

                if (samples.length < 5) {
                    if (calibFeedbackText) {
                        calibFeedbackText.innerHTML = '⚠️ Poucas amostras coletadas. Tente novamente.';
                    }
                    return;
                }

                // Ordena amostras e calcula média descartando extremos (Trimmed Mean)
                samples.sort((a, b) => a - b);
                const trimCount = Math.floor(samples.length * 0.15);
                const trimmed = samples.slice(trimCount, samples.length - trimCount);
                const basalDb = trimmed.reduce((acc, v) => acc + v, 0) / trimmed.length;

                // Determina limite de alerta ideal para a sala de aula:
                // Basal + 26 dB (com folga para conversas pedagógicas e corte para bagunça)
                let idealThreshold = Math.round(basalDb + 26);
                idealThreshold = Math.max(55, Math.min(90, idealThreshold));

                // Aplica o novo limite calibrado
                setThresholdValue(idealThreshold);

                if (calibFeedbackText) {
                    calibFeedbackText.innerHTML = `✅ <strong>Calibração Concluída com Sucesso!</strong><br>` +
                        `• Ruído natural basal detectado: <strong>${basalDb.toFixed(1)} dB</strong><br>` +
                        `• Limite de tolerância ajustado automaticamente para: <strong style="color:#fbbf24; font-size:0.85rem;">${idealThreshold} dB</strong> (ideal para a dinâmica desta sala).`;
                }

                showToast(`🎯 Sala calibrada! Limite de ruído ajustado para ${idealThreshold} dB.`, 'success', 5000);
            }
        }

        if (autoCalibBtn) {
            autoCalibBtn.addEventListener('click', runSmartAutoCalibration);
        }

        if (deviceSelect) {
            deviceSelect.addEventListener('change', (e) => {
                selectedDeviceId = e.target.value;
                localStorage.setItem('decibel_device_id', selectedDeviceId);
                if (isMonitoring) {
                    stopMonitoring();
                    startMonitoring();
                }
            });
        }

        const autoSilenceToggle = document.getElementById('decibel-auto-silence-alert-toggle');
        if (autoSilenceToggle) {
            autoSilenceToggle.checked = autoSilenceAlertEnabled;
            autoSilenceToggle.addEventListener('change', (e) => {
                autoSilenceAlertEnabled = e.target.checked;
                localStorage.setItem('decibel_auto_silence_enabled', autoSilenceAlertEnabled);
            });
        }

        const silenceDurationSelect = document.getElementById('decibel-silence-duration-select');
        if (silenceDurationSelect) {
            silenceDurationSelect.value = silenceContinuousDurationSec;
            silenceDurationSelect.addEventListener('change', (e) => {
                silenceContinuousDurationSec = parseInt(e.target.value, 10) || 3;
                localStorage.setItem('decibel_silence_duration', silenceContinuousDurationSec);
            });
        }

        const testSilenceBtn = document.getElementById('decibel-test-silence-btn');
        if (testSilenceBtn) {
            testSilenceBtn.addEventListener('click', async () => {
                testSilenceBtn.disabled = true;
                testSilenceBtn.innerText = 'Enviando...';
                try {
                    const pwd = typeof getActivePassword === 'function' ? getActivePassword() : 'qwe123';
                    const resp = await fetch('/api/noise/silence', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            threshold: alertThreshold,
                            password: pwd,
                            message: "🤫 O professor solicitou silêncio imediato e atenção de todos na sala de aula."
                        })
                    });
                    const res = await resp.json();
                    if (res.success) {
                        showToast(`🤫 Alerta "Pedir Silêncio" disparado com sucesso para ${res.delivered_count || 'todas as'} máquinas!`, 'success', 5000);
                    } else {
                        showToast('Falha ao disparar silêncio: ' + (res.message || 'Erro'), 'error');
                    }
                } catch (e) {
                    showToast('Erro de rede ao disparar alerta de silêncio.', 'error');
                } finally {
                    testSilenceBtn.disabled = false;
                    testSilenceBtn.innerText = '🤫 Disparar "Pedir Silêncio" Agora';
                }
            });
        }

        // Listeners do Semáforo no Monitor do Aluno & Gamificação
        if (studentTrafficLightToggle) {
            studentTrafficLightToggle.checked = isStudentTrafficLightEnabled;
            studentTrafficLightToggle.addEventListener('change', (e) => {
                isStudentTrafficLightEnabled = e.target.checked;
                localStorage.setItem('decibel_traffic_light_enabled', isStudentTrafficLightEnabled ? 'true' : 'false');
                if (isStudentTrafficLightEnabled) {
                    syncTrafficLightToStudents(currentTrafficLevel, smoothedDb, true);
                    showToast('🚦 Semáforo de ruído ativado nas telas dos alunos!', 'success', 3500);
                } else {
                    const pwd = typeof getActivePassword === 'function' ? getActivePassword() : 'qwe123';
                    fetch('/api/noise/traffic-light', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ level: 'off', db: 0, threshold: alertThreshold, password: pwd })
                    });
                    showToast('Semáforo de ruído desativado nas telas dos alunos.', 'info', 2500);
                }
            });
        }

        if (tfSyncBtn) {
            tfSyncBtn.addEventListener('click', () => {
                syncTrafficLightToStudents(currentTrafficLevel, smoothedDb, true);
                showToast(`🚦 Semáforo sincronizado nas telas dos alunos (${currentTrafficLevel.toUpperCase()})!`, 'info', 3000);
            });
        }

        if (sendCelebrationBtn) {
            sendCelebrationBtn.addEventListener('click', celebrateTurmaNota10);
        }

        // =========================================================================
        // 💾 SALVAR E PERSISTIR DEFINIÇÕES DO MEDIDOR DE RUÍDO
        // =========================================================================
        function saveDecibelSettings(showFeedback = true) {
            // 1. Limite de Tolerância (dB)
            const inputVal = thresholdNumberInput ? parseInt(thresholdNumberInput.value, 10) : (thresholdInput ? parseInt(thresholdInput.value, 10) : alertThreshold);
            if (!isNaN(inputVal)) {
                alertThreshold = Math.max(30, Math.min(120, inputVal));
                localStorage.setItem('decibel_alert_threshold', alertThreshold.toString());
            }

            // 2. Alerta Geral Ativado
            if (alertEnableToggle) {
                isAlertEnabled = alertEnableToggle.checked;
                localStorage.setItem('decibel_alert_enabled', isAlertEnabled ? 'true' : 'false');
            }

            // 3. Aviso Sonoro (Beep)
            if (beepToggle) {
                isBeepEnabled = beepToggle.checked;
                localStorage.setItem('decibel_beep_enabled', isBeepEnabled ? 'true' : 'false');
            }

            // 4. Alerta Automático Pedir Silêncio
            if (autoSilenceToggle) {
                autoSilenceAlertEnabled = autoSilenceToggle.checked;
                localStorage.setItem('decibel_auto_silence_enabled', autoSilenceAlertEnabled ? 'true' : 'false');
            }

            // 5. Duração contínua de silêncio (segundos)
            if (silenceDurationSelect) {
                silenceContinuousDurationSec = parseInt(silenceDurationSelect.value, 10) || 3;
                localStorage.setItem('decibel_silence_duration', silenceContinuousDurationSec.toString());
            }

            // 6. Ações Automáticas de Rede / Disciplina (Avisos & Bloqueio)
            if (autoActionsToggle) {
                autoNetworkActionsEnabled = autoActionsToggle.checked;
                localStorage.setItem('decibel_auto_actions_enabled', autoNetworkActionsEnabled ? 'true' : 'false');
            }

            // 7. Semáforo no Monitor do Aluno
            if (studentTrafficLightToggle) {
                isStudentTrafficLightEnabled = studentTrafficLightToggle.checked;
                localStorage.setItem('decibel_traffic_light_enabled', isStudentTrafficLightEnabled ? 'true' : 'false');
            }

            // 8. Microfone Selecionado
            if (deviceSelect) {
                selectedDeviceId = deviceSelect.value || '';
                localStorage.setItem('decibel_device_id', selectedDeviceId);
            }

            // 9. Calibração Manual (Offset dB)
            if (calibInput) {
                calibrationOffset = parseInt(calibInput.value, 10) || 0;
                localStorage.setItem('decibel_calib_offset', calibrationOffset.toString());
            }

            // Atualiza marcadores e interfaces no DOM
            setThresholdValue(alertThreshold);
            updateDisciplineUI();
            updateTrafficLightVisual(currentTrafficLevel, smoothedDb);

            if (showFeedback) {
                const saveButtons = [saveSettingsBtn, saveSettingsTopBtn].filter(Boolean);
                saveButtons.forEach(btn => {
                    const originalHtml = btn.innerHTML;
                    btn.classList.add('saved-success');
                    btn.innerHTML = `<i data-feather="check"></i> <span>Definições Salvas!</span>`;
                    if (window.feather) feather.replace();
                    setTimeout(() => {
                        btn.classList.remove('saved-success');
                        btn.innerHTML = originalHtml;
                        if (window.feather) feather.replace();
                    }, 2200);
                });

                showToast(`💾 Definições do medidor de ruído gravadas com sucesso! (Limite: ${alertThreshold} dB)`, 'success', 3500);
            }
        }

        window.saveDecibelSettings = saveDecibelSettings;

        if (saveSettingsBtn) {
            saveSettingsBtn.addEventListener('click', () => saveDecibelSettings(true));
        }

        if (saveSettingsTopBtn) {
            saveSettingsTopBtn.addEventListener('click', () => saveDecibelSettings(true));
        }

        // =========================================================================
        // 🔊 VOZ DO PROFESSOR (Sintetizador TTS em Português) NO MEDIDOR
        // =========================================================================
        const ttsChips = document.querySelectorAll('.decibel-tts-chip');
        const customTtsInput = document.getElementById('decibel-custom-tts-input');
        const sendTtsBtn = document.getElementById('decibel-send-tts-btn');
        const sendTtsLabel = document.getElementById('decibel-send-tts-label');
        const ttsStatusBadge = document.getElementById('decibel-tts-status-badge');

        async function speakTeacherVoice(text) {
            if (!text || !text.trim()) {
                showToast('⚠️ Digite ou selecione uma mensagem de voz para a turma.', 'warning');
                return;
            }

            if (sendTtsBtn) {
                sendTtsBtn.disabled = true;
                if (sendTtsLabel) sendTtsLabel.textContent = 'Falando...';
            }
            if (ttsStatusBadge) {
                ttsStatusBadge.textContent = '🔊 Transmitindo voz...';
                ttsStatusBadge.style.background = 'rgba(139,92,246,0.4)';
            }

            try {
                const resp = await fetch('/api/tts/speak', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text.trim() })
                });
                const res = await resp.json();
                if (res && res.success) {
                    showToast(`🔊 Voz do professor transmitida para ${res.delivered_count || 'todas as'} estações!`, 'success', 4500);
                    if (ttsStatusBadge) {
                        ttsStatusBadge.textContent = '✓ Voz transmitida com sucesso';
                        setTimeout(() => {
                            if (ttsStatusBadge) ttsStatusBadge.textContent = '🎙️ Pronto para falar';
                        }, 4000);
                    }
                } else {
                    showToast('Falha ao sintetizar voz: ' + (res.message || 'Erro'), 'error');
                }
            } catch (err) {
                showToast('Erro de rede ao enviar comando de voz: ' + err.message, 'error');
            } finally {
                if (sendTtsBtn) {
                    sendTtsBtn.disabled = false;
                    if (sendTtsLabel) sendTtsLabel.textContent = 'Falar Agora';
                }
            }
        }

        ttsChips.forEach(chip => {
            chip.addEventListener('click', () => {
                const phrase = chip.getAttribute('data-phrase') || '';
                if (customTtsInput) customTtsInput.value = phrase;
                speakTeacherVoice(phrase);
            });
        });

        if (sendTtsBtn) {
            sendTtsBtn.addEventListener('click', () => {
                const text = customTtsInput ? customTtsInput.value : '';
                speakTeacherVoice(text);
            });
        }

        // =========================================================================
        // 📊 HISTÓRICO E GRÁFICOS DE RUÍDO DO DIA POR AULA / PERÍODO
        // =========================================================================
        async function logNoiseReadingToBackend(dbVal, peakVal, isExceed) {
            try {
                const schoolSelect = document.getElementById('decibel-report-school-select');
                const schoolId = schoolSelect ? schoolSelect.value : 'escola_1';
                await fetch('/api/noise/log-reading', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        db_level: parseFloat(dbVal),
                        peak_db: parseFloat(peakVal),
                        is_excess: isExceed ? 1 : 0,
                        school_id: schoolId
                    })
                });
            } catch(e) {}
        }

        async function loadNoiseHistoryReport() {
            const dateInput = document.getElementById('decibel-report-date-input');
            const schoolSelect = document.getElementById('decibel-report-school-select');
            const targetDate = dateInput ? (dateInput.value || new Date().toISOString().split('T')[0]) : new Date().toISOString().split('T')[0];
            const schoolId = schoolSelect ? schoolSelect.value : 'escola_1';

            try {
                const resp = await fetch(`/api/noise/history?date=${encodeURIComponent(targetDate)}&school_id=${encodeURIComponent(schoolId)}`);
                const data = await resp.json();
                if (!data || !data.success) return;

                // Atualiza métricas gerais
                const overallAvgEl = document.getElementById('decibel-report-overall-avg');
                const overallPeakEl = document.getElementById('decibel-report-overall-peak');
                const overallExcessEl = document.getElementById('decibel-report-overall-excess');
                const pointsCountEl = document.getElementById('decibel-chart-points-count');
                
                if (overallAvgEl) overallAvgEl.innerHTML = `${data.overall_avg || 0} <span style="font-size:0.65rem;">dB</span>`;
                if (overallPeakEl) overallPeakEl.innerHTML = `${data.overall_peak || 0} <span style="font-size:0.65rem;">dB</span>`;
                if (overallExcessEl) overallExcessEl.textContent = data.overall_excess || 0;
                if (pointsCountEl) pointsCountEl.textContent = `${data.total_samples || 0} medições gravadas`;

                // Melhor aula / período do dia
                const bestPeriodNameEl = document.getElementById('decibel-best-period-name');
                const bestPeriodAvgEl = document.getElementById('decibel-best-period-avg');
                const bestPeriodBadgeEl = document.getElementById('decibel-best-period-badge');

                if (data.best_period) {
                    if (bestPeriodNameEl) bestPeriodNameEl.textContent = data.best_period.period_name;
                    if (bestPeriodAvgEl) bestPeriodAvgEl.textContent = `${data.best_period.avg_db} dB méd.`;
                    if (bestPeriodBadgeEl) bestPeriodBadgeEl.textContent = data.best_period.rating_badge || 'Maior Concentração ⭐⭐⭐';
                } else {
                    if (bestPeriodNameEl) bestPeriodNameEl.textContent = data.total_samples > 0 ? 'Dados em coleta...' : 'Sem medições suficientes';
                    if (bestPeriodAvgEl) bestPeriodAvgEl.textContent = '-- dB';
                    if (bestPeriodBadgeEl) bestPeriodBadgeEl.textContent = 'Aguardando aulas';
                }

                // Renderiza Tabela de Períodos
                renderPeriodsTable(data.periods_summary || []);

                // Renderiza Gráfico SVG da Linha do Tempo
                renderNoiseTimelineSVG(data.raw_points || []);
            } catch(e) {
                console.error('[DecibelReport] Erro ao carregar histórico:', e);
            }
        }

        function renderNoiseTimelineSVG(points) {
            const svg = document.getElementById('decibel-timeline-svg');
            const wrapper = document.getElementById('decibel-timeline-svg-wrapper');
            if (!svg || !wrapper) return;

            if (!points || points.length === 0) {
                svg.innerHTML = `
                    <text x="50%" y="50%" text-anchor="middle" dominant-baseline="middle" fill="#64748b" font-size="12">
                        Sem dados de ruído para o gráfico nesta data. O decibelímetro grava automaticamente durante a aula.
                    </text>
                `;
                return;
            }

            const width = wrapper.clientWidth || 480;
            const height = wrapper.clientHeight || 130;
            const padding = { top: 15, right: 15, bottom: 25, left: 35 };

            const plotW = Math.max(10, width - padding.left - padding.right);
            const plotH = Math.max(10, height - padding.top - padding.bottom);

            const minDbVal = 30;
            const maxDbVal = 105;

            const getX = (index) => padding.left + (index / Math.max(1, points.length - 1)) * plotW;
            const getY = (dbVal) => {
                const clamped = Math.max(minDbVal, Math.min(maxDbVal, dbVal));
                return padding.top + plotH - ((clamped - minDbVal) / (maxDbVal - minDbVal)) * plotH;
            };

            const threshY = getY(alertThreshold);

            let pathD = "";
            let areaD = `M ${getX(0)} ${padding.top + plotH}`;
            points.forEach((p, idx) => {
                const x = getX(idx);
                const y = getY(p.db);
                if (idx === 0) {
                    pathD += `M ${x} ${y}`;
                    areaD += ` L ${x} ${y}`;
                } else {
                    pathD += ` L ${x} ${y}`;
                    areaD += ` L ${x} ${y}`;
                }
            });
            areaD += ` L ${getX(points.length - 1)} ${padding.top + plotH} Z`;

            let svgHtml = `
                <defs>
                    <linearGradient id="dbAreaGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.35"/>
                        <stop offset="100%" stop-color="#38bdf8" stop-opacity="0.0"/>
                    </linearGradient>
                </defs>

                <!-- Grid lines -->
                <line x1="${padding.left}" y1="${getY(50)}" x2="${width - padding.right}" y2="${getY(50)}" stroke="rgba(255,255,255,0.06)" stroke-dasharray="3,3"/>
                <text x="${padding.left - 6}" y="${getY(50) + 3}" text-anchor="end" fill="#64748b" font-size="9">50dB</text>

                <line x1="${padding.left}" y1="${getY(75)}" x2="${width - padding.right}" y2="${getY(75)}" stroke="rgba(255,255,255,0.06)" stroke-dasharray="3,3"/>
                <text x="${padding.left - 6}" y="${getY(75) + 3}" text-anchor="end" fill="#64748b" font-size="9">75dB</text>

                <!-- Threshold Alert Line -->
                <line x1="${padding.left}" y1="${threshY}" x2="${width - padding.right}" y2="${threshY}" stroke="#f59e0b" stroke-dasharray="4,3" stroke-width="1.2"/>
                <text x="${width - padding.right}" y="${threshY - 4}" text-anchor="end" fill="#f59e0b" font-size="9" font-weight="bold">Limite (${alertThreshold}dB)</text>

                <!-- Area & Line -->
                <path d="${areaD}" fill="url(#dbAreaGrad)"/>
                <path d="${pathD}" fill="none" stroke="#38bdf8" stroke-width="2" stroke-linejoin="round"/>
            `;

            points.forEach((p, idx) => {
                if (points.length <= 40 || p.is_excess || idx % Math.ceil(points.length / 30) === 0 || idx === points.length - 1) {
                    const x = getX(idx);
                    const y = getY(p.db);
                    const color = p.is_excess ? "#ef4444" : (p.db >= 70 ? "#f59e0b" : "#10b981");
                    const radius = p.is_excess ? 4.5 : 2.5;
                    svgHtml += `
                        <circle cx="${x}" cy="${y}" r="${radius}" fill="${color}" stroke="#0f172a" stroke-width="1">
                            <title>${p.time || ''} - ${p.db} dB (Pico: ${p.peak} dB)${p.period ? ' - ' + p.period : ''}</title>
                        </circle>
                    `;
                }
            });

            if (points.length > 0) {
                svgHtml += `
                    <text x="${padding.left}" y="${height - 6}" fill="#64748b" font-size="9">${points[0].time || ''}</text>
                    <text x="${width - padding.right}" y="${height - 6}" text-anchor="end" fill="#64748b" font-size="9">${points[points.length - 1].time || ''}</text>
                `;
            }

            svg.innerHTML = svgHtml;
        }

        function renderPeriodsTable(summary) {
            const tbody = document.getElementById('decibel-periods-table-body');
            if (!tbody) return;

            if (!summary || summary.length === 0) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="6" style="padding:12px; text-align:center; color:#64748b;">
                            Nenhum registro por aula ainda hoje. A captação em tempo real grava automaticamente as amostras.
                        </td>
                    </tr>
                `;
                return;
            }

            tbody.innerHTML = summary.map(p => `
                <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
                    <td style="padding:6px; font-weight:600; color:#f8fafc;">${p.period_name}</td>
                    <td style="padding:6px; color:#94a3b8;">${p.shift}</td>
                    <td style="padding:6px; font-weight:700; color:#38bdf8;">${p.avg_db} dB</td>
                    <td style="padding:6px; color:#f59e0b;">${p.peak_db} dB</td>
                    <td style="padding:6px; color:${p.excess_count > 0 ? '#ef4444' : '#22c55e'}; font-weight:600;">
                        ${p.excess_count > 0 ? `🚨 ${p.excess_count}` : '✓ 0'}
                    </td>
                    <td style="padding:6px;">
                        <span class="decibel-rating-pill" style="background:${p.rating_color}22; color:${p.rating_color}; border:1px solid ${p.rating_color}66;" title="${p.rating_desc}">
                            ${p.rating_badge}
                        </span>
                    </td>
                </tr>
            `).join('');
        }

        // Listeners dos Controles do Relatório
        const reportDateInput = document.getElementById('decibel-report-date-input');
        if (reportDateInput) {
            reportDateInput.value = new Date().toISOString().split('T')[0];
            reportDateInput.addEventListener('change', loadNoiseHistoryReport);
        }

        const reportSchoolSelect = document.getElementById('decibel-report-school-select');
        if (reportSchoolSelect) {
            reportSchoolSelect.addEventListener('change', loadNoiseHistoryReport);
        }

        const refreshReportBtn = document.getElementById('decibel-refresh-report-btn');
        if (refreshReportBtn) {
            refreshReportBtn.addEventListener('click', loadNoiseHistoryReport);
        }

        const clearHistoryBtn = document.getElementById('decibel-clear-history-btn');
        if (clearHistoryBtn) {
            clearHistoryBtn.addEventListener('click', async () => {
                if (!confirm('Deseja realmente limpar o histórico de medições de ruído deste dia?')) return;
                const targetDate = reportDateInput ? reportDateInput.value : '';
                const schoolId = reportSchoolSelect ? reportSchoolSelect.value : '';
                try {
                    await fetch(`/api/noise/history?date=${encodeURIComponent(targetDate)}&school_id=${encodeURIComponent(schoolId)}`, {
                        method: 'DELETE'
                    });
                    showToast('🗑️ Histórico de ruído do dia limpo com sucesso.', 'success', 3000);
                    loadNoiseHistoryReport();
                } catch(e) {
                    showToast('Erro ao limpar histórico.', 'error');
                }
            });
        }

        // Renderização inicial do Mostrador Analógico VU em repouso
        drawAnalogMeterDial(20, 20, alertThreshold);

    }

    // Inicializa o decibelímetro
    initDecibelMeterModule();

    // --- MÓDULO DE INVENTÁRIO DE MÁQUINAS CLIENTES (IP & MAC) & BUSCA ULTRARRÁPIDA ---
    function initSavedClientsInventoryModule() {
        const modal = document.getElementById('saved-clients-modal');
        const openBtn = document.getElementById('open-saved-clients-btn');
        const openToolbarBtn = document.getElementById('open-saved-clients-toolbar-btn');
        const closeBtn = document.getElementById('close-saved-clients-modal-btn');
        const countBadge = document.getElementById('saved-clients-count-badge');
        const headerBadge = document.getElementById('header-saved-clients-badge');
        const tbody = document.getElementById('saved-clients-tbody');
        const emptyMsg = document.getElementById('saved-clients-empty-msg');
        const searchInput = document.getElementById('saved-clients-search-input');
        const selectAll = document.getElementById('saved-clients-select-all');
        const selectedCountLabel = document.getElementById('clients-selected-count-label');

        const toggleFormBtn = document.getElementById('toggle-add-client-form-btn');
        const formBox = document.getElementById('add-client-inline-form');
        const saveFormBtn = document.getElementById('save-new-client-form-btn');
        const cancelFormBtn = document.getElementById('cancel-add-client-form-btn');
        const importDiscoveredBtn = document.getElementById('import-current-discovered-clients-btn');
        const quickScanBtn = document.getElementById('clients-modal-quick-scan-btn');
        const clearAllBtn = document.getElementById('clear-all-saved-clients-btn');
        const applyToGridBtn = document.getElementById('apply-saved-clients-to-grid-btn');
        const importFileInput = document.getElementById('import-clients-json-file');
        const importFileBtn = document.getElementById('import-clients-json-btn');
        const exportFileBtn = document.getElementById('export-clients-json-btn');
        const startupToggle = document.getElementById('use-fast-scan-on-startup-toggle');

        // Painel de Varredura / Nova Procura
        const toggleScanPanelBtn = document.getElementById('toggle-network-scan-panel-btn');
        const scanPanel = document.getElementById('clients-network-scan-panel');
        const scanRangeInput = document.getElementById('clients-scan-range-input');
        const scanDetectedIpBadge = document.getElementById('scan-detected-ip-badge');
        const startScanBtn = document.getElementById('start-clients-network-scan-btn');
        const cancelScanBtn = document.getElementById('cancel-clients-network-scan-btn');
        const scanProgressBox = document.getElementById('clients-scan-progress-box');
        const scanProgressText = document.getElementById('clients-scan-progress-text');
        const saveScannedBtn = document.getElementById('save-scanned-to-inventory-btn');

        // Seleção de Online e Painel de Atribuição em Lote a Grupos
        const selectOnlineBtn = document.getElementById('select-online-clients-btn');
        const toggleBatchGroupBtn = document.getElementById('toggle-batch-group-panel-btn');
        const batchGroupPanel = document.getElementById('batch-assign-group-panel');
        const batchGroupNameInput = document.getElementById('batch-group-name-input');
        const existingGroupsDatalist = document.getElementById('existing-client-groups-datalist');
        const applyBatchGroupBtn = document.getElementById('apply-batch-group-btn');
        const removeBatchGroupBtn = document.getElementById('remove-batch-group-btn');
        const closeBatchGroupPanelBtn = document.getElementById('close-batch-group-panel-btn');
        const filterBar = document.getElementById('clients-group-filter-bar');

        // Painel de Manutenção dos Grupos / Laboratórios
        const toggleGroupMaintBtn = document.getElementById('toggle-group-maintenance-view-btn');
        const groupMaintPanel = document.getElementById('group-maintenance-panel');
        const closeGroupMaintBtn = document.getElementById('close-group-maintenance-panel-btn');
        const groupMaintGrid = document.getElementById('group-maintenance-cards-grid');

        // Painel de Transmitir URL / Abrir Site em Massa
        const toggleOpenUrlBtn = document.getElementById('toggle-open-url-panel-btn');
        const openUrlPanel = document.getElementById('clients-open-url-panel');
        const broadcastUrlInput = document.getElementById('clients-broadcast-url-input');
        const sendBroadcastUrlBtn = document.getElementById('send-broadcast-url-btn');
        const closeOpenUrlPanelBtn = document.getElementById('close-open-url-panel-btn');

        // Painel de Auto-Numeração Sequencial
        const toggleAutonumberBtn = document.getElementById('toggle-autonumber-panel-btn');
        const autonumberPanel = document.getElementById('clients-autonumber-panel');
        const autonumberPatternInput = document.getElementById('autonumber-pattern-input');
        const autonumberStartInput = document.getElementById('autonumber-start-input');
        const applyAutonumberBtn = document.getElementById('apply-autonumber-btn');
        const closeAutonumberPanelBtn = document.getElementById('close-autonumber-panel-btn');

        let allSavedDevices = [];
        let clientStatusCache = {}; // ip -> { type: 'online'|'offline', os: ... }
        let currentFilter = { type: 'all', value: null }; // 'all' | 'online' | 'offline' | 'group' | 'ungrouped'
        let currentSort = { column: 'ip', asc: true }; // 'ip' | 'status' | 'name' | 'group' | 'mac'

        // Inicializa estado do toggle de inicialização rápida
        if (startupToggle) {
            startupToggle.checked = localStorage.getItem('useFastSavedClientsScan') !== 'false';
            startupToggle.addEventListener('change', () => {
                localStorage.setItem('useFastSavedClientsScan', startupToggle.checked ? 'true' : 'false');
                showToast(startupToggle.checked 
                    ? '⚡ Modo de inicialização ultrarrápida ativado!' 
                    : '🔍 Modo de inicialização com varredura completa ativado.', 'info', 3000);
            });
        }

        function toggleExclusiveSubpanel(targetPanel) {
            const isCurrentlyOpen = targetPanel && !targetPanel.classList.contains('hidden');
            if (formBox) formBox.classList.add('hidden');
            if (scanPanel) scanPanel.classList.add('hidden');
            if (batchGroupPanel) batchGroupPanel.classList.add('hidden');
            if (groupMaintPanel) groupMaintPanel.classList.add('hidden');
            if (openUrlPanel) openUrlPanel.classList.add('hidden');
            if (autonumberPanel) autonumberPanel.classList.add('hidden');
            if (!isCurrentlyOpen && targetPanel) {
                targetPanel.classList.remove('hidden');
            }
        }

        function openModal() {
            if (modal) {
                modal.classList.remove('hidden');
                // Garante que a tabela comece limpa e visível
                if (formBox) formBox.classList.add('hidden');
                if (scanPanel) scanPanel.classList.add('hidden');
                if (batchGroupPanel) batchGroupPanel.classList.add('hidden');
                if (groupMaintPanel) groupMaintPanel.classList.add('hidden');
                if (openUrlPanel) openUrlPanel.classList.add('hidden');
                if (autonumberPanel) autonumberPanel.classList.add('hidden');
                if (scanRangeInput && !scanRangeInput.value.trim()) {
                    const mainRange = document.getElementById('ip-range-input')?.value?.trim();
                    if (mainRange) scanRangeInput.value = mainRange;
                }
                loadSavedDevices();
            }
        }

        function closeModal() {
            if (modal) {
                modal.classList.add('hidden');
                if (formBox) formBox.classList.add('hidden');
                if (scanPanel) scanPanel.classList.add('hidden');
                if (batchGroupPanel) batchGroupPanel.classList.add('hidden');
                if (groupMaintPanel) groupMaintPanel.classList.add('hidden');
                if (openUrlPanel) openUrlPanel.classList.add('hidden');
                if (autonumberPanel) autonumberPanel.classList.add('hidden');
            }
        }

        if (openBtn) openBtn.addEventListener('click', openModal);
        if (openToolbarBtn) openToolbarBtn.addEventListener('click', openModal);
        if (closeBtn) closeBtn.addEventListener('click', closeModal);

        if (modal) {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    closeModal();
                    return;
                }
                if (e.target.closest('#close-saved-clients-modal-btn')) {
                    closeModal();
                    return;
                }
                if (e.target.closest('#cancel-clients-network-scan-btn')) {
                    if (scanPanel) scanPanel.classList.add('hidden');
                    return;
                }
                if (e.target.closest('#close-batch-group-panel-btn')) {
                    if (batchGroupPanel) batchGroupPanel.classList.add('hidden');
                    return;
                }
                if (e.target.closest('#close-group-maintenance-panel-btn')) {
                    if (groupMaintPanel) groupMaintPanel.classList.add('hidden');
                    return;
                }
                if (e.target.closest('#cancel-add-client-form-btn')) {
                    if (formBox) formBox.classList.add('hidden');
                    return;
                }
                if (e.target.closest('#close-open-url-panel-btn')) {
                    if (openUrlPanel) openUrlPanel.classList.add('hidden');
                    return;
                }
                if (e.target.closest('#close-autonumber-panel-btn')) {
                    if (autonumberPanel) autonumberPanel.classList.add('hidden');
                    return;
                }
            });
        }

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && modal && !modal.classList.contains('hidden')) {
                if (formBox && !formBox.classList.contains('hidden')) { formBox.classList.add('hidden'); return; }
                if (scanPanel && !scanPanel.classList.contains('hidden')) { scanPanel.classList.add('hidden'); return; }
                if (batchGroupPanel && !batchGroupPanel.classList.contains('hidden')) { batchGroupPanel.classList.add('hidden'); return; }
                if (groupMaintPanel && !groupMaintPanel.classList.contains('hidden')) { groupMaintPanel.classList.add('hidden'); return; }
                if (openUrlPanel && !openUrlPanel.classList.contains('hidden')) { openUrlPanel.classList.add('hidden'); return; }
                if (autonumberPanel && !autonumberPanel.classList.contains('hidden')) { autonumberPanel.classList.add('hidden'); return; }
                closeModal();
            }
        });

        // Configuração de ordenação clicando nas colunas da tabela
        document.querySelectorAll('#saved-clients-table .inv-sortable-th').forEach(th => {
            th.addEventListener('click', () => {
                const col = th.getAttribute('data-sort');
                if (currentSort.column === col) {
                    currentSort.asc = !currentSort.asc;
                } else {
                    currentSort.column = col;
                    currentSort.asc = true;
                }
                updateSortHeaderIcons();
                renderSavedDevicesTable();
            });
        });

        function updateSortHeaderIcons() {
            document.querySelectorAll('#saved-clients-table .inv-sortable-th').forEach(th => {
                const col = th.getAttribute('data-sort');
                const icon = th.querySelector('.inv-sort-icon');
                if (!icon) return;
                if (col === currentSort.column) {
                    icon.textContent = currentSort.asc ? '▲' : '▼';
                    th.style.color = '#38bdf8';
                } else {
                    icon.textContent = '↕️';
                    th.style.color = '';
                }
            });
        }

        // Atualiza o contador de selecionados
        function updateSelectedCount() {
            const checkedBoxes = document.querySelectorAll('.saved-client-cb:checked');
            const count = checkedBoxes.length;
            if (selectedCountLabel) {
                selectedCountLabel.textContent = count;
            }
            if (toggleBatchGroupBtn) {
                if (count > 0) {
                    toggleBatchGroupBtn.style.borderColor = '#818cf8';
                    toggleBatchGroupBtn.style.color = '#c7d2fe';
                } else {
                    toggleBatchGroupBtn.style.borderColor = 'rgba(99, 102, 241, 0.35)';
                    toggleBatchGroupBtn.style.color = '#a5b4fc';
                }
            }
        }

        // Carrega e atualiza a lista de dispositivos do backend
        async function loadSavedDevices() {
            try {
                const res = await fetch(`${API_BASE_URL}/api/devices`);
                const data = await res.json();
                if (data.success && Array.isArray(data.list)) {
                    allSavedDevices = data.list;
                    updateHeaderBadge(allSavedDevices.length);
                    renderGroupFilterPills();
                    renderSavedDevicesTable();

                    // Sincroniza metadados e grupos nos caches globais e nos cards da tela inicial
                    data.list.forEach(d => {
                        if (d.ip) {
                            deviceMetadataMap[d.ip] = d;
                            if (d.mac) deviceMacs[d.ip] = d.mac;
                            if (d.hostname) deviceHostnames[d.ip] = d.hostname;
                            if (d.alias) deviceAliases[d.ip] = d.alias;
                            if (d.group_name) {
                                deviceGroupsMap[d.ip] = d.group_name;
                            } else {
                                delete deviceGroupsMap[d.ip];
                            }
                        }
                    });

                    if (typeof syncCardsMetadataAndGroups === 'function') {
                        syncCardsMetadataAndGroups();
                    }

                    // Atualiza as pílulas de grupo na tela inicial
                    if (typeof renderGroupPills === 'function') {
                        fetch(`${API_BASE_URL}/api/groups`)
                            .then(r => r.json())
                            .then(grpData => {
                                if (grpData.success && grpData.groups) {
                                    renderGroupPills(grpData.groups);
                                    if (typeof updateGroupDatalist === 'function') {
                                        updateGroupDatalist(Object.keys(grpData.groups));
                                    }
                                }
                            })
                            .catch(() => {});
                    }
                }
            } catch (err) {
                console.warn('[SavedClients] Erro ao carregar dispositivos:', err);
            }
        }
        window.refreshSavedClientsData = loadSavedDevices;

        function updateHeaderBadge(total) {
            if (headerBadge) {
                if (total > 0) {
                    headerBadge.textContent = total;
                    headerBadge.style.display = 'inline-block';
                } else {
                    headerBadge.style.display = 'none';
                }
            }
            if (countBadge) {
                countBadge.textContent = `${total} cadastrada(s)`;
            }
        }

        // Renderiza as pílulas de filtro de grupos e status
        function renderGroupFilterPills() {
            if (!filterBar) return;

            // Coleta grupos únicos
            const groupCounts = {};
            let ungroupedCount = 0;
            let onlineCount = 0;
            let offlineCount = 0;

            allSavedDevices.forEach(d => {
                const grp = (d.group_name || '').trim();
                if (grp) {
                    groupCounts[grp] = (groupCounts[grp] || 0) + 1;
                } else {
                    ungroupedCount++;
                }

                const status = clientStatusCache[d.ip];
                if (status) {
                    if (status.type !== 'offline') onlineCount++;
                    else offlineCount++;
                }
            });

            const withMacCount = allSavedDevices.filter(d => (d.mac || '').trim()).length;
            const groupsTotal = Object.keys(groupCounts).length;

            const statOnline = document.getElementById('inv-stat-online');
            const statOffline = document.getElementById('inv-stat-offline');
            const statMac = document.getElementById('inv-stat-mac');
            const statGroups = document.getElementById('inv-stat-groups');
            if (statOnline) statOnline.textContent = onlineCount;
            if (statOffline) statOffline.textContent = offlineCount;
            if (statMac) statMac.textContent = withMacCount;
            if (statGroups) statGroups.textContent = groupsTotal;

            // Popula o datalist para autocompletar nomes de grupos
            if (existingGroupsDatalist) {
                existingGroupsDatalist.innerHTML = Object.keys(groupCounts).map(g => `<option value="${g}">`).join('');
            }

            const total = allSavedDevices.length;
            const groupsList = Object.keys(groupCounts).sort();

            let pillsHtml = `
                <button type="button" class="inv-filter-chip ${currentFilter.type === 'all' ? 'active' : ''}" data-filter-type="all">
                    📋 Todos (${total})
                </button>
            `;

            if (Object.keys(clientStatusCache).length > 0) {
                pillsHtml += `
                    <button type="button" class="inv-filter-chip ${currentFilter.type === 'online' ? 'active' : ''}" data-filter-type="online" style="${currentFilter.type === 'online' ? 'background:#059669; border-color:#34d399; color:#fff;' : 'color:#34d399; border-color:rgba(16,185,129,0.3); background:rgba(16,185,129,0.1);'}">
                        🟢 Online (${onlineCount})
                    </button>
                    <button type="button" class="inv-filter-chip ${currentFilter.type === 'offline' ? 'active' : ''}" data-filter-type="offline" style="${currentFilter.type === 'offline' ? 'background:#475569; border-color:#94a3b8; color:#fff;' : 'color:#94a3b8; border-color:rgba(100,116,139,0.25); background:rgba(100,116,139,0.1);'}">
                        ⚪ Offline (${offlineCount})
                    </button>
                `;
            }

            groupsList.forEach(grp => {
                const isActive = currentFilter.type === 'group' && currentFilter.value === grp;
                pillsHtml += `
                    <button type="button" class="inv-filter-chip ${isActive ? 'active' : ''}" data-filter-type="group" data-filter-value="${grp}" style="${isActive ? 'background:#4f46e5; border-color:#818cf8; color:#fff;' : 'color:#a5b4fc; border-color:rgba(99,102,241,0.3); background:rgba(99,102,241,0.12);'}">
                        🏢 ${grp} (${groupCounts[grp]})
                    </button>
                `;
            });

            if (ungroupedCount > 0 && groupsList.length > 0) {
                const isActive = currentFilter.type === 'ungrouped';
                pillsHtml += `
                    <button type="button" class="inv-filter-chip ${isActive ? 'active' : ''}" data-filter-type="ungrouped" style="${isActive ? 'background:#334155; border-color:#64748b; color:#fff;' : ''}">
                        Sem Grupo (${ungroupedCount})
                    </button>
                `;
            }

            filterBar.innerHTML = pillsHtml;

            // Event listeners nos pills
            filterBar.querySelectorAll('.inv-filter-chip').forEach(pill => {
                pill.addEventListener('click', () => {
                    const fType = pill.getAttribute('data-filter-type');
                    const fVal = pill.getAttribute('data-filter-value') || null;
                    currentFilter = { type: fType, value: fVal };
                    renderGroupFilterPills();
                    renderSavedDevicesTable();
                });
            });
        }

        function renderSavedDevicesTable() {
            if (!tbody) return;
            const query = (searchInput?.value || '').trim().toLowerCase();

            let filtered = allSavedDevices.filter(d => {
                if (query) {
                    const ip = (d.ip || '').toLowerCase();
                    const mac = (d.mac || '').toLowerCase();
                    const alias = (d.alias || '').toLowerCase();
                    const hostname = (d.hostname || '').toLowerCase();
                    const group = (d.group_name || '').toLowerCase();
                    const matchText = ip.includes(query) || mac.includes(query) || alias.includes(query) || hostname.includes(query) || group.includes(query);
                    if (!matchText) return false;
                }

                if (currentFilter.type === 'online') {
                    const statusInfo = clientStatusCache[d.ip];
                    return statusInfo && statusInfo.type !== 'offline';
                }
                if (currentFilter.type === 'offline') {
                    const statusInfo = clientStatusCache[d.ip];
                    return statusInfo && statusInfo.type === 'offline';
                }
                if (currentFilter.type === 'group') {
                    return (d.group_name || '').trim().toLowerCase() === (currentFilter.value || '').toLowerCase();
                }
                if (currentFilter.type === 'ungrouped') {
                    return !(d.group_name || '').trim();
                }

                return true;
            });

            // Ordenação Inteligente por Coluna
            filtered.sort((a, b) => {
                let res = 0;
                if (currentSort.column === 'ip') {
                    const parseIp = (ipStr) => (ipStr || '').split('/')[0].split('.').map(n => parseInt(n, 10) || 0);
                    const aParts = parseIp(a.ip);
                    const bParts = parseIp(b.ip);
                    for (let i = 0; i < 4; i++) {
                        if (aParts[i] !== bParts[i]) {
                            res = aParts[i] - bParts[i];
                            break;
                        }
                    }
                } else if (currentSort.column === 'status') {
                    const aSt = (clientStatusCache[a.ip]?.type !== 'offline') ? 1 : 0;
                    const bSt = (clientStatusCache[b.ip]?.type !== 'offline') ? 1 : 0;
                    res = bSt - aSt;
                } else if (currentSort.column === 'name') {
                    const aName = (a.alias || a.hostname || '').toLowerCase();
                    const bName = (b.alias || b.hostname || '').toLowerCase();
                    res = aName.localeCompare(bName, 'pt-BR');
                } else if (currentSort.column === 'group') {
                    const aGrp = (a.group_name || '').toLowerCase();
                    const bGrp = (b.group_name || '').toLowerCase();
                    res = aGrp.localeCompare(bGrp, 'pt-BR');
                } else if (currentSort.column === 'mac') {
                    const aMac = (a.mac || '').toLowerCase();
                    const bMac = (b.mac || '').toLowerCase();
                    res = aMac.localeCompare(bMac);
                }
                return currentSort.asc ? res : -res;
            });

            if (filtered.length === 0) {
                tbody.innerHTML = '';
                if (emptyMsg) emptyMsg.classList.remove('hidden');
                updateSelectedCount();
                return;
            }

            if (emptyMsg) emptyMsg.classList.add('hidden');

            tbody.innerHTML = filtered.map(d => {
                const statusInfo = clientStatusCache[d.ip];
                const isOnline = statusInfo ? (statusInfo.type !== 'offline') : null;
                const statusBadge = isOnline === true 
                    ? '<span style="color:#34d399; font-weight:700; display:inline-flex; align-items:center; font-size:0.74rem;"><span class="inv-status-dot online"></span>Online</span>'
                    : (isOnline === false 
                        ? '<span style="color:#94a3b8; font-weight:500; display:inline-flex; align-items:center; font-size:0.74rem;"><span class="inv-status-dot offline"></span>Offline</span>'
                        : '<span style="color:#64748b; font-size:0.72rem;">--</span>');

                const macDisplay = d.mac 
                    ? `<code style="color:#38bdf8; font-family:'JetBrains Mono',monospace; font-size:0.74rem; background:rgba(56,189,248,0.1); padding:2px 6px; border-radius:5px; border:1px solid rgba(56,189,248,0.2);">${d.mac}</code>`
                    : '<span style="color:#64748b; font-style:italic; font-size:0.72rem;">Sem MAC</span>';

                const nameDisplay = d.alias || d.hostname || '<span style="color:#64748b; font-style:italic;">Clique duplo para nomear</span>';
                const groupDisplay = d.group_name 
                    ? `<span style="background:rgba(99,102,241,0.15); color:#c7d2fe; border:1px solid rgba(99,102,241,0.35); padding:2px 8px; border-radius:12px; font-weight:700; font-size:0.7rem;">🏢 ${d.group_name}</span>`
                    : '<span style="color:#64748b; font-size:0.72rem;">--</span>';

                const wolBtn = d.mac 
                    ? `<button type="button" class="inv-micro-btn wol action-btn-wol" data-ip="${d.ip}" data-mac="${d.mac}" title="Enviar Wake-on-LAN para ligar esta máquina">⚡ Ligar</button>`
                    : '';

                return `
                    <tr>
                        <td style="text-align:center;">
                            <input type="checkbox" class="saved-client-cb" value="${d.ip}" style="cursor:pointer; accent-color:#38bdf8; width:14px; height:14px;">
                        </td>
                        <td>${statusBadge}</td>
                        <td>
                            <strong style="color:#f8fafc; font-family:'JetBrains Mono',monospace; font-size:0.78rem;">${d.ip}</strong>
                        </td>
                        <td>${macDisplay}</td>
                        <td class="saved-client-name-cell" data-ip="${d.ip}" data-name="${d.alias||d.hostname||''}" title="Duplo clique para renomear rápido" style="cursor:pointer; color:#e2e8f0; font-weight:500;">
                            ${nameDisplay} <span style="font-size:0.65rem; color:#64748b; opacity:0.7;">✏️</span>
                        </td>
                        <td>${groupDisplay}</td>
                        <td style="text-align:right;">
                            <div style="display:inline-flex; gap:5px; align-items:center;">
                                <button type="button" class="inv-micro-btn vnc action-btn-vnc" data-ip="${d.ip}" title="Visualizar ou controlar tela via noVNC">🖥️ VNC</button>
                                ${wolBtn}
                                <button type="button" class="inv-micro-btn edit action-btn-edit" data-ip="${d.ip}" data-mac="${d.mac||''}" data-name="${d.alias||d.hostname||''}" data-group="${d.group_name||''}" title="Editar Detalhes">✏️</button>
                                <button type="button" class="inv-micro-btn delete action-btn-delete" data-ip="${d.ip}" title="Excluir do inventário">🗑️</button>
                            </div>
                        </td>
                    </tr>
                `;
            }).join('');

            tbody.querySelectorAll('.saved-client-cb').forEach(cb => {
                cb.addEventListener('change', updateSelectedCount);
            });
            updateSelectedCount();
        }

        if (searchInput) {
            searchInput.addEventListener('input', renderSavedDevicesTable);
        }

        if (selectAll) {
            selectAll.addEventListener('change', () => {
                document.querySelectorAll('.saved-client-cb').forEach(cb => cb.checked = selectAll.checked);
                updateSelectedCount();
            });
        }

        // --- BOTÃO ⚡ SELECIONAR ONLINE ---
        if (selectOnlineBtn) {
            selectOnlineBtn.addEventListener('click', async () => {
                // Se o cache de status estiver vazio, executa o teste rápido primeiro
                if (Object.keys(clientStatusCache).length === 0) {
                    selectOnlineBtn.disabled = true;
                    selectOnlineBtn.innerText = 'Testando status...';
                    try {
                        const res = await fetch(`${API_BASE_URL}/api/devices/quick-scan`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({})
                        });
                        const data = await res.json();
                        if (data.success && Array.isArray(data.ips)) {
                            clientStatusCache = {};
                            data.ips.forEach(item => {
                                clientStatusCache[item.ip] = { type: item.type, os: item.os_type };
                            });
                            renderGroupFilterPills();
                            renderSavedDevicesTable();
                        }
                    } catch (e) {
                        console.warn('Erro ao testar status rápido:', e);
                    } finally {
                        selectOnlineBtn.disabled = false;
                        selectOnlineBtn.innerText = '⚡ Selecionar Online';
                    }
                }

                // Marca as caixas de seleção apenas dos computadores que estão online
                let onlineCount = 0;
                document.querySelectorAll('.saved-client-cb').forEach(cb => {
                    const ip = cb.value;
                    const st = clientStatusCache[ip];
                    if (st && st.type !== 'offline') {
                        cb.checked = true;
                        onlineCount++;
                    } else {
                        cb.checked = false;
                    }
                });

                updateSelectedCount();

                if (onlineCount > 0) {
                    showToast(`⚡ ${onlineCount} computador(es) online selecionado(s)!`, 'success', 3500);
                    // Abre o painel de atribuição de grupo para facilitar o fluxo
                    if (batchGroupPanel) {
                        batchGroupPanel.classList.remove('hidden');
                        if (batchGroupNameInput) batchGroupNameInput.focus();
                    }
                } else {
                    showToast('Nenhum computador marcado como online no momento. Clique em "⚡ Testar Conexão" para verificar.', 'info', 4000);
                }
            });
        }

        // --- PAINEL DE ATRIBUIÇÃO DE GRUPO EM LOTE ---
        if (toggleBatchGroupBtn && batchGroupPanel) {
            toggleBatchGroupBtn.addEventListener('click', () => {
                toggleExclusiveSubpanel(batchGroupPanel);
                if (!batchGroupPanel.classList.contains('hidden') && batchGroupNameInput) {
                    batchGroupNameInput.focus();
                }
            });
        }

        if (closeBatchGroupPanelBtn && batchGroupPanel) {
            closeBatchGroupPanelBtn.addEventListener('click', () => batchGroupPanel.classList.add('hidden'));
        }

        if (applyBatchGroupBtn) {
            applyBatchGroupBtn.addEventListener('click', async () => {
                const selectedIps = Array.from(document.querySelectorAll('.saved-client-cb:checked')).map(cb => cb.value);
                if (selectedIps.length === 0) {
                    showToast('Selecione pelo menos um computador na lista para atribuir ao grupo.', 'warning');
                    return;
                }

                const groupName = (batchGroupNameInput?.value || '').trim();
                if (!groupName) {
                    showToast('Digite o nome do grupo / laboratório.', 'warning');
                    if (batchGroupNameInput) batchGroupNameInput.focus();
                    return;
                }

                try {
                    applyBatchGroupBtn.disabled = true;
                    applyBatchGroupBtn.innerText = 'Salvando...';

                    const res = await fetch(`${API_BASE_URL}/api/device/group`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ ips: selectedIps, group_name: groupName })
                    });
                    const data = await res.json();
                    if (data.success) {
                        showToast(`🎉 ${selectedIps.length} computador(es) salvos no grupo "${groupName}"!`, 'success', 4000);
                        if (batchGroupPanel) batchGroupPanel.classList.add('hidden');
                        loadSavedDevices();
                    } else {
                        showToast('Erro ao atualizar grupos: ' + data.message, 'error');
                    }
                } catch (err) {
                    showToast('Erro de comunicação ao salvar grupo.', 'error');
                } finally {
                    applyBatchGroupBtn.disabled = false;
                    applyBatchGroupBtn.innerText = '💾 Salvar Grupo nas Selecionadas';
                }
            });
        }

        if (removeBatchGroupBtn) {
            removeBatchGroupBtn.addEventListener('click', async () => {
                const selectedIps = Array.from(document.querySelectorAll('.saved-client-cb:checked')).map(cb => cb.value);
                if (selectedIps.length === 0) {
                    showToast('Selecione pelo menos um computador para remover o grupo.', 'warning');
                    return;
                }

                try {
                    removeBatchGroupBtn.disabled = true;
                    removeBatchGroupBtn.innerText = 'Removendo...';

                    const res = await fetch(`${API_BASE_URL}/api/device/group`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ ips: selectedIps, group_name: '' })
                    });
                    const data = await res.json();
                    if (data.success) {
                        showToast(`Grupo removido de ${selectedIps.length} computador(es).`, 'info', 3000);
                        if (batchGroupPanel) batchGroupPanel.classList.add('hidden');
                        loadSavedDevices();
                    } else {
                        showToast('Erro: ' + data.message, 'error');
                    }
                } catch (err) {
                    showToast('Erro ao remover grupo.', 'error');
                } finally {
                    removeBatchGroupBtn.disabled = false;
                    removeBatchGroupBtn.innerText = 'Remover Grupo';
                }
            });
        }

        // --- PAINEL DE MANUTENÇÃO DE GRUPOS / LABORATÓRIOS ---
        async function loadAndRenderGroupMaintenanceCards() {
            if (!groupMaintGrid) return;
            groupMaintGrid.innerHTML = '<div style="grid-column: 1/-1; text-align:center; padding:20px; color:#94a3b8;">⏳ Carregando dados dos laboratórios...</div>';

            try {
                const res = await fetch(`${API_BASE_URL}/api/groups/details`);
                const data = await res.json();
                if (!data.success || !Array.isArray(data.groups) || data.groups.length === 0) {
                    groupMaintGrid.innerHTML = `
                        <div style="grid-column: 1/-1; text-align:center; padding:30px; color:#64748b;">
                            <span style="font-size:1.8rem; display:block; margin-bottom:6px;">📂</span>
                            <strong>Nenhum grupo cadastrado ainda.</strong>
                            <p style="font-size:0.75rem; margin-top:4px;">Selecione computadores na tabela e clique em <b>"📁 Salvar em Grupo"</b> para criar seu primeiro laboratório.</p>
                        </div>
                    `;
                    return;
                }

                groupMaintGrid.innerHTML = data.groups.map(grp => {
                    const gName = grp.group_name;
                    const isUngrouped = grp.is_ungrouped;
                    const devices = grp.devices || [];
                    let onlineCount = 0;
                    let offlineCount = 0;
                    devices.forEach(d => {
                        const st = clientStatusCache[d.ip];
                        if (st && st.type !== 'offline') onlineCount++;
                        else if (st) offlineCount++;
                    });

                    const statusBadge = Object.keys(clientStatusCache).length > 0 
                        ? `<span style="font-size:0.68rem; color:#34d399; font-weight:700; background:rgba(16,185,129,0.15); padding:1px 6px; border-radius:10px;">🟢 ${onlineCount}</span> <span style="font-size:0.68rem; color:#94a3b8; background:rgba(100,116,139,0.15); padding:1px 6px; border-radius:10px;">⚪ ${offlineCount}</span>`
                        : `<span style="font-size:0.68rem; color:#94a3b8;">${devices.length} PCs</span>`;

                    const renameBtn = !isUngrouped 
                        ? `<button type="button" class="group-rename-btn small-btn" data-group="${gName}" title="Renomear Laboratório" style="padding:2px 5px; font-size:0.68rem; background:rgba(56,189,248,0.12); color:#38bdf8; border-color:rgba(56,189,248,0.3);">✏️</button>` 
                        : '';
                    const deleteBtn = !isUngrouped 
                        ? `<button type="button" class="group-delete-btn small-btn" data-group="${gName}" title="Desvincular Grupo de todos os computadores" style="padding:2px 5px; font-size:0.68rem; color:#f87171; border-color:rgba(239,68,68,0.3); background:rgba(239,68,68,0.1);">🗑️</button>` 
                        : '';

                    return `
                        <div class="group-card-item" style="background: rgba(30, 41, 59, 0.7); border: 1px solid rgba(139,92,246,0.3); border-radius: 8px; padding: 10px; display: flex; flex-direction: column; gap: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
                            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(255,255,255,0.06); padding-bottom:6px;">
                                <div style="display:flex; align-items:center; gap:6px;">
                                    <span style="font-size:1rem;">${isUngrouped ? '❓' : '🏢'}</span>
                                    <strong style="color:#f8fafc; font-size:0.85rem;">${gName}</strong>
                                    <span style="font-size:0.7rem; color:#a5b4fc; background:rgba(99,102,241,0.2); padding:1px 5px; border-radius:4px; font-weight:700;">${devices.length}</span>
                                </div>
                                <div style="display:flex; gap:4px; align-items:center;">
                                    ${statusBadge}
                                    ${renameBtn}
                                    ${deleteBtn}
                                </div>
                            </div>

                            <!-- Botões de Ações de Manutenção em Lote -->
                            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:4px;">
                                <button type="button" class="grp-action-btn" data-group="${gName}" data-action="wol" title="Enviar Wake-on-LAN para ligar todas as máquinas deste laboratório" style="background:rgba(234,179,8,0.15); color:#facc15; border:1px solid rgba(234,179,8,0.3); padding:4px 6px; border-radius:4px; font-size:0.68rem; cursor:pointer; font-weight:700; text-align:center;">
                                    ⚡ Ligar (WoL)
                                </button>
                                <button type="button" class="grp-action-btn" data-group="${gName}" data-action="open_url" title="Abrir site/link no navegador de todas as máquinas da sala" style="background:rgba(2,132,199,0.15); color:#38bdf8; border:1px solid rgba(2,132,199,0.3); padding:4px 6px; border-radius:4px; font-size:0.68rem; cursor:pointer; font-weight:600; text-align:center;">
                                    🌐 Abrir Link
                                </button>
                                <button type="button" class="grp-action-btn" data-group="${gName}" data-action="shutdown" title="Desligar todos os computadores da sala" style="background:rgba(239,68,68,0.15); color:#fca5a5; border:1px solid rgba(239,68,68,0.3); padding:4px 6px; border-radius:4px; font-size:0.68rem; cursor:pointer; font-weight:700; text-align:center;">
                                    🌙 Desligar Sala
                                </button>
                                <button type="button" class="grp-action-btn" data-group="${gName}" data-action="reboot" title="Reiniciar todos os computadores da sala" style="background:rgba(56,189,248,0.12); color:#38bdf8; border:1px solid rgba(56,189,248,0.3); padding:4px 6px; border-radius:4px; font-size:0.68rem; cursor:pointer; font-weight:600; text-align:center;">
                                    🔄 Reiniciar
                                </button>
                                <button type="button" class="grp-action-btn" data-group="${gName}" data-action="clean_temp" title="Limpar cache dos navegadores, /tmp e lixeira em todas as máquinas" style="background:rgba(16,185,129,0.12); color:#34d399; border:1px solid rgba(16,185,129,0.3); padding:4px 6px; border-radius:4px; font-size:0.68rem; cursor:pointer; font-weight:600; text-align:center;">
                                    🧹 Limpar Cache/Tmp
                                </button>
                                <button type="button" class="grp-action-btn" data-group="${gName}" data-action="close_browsers" title="Fechar janelas de navegadores (Chrome, Firefox) dos alunos" style="background:rgba(249,115,22,0.12); color:#fdba74; border:1px solid rgba(249,115,22,0.3); padding:4px 6px; border-radius:4px; font-size:0.68rem; cursor:pointer; font-weight:600; text-align:center;">
                                    🌐 Fechar Navegadores
                                </button>
                                <button type="button" class="grp-action-btn" data-group="${gName}" data-action="lock" title="Bloquear teclado e mouse de todo o laboratório" style="background:rgba(239,68,68,0.12); color:#f87171; border:1px solid rgba(239,68,68,0.25); padding:4px 6px; border-radius:4px; font-size:0.68rem; cursor:pointer; font-weight:600; text-align:center;">
                                    🔒 Bloquear Sala
                                </button>
                                <button type="button" class="grp-action-btn" data-group="${gName}" data-action="unlock" title="Desbloquear telas dos alunos" style="background:rgba(16,185,129,0.12); color:#6ee7b7; border:1px solid rgba(16,185,129,0.25); padding:4px 6px; border-radius:4px; font-size:0.68rem; cursor:pointer; font-weight:600; text-align:center;">
                                    🔓 Desbloquear
                                </button>
                                <button type="button" class="grp-action-btn" data-group="${gName}" data-action="tts" title="Transmitir aviso de voz nas caixas de som deste laboratório" style="background:rgba(139,92,246,0.15); color:#c4b5fd; border:1px solid rgba(139,92,246,0.3); padding:4px 6px; border-radius:4px; font-size:0.68rem; cursor:pointer; font-weight:600; text-align:center; grid-column: 1 / -1;">
                                    🔊 Falar TTS
                                </button>
                            </div>
                        </div>
                    `;
                }).join('');
            } catch (err) {
                console.warn('[GroupMaintenance] Erro ao carregar detalhes dos grupos:', err);
            }
        }

        // Toggle do painel de manutenção de grupos
        if (toggleGroupMaintBtn && groupMaintPanel) {
            toggleGroupMaintBtn.addEventListener('click', () => {
                toggleExclusiveSubpanel(groupMaintPanel);
                if (!groupMaintPanel.classList.contains('hidden')) {
                    loadAndRenderGroupMaintenanceCards();
                }
            });
        }

        if (closeGroupMaintBtn && groupMaintPanel) {
            closeGroupMaintBtn.addEventListener('click', () => groupMaintPanel.classList.add('hidden'));
        }

        // Delegação de eventos no grid de manutenção de grupos
        if (groupMaintGrid) {
            groupMaintGrid.addEventListener('click', async (e) => {
                // Renomear Grupo
                const renameBtn = e.target.closest('.group-rename-btn');
                if (renameBtn) {
                    const oldName = renameBtn.getAttribute('data-group');
                    const newName = prompt(`Digite o novo nome para o grupo "${oldName}":`, oldName);
                    if (!newName || newName.trim() === '' || newName.trim() === oldName) return;

                    try {
                        const res = await fetch(`${API_BASE_URL}/api/group/rename`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ old_name: oldName, new_name: newName.trim() })
                        });
                        const data = await res.json();
                        if (data.success) {
                            showToast(`🎉 Grupo "${oldName}" renomeado para "${newName.trim()}"!`, 'success');
                            loadSavedDevices();
                            loadAndRenderGroupMaintenanceCards();
                        } else {
                            showToast('Erro: ' + data.message, 'error');
                        }
                    } catch (err) {
                        showToast('Erro ao renomear grupo.', 'error');
                    }
                    return;
                }

                // Excluir / Desvincular Grupo
                const deleteBtn = e.target.closest('.group-delete-btn');
                if (deleteBtn) {
                    const gName = deleteBtn.getAttribute('data-group');
                    if (!confirm(`Deseja realmente desvincular o grupo "${gName}" de todos os computadores?`)) return;

                    try {
                        const res = await fetch(`${API_BASE_URL}/api/groups/${encodeURIComponent(gName)}`, { method: 'DELETE' });
                        const data = await res.json();
                        if (data.success) {
                            showToast(`Grupo "${gName}" desvinculado com sucesso.`, 'info');
                            loadSavedDevices();
                            loadAndRenderGroupMaintenanceCards();
                        } else {
                            showToast('Erro: ' + data.message, 'error');
                        }
                    } catch (err) {
                        showToast('Erro ao desvincular grupo.', 'error');
                    }
                    return;
                }

                // Ações de Manutenção em Lote no Grupo
                const actBtn = e.target.closest('.grp-action-btn');
                if (actBtn) {
                    const groupName = actBtn.getAttribute('data-group');
                    const action = actBtn.getAttribute('data-action');
                    let textPayload = '';

                    if (action === 'tts') {
                        textPayload = prompt(`Digite a mensagem de voz a ser transmitida para o grupo "${groupName}":`, 'Atenção alunos: por favor prestem atenção nas orientações do professor.');
                        if (!textPayload || !textPayload.trim()) return;
                    }

                    if (action === 'open_url') {
                        textPayload = prompt(`Digite ou cole a URL do site a ser aberto no laboratório "${groupName}":`, 'https://classroom.google.com');
                        if (!textPayload || !textPayload.trim()) return;
                    }

                    if (action === 'shutdown' || action === 'reboot') {
                        if (!confirm(`Confirma ${action === 'shutdown' ? 'DESLIGAR' : 'REINICIAR'} todos os computadores do grupo "${groupName}"?`)) return;
                    }

                    const originalText = actBtn.innerText;
                    actBtn.disabled = true;
                    actBtn.innerText = 'Enviando...';

                    try {
                        const res = await fetch(`${API_BASE_URL}/api/group/action`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ group_name: groupName, action, text: textPayload })
                        });
                        const data = await res.json();
                        if (data.success) {
                            showToast(`⚡ ${data.message}`, 'success', 4000);
                        } else {
                            showToast('Erro: ' + data.message, 'error');
                        }
                    } catch (err) {
                        showToast('Erro de comunicação ao executar ação no grupo.', 'error');
                    } finally {
                        actBtn.disabled = false;
                        actBtn.innerText = originalText;
                    }
                }
            });
        }

        // --- PAINEL DE TRANSMISSÃO DE LINK / SITE ---
        if (toggleOpenUrlBtn && openUrlPanel) {
            toggleOpenUrlBtn.addEventListener('click', () => {
                toggleExclusiveSubpanel(openUrlPanel);
                if (!openUrlPanel.classList.contains('hidden') && broadcastUrlInput) {
                    broadcastUrlInput.focus();
                }
            });
        }

        if (closeOpenUrlPanelBtn && openUrlPanel) {
            closeOpenUrlPanelBtn.addEventListener('click', () => openUrlPanel.classList.add('hidden'));
        }

        if (sendBroadcastUrlBtn) {
            sendBroadcastUrlBtn.addEventListener('click', async () => {
                const selectedIps = Array.from(document.querySelectorAll('.saved-client-cb:checked')).map(cb => cb.value);
                if (selectedIps.length === 0) {
                    showToast('Selecione pelo menos um computador na lista para abrir o site.', 'warning');
                    return;
                }

                const url = (broadcastUrlInput?.value || '').trim();
                if (!url) {
                    showToast('Digite ou cole a URL do site a ser aberto.', 'warning');
                    if (broadcastUrlInput) broadcastUrlInput.focus();
                    return;
                }

                sendBroadcastUrlBtn.disabled = true;
                sendBroadcastUrlBtn.innerText = 'Enviando...';

                try {
                    const res = await fetch(`${API_BASE_URL}/api/devices/open-url`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ ips: selectedIps, url })
                    });
                    const data = await res.json();
                    if (data.success) {
                        showToast(`🌐 ${data.message}`, 'success', 4500);
                        if (openUrlPanel) openUrlPanel.classList.add('hidden');
                    } else {
                        showToast('Erro: ' + data.message, 'error');
                    }
                } catch (err) {
                    showToast('Erro ao transmitir site para as máquinas.', 'error');
                } finally {
                    sendBroadcastUrlBtn.disabled = false;
                    sendBroadcastUrlBtn.innerText = '🚀 Abrir em Massa';
                }
            });
        }

        // --- PAINEL DE AUTO-NUMERAÇÃO SEQUENCIAL ---
        if (toggleAutonumberBtn && autonumberPanel) {
            toggleAutonumberBtn.addEventListener('click', () => {
                toggleExclusiveSubpanel(autonumberPanel);
                if (!autonumberPanel.classList.contains('hidden') && autonumberPatternInput) {
                    autonumberPatternInput.focus();
                }
            });
        }

        if (closeAutonumberPanelBtn && autonumberPanel) {
            closeAutonumberPanelBtn.addEventListener('click', () => autonumberPanel.classList.add('hidden'));
        }

        if (applyAutonumberBtn) {
            applyAutonumberBtn.addEventListener('click', async () => {
                const selectedIps = Array.from(document.querySelectorAll('.saved-client-cb:checked')).map(cb => cb.value);
                if (selectedIps.length === 0) {
                    showToast('Selecione os computadores que deseja numerar sequencialmente.', 'warning');
                    return;
                }

                const pattern = (autonumberPatternInput?.value || 'Aluno {n}').trim();
                const startNum = parseInt(autonumberStartInput?.value || '1', 10) || 1;

                applyAutonumberBtn.disabled = true;
                applyAutonumberBtn.innerText = 'Numerando...';

                try {
                    const res = await fetch(`${API_BASE_URL}/api/devices/autonumber`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ ips: selectedIps, pattern, start_at: startNum, pad: 2 })
                    });
                    const data = await res.json();
                    if (data.success) {
                        showToast(`🔢 ${data.message}`, 'success', 4000);
                        if (autonumberPanel) autonumberPanel.classList.add('hidden');
                        loadSavedDevices();
                    } else {
                        showToast('Erro: ' + data.message, 'error');
                    }
                } catch (err) {
                    showToast('Erro ao auto-numerar máquinas.', 'error');
                } finally {
                    applyAutonumberBtn.disabled = false;
                    applyAutonumberBtn.innerText = '✨ Aplicar Nomes';
                }
            });
        }

        // --- PAINEL DE NOVA PROCURA / VARREDURA DE REDE ---
        if (toggleScanPanelBtn && scanPanel) {
            toggleScanPanelBtn.addEventListener('click', () => {
                toggleExclusiveSubpanel(scanPanel);
                if (!scanPanel.classList.contains('hidden') && scanRangeInput) {
                    if (!scanRangeInput.value.trim()) {
                        const mainRange = document.getElementById('ip-range-input')?.value?.trim();
                        if (mainRange) scanRangeInput.value = mainRange;
                    }
                    scanRangeInput.focus();
                }
            });
        }

        if (cancelScanBtn && scanPanel) {
            cancelScanBtn.addEventListener('click', () => scanPanel.classList.add('hidden'));
        }

        if (startScanBtn) {
            startScanBtn.addEventListener('click', async () => {
                const rangeVal = (scanRangeInput?.value || '').trim();
                startScanBtn.disabled = true;
                startScanBtn.innerText = '⏳ Varrendo...';
                if (scanProgressBox) scanProgressBox.classList.remove('hidden');
                if (scanProgressText) scanProgressText.textContent = '⏳ Varrendo a rede local em busca de computadores ligados...';
                if (saveScannedBtn) saveScannedBtn.style.display = 'none';

                try {
                    const res = await fetch(`${API_BASE_URL}/discover-ips`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ custom_range: rangeVal })
                    });
                    const data = await res.json();
                    if (data.success && Array.isArray(data.ips) && data.ips.length > 0) {
                        if (scanProgressText) {
                            scanProgressText.innerHTML = `✅ Encontrados <b>${data.ips.length} computadores ativos</b> na rede!`;
                        }

                        // Salva automaticamente no inventário preservando hostname e alias descobertos
                        const devicesToSave = data.ips.map(item => ({
                            ip: item.ip,
                            mac: item.mac || '',
                            alias: item.alias || item.hostname || '',
                            hostname: item.hostname || item.alias || '',
                            group_name: item.group_name || ''
                        }));

                        await fetch(`${API_BASE_URL}/api/devices/batch`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ devices: devicesToSave })
                        });

                        // Atualiza cache de status como online para todos encontrados
                        data.ips.forEach(item => {
                            clientStatusCache[item.ip] = { type: item.type || 'online', os: item.os_type };
                            if (item.hostname) deviceHostnames[item.ip] = item.hostname;
                            if (item.alias) deviceAliases[item.ip] = item.alias;
                        });

                        showToast(`🎉 ${data.ips.length} computadores descobertos e salvos no inventário com seus nomes!`, 'success', 4500);
                        loadSavedDevices();
                    } else {
                        if (scanProgressText) {
                            scanProgressText.textContent = '⚠️ Nenhum computador respondeu na faixa de IP informada.';
                        }
                        showToast('Nenhum computador encontrado na varredura.', 'warning');
                    }
                } catch (err) {
                    if (scanProgressText) scanProgressText.textContent = '❌ Erro de comunicação durante a varredura.';
                    showToast('Erro ao executar varredura de rede.', 'error');
                } finally {
                    startScanBtn.disabled = false;
                    startScanBtn.innerText = '🚀 Iniciar Varredura';
                }
            });
        }

        // Ações da Tabela (Delegação)
        if (tbody) {
            tbody.addEventListener('click', async (e) => {
                const vncBtn = e.target.closest('.action-btn-vnc');
                if (vncBtn) {
                    const ip = vncBtn.getAttribute('data-ip');
                    window.open(`grid_view.html?ips=${encodeURIComponent(ip)}`, '_blank');
                    return;
                }

                const nameCell = e.target.closest('.saved-client-name-cell');
                if (nameCell && !e.target.closest('.inv-micro-btn')) {
                    const ip = nameCell.getAttribute('data-ip');
                    const curName = nameCell.getAttribute('data-name') || '';
                    const newName = prompt(`Digite o novo nome / apelido para a máquina ${ip}:`, curName);
                    if (newName !== null && newName.trim() !== curName) {
                        const d = allSavedDevices.find(item => item.ip === ip);
                        fetch(`${API_BASE_URL}/api/devices`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                ip,
                                mac: d?.mac || '',
                                alias: newName.trim(),
                                hostname: newName.trim(),
                                group_name: d?.group_name || ''
                            })
                        }).then(res => res.json()).then(data => {
                            if (data.success) {
                                showToast(`Máquina ${ip} renomeada com sucesso!`, 'success');
                                loadSavedDevices();
                            } else {
                                showToast('Erro ao renomear: ' + data.message, 'error');
                            }
                        }).catch(() => showToast('Erro de comunicação.', 'error'));
                    }
                    return;
                }

                const wolBtn = e.target.closest('.action-btn-wol');
                if (wolBtn) {
                    const ip = wolBtn.getAttribute('data-ip');
                    const mac = wolBtn.getAttribute('data-mac');
                    wolBtn.innerText = 'Enviando...';
                    try {
                        const res = await fetch(`${API_BASE_URL}/api/devices/wol-single`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ ip, mac })
                        });
                        const data = await res.json();
                        if (data.success) {
                            showToast(`⚡ Sinal Wake-on-LAN enviado para ${ip} (${mac})!`, 'success', 4000);
                        } else {
                            showToast('Falha no WoL: ' + data.message, 'error');
                        }
                    } catch (err) {
                        showToast(`Erro de rede ao enviar WoL: ${err.message || 'Servidor inacessível'}`, 'error');
                    } finally {
                        wolBtn.innerText = '⚡ Ligar';
                    }
                    return;
                }

                const editBtn = e.target.closest('.action-btn-edit');
                if (editBtn) {
                    const ip = editBtn.getAttribute('data-ip');
                    const mac = editBtn.getAttribute('data-mac');
                    const name = editBtn.getAttribute('data-name');
                    const group = editBtn.getAttribute('data-group');

                    if (formBox) {
                        toggleExclusiveSubpanel(formBox);
                        document.getElementById('new-client-ip-input').value = ip;
                        document.getElementById('new-client-ip-input').disabled = true;
                        document.getElementById('new-client-mac-input').value = mac;
                        document.getElementById('new-client-name-input').value = name;
                        document.getElementById('new-client-group-input').value = group;
                        document.getElementById('add-client-form-mode-badge').textContent = `Editando ${ip}`;
                    }
                    return;
                }

                const deleteBtn = e.target.closest('.action-btn-delete');
                if (deleteBtn) {
                    const ip = deleteBtn.getAttribute('data-ip');
                    if (!confirm(`Deseja realmente remover o computador ${ip} do inventário?`)) return;
                    try {
                        const res = await fetch(`${API_BASE_URL}/api/devices/${encodeURIComponent(ip)}`, { method: 'DELETE' });
                        const data = await res.json();
                        if (data.success) {
                            showToast(`Dispositivo ${ip} removido!`, 'info');
                            loadSavedDevices();
                        } else {
                            showToast('Erro: ' + data.message, 'error');
                        }
                    } catch (err) {
                        showToast('Erro ao excluir dispositivo.', 'error');
                    }
                }
            });
        }

        // Formulário de Adicionar / Editar
        if (toggleFormBtn && formBox) {
            toggleFormBtn.addEventListener('click', () => {
                const isHidden = formBox.classList.contains('hidden');
                toggleExclusiveSubpanel(formBox);
                if (isHidden) {
                    document.getElementById('new-client-ip-input').value = '';
                    document.getElementById('new-client-ip-input').disabled = false;
                    document.getElementById('new-client-mac-input').value = '';
                    document.getElementById('new-client-name-input').value = '';
                    document.getElementById('new-client-group-input').value = '';
                    document.getElementById('add-client-form-mode-badge').textContent = 'Novo Registro';
                }
            });
        }

        if (cancelFormBtn && formBox) {
            cancelFormBtn.addEventListener('click', () => formBox.classList.add('hidden'));
        }

        if (saveFormBtn) {
            saveFormBtn.addEventListener('click', async () => {
                const ip = document.getElementById('new-client-ip-input')?.value.trim();
                const mac = document.getElementById('new-client-mac-input')?.value.trim();
                const name = document.getElementById('new-client-name-input')?.value.trim();
                const group = document.getElementById('new-client-group-input')?.value.trim();

                if (!ip) {
                    showToast('O endereço IP é obrigatório.', 'warning');
                    return;
                }

                try {
                    saveFormBtn.disabled = true;
                    saveFormBtn.innerText = 'Salvando...';
                    const res = await fetch(`${API_BASE_URL}/api/devices`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ ip, mac, alias: name, hostname: name, group_name: group })
                    });
                    const data = await res.json();
                    if (data.success) {
                        showToast(`Máquina ${ip} salva com sucesso!`, 'success');
                        formBox.classList.add('hidden');
                        loadSavedDevices();
                    } else {
                        showToast('Erro ao salvar: ' + data.message, 'error');
                    }
                } catch (err) {
                    showToast('Erro de comunicação.', 'error');
                } finally {
                    saveFormBtn.disabled = false;
                    saveFormBtn.innerText = 'Salvar Máquina';
                }
            });
        }

        // Importar Descobertos Atuais da Tela
        if (importDiscoveredBtn) {
            importDiscoveredBtn.addEventListener('click', async () => {
                const domItems = Array.from(document.querySelectorAll('#ip-list .ip-item'));
                if (domItems.length === 0) {
                    showToast('Nenhum computador encontrado na tela principal para importar.', 'warning');
                    return;
                }

                importDiscoveredBtn.disabled = true;
                importDiscoveredBtn.innerText = 'Importando...';

                const devicesToSave = domItems.map(item => {
                    const ip = item.dataset.baseIp || item.dataset.ip || item.querySelector('.ip-address')?.textContent.trim();
                    const mac = item.dataset.mac || deviceMacs[ip] || item.querySelector('.mac-address')?.textContent.trim() || '';
                    const hostname = item.dataset.hostname || deviceHostnames[ip] || item.querySelector('.hostname')?.textContent.trim() || '';
                    const alias = item.dataset.alias || deviceAliases[ip] || item.querySelector('.alias-text')?.textContent.trim() || hostname;
                    const group = item.dataset.group || deviceGroupsMap[ip] || '';
                    return { ip, mac, alias: alias || hostname, hostname: hostname || alias, group_name: group };
                }).filter(d => d.ip);

                try {
                    const res = await fetch(`${API_BASE_URL}/api/devices/batch`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ devices: devicesToSave })
                    });
                    const data = await res.json();
                    if (data.success) {
                        showToast(`🎉 ${data.count} computadores salvos no inventário!`, 'success', 4000);
                        loadSavedDevices();
                    } else {
                        showToast('Erro ao importar: ' + data.message, 'error');
                    }
                } catch (err) {
                    showToast('Erro ao salvar computadores.', 'error');
                } finally {
                    importDiscoveredBtn.disabled = false;
                    importDiscoveredBtn.innerText = '📥 Salvar Descobertos Atuais';
                }
            });
        }

        // Testar Conexão Rápida (< 1s) dentro do Modal
        if (quickScanBtn) {
            quickScanBtn.addEventListener('click', async () => {
                quickScanBtn.disabled = true;
                quickScanBtn.innerText = 'Testando...';
                try {
                    const res = await fetch(`${API_BASE_URL}/api/devices/quick-scan`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({})
                    });
                    const data = await res.json();
                    if (data.success && Array.isArray(data.ips)) {
                        clientStatusCache = {};
                        data.ips.forEach(item => {
                            clientStatusCache[item.ip] = { type: item.type, os: item.os_type };
                        });
                        showToast(`⚡ Teste concluído: ${data.online_count} online de ${data.total_saved} em menos de 1 segundo!`, 'success', 4000);
                        renderSavedDevicesTable();
                    }
                } catch (err) {
                    showToast('Erro ao testar conectividade rápida.', 'error');
                } finally {
                    quickScanBtn.disabled = false;
                    quickScanBtn.innerText = '⚡ Testar Conexão (< 1s)';
                }
            });
        }

        // Limpar Todos
        if (clearAllBtn) {
            clearAllBtn.addEventListener('click', async () => {
                if (!confirm('Deseja realmente apagar TODOS os computadores do inventário de clientes?')) return;
                try {
                    const res = await fetch(`${API_BASE_URL}/api/devices/clear`, { method: 'POST' });
                    const data = await res.json();
                    if (data.success) {
                        showToast('Inventário de clientes limpo com sucesso.', 'info');
                        clientStatusCache = {};
                        loadSavedDevices();
                    }
                } catch (err) {
                    showToast('Erro ao limpar inventário.', 'error');
                }
            });
        }

        // Carregar na Tela Principal
        if (applyToGridBtn) {
            applyToGridBtn.addEventListener('click', () => {
                closeModal();
                showToast('⚡ Carregando clientes salvos na tela principal...', 'info', 2000);
                if (typeof fetchAndDisplayIps === 'function') {
                    fetchAndDisplayIps({ forceQuickScan: true });
                }
            });
        }

        // Exportar Backup JSON
        if (exportFileBtn) {
            exportFileBtn.addEventListener('click', () => {
                if (allSavedDevices.length === 0) {
                    showToast('Nenhum computador cadastrado para exportar.', 'warning');
                    return;
                }
                const jsonStr = JSON.stringify({
                    export_date: new Date().toISOString(),
                    total: allSavedDevices.length,
                    devices: allSavedDevices
                }, null, 2);
                const blob = new Blob([jsonStr], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `inventario_clientes_lab_${new Date().toISOString().split('T')[0]}.json`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
                showToast('💾 Arquivo de backup baixado com sucesso!', 'success');
            });
        }

        // Exportar Relatório em Planilha CSV (Excel)
        const exportCsvBtn = document.getElementById('export-clients-csv-btn');
        if (exportCsvBtn) {
            exportCsvBtn.addEventListener('click', () => {
                if (allSavedDevices.length === 0) {
                    showToast('Nenhum computador cadastrado para exportar.', 'warning');
                    return;
                }

                let csvContent = "Endereço IP;Endereço MAC;Nome / Apelido;Hostname;Grupo / Sala;Status\r\n";
                allSavedDevices.forEach(d => {
                    const st = clientStatusCache[d.ip];
                    const statusText = st ? (st.type !== 'offline' ? 'Online' : 'Offline') : 'Desconhecido';
                    const line = [
                        d.ip || '',
                        d.mac || '',
                        d.alias || '',
                        d.hostname || '',
                        d.group_name || '',
                        statusText
                    ].map(v => `"${String(v).replace(/"/g, '""')}"`).join(';');
                    csvContent += line + "\r\n";
                });

                const blob = new Blob(["\uFEFF" + csvContent], { type: 'text/csv;charset=utf-8;' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `inventario_computadores_${new Date().toISOString().split('T')[0]}.csv`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
                showToast('📊 Tabela de inventário exportada em CSV com sucesso!', 'success');
            });
        }

        // Auto-Detectar MACs e Hostnames via ARP/SSH na rede
        const discoverDetailsBtn = document.getElementById('discover-device-details-btn');
        if (discoverDetailsBtn) {
            discoverDetailsBtn.addEventListener('click', async () => {
                discoverDetailsBtn.disabled = true;
                discoverDetailsBtn.innerText = '📡 Detectando...';
                showToast('📡 Consultando tabela ARP e testando máquinas na rede para preencher MACs e Nomes...', 'info', 4000);

                try {
                    const res = await fetch(`${API_BASE_URL}/api/devices/discover-details`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({})
                    });
                    const data = await res.json();
                    if (data.success) {
                        showToast(data.message || `Detecção concluída! ${data.updated} máquinas enriquecidas.`, 'success', 5000);
                        await loadSavedDevices();
                        if (typeof loadGroupAndDeviceMetadata === 'function') loadGroupAndDeviceMetadata();
                    } else {
                        showToast('Erro ao detectar detalhes: ' + data.message, 'error');
                    }
                } catch (err) {
                    showToast('Erro de comunicação ao detectar detalhes.', 'error');
                } finally {
                    discoverDetailsBtn.disabled = false;
                    discoverDetailsBtn.innerText = '📡 Capturar MACs/Nomes';
                }
            });
        }

        // Ligar Marcados via WoL
        const wolSelectedBtn = document.getElementById('wol-selected-clients-btn');
        if (wolSelectedBtn) {
            wolSelectedBtn.addEventListener('click', async () => {
                const selectedCheckboxes = Array.from(document.querySelectorAll('.saved-client-cb:checked'));
                if (selectedCheckboxes.length === 0) {
                    showToast('Selecione pelo menos um computador na lista para ligar.', 'warning');
                    return;
                }

                const selectedIps = selectedCheckboxes.map(cb => cb.value);
                const devicesWithMac = allSavedDevices.filter(d => selectedIps.includes(d.ip) && (d.mac || '').trim());

                if (devicesWithMac.length === 0) {
                    showToast('Nenhum dos computadores selecionados possui endereço MAC cadastrado para Wake-on-LAN.', 'warning', 5000);
                    return;
                }

                wolSelectedBtn.disabled = true;
                wolSelectedBtn.innerText = '⚡ Enviando WoL...';

                try {
                    const res = await fetch(`${API_BASE_URL}/api/devices/wol-batch`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ ips: devicesWithMac.map(d => d.ip) })
                    });
                    const data = await res.json();
                    if (data.success) {
                        showToast(`⚡ Sinal Wake-on-LAN transmitido para ${devicesWithMac.length} computador(es)!`, 'success', 4500);
                    } else {
                        showToast('Falha no WoL: ' + data.message, 'error');
                    }
                } catch (err) {
                    showToast(`Erro de comunicação ao enviar sinal WoL: ${err.message || 'Servidor inacessível'}`, 'error');
                } finally {
                    wolSelectedBtn.disabled = false;
                    wolSelectedBtn.innerText = '⚡ Ligar Marcados (WoL)';
                }
            });
        }

        // Excluir Marcados do Inventário em Lote
        const deleteSelectedBtn = document.getElementById('delete-selected-clients-btn');
        if (deleteSelectedBtn) {
            deleteSelectedBtn.addEventListener('click', async () => {
                const selectedCheckboxes = Array.from(document.querySelectorAll('.saved-client-cb:checked'));
                if (selectedCheckboxes.length === 0) {
                    showToast('Selecione os computadores que deseja excluir do inventário.', 'warning');
                    return;
                }

                const selectedIps = selectedCheckboxes.map(cb => cb.value);
                if (!confirm(`Deseja realmente remover os ${selectedIps.length} computadores selecionados do inventário?`)) {
                    return;
                }

                deleteSelectedBtn.disabled = true;
                deleteSelectedBtn.innerText = 'Excluindo...';

                try {
                    const res = await fetch(`${API_BASE_URL}/api/devices/delete-batch`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ ips: selectedIps })
                    });
                    const data = await res.json();
                    if (data.success) {
                        showToast(`🗑️ ${data.deleted} computador(es) removido(s) do inventário.`, 'info', 3500);
                        loadSavedDevices();
                    } else {
                        showToast('Erro: ' + data.message, 'error');
                    }
                } catch (err) {
                    showToast('Erro ao excluir computadores em lote.', 'error');
                } finally {
                    deleteSelectedBtn.disabled = false;
                    deleteSelectedBtn.innerText = '🗑️ Excluir Marcados';
                }
            });
        }

        // Importar Backup JSON/CSV
        if (importFileBtn && importFileInput) {
            importFileBtn.addEventListener('click', () => importFileInput.click());
            importFileInput.addEventListener('change', async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                const text = await file.text();
                let devicesToImport = [];

                try {
                    const parsed = JSON.parse(text);
                    if (Array.isArray(parsed)) {
                        devicesToImport = parsed;
                    } else if (parsed && Array.isArray(parsed.devices)) {
                        devicesToImport = parsed.devices;
                    }
                } catch (jsonErr) {
                    const lines = text.split(/\r?\n/);
                    for (const line of lines) {
                        const trimmed = line.trim();
                        if (!trimmed || trimmed.startsWith('#')) continue;
                        const parts = trimmed.split(/[,;\t]/);
                        if (parts.length >= 1 && parts[0].includes('.')) {
                            devicesToImport.push({
                                ip: parts[0].trim(),
                                mac: parts[1]?.trim(),
                                alias: parts[2]?.trim(),
                                group_name: parts[3]?.trim()
                            });
                        }
                    }
                }

                if (devicesToImport.length === 0) {
                    showToast('Nenhum formato válido de IP encontrado no arquivo.', 'error');
                    importFileInput.value = '';
                    return;
                }

                try {
                    const res = await fetch(`${API_BASE_URL}/api/devices/batch`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ devices: devicesToImport })
                    });
                    const data = await res.json();
                    if (data.success) {
                        showToast(`🎉 ${data.count} dispositivos importados com sucesso!`, 'success');
                        loadSavedDevices();
                    } else {
                        showToast('Erro na importação: ' + data.message, 'error');
                    }
                } catch (err) {
                    showToast('Falha ao enviar dados de importação.', 'error');
                } finally {
                    importFileInput.value = '';
                }
            });
        }

        // Carregamento inicial de contagem para o badge
        loadSavedDevices();
    }

    // Inicializa o inventário de máquinas clientes
    initSavedClientsInventoryModule();

    // --- Módulo de Reinício do Backend ---
    function initRestartBackendModule() {
        document.addEventListener('click', async (e) => {
            const restartBackendBtn = e.target.closest('#restart-backend-btn, .btn-restart-backend, .restart-badge');
            if (!restartBackendBtn) return;

            e.preventDefault();
            const confirmed = window.confirm('Deseja realmente reiniciar o servidor backend (Flask/Python)?\nO serviço será reiniciado em segundo plano e reconectado automaticamente.');
            if (!confirmed) return;

            const allRestartBtns = document.querySelectorAll('#restart-backend-btn, .btn-restart-backend, .restart-badge');
            allRestartBtns.forEach(btn => {
                btn.disabled = true;
                btn.classList.add('restarting');
                btn.innerHTML = `${typeof getIconSvg === 'function' ? getIconSvg('rotate-cw', { width: 12, height: 12 }) : '<i data-feather="rotate-cw"></i>'} <span>Reiniciando...</span>`;
            });
            if (window.feather) feather.replace();

            showToast('🔄 Solicitando reinício do servidor backend...', 'info', 6000);

            try {
                const response = await fetch(`${API_BASE_URL}/api/system/restart-backend`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                const data = await response.json();
                if (data && data.success) {
                    showToast('⏳ Servidor backend reiniciando. Aguardando reconexão...', 'warning', 10000);
                }
            } catch (err) {
                showToast('⏳ Servidor backend em processo de reinício...', 'warning', 8000);
            }

            // Polling de reconexão
            let attempts = 0;
            const maxAttempts = 35;
            const pollInterval = setInterval(async () => {
                attempts++;
                try {
                    const checkRes = await fetch(`${API_BASE_URL}/get-aliases?t=${Date.now()}`, { cache: 'no-store' });
                    if (checkRes.ok) {
                        clearInterval(pollInterval);
                        const btnsToRestore = document.querySelectorAll('#restart-backend-btn, .btn-restart-backend, .restart-badge');
                        btnsToRestore.forEach(btn => {
                            btn.classList.remove('restarting');
                            btn.disabled = false;
                            btn.innerHTML = `${typeof getIconSvg === 'function' ? getIconSvg('rotate-cw', { width: 12, height: 12 }) : '<i data-feather="rotate-cw"></i>'} <span>Reiniciar Backend</span>`;
                        });
                        if (window.feather) feather.replace();
                        showToast('✅ Servidor backend reiniciado e reconectado com sucesso!', 'success', 5000);
                        
                        if (typeof fetchAndDisplayIps === 'function') fetchAndDisplayIps();
                        if (typeof loadMetadata === 'function') loadMetadata();
                        if (typeof loadGroupAndDeviceMetadata === 'function') loadGroupAndDeviceMetadata();
                    }
                } catch (e) {
                    if (attempts >= maxAttempts) {
                        clearInterval(pollInterval);
                        const btnsToRestore = document.querySelectorAll('#restart-backend-btn, .btn-restart-backend, .restart-badge');
                        btnsToRestore.forEach(btn => {
                            btn.classList.remove('restarting');
                            btn.disabled = false;
                            btn.innerHTML = `${typeof getIconSvg === 'function' ? getIconSvg('rotate-cw', { width: 12, height: 12 }) : '<i data-feather="rotate-cw"></i>'} <span>Reiniciar Backend</span>`;
                        });
                        if (window.feather) feather.replace();
                        showToast('⚠️ O servidor demorou para responder. Verifique se o processo está em execução.', 'error', 8000);
                    }
                }
            }, 1000);
        });
    }

    // Inicializa o módulo de reinício do backend
    initRestartBackendModule();

    // ETAPA FINAL: Inicia a carga de metadados apenas após todos os elementos 
    // e variáveis do DOM terem sido declarados acima.
    Promise.all([loadMetadata(), loadGroupAndDeviceMetadata(), fetchAndDisplayIps(), loadScheduleConfig()]).then(() => {
        if (header) header.classList.add('header-ready');
        fetchScheduledTasks();
        if (typeof scanChildProtectionStatus === 'function') {
            scanChildProtectionStatus();
        }
    });

}

// Inicialização segura que funciona mesmo se o script for carregado após a emissão de DOMContentLoaded
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mainInit);
} else {
    mainInit();
}

