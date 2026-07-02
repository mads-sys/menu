# Testar bloqueio de pop-ups (Bloquear Pop-ups / Desbloquear Pop-ups)

## 1) O que o sistema faz (backend)
- A ação **Bloquear Pop-ups** grava policies/prefs no **HOME do usuário remoto**:
  - Firefox:
    - `~/.config/firefox/policies/policies.json`
    - com `PopupsBlocker: { Behavior: "block" }`
  - Chromium/Chrome:
    - `~/.config/chromium/policies/managed/policies.json`
    - com `PopupsBlocked: true`
  - Fallback (se prefs não existirem):
    - `~/.config/chromium/Default/Preferences`

- A ação **Desbloquear Pop-ups** remove esses arquivos de policy.

## 2) Checklist manual (funcional)
1. No dashboard, selecione um **IP** e execute **Bloquear Pop-ups**.
2. No **host remoto** (usuário que abre o navegador): **reinicie o navegador**.
3. Teste páginas que disparam interstitial/pop-ups.
4. Execute **Desbloquear Pop-ups**.
5. Reinicie o navegador novamente e repita o teste.

## 3) Opção “teste objetivo” (verificação por arquivo + comando)
### 3.1 Verificar se as policies foram aplicadas
No host remoto (ou via ação remota `executar comando`, se você tiver):

**Firefox**
- Verifique:
  - `~/.config/firefox/policies/policies.json`
- Deve existir e conter:
  - `"PopupsBlocker"` e `"Behavior": "block"`

**Chrome/Chromium**
- Verifique:
  - `~/.config/chromium/policies/managed/policies.json`
- Deve existir e conter:
  - `"PopupsBlocked": true`

### 3.2 Teste rápido (script de verificação)
Execute no host remoto (como o usuário que usa o navegador):

```bash
echo "== Firefox policies ==";
if [ -f "$HOME/.config/firefox/policies/policies.json" ]; then
  grep -n "PopupsBlocker" "$HOME/.config/firefox/policies/policies.json" || true
  grep -n "Behavior" "$HOME/.config/firefox/policies/policies.json" || true
else
  echo "Firefox policies.json NÃO existe";
fi

echo "== Chromium/Chrome policies ==";
if [ -f "$HOME/.config/chromium/policies/managed/policies.json" ]; then
  grep -n "PopupsBlocked" "$HOME/.config/chromium/policies/managed/policies.json" || true
else
  echo "Chromium policies.json NÃO existe";
fi

echo "== Fallback prefs (se existir) ==";
if [ -f "$HOME/.config/chromium/Default/Preferences" ]; then
  echo "Preferences fallback existe (não é garantia de bloqueio)";
else
  echo "Preferences fallback não existe";
fi
```

Interpretação:
- Se os arquivos existirem e os valores “certo” estiverem presentes, o bloqueio foi aplicado no perfil esperado.
- Se você não encontrar os arquivos, ou eles estiverem em outro HOME/perfil, o bloqueio não vai afetar o navegador que você está testando.

## 4) Teste funcional usando uma página de referência
Se você quiser um teste repetível:
- Use uma página conhecida por disparar interstitials/popups.
- Exemplos comuns incluem fluxos de login/consentimento e sites com anúncios.

Procedimento:
1. Com **Bloquear Pop-ups** ativo, a janela/interstitial deve ser bloqueada.
2. Com **Desbloquear Pop-ups**, o comportamento deve voltar ao normal.

## 5) Erros comuns (causas prováveis)
- Navegador aberto com **outro usuário** (HOME diferente).
- Snap/Flatpak usando **outro perfil** (não usa `~/.config/...` diretamente).
- Navegador não reiniciado após gravar policies.
- Testar Chrome quando o navegador é Firefox (ou vice-versa).

## 6) Resultado esperado
- Após **Bloquear Pop-ups** + reinício do navegador:
  - Interstitials/pop-ups bloqueados.
- Após **Desbloquear Pop-ups** + reinício do navegador:
  - Interstitials/pop-ups voltam.

