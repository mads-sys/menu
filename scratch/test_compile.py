import command_builder
import subprocess
import re
import os

fn = command_builder.COMMANDS['bloquear_tela_mensagem']
script, err = fn({})

# Extract python script written between cat <<'EOF' > /tmp/fullscreen_lock_overlay.py and EOF
match = re.search(r"cat <<'EOF' > /tmp/fullscreen_lock_overlay\.py\n(.*?)\nEOF", script, re.DOTALL)
if match:
    py_code = match.group(1)
    os.makedirs('scratch', exist_ok=True)
    with open('scratch/test_overlay.py', 'w', encoding='utf-8') as f:
        f.write(py_code)
    print('Extracted py_code length:', len(py_code))
    res = subprocess.run(['python', '-m', 'py_compile', 'scratch/test_overlay.py'], capture_output=True, text=True)
    if res.returncode == 0:
        print('[OK] Generated Python script compiles cleanly!')
    else:
        print('[ERROR] Compile error:', res.stderr)
else:
    print('❌ Could not match EOF block')
