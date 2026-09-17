/**
 * inspector.js - Inspecionador Visual de Elementos & Dev HUD
 * 
 * Funcionalidade:
 * 1. Segure a tecla CTRL e aponte o mouse para qualquer elemento da interface para inspecioná-lo.
 * 2. Mostra um HUD flutuante com Tag, ID, Classes, Atributos de Ação (data-*), dimensões e arquivo provável.
 * 3. Destaque visual do elemento em foco (outline neon suave).
 * 4. Clique enquanto segura CTRL para copiar o Seletor CSS / ID diretamente para a área de transferência.
 * 5. Atalho de alternância permanente: CTRL + SHIFT + D (Ligar/Desligar Modo Inspeção Fixo).
 */

(function () {
    'use strict';

    let isCtrlPressed = false;
    let isPinnedMode = false;
    let currentHoveredEl = null;
    let hudElement = null;
    let highlightOverlay = null;

    // Cria os elementos do HUD e Overlay no DOM
    function initInspectorDOM() {
        if (document.getElementById('dev-element-inspector-hud')) return;

        // Overlay de contorno do elemento em foco
        highlightOverlay = document.createElement('div');
        highlightOverlay.id = 'dev-element-inspector-overlay';
        highlightOverlay.style.cssText = `
            position: fixed;
            pointer-events: none;
            z-index: 2147483640;
            border: 2px dashed #38bdf8;
            border-radius: 4px;
            background: rgba(56, 189, 248, 0.12);
            box-shadow: 0 0 16px rgba(56, 189, 248, 0.45), inset 0 0 8px rgba(56, 189, 248, 0.2);
            transition: all 0.08s ease-out;
            display: none;
        `;
        document.body.appendChild(highlightOverlay);

        // Tooltip Flutuante de Informações (HUD)
        hudElement = document.createElement('div');
        hudElement.id = 'dev-element-inspector-hud';
        hudElement.style.cssText = `
            position: fixed;
            z-index: 2147483647;
            pointer-events: none;
            background: rgba(15, 23, 42, 0.96);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(99, 102, 241, 0.6);
            border-radius: 10px;
            padding: 10px 14px;
            box-shadow: 0 20px 45px rgba(0, 0, 0, 0.9), 0 0 25px rgba(99, 102, 241, 0.35);
            font-family: 'JetBrains Mono', Consolas, Monaco, monospace;
            font-size: 11px;
            line-height: 1.45;
            color: #f8fafc;
            min-width: 260px;
            max-width: 440px;
            display: none;
            animation: devHudFadeIn 0.12s ease-out;
        `;
        document.body.appendChild(hudElement);

        // Injeta estilos de animação e toasts
        const style = document.createElement('style');
        style.textContent = `
            @keyframes devHudFadeIn {
                from { opacity: 0; transform: translateY(4px) scale(0.98); }
                to { opacity: 1; transform: translateY(0) scale(1); }
            }
            .dev-hud-title {
                display: flex;
                align-items: center;
                justify-content: space-between;
                font-weight: 700;
                color: #818cf8;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
                padding-bottom: 4px;
                margin-bottom: 6px;
                font-size: 11px;
                letter-spacing: 0.3px;
            }
            .dev-hud-row {
                display: flex;
                gap: 6px;
                margin-bottom: 3px;
                word-break: break-all;
            }
            .dev-hud-label {
                color: #94a3b8;
                font-weight: 600;
                min-width: 58px;
                flex-shrink: 0;
            }
            .dev-hud-val-tag { color: #f43f5e; font-weight: 700; }
            .dev-hud-val-id { color: #38bdf8; font-weight: 700; }
            .dev-hud-val-class { color: #fbbf24; font-weight: 500; }
            .dev-hud-val-attr { color: #a78bfa; font-weight: 500; }
            .dev-hud-val-file { color: #34d399; font-weight: 600; }
            .dev-hud-footer {
                margin-top: 6px;
                padding-top: 4px;
                border-top: 1px dashed rgba(255, 255, 255, 0.12);
                color: #64748b;
                font-size: 10px;
                text-align: right;
            }
            .dev-inspector-toast {
                position: fixed;
                bottom: 24px;
                right: 24px;
                background: linear-gradient(135deg, #4f46e5 0%, #06b6d4 100%);
                color: #ffffff;
                padding: 10px 18px;
                border-radius: 8px;
                box-shadow: 0 10px 30px rgba(0, 0, 0, 0.6);
                font-family: 'Inter', sans-serif;
                font-size: 12px;
                font-weight: 600;
                z-index: 2147483647;
                pointer-events: none;
                animation: devToastSlideUp 0.2s ease-out;
            }
            @keyframes devToastSlideUp {
                from { opacity: 0; transform: translateY(12px); }
                to { opacity: 1; transform: translateY(0); }
            }
        `;
        document.head.appendChild(style);
    }

    // Identifica o provável arquivo fonte / módulo baseado no seletor e contexto
    function inferSourceLocation(el) {
        const id = el.id || '';
        const cls = typeof el.className === 'string' ? el.className : '';
        const inGrid = el.closest('#vnc-grid-modal, .standalone-grid-wrapper, #vnc-grid-container, .vnc-grid-header');
        const inSchedule = el.closest('#schedule-alert-modal, .btn-schedule');
        const inPower = el.closest('#power-management-modal, .btn-power');
        const inDecibel = el.closest('#decibel-meter-modal, #decibel-floating-hud, .btn-decibel');

        if (inGrid || id.startsWith('vnc-') || cls.includes('vnc-')) {
            return 'grid_view.html / grid_view.js / grid_view.css';
        }
        if (inSchedule || id.includes('schedule')) {
            return 'index.html / script.js / schedule_service.py';
        }
        if (inPower || id.includes('power')) {
            return 'index.html / script.js (Power Modal)';
        }
        if (inDecibel || id.includes('decibel')) {
            return 'index.html / script.js (Decibel Meter)';
        }
        return 'index.html / script.js / style.css';
    }

    // Formata o Seletor CSS mais direto para cópia
    function getBestSelector(el) {
        if (el.id) {
            return `#${el.id}`;
        }
        const tag = el.tagName.toLowerCase();
        const action = el.getAttribute('data-action') || el.getAttribute('data-batch-action');
        if (action) {
            const attr = el.hasAttribute('data-action') ? 'data-action' : 'data-batch-action';
            return `${tag}[${attr}="${action}"]`;
        }
        if (el.classList && el.classList.length > 0) {
            const firstClass = Array.from(el.classList).filter(c => !c.startsWith('dev-'))[0];
            if (firstClass) return `.${firstClass}`;
        }
        return tag;
    }

    // Renderiza os dados no HUD
    function updateHUD(el, mouseX, mouseY) {
        if (!el || el === document.body || el === document.documentElement || el === highlightOverlay || el === hudElement) {
            hideInspector();
            return;
        }

        const rect = el.getBoundingClientRect();
        
        // 1. Atualiza Contorno (Highlight Overlay)
        highlightOverlay.style.display = 'block';
        highlightOverlay.style.top = `${rect.top}px`;
        highlightOverlay.style.left = `${rect.left}px`;
        highlightOverlay.style.width = `${rect.width}px`;
        highlightOverlay.style.height = `${rect.height}px`;

        // 2. Extrai Metadados
        const tag = el.tagName.toLowerCase();
        const idStr = el.id ? `#${el.id}` : '<sem ID>';
        const classNames = Array.from(el.classList || []).filter(c => !c.startsWith('dev-'));
        const classStr = classNames.length > 0 ? `.${classNames.join(' .')}` : '<sem classes>';
        
        // Atributos Relevantes
        const dataAttrs = [];
        Array.from(el.attributes || []).forEach(attr => {
            if (attr.name.startsWith('data-') || attr.name === 'title' || attr.name === 'type' || attr.name === 'name') {
                dataAttrs.push(`${attr.name}="${attr.value}"`);
            }
        });
        const attrStr = dataAttrs.length > 0 ? dataAttrs.slice(0, 3).join(' ') : '';
        const dimensions = `${Math.round(rect.width)} × ${Math.round(rect.height)} px`;
        const sourceFile = inferSourceLocation(el);

        // 3. Monta HTML do Tooltip
        hudElement.innerHTML = `
            <div class="dev-hud-title">
                <span>🔍 INSPECTOR DE ELEMENTO</span>
                <span style="color:#38bdf8;">${dimensions}</span>
            </div>
            <div class="dev-hud-row">
                <span class="dev-hud-label">Tag:</span>
                <span class="dev-hud-val-tag">&lt;${tag}&gt;</span>
            </div>
            <div class="dev-hud-row">
                <span class="dev-hud-label">ID:</span>
                <span class="dev-hud-val-id">${idStr}</span>
            </div>
            <div class="dev-hud-row">
                <span class="dev-hud-label">Classes:</span>
                <span class="dev-hud-val-class">${classStr}</span>
            </div>
            ${attrStr ? `
            <div class="dev-hud-row">
                <span class="dev-hud-label">Ação:</span>
                <span class="dev-hud-val-attr">${attrStr}</span>
            </div>` : ''}
            <div class="dev-hud-row">
                <span class="dev-hud-label">Origem:</span>
                <span class="dev-hud-val-file">${sourceFile}</span>
            </div>
            <div class="dev-hud-footer">
                💡 Clique para copiar seletor para o VS Code
            </div>
        `;

        // 4. Posiciona o HUD próximo ao cursor evitando estourar a tela
        hudElement.style.display = 'block';
        const hudWidth = hudElement.offsetWidth || 280;
        const hudHeight = hudElement.offsetHeight || 140;
        const winW = window.innerWidth;
        const winH = window.innerHeight;

        let posX = mouseX + 16;
        let posY = mouseY + 16;

        if (posX + hudWidth > winW - 12) {
            posX = mouseX - hudWidth - 12;
        }
        if (posY + hudHeight > winH - 12) {
            posY = mouseY - hudHeight - 12;
        }

        hudElement.style.left = `${Math.max(10, posX)}px`;
        hudElement.style.top = `${Math.max(10, posY)}px`;
    }

    function hideInspector() {
        if (isPinnedMode) return;
        if (highlightOverlay) highlightOverlay.style.display = 'none';
        if (hudElement) hudElement.style.display = 'none';
        currentHoveredEl = null;
    }

    function showCopyToast(text) {
        const toast = document.createElement('div');
        toast.className = 'dev-inspector-toast';
        toast.innerHTML = `📋 <strong>Seletor Copiado!</strong><br><span style="font-family:monospace; font-size:11px; color:#e0e7ff;">${text}</span>`;
        document.body.appendChild(toast);
        setTimeout(() => {
            toast.style.transition = 'opacity 0.3s ease';
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 300);
        }, 2200);
    }

    // Copia seletor para clipboard
    function copyElementSelector(el) {
        if (!el) return;
        const selector = getBestSelector(el);
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(selector).then(() => {
                showCopyToast(selector);
            }).catch(() => {
                showCopyToast(selector);
            });
        } else {
            showCopyToast(selector);
        }
    }

    // --- Listeners de Teclado e Mouse ---
    window.addEventListener('keydown', (e) => {
        // Atalho de Alternância Fixa: CTRL + SHIFT + D
        if (e.ctrlKey && e.shiftKey && (e.key === 'D' || e.key === 'd')) {
            e.preventDefault();
            isPinnedMode = !isPinnedMode;
            if (!isPinnedMode) {
                hideInspector();
                showCopyToast('Modo Inspector: Desativado');
            } else {
                showCopyToast('Modo Inspector: ATIVADO (Fixado)');
            }
            return;
        }

        if (e.key === 'Control' || e.ctrlKey) {
            isCtrlPressed = true;
            if (currentHoveredEl) {
                const rect = currentHoveredEl.getBoundingClientRect();
                updateHUD(currentHoveredEl, rect.left + 20, rect.top + 20);
            }
        }
    });

    window.addEventListener('keyup', (e) => {
        if (e.key === 'Control' || !e.ctrlKey) {
            isCtrlPressed = false;
            if (!isPinnedMode) {
                hideInspector();
            }
        }
    });

    window.addEventListener('mousemove', (e) => {
        currentHoveredEl = e.target;
        if (isCtrlPressed || isPinnedMode) {
            initInspectorDOM();
            updateHUD(e.target, e.clientX, e.clientY);
        }
    }, { passive: true });

    // Intercepta clique para copiar quando estiver no modo inspeção
    window.addEventListener('click', (e) => {
        if (isCtrlPressed || isPinnedMode) {
            // Evita disparar ações do botão inspecionado (ex: fechar modal, reiniciar, desligar)
            e.preventDefault();
            e.stopPropagation();
            copyElementSelector(e.target);
        }
    }, true);

    // Inicialização segura
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initInspectorDOM);
    } else {
        initInspectorDOM();
    }

})();
