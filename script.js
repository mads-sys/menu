// --- Importação de Constantes (Sempre no topo do arquivo) ---
import { ACTIONS, CONFLICTING_ACTIONS, LOCAL_ACTIONS, NO_PASSWORD_ACTIONS } from './constants.js';

document.addEventListener('DOMContentLoaded', () => {
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

        // 2. Cria um container para as ferramentas (Relógio + Tema) à direita
        const headerTools = document.createElement('div');
        headerTools.className = 'header-tools';
        headerTools.appendChild(clockContainer);
        if (themeSwitcher) headerTools.appendChild(themeSwitcher);
        header.appendChild(headerTools);

        // Inicializa o novo ícone do título inserido dinamicamente
        if (window.feather) feather.replace({ 'container': header });
    }
    const pad2 = (n) => String(n).padStart(2, '0');
    const updateClock = () => {
        const now = new Date();
        const hours = now.getHours();
        const minutes = now.getMinutes();
        const seconds = now.getSeconds();

        const is24h = true;
        const hh = is24h ? pad2(hours) : pad2(((hours + 11) % 12) + 1);
        const ampm = is24h ? '' : (hours >= 12 ? ' PM' : ' AM');

        const weekday = now.toLocaleDateString('pt-BR', { weekday: 'long' });
        const dateStr = now.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });

        clockContainer.innerHTML = `
            <i data-feather="clock" style="width:14px;height:14px"></i>
            <span class="clock-time"><strong>${hh}:${pad2(minutes)}</strong></span>
            <span class="clock-seconds">:${pad2(seconds)}</span>
            <span class="clock-ampm">${ampm}</span>
            <span class="clock-date">${weekday} · ${dateStr}</span>
        `;

        if (window.feather) feather.replace({ 'container': clockContainer });
    };
    // Atualiza a cada 1s, mas com sincronização para começar no “segundo certo”
    const scheduleNextTick = () => {
        const ms = 1000 - (Date.now() % 1000);
        setTimeout(() => {
            updateClock();
            scheduleNextTick();
        }, ms);
    };

    scheduleNextTick();
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
        scheduledTasksList.innerHTML = '';
        const pendingTasks = tasks.filter(t => t.status === 'pending');
        const currentTaskIds = new Set(pendingTasks.map(t => t.id));
        
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
            const actionLabel = ACTION_METADATA[task.action]?.label || task.action;
            const ips = JSON.parse(task.ips);
            
            item.innerHTML = `
                <div class="task-info">
                    <span class="task-action">${actionLabel}</span>
                    <span class="task-details">${ips.length} máquina(s) selecionada(s)</span>
                    <span class="task-time">⏰ ${task.execution_time.replace('T', ' ')}</span>
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
                // Sem confirmação extra para evitar atrasos/desconforto
                await cancelTask(btn.dataset.id);
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
    const ipListSection = document.querySelector('.ip-list-section');
    if (ipListSection) {
        const header = ipListSection.querySelector('h3');
        const controls = ipListSection.querySelector('.ip-list-controls');
        const rangeStart = document.getElementById('network-range-start');
        const rangeEnd = document.getElementById('network-range-end');

        if (rangeStart && rangeEnd) {
            // Carrega o valor salvo anteriormente no navegador
            const savedRange = localStorage.getItem('customNetworkRange') || '';
            if (savedRange.includes(' a ')) {
                const [start, end] = savedRange.split(' a ');
                rangeStart.value = start;
                rangeEnd.value = end;
            } else {
                rangeStart.value = savedRange;
            }

            // Validação visual da faixa de rede enquanto o usuário digita
            const validateRange = () => {
                const startVal = rangeStart.value.trim();
                const endVal = rangeEnd.value.trim();
                const refreshBtn = document.getElementById('refresh-btn');
                const isBtnLoading = refreshBtn?.classList.contains('loading');
                
                const wrapper = rangeStart.closest('.range-input-wrapper');

                if (!startVal && !endVal) {
                    wrapper?.classList.remove('valid', 'invalid');
                    if (refreshBtn && !isBtnLoading) {
                        refreshBtn.disabled = false;
                        refreshBtn.setAttribute('data-tooltip', 'Recarregar lista de dispositivos');
                    }
                    return;
                }
                
                // Regex para validar se é um número (octet) ou um IP completo
                const ipRegex = /^(\d{1,3}\.){3}(\d{1,3}|x)(\/\d{1,2})?$/; // IP ou CIDR
                const octetRegex = /^\d{1,3}$/;

                const isStartValid = ipRegex.test(startVal) || octetRegex.test(startVal);
                const isEndValid = endVal === "" || ipRegex.test(endVal) || octetRegex.test(endVal);
                const isValid = isStartValid && isEndValid;

                wrapper?.classList.toggle('valid', isValid);
                wrapper?.classList.toggle('invalid', !isValid);
                
                // Salva a combinação no localStorage para persistência
                if (isValid && startVal) {
                    const combined = endVal ? `${startVal} a ${endVal}` : startVal;
                    localStorage.setItem('customNetworkRange', combined);
                }

                if (refreshBtn && !isBtnLoading) {
                    refreshBtn.disabled = !isValid;
                    refreshBtn.setAttribute('data-tooltip', isValid ? 
                        'Recarregar lista de dispositivos' : 
                        'Formato inválido. Use: 192.168.1.x, 50-80, ou lista (ex: 10, 20-30)');
                }
            };
            rangeStart.addEventListener('input', validateRange);
            rangeEnd.addEventListener('input', validateRange);
            validateRange(); // Valida o estado inicial (caso haja valor no localStorage)

            // Lógica para o botão de limpar o input
            const clearRangeBtn = document.getElementById('clear-range-btn');
            if (clearRangeBtn) {
                clearRangeBtn.addEventListener('click', () => {
                    rangeStart.value = '';
                    rangeEnd.value = '';
                    localStorage.removeItem('customNetworkRange');
                    validateRange(); // Reseta o estado do botão de refresh e classes CSS
                    rangeStart.focus();
                });
            }
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

    // Define a URL base para as chamadas de API de forma dinâmica
    const API_HOST = window.location.hostname || '127.0.0.1';
    let API_BASE_URL = `${window.location.protocol}//${API_HOST}:5000`;

    // Ajusta a URL base conforme o ambiente (Produção, Dev ou Local)
    if (window.location.port === '5000') {
        API_BASE_URL = window.location.origin;
    } else if (window.location.protocol === 'file:') {
        API_BASE_URL = 'http://127.0.0.1:5000';
    }
    console.log(`[Config] API_BASE_URL definida como: ${API_BASE_URL}`);

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
        [ACTIONS.DISABLE_AUTOLOGIN]: 'Comenta o autologin do LightDM para exigir login manual',
        [ACTIONS.ENABLE_AUTOLOGIN]: 'Descomenta o autologin do LightDM para permitir login automático',
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
            const response = await fetch(`${API_BASE_URL}/api/metadata`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            
            const data = await response.json();
            if (data.success) {
                ACTION_METADATA = data.metadata;
                console.log("ACTION_METADATA recebido do backend:", ACTION_METADATA); // DEBUG: Verificar conteúdo
                renderDynamicActionMenu(data.metadata);
                // Filtra metadados dinâmicos para categorias específicas de processamento
                STREAMING_ACTIONS = Object.keys(data.metadata).filter(k => data.metadata[k].is_streaming || k.includes('install') || k.includes('atualizar'));
                DANGEROUS_ACTIONS = Object.keys(data.metadata).filter(k => data.metadata[k].is_dangerous || k === 'desligar' || k === 'reiniciar');
                if (data.version) {
                    displayAppVersion(data.version, data.branch);
                }
                if (logo) logo.classList.remove('logo-error-glow');
                backendErrorOverlay.classList.add('hidden'); // Esconde o overlay se estava visível
                console.log("[Conexão] Metadados carregados.");
            }
        } catch (e) {
            console.error(`[Erro de Conexão] Falha ao conectar ao backend em ${API_BASE_URL}:`, e);
            if (logo) logo.classList.add('logo-error-glow');
            playAlertSound();
            logStatusMessage(`Falha ao carregar metadados das ações. Verifique se o servidor está rodando em ${API_BASE_URL}`, "error");
            backendErrorOverlay.classList.remove('hidden'); // Mostra o overlay de erro
        } finally {
            // Removido o fetchAndDisplayIps daqui para evitar chamadas duplas
            console.log("[Conexão] Inicialização de metadados finalizada.");
        }
    }

    /**
     * Retorna a classe CSS de grupo com base na categoria da ação definida no metadado.
     */
    function getCategoryClass(actionKey) {
        const meta = ACTION_METADATA[actionKey];
        if (!meta || !meta.category) return '';
        return `group-${meta.category.toLowerCase().replace(/\s/g, '-')}`;
    }

    function displayAppVersion(version, branch) {
        const container = document.querySelector('.container');
        if (!container) return;
        
        let footer = document.querySelector('.app-version-footer');
        if (!footer) {
            footer = document.createElement('div');
            footer.className = 'app-version-footer';
            container.appendChild(footer);
        }
        const branchDisplay = branch ? `<strong>${branch}</strong> · ` : '';
        footer.innerHTML = `
            <div class="app-version-footer-content">
                <span>GitHub</span>
                <span class="footer-divider">•</span>
                <span>${branchDisplay}<code>${version}</code></span>
                <a class="footer-link" href="https://github.com/mads-sys/menu" target="_blank" rel="noopener noreferrer">Repositório</a>
            </div>
        `;
    }

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
            if (action.icon) {
                const icon = document.createElement('i');
                icon.setAttribute('data-feather', action.icon);
                label.appendChild(icon);
            }
            label.appendChild(document.createTextNode(action.label));
            
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
    const togglePasswordBtn = document.getElementById('toggle-password-btn');
    const passwordToggleIcon = document.getElementById('password-toggle-icon');

    let autoRefreshTimer = null;
    let statusMonitorTimer = null;
    let sessionPassword = null;
    // Initial state for submit button text
    submitBtnText.textContent = 'Executar Ação';

    let deviceAliases = {}; // Cache local de apelidos
    let ipsWithKeyErrors = new Set();

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
        return sessionPassword || passwordInput.value || "qwe123";
    }

    // Função de validação que habilita/desabilita o botão de submit
    function checkFormValidity() {
        const hasSelectedActions = Array.from(actionSelect.selectedOptions).length > 0;

        // O botão agora permanece habilitado se houver uma ação selecionada.
        // Isso permite que o usuário clique e receba o feedback de "shake" se esquecer os IPs.
        submitBtn.disabled = !hasSelectedActions;
    }

    // --- Lógica do Seletor de Tema ---
    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        
        // Sincroniza o estado visual do checkbox e o ícone
        if (theme === 'dark') {
            themeToggle.checked = true;
            themeLabel.textContent = '☀️';
        } else if (theme === 'high-contrast') {
            themeToggle.checked = true;
            themeLabel.textContent = '👁️';
        } else {
            themeToggle.checked = false;
            themeLabel.textContent = '🌙';
        }
    }

    // Lista de temas disponíveis para rotação
    const availableThemes = ['light', 'dark', 'high-contrast'];

    // Alteramos para ouvir o clique no container do switcher para rotacionar os 3 temas
    themeLabel.parentElement.addEventListener('click', (e) => {
        e.preventDefault(); // Impede o comportamento padrão do checkbox
        const currentTheme = localStorage.getItem('theme') || 'dark';
        const nextIndex = (availableThemes.indexOf(currentTheme) + 1) % availableThemes.length;
        const newTheme = availableThemes[nextIndex];

        localStorage.setItem('theme', newTheme);
        applyTheme(newTheme);
        playConfirmSound();
    });

    // Aplica o tema salvo no carregamento da página
    const currentTheme = localStorage.getItem('theme') || 'dark'; // Padrão para 'dark'
    applyTheme(currentTheme);

    // --- Lógica de Zoom da Lista de IPs ---
    const zoomSlider = document.getElementById('zoom-slider');
    let currentZoom = parseInt(localStorage.getItem('ipListZoom')) || 220;

    const applyZoom = (val) => {
        document.documentElement.style.setProperty('--ip-item-min-width', `${val}px`);
        localStorage.setItem('ipListZoom', val);
        if (zoomSlider) zoomSlider.value = val;
    };

    // Aplica o zoom salvo inicialmente
    applyZoom(currentZoom);

    if (zoomSlider) {
        zoomSlider.addEventListener('input', (e) => {
            applyZoom(parseInt(e.target.value));
        });
    }

    // --- Lógica do Botão de Visualizar Senha ---
    if (togglePasswordBtn && passwordInput && passwordToggleIcon) {
        togglePasswordBtn.addEventListener('click', () => {
            const isPassword = passwordInput.type === 'password';
            if (isPassword) {
                passwordInput.type = 'text'; 
                passwordToggleIcon.innerHTML = '<i data-feather="eye-off"></i>';
            } else {
                passwordInput.type = 'password';
                passwordToggleIcon.innerHTML = '<i data-feather="eye"></i>';
            }
            feather.replace({ width: '1em', height: '1em' }); // Redesenha o ícone
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

    function renderQuickAccessButtons() {
        const counts = JSON.parse(localStorage.getItem('actionUsageCounts')) || {};
        // Pega as 4 ações mais usadas para garantir que caibam na mesma linha do rodapé
        const sortedActions = Object.entries(counts)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 4)
            .map(entry => entry[0]);

        if (sortedActions.length === 0) {
            quickActionsContainer.classList.add('hidden');
            return;
        }

        quickActionsContainer.innerHTML = '';
        quickActionsContainer.classList.remove('hidden');

        const label = document.createElement('div');
        label.className = 'quick-actions-label';
        label.textContent = '⚡ Mais Acessados';
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
                iconName = CATEGORY_DEFAULT_ICONS[meta.category] || 'tool'; // Fallback para 'tool' se a categoria não tiver um ícone padrão
            }
            if (iconName) {
                const icon = document.createElement('i');
                icon.setAttribute('data-feather', iconName);
                btn.appendChild(icon);
            }

            const span = document.createElement('span');
            const fullLabel = option.textContent.trim();
            const shortLabel = fullLabel.length > 18 ? fullLabel.split(' ').slice(0, 2).join(' ') : fullLabel;
            span.textContent = shortLabel;
            btn.appendChild(span);

            // Usa a descrição amigável se disponível, senão usa o texto do botão completo
            btn.setAttribute('data-tooltip', ACTION_DESCRIPTIONS[action] || `Ação: ${fullLabel}`);
            
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
            groupDiv.className = 'custom-option-group';

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

        // 2. Lógica para abrir/fechar o menu
        customSelectTrigger.addEventListener('click', () => {
            customSelectContainer.classList.toggle('open');
        });

        // Fecha o menu se clicar fora dele
        window.addEventListener('click', (e) => {
            if (!customSelectContainer.contains(e.target)) {
                customSelectContainer.classList.remove('open');
            }
        });

        // Lógica da barra de pesquisa de ações
        const actionSearchInput = document.getElementById('action-search-input');

        // Garante que o menu abra ao focar ou digitar na busca externa
        actionSearchInput.addEventListener('focus', () => {
            customSelectContainer.classList.add('open');
        });

        actionSearchInput.addEventListener('input', () => {
            if (!customSelectContainer.classList.contains('open')) {
                customSelectContainer.classList.add('open');
            }
            const searchTerm = actionSearchInput.value.toLowerCase().trim();
            const allGroups = customOptionsContent.querySelectorAll('.custom-option-group');

            allGroups.forEach(group => {
                const allOptions = group.querySelectorAll('.checkbox-item');
                let groupHasVisibleOptions = false;

                allOptions.forEach(option => {
                    const label = option.querySelector('label');
                    const isVisible = label.textContent.toLowerCase().includes(searchTerm);
                    option.style.display = isVisible ? '' : 'none';
                    if (isVisible) {
                        groupHasVisibleOptions = true;
                    }
                });

                // Esconde o grupo inteiro se nenhuma de suas opções corresponder à busca
                group.style.display = groupHasVisibleOptions ? '' : 'none';
            });
        });

        // 3. Lógica para atualizar o texto do botão e os campos condicionais
        actionSelect.addEventListener('change', () => {
            const selectedOptions = Array.from(actionSelect.selectedOptions);
            const triggerContainer = customSelectTrigger.querySelector('.trigger-text-container');
            const placeholder = triggerContainer.querySelector('.trigger-placeholder');

            // Limpa as tags existentes
            triggerContainer.querySelectorAll('.selected-action-tag').forEach(tag => tag.remove());

            if (selectedOptions.length === 0) {
                placeholder.style.display = 'inline';
            } else {
                placeholder.style.display = 'none';
                selectedOptions.forEach(option => {
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

                    // Evento para remover a tag e desmarcar a opção
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
            }
            if (window.feather) feather.replace();
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
            if (selectedActions.includes(ACTIONS.SEND_MESSAGE)) {
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
                   selectedActions.includes('remover_whitelist')) {
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
    async function fetchAliases() {
        try {
            const response = await fetch(`${API_BASE_URL}/get-aliases`);
            const data = await response.json();
            if (data.success) {
                deviceAliases = data.aliases || {};
            }
        } catch (e) {
            console.error("Erro ao buscar apelidos:", e);
        }
    }

    // Função para buscar e exibir os IPs
    async function fetchAndDisplayIps() {
        console.log("[fetchAndDisplayIps] Iniciando busca e exibição de IPs.");
        
        const logo = document.querySelector('.app-logo, .logo-fallback-icon');
        if (logo) {
            logo.classList.add('spinning-logo');
            logo.classList.remove('logo-error-glow'); // Remove brilho de erro ao tentar novamente
        }

        refreshBtn.disabled = true;
        refreshBtn.classList.add('loading');
        refreshBtnText.textContent = 'Buscando IPs...';

        // Constrói a string de faixa a partir dos dois campos
        const start = document.getElementById('network-range-start')?.value.trim();
        const end = document.getElementById('network-range-end')?.value.trim();
        const customRange = (start && end) ? `${start} a ${end}` : (start || "");

        // Mantém os IPs selecionados para reaplicar a seleção após a atualização.
        const previouslySelectedIps = new Set(Array.from(document.querySelectorAll('input[name="ip"]:checked')).map(cb => cb.value));

        // Carrega a ordem salva dos IPs, se existir.
        const savedIpOrder = JSON.parse(localStorage.getItem('ipOrder'));

        /**
         * Helper para obter SVG do Feather sem disparar um scan global do DOM.
         */
        const getIconSvg = (name, options = { width: 14, height: 14 }) => {
            if (window.feather && feather.icons[name]) {
                return feather.icons[name].toSvg(options);
            }
            return `<i data-feather="${name}"></i>`;
        };

        // Função para ordenar os IPs com base na ordem salva
        const sortIps = (backendIps) => {
            if (!backendIps) return [];
            if (!savedIpOrder || savedIpOrder.length === 0) return backendIps;

            // Otimização: Usa um Map para lookup O(1) em vez de find/some O(N)
            const backendMap = new Map(backendIps.map(item => [item.ip, item]));
            const savedIpSet = new Set(savedIpOrder);

            // IPs que já têm ordem definida
            const orderedPart = savedIpOrder
                .filter(ipStr => backendMap.has(ipStr))
                .map(ipStr => backendMap.get(ipStr));

            // Novos IPs (não presentes na ordem salva)
            const newPart = backendIps.filter(item => !savedIpSet.has(item.ip));

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
            // Dispara a busca de apelidos e a varredura de rede em paralelo para ganhar velocidade
            const [aliasRes, scanRes] = await Promise.all([
                fetchAliases(),
                fetch(`${API_BASE_URL}/discover-ips`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ custom_range: customRange })
                })
            ]);
            const data = await scanRes.json();

            if (data.success) {
                if (logo && logo.classList.contains('logo-error-glow')) {
                    logo.classList.remove('logo-error-glow');
                }
                // Ordena os IPs ativos com base na ordem salva antes de exibi-los
                const activeIps = sortIps(data.ips);
                // Limpa o esqueleto de carregamento antes de adicionar os IPs reais.
                ipListContainer.innerHTML = '';

                if (ipCountElement) {
                    const rangeInfo = data.range ? ` na rede ${data.range}` : '';
                    ipCountElement.textContent = `(${activeIps.length} encontrados${rangeInfo})`;
                }

                const fragment = document.createDocumentFragment();
                activeIps.forEach((itemObj, index) => {
                    // Extrai IP e Tipo do objeto retornado pelo backend
                    const ip = itemObj.ip;
                    const connectionType = itemObj.type || 'ssh'; // Padrão 'ssh' se não vier definido
                    const mac = itemObj.mac || "Não capturado";

                    const item = document.createElement('div');
                    item.className = 'ip-item draggable-item';
                    item.dataset.ip = ip;
                    item.style.animationDelay = `${index * 0.05}s`;
                    item.draggable = true; // Torna o item arrastável
                    const lastOctet = ip.split('.').pop();

                    const statusDot = document.createElement('span');
                    statusDot.className = 'status-dot';

                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.id = `ip-${ip}`;
                    checkbox.name = 'ip';
                    checkbox.value = ip;

                    const label = document.createElement('label');
                    label.htmlFor = `ip-${ip}`;
                    
                    // Lógica de exibição do apelido
                    const alias = deviceAliases[ip];
                    if (alias) {
                        label.innerHTML = `<span class="alias-text">${alias}</span><span class="ip-subtext">${ip}</span>`;
                        label.classList.add('has-alias');
                        item.setAttribute('data-tooltip', `IP: ${ip} | MAC: ${mac}`); // Tooltip personalizado
                    } else {
                        label.textContent = lastOctet; // Padrão antigo
                        item.setAttribute('data-tooltip', `MAC: ${mac} | Clique duplo para renomear`);
                    }

                    // --- Indicador de Sinal de Rede (Ícone + Barras) ---
                    const signalIndicator = document.createElement('div');
                    signalIndicator.className = 'network-signal-indicator hidden';
                    signalIndicator.innerHTML = getIconSvg('wifi', { width: 12, height: 12 });
                    signalIndicator.style.color = 'var(--subtle-text-color)';
                    
                    for (let i = 1; i <= 4; i++) {
                        const bar = document.createElement('span');
                        bar.className = `bar bar-${i}`;
                        signalIndicator.appendChild(bar);
                    }

                // Se o IP foi retornado como offline pelo backend, já marca visualmente
                if (connectionType === 'offline') {
                    item.classList.add('status-offline');
                } else {
                    item.classList.add('status-online');
                }

                    // --- Indicador de Tipo de Detecção (SSH ou Ping) ---
                    const typeIndicator = document.createElement('span');
                    typeIndicator.className = 'type-indicator';
                    typeIndicator.setAttribute('data-tooltip', connectionType === 'ssh' ? 'Detectado via SSH (Porta 22)' : 'Detectado via Ping (ICMP)');
                    typeIndicator.innerHTML = connectionType === 'ssh' ? getIconSvg('terminal') : getIconSvg('activity');
                    typeIndicator.style.marginLeft = '6px';
                    typeIndicator.style.color = 'var(--subtle-text-color)';

                    // Evento para renomear com clique duplo
                    label.addEventListener('dblclick', async (e) => {
                        e.preventDefault();
                        const currentName = deviceAliases[ip] || "";
                        const newName = prompt(`Definir nome para este dispositivo (${ip}):`, currentName);
                        
                        if (newName !== null) { // Se não cancelou
                            try {
                                await fetch(`${API_BASE_URL}/set-alias`, {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ ip: ip, alias: newName })
                                });
                                logStatusMessage(`Nome do dispositivo ${ip} atualizado.`, 'success');
                                fetchAndDisplayIps(); // Recarrega a lista para atualizar visual
                            } catch (err) {
                                logStatusMessage(`Erro ao salvar nome: ${err.message}`, 'error');
                            }
                        }
                    });

                    const blockBtn = document.createElement('button');
                    blockBtn.type = 'button';
                    blockBtn.className = 'block-ip-btn';
                    blockBtn.setAttribute('data-tooltip', 'Bloquear este IP');
                    blockBtn.innerHTML = getIconSvg('x-circle');
                    blockBtn.dataset.ip = ip;

                    // --- Botão para Editar MAC Manualmente ---
                    const editMacBtn = document.createElement('button');
                    editMacBtn.type = 'button';
                    editMacBtn.className = 'edit-mac-btn';
                    editMacBtn.setAttribute('data-tooltip', 'Definir MAC manualmente');
                    editMacBtn.innerHTML = getIconSvg('hash'); // Ícone de sustenido/ID
                    editMacBtn.style.color = mac === "Não capturado" ? 'var(--error-color)' : 'var(--subtle-text-color)';

                    editMacBtn.onclick = async (e) => {
                        e.preventDefault();
                        const currentMac = mac === "Não capturado" ? "" : mac;
                        const newMac = prompt(`Digite o endereço MAC para ${ip}:`, currentMac);
                        if (newMac) {
                            try {
                                const res = await fetch(`${API_BASE_URL}/set-mac`, {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ ip, mac: newMac })
                                });
                                const resData = await res.json();
                                if (resData.success) {
                                    showToast(resData.message, 'success');
                                    fetchAndDisplayIps();
                                } else { showToast(resData.message, 'error'); }
                            } catch (err) { showToast("Erro ao salvar MAC", 'error'); }
                        }
                    };

                    // --- Botão de Toggle de Usuário (Flag no IP) ---
                    const userToggleBtn = document.createElement('button');
                    userToggleBtn.type = 'button';
                    userToggleBtn.className = 'user-toggle-btn';
                    userToggleBtn.innerHTML = '👥';
                    userToggleBtn.setAttribute('data-tooltip', 'Alvo: Todos');
                    userToggleBtn.dataset.target = ''; // Vazio = todos
                    userToggleBtn.style.display = 'none'; // Oculto por padrão, aparece apenas se houver múltiplos usuários

                    userToggleBtn.addEventListener('click', (e) => {
                        e.preventDefault();
                        e.stopPropagation(); // Impede que marque o checkbox do IP
                        
                        const current = userToggleBtn.dataset.target;
                        if (current === '') {
                            // Muda para Aluno 1
                            userToggleBtn.dataset.target = 'aluno1';
                            userToggleBtn.innerHTML = '1️⃣';
                            userToggleBtn.setAttribute('data-tooltip', 'Alvo: aluno1');
                            userToggleBtn.classList.add('active-1');
                        } else if (current === 'aluno1') {
                            // Muda para Aluno 2
                            userToggleBtn.dataset.target = 'aluno2';
                            userToggleBtn.innerHTML = '2️⃣';
                            userToggleBtn.setAttribute('data-tooltip', 'Alvo: aluno2');
                            userToggleBtn.classList.remove('active-1');
                            userToggleBtn.classList.add('active-2');
                        } else {
                            // Volta para Todos
                            userToggleBtn.dataset.target = '';
                            userToggleBtn.innerHTML = '👥';
                            userToggleBtn.setAttribute('data-tooltip', 'Alvo: Todos');
                            userToggleBtn.classList.remove('active-2');
                        }
                    });

                    const statusIcon = document.createElement('span');
                    statusIcon.className = 'status-icon';
                    statusIcon.id = `status-${ip}`;

                    if (previouslySelectedIps.has(ip)) {
                        checkbox.checked = true;
                    }

                    item.append(statusDot, checkbox, label, signalIndicator, typeIndicator, userToggleBtn, blockBtn, statusIcon);
                    fragment.appendChild(item);
                    
                    // Inicia a observação de visibilidade para este item
                    statusObserver.observe(item);
                });

                if (activeIps.length > 0) {
                    ipListContainer.appendChild(fragment);
                    // feather.replace() não é mais necessário aqui pois injetamos SVGs estáticos
                    if (exportIpsBtn) exportIpsBtn.disabled = false;
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
        // Agendamos a atualização para o próximo quadro de animação disponível
        requestAnimationFrame(() => {
            // Cria um mapa de todos os itens de IP visíveis para acesso rápido
            const ipItemMap = new Map();
            ipListContainer.querySelectorAll('.ip-item').forEach(item => {
                ipItemMap.set(item.dataset.ip, item);
            });

            for (const ip in statuses) {
                const item = ipItemMap.get(ip);
                if (!item) continue;

                // Batch de leitura e escrita: evitamos alternar entre ler e escrever no DOM
                const statusData = statuses[ip];
                const status = (typeof statusData === 'object') ? statusData.status : statusData;
                const userCount = (typeof statusData === 'object' && statusData.user_count) ? statusData.user_count : 0;
                const signal = (typeof statusData === 'object') ? statusData.signal : null;

                // Atualização das classes
                item.classList.remove('status-online', 'status-offline', 'status-auth-error');

                if (status === 'offline') {
                    item.classList.add('status-offline');
                } else if (status === 'auth_error') {
                    item.classList.add('status-auth-error');
                } else {
                    item.classList.add('status-online');

                    // Lógica Multiseat
                    const toggleBtn = item.querySelector('.user-toggle-btn');
                    if (toggleBtn) {
                        if (userCount >= 2) {
                            if (toggleBtn.style.display !== 'inline-block') {
                                toggleBtn.style.display = 'inline-block';
                                toggleBtn.title = `Multiseat detectado (${userCount} usuários).`;
                                item.style.borderLeft = "5px solid var(--group-color-3)";
                            }
                        } else {
                            if (toggleBtn.style.display !== 'none') {
                                toggleBtn.style.display = 'none';
                                item.style.borderLeft = "1px solid transparent";
                            }
                        }
                    }
                }

                // Atualiza Indicador de Sinal
                const signalIndicator = item.querySelector('.network-signal-indicator');
                if (signalIndicator && signal !== null && status === 'online') {
                    let level = 0;
                    if (signal > 75) level = 4;
                    else if (signal > 50) level = 3;
                    else if (signal > 25) level = 2;
                    else if (signal > 0) level = 1;
                    
                    signalIndicator.className = `network-signal-indicator level-${level}`;
                    signalIndicator.classList.remove('hidden');
                    signalIndicator.setAttribute('data-tooltip', `Sinal: ${signal}%`);
                } else if (signalIndicator) {
                    signalIndicator.classList.add('hidden');
                }
            }
            // Re-aplica os filtros dentro do mesmo quadro de animação
            applyIpFilters();
        });
    }

    function startStatusMonitor() {
        stopStatusMonitor(); // Garante que não haja timers duplicados
        statusMonitorTimer = setInterval(checkIpStatuses, STATUS_MONITOR_INTERVAL);
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
        // 1. Desmarcar todos os checkboxes de IP
        document.querySelectorAll('input[name="ip"]').forEach(checkbox => {
            checkbox.checked = false;
        });
        selectAllCheckbox.checked = false;

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

        // Revalidar o formulário (isso desabilitará o botão "Executar")
        checkFormValidity();
        logStatusMessage('Interface limpa.', 'details');
    }

    // Listener para o botão de limpar/resetar
    resetBtn.addEventListener('click', resetUI);

    // Listener para o checkbox "Selecionar Todos"
    selectAllCheckbox.addEventListener('change', (event) => { // Este listener ainda é útil para a lógica específica de marcar/desmarcar todos
        const isChecked = event.target.checked;
        document.querySelectorAll('input[name="ip"]').forEach(checkbox => {
            checkbox.checked = isChecked;
        });
        checkFormValidity(); // Chama a validação após a seleção
    });

    // --- Botão para Selecionar Apenas Online ---
    // A estrutura do botão agora está no HTML (#select-online-btn)
    const selectOnlineBtn = document.getElementById('select-online-btn');
    
    if (selectOnlineBtn) {
        selectOnlineBtn.addEventListener('click', () => {
            const ipItems = document.querySelectorAll('.ip-item');
            let count = 0;
            
            ipItems.forEach(item => {
                // Considera apenas itens visíveis (caso haja filtro de busca)
                if (item.style.display !== 'none') {
                    const checkbox = item.querySelector('input[name="ip"]');
                    if (checkbox) {
                        const isOnline = item.classList.contains('status-online');
                        checkbox.checked = isOnline;
                        if (isOnline) count++;
                    }
                }
            });
            
            // Atualiza o estado do checkbox "Selecionar Todos"
            const visibleItems = Array.from(ipItems).filter(item => item.style.display !== 'none');
            const total = visibleItems.length;
            
            selectAllCheckbox.checked = (count === total && total > 0);
            selectAllCheckbox.indeterminate = (count > 0 && count < total);
            
            checkFormValidity();
            logStatusMessage(`${count} dispositivo(s) online selecionado(s).`, 'details');
        });
    }

    // --- Função Centralizada de Filtragem (Pesquisa + Status) ---
    let lastDesyncTotal = null;
    function applyIpFilters() {
        const searchTerm = ipSearchInput.value.toLowerCase().trim();
        const hideOffline = hideOfflineToggle ? hideOfflineToggle.checked : false;
        const showDesyncOnly = showDesyncOnlyToggle ? showDesyncOnlyToggle.checked : false;
        const ipItems = document.querySelectorAll('.ip-item');
        let visibleCount = 0;
        let desyncTotal = 0;
        let onlineCount = 0;
        let offlineCount = 0;

        ipItems.forEach(item => {
            if (item.classList.contains('status-sync-error')) desyncTotal++;
            if (item.classList.contains('status-online')) onlineCount++;
            if (item.classList.contains('status-offline')) offlineCount++;

            const ip = item.dataset.ip;
            const matchesSearch = ip.includes(searchTerm);
            
            // Verifica se o item deve ser escondido por estar offline
            // Consideramos offline se tiver a classe 'status-offline' E não tiver 'status-online' (segurança)
            const isOffline = item.classList.contains('status-offline');
            const shouldHide = hideOffline && isOffline;
            const shouldHideSyncOk = showDesyncOnly && !item.classList.contains('status-sync-error');

            if (matchesSearch && !shouldHide && !shouldHideSyncOk) {
                const isHidden = item.style.display === 'none';
                item.style.display = '';
                if (isHidden) {
                    item.style.animation = 'none';
                    void item.offsetWidth; // Trigger reflow de forma leve
                    item.style.animation = '';
                }
                item.style.animationDelay = `${visibleCount * 0.01}s`;
                visibleCount++;
            } else {
                item.style.display = 'none';
            }
        });

        // Alerta visual no cabeçalho se o número de máquinas desincronizadas mudar
        if (lastDesyncTotal !== null && desyncTotal !== lastDesyncTotal) {
            const headerElement = document.querySelector('header');
            if (headerElement) {
                headerElement.classList.remove('header-desync-alert');
                void headerElement.offsetWidth; // Força reflow para reiniciar animação se necessário
                headerElement.classList.add('header-desync-alert');
                setTimeout(() => headerElement.classList.remove('header-desync-alert'), 3000);
            }
        }
        lastDesyncTotal = desyncTotal;

        // Atualiza o contador para refletir o que está visível
        if (ipCountElement) {
             const total = ipItems.length;
             ipCountElement.textContent = `(${visibleCount} visíveis de ${total})`;
        }

        // Atualiza o contador de desincronizados no cabeçalho da lista
        const badgeContainer = document.getElementById('desync-badge-container');
        if (badgeContainer) {
            badgeContainer.innerHTML = desyncTotal > 0 
                ? `<span class="error-text" style="font-size: 0.7em; margin-left: 10px; background: color-mix(in srgb, var(--error-color) 15%, transparent); padding: 2px 8px; border-radius: 10px; border: 1px solid var(--error-color); white-space: nowrap;">⚠️ ${desyncTotal} com hora errada</span>` 
                : '';
        }

        // Aproveitamos para atualizar os stats do topo da página
        const statsOnline = document.getElementById('stats-online');
        const statsOffline = document.getElementById('stats-offline');
        if (statsOnline) statsOnline.textContent = onlineCount;
        if (statsOffline) statsOffline.textContent = offlineCount;
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
    function showToast(message, type = 'details') {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        
        // Ícones baseados no tipo
        let icon = '';
        if (type === 'success') icon = '<i data-feather="check-circle"></i> ';
        else if (type === 'error') icon = '<i data-feather="alert-circle"></i> ';
        else icon = '<i data-feather="info"></i> ';

        toast.innerHTML = `${icon}<span>${message}</span>`;
        
        // Adiciona ao container
        toastContainer.appendChild(toast);
        feather.replace(); // Renderiza o ícone

        // Remove após 4 segundos
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
    let logBuffer = [];
    let isLogUpdatePending = false;

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

        const iconElement = document.getElementById(`status-${ip}`);
        iconElement.innerHTML = '🔄'; // Feedback visual imediato
        iconElement.className = 'status-icon processing';
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
        // Ações de streaming podem demorar muito, então o timeout é maior.
        const isStreaming = STREAMING_ACTIONS.includes(payload.action);
        const timeoutDuration = isStreaming ? 300000 : 30000; // 5 minutos para streaming, 30s para o resto.
        const timeoutId = setTimeout(() => controller.abort(), timeoutDuration);

        // Para ações de streaming, gera um ID único para o log. O backend usará isso
        // para criar um logger específico para esta requisição, resolvendo o erro
        // "ssh_connect() missing 1 required positional argument: 'logger'".
        const requestBody = isStreaming
            ? { ...payload, ip, log_id: `log-group-${ip.replace(/\./g, '-')}-${Date.now()}` }
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
                    const logContentElement = document.querySelector(`#${logGroupId} .log-group-content`);
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
        const iconElement = document.getElementById(`status-${ip}`);
        const logGroupId = `log-group-${ip.replace(/\./g, '-')}-${Date.now()}`;

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

    setupCategoryButtons('sites-group', 'sites-text');
    setupCategoryButtons('whitelist-sites-group', 'whitelist-sites-text');

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
                    const statusIcon = document.getElementById(`status-${ip}`);
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

    // Listener para o evento de submit do formulário
    actionForm.addEventListener('submit', async (event) => {
        event.preventDefault(); // Impede o recarregamento da página

        let password = getActivePassword();
        let selectedActions = Array.from(actionSelect.selectedOptions).map(opt => opt.value);
        
        // Coleta os IPs, anexando a flag de usuário se estiver definida no botão de toggle
        const selectedIps = Array.from(document.querySelectorAll('input[name="ip"]:checked')).map(checkbox => {
            const toggleBtn = checkbox.closest('.ip-item').querySelector('.user-toggle-btn');
            const targetUser = toggleBtn ? toggleBtn.dataset.target : '';
            return targetUser ? `${checkbox.value}/${targetUser}` : checkbox.value;
        });

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
            // A correção aqui é garantir que o payload inicial já contenha a senha,
            // pois algumas ações (como UPDATE_SYSTEM) não entravam nos 'if' abaixo
            // e acabavam com um payload sem a senha.
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

            async function processBatch(payload, actionText) {
                logStatusMessage(`--- Iniciando ação: "${actionText}" ---`, 'details');
                let batchSuccess = false;
                const totalIPs = selectedIps.length;
                let processedIPs = 0;
                updateProgressBar(0, totalIPs, actionText);

                const tasks = selectedIps.map(targetIp => async () => {
                    const ipItem = ipListContainer.querySelector(`.ip-item[data-ip="${targetIp}"]`);
                    if (ipItem) {
                        ipItem.classList.add('processing');
                    }

                    // Limpa o conteúdo do ícone para que apenas o spinner do CSS seja exibido.
                    const iconElement = document.getElementById(`status-${targetIp}`);
                    const result = await executeRemoteAction(targetIp, payload);
                    if (result.success) batchSuccess = true;                    
                    // Passa o payload para que a função saiba se deve pular o log (no caso de streaming)
                    updateIpStatus(targetIp, result, actionText, payload); // Passa o payload
                    processedIPs++;
                    updateProgressBar(processedIPs, totalIPs, actionText);
                });
                await runPromisesInParallel(tasks, MAX_CONCURRENT_TASKS);
                return batchSuccess;
            }

            /**
             * Executa tarefas em paralelo com limite de concorrência e política de re-tentativa.
             */
            async function runPromisesInParallel(taskFunctions, concurrency, retries = 1) {
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
                const workers = Array(Math.min(concurrency, queue.length)).fill(null).map(async () => {
                    while (queue.length > 0) {
                        const task = queue.shift();
                        if (task) await executeWithRetry(task);
                    }
                });
                await Promise.all(workers);
            }

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

            if (anySuccess && sessionPassword === null) {
                sessionPassword = password;
                passwordGroup.style.display = 'none';
                logStatusMessage('Senha salva para esta sessão. Para alterar, recarregue a página.', 'details');
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
        { id: 'zoom-slider', text: 'Ajustar tamanho da grade de dispositivos' },
        { id: 'clear-log-btn', text: 'Limpar histórico de log' },
        { id: 'fix-keys-btn', text: 'Corrigir erros de chave SSH' },
        { id: 'select-online-btn', text: 'Selecionar apenas Online' },
        { id: 'manage-blocklist-btn', text: 'Gerenciar IPs bloqueados' }
    ];
    staticTooltips.forEach(t => {
        const el = document.getElementById(t.id);
        if (el) el.setAttribute('data-tooltip', t.text);
    });

    // --- Modal Integração Horário ---
    const horarioModal = document.getElementById('horario-modal');
    const horarioCloseBtn = document.getElementById('horario-close-btn');
    const horarioOpenBtn = document.getElementById('horario-open-btn');
    if (horarioModal && horarioCloseBtn) {
        // Fecha ao clicar no botão
        horarioCloseBtn.addEventListener('click', () => {
            horarioModal.classList.add('hidden');
            const iframe = document.getElementById('horario-iframe');
            if (iframe) iframe.contentWindow?.postMessage({ type: 'horario:resume' }, '*');
        });

        // Fecha ao clicar fora do conteúdo
        horarioModal.addEventListener('click', (e) => {
            if (e.target === horarioModal) {
                horarioModal.classList.add('hidden');
            }
        });
    }

    // Abre SOMENTE ao clicar no botão ao lado da senha
    if (horarioModal && horarioOpenBtn) {
        horarioOpenBtn.addEventListener('click', () => {
            horarioModal.classList.remove('hidden');
            const iframe = document.getElementById('horario-iframe');
            if (iframe) {
                // Ajuda a garantir foco/reativação após abrir modal
                try { iframe.contentWindow?.focus?.(); } catch (e) {}
            }
        });
    }


    // Modal de Integração Horário: NÃO abrir automaticamente.
    // Deve ser aberto apenas via clique em um botão (ao lado da senha) ou outro gatilho do usuário.
    try {
        localStorage.removeItem('horario-modal-opened');
    } catch (e) {}


    // ETAPA FINAL: Inicia a carga de metadados apenas após todos os elementos 

    // e variáveis do DOM terem sido declarados acima.
    // Chamamos as duas funções de forma independente para que uma não trave a outra.
    // Aguarda o carregamento inicial de metadados e IPs para marcar o sistema como pronto
    Promise.all([loadMetadata(), fetchAndDisplayIps()]).then(() => {
        if (header) header.classList.add('header-ready');
        fetchScheduledTasks();
    });
});
