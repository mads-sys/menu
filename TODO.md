# TODO

- [ ] Revogar imediatamente o token GitHub (`github_pat_...`) que foi colado aqui (Settings → Personal access tokens → Revoke).
- [ ] Se o token tiver sido commitado/pushado, remover do histórico do git (ex.: `git filter-repo` / `bfg`) e fazer novo push com credenciais limpas.
- [ ] Verificar o repositório para garantir que não há o token (ou padrões como `github_pat_`, `ghp_`, `GITHUB_TOKEN`, `PERSONAL_ACCESS_TOKEN`) em nenhum arquivo.
- [ ] Remover prompts de "Pressione Enter" no backend quando detecção de IPs/Nmap estiver lenta ou Nmap não encontrado (evitar bloquear execuções não-interativas).

