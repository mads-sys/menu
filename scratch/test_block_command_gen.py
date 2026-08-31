import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from command_builder import COMMANDS

print("Comandos registrados contendo 'sticker':")
for k in COMMANDS:
    if 'sticker' in k:
        print(" -", k)

block_func = COMMANDS.get('bloquear_stickers')
if block_func:
    script, err = block_func({})
    print("\n--- INÍCIO DO SCRIPT DE BLOQUEIO ---")
    print(script[:1500])
    print("...\n--- FIM DA PRÉVIA DO SCRIPT ---")
else:
    print("ERRO: bloquear_stickers não foi encontrado em COMMANDS")
