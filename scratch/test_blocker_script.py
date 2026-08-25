import os, sys, json, hashlib, zipfile, subprocess, glob

opt_dir = "/opt/elefante_blocker"
src_dir = os.path.join(opt_dir, "src")
os.makedirs(src_dir, exist_ok=True)

manifest = {
    "manifest_version": 2,
    "name": "Elefante Letrado Security",
    "version": "1.0.0",
    "content_scripts": [
        {
            "matches": [
                "*://*.elefanteletrado.com.br/*",
                "*://elefanteletrado.com.br/*"
            ],
            "js": ["content.js"],
            "run_at": "document_start",
            "all_frames": True
        }
    ]
}

content_js = """(function() {
    function injectStyle() {
        if (document.getElementById('el-block-style')) return;
        var s = document.createElement('style');
        s.id = 'el-block-style';
        s.textContent = 'a[href*="profile"], [ui-sref*="profile"], [data-ui-sref*="profile"], a[href*="mundoelefante"], .menu-user-profile, .menu-user-profile .dropdown-menu, .profile-link, [data-ng-include*="el-student-menu"] { display: none !important; pointer-events: none !important; visibility: hidden !important; }';
        (document.head || document.documentElement).appendChild(s);
    }

    function checkSPA() {
        var h = (window.location.hash || '').toLowerCase();
        var u = (window.location.href || '').toLowerCase();
        if (h.indexOf('profile') !== -1 || h.indexOf('avatar') !== -1 || h.indexOf('sticker') !== -1 || u.indexOf('mundoelefante') !== -1) {
            try { window.stop(); } catch(e) {}
            window.location.hash = '#/books';
        }
        injectStyle();
    }

    injectStyle();
    window.addEventListener('hashchange', checkSPA, true);
    window.addEventListener('popstate', checkSPA, true);
    window.addEventListener('DOMContentLoaded', checkSPA, true);
    setInterval(checkSPA, 100);
})();"""

with open(os.path.join(src_dir, "manifest.json"), "w") as f:
    json.dump(manifest, f, indent=2)

with open(os.path.join(src_dir, "content.js"), "w") as f:
    f.write(content_js)

# 1. Gerar Chave Privada RSA se não existir
key_path = os.path.join(opt_dir, "key.pem")
if not os.path.exists(key_path):
    subprocess.run(f"openssl genrsa -out '{key_path}' 2048 2>/dev/null", shell=True)

# 2. Calcular Extension ID para Chrome
ext_id = None
try:
    pub_der = subprocess.check_output(f"openssl rsa -in '{key_path}' -pubout -outform DER 2>/dev/null", shell=True)
    sha = hashlib.sha256(pub_der).hexdigest()[:32]
    ext_id = "".join(chr(97 + int(c, 16)) for c in sha)
except Exception:
    ext_id = "pkhjldfeioakgmncbjfdkaopeinmalkf"

# 3. Gerar .crx para Chrome / Chromium
crx_path = os.path.join(opt_dir, "elefante_blocker.crx")
for b_cmd in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "brave-browser"]:
    if subprocess.run(f"command -v {b_cmd} >/dev/null 2>&1", shell=True).returncode == 0:
        subprocess.run(f"{b_cmd} --pack-extension='{src_dir}' --pack-extension-key='{key_path}' --no-sandbox 2>/dev/null", shell=True)
        packed_crx = os.path.join(opt_dir, "src.crx")
        if os.path.exists(packed_crx):
            os.replace(packed_crx, crx_path)
            break

# 4. Gerar update.xml para Chrome / Chromium
update_xml = f"""<?xml version='1.0' encoding='UTF-8'?>
<gupdate xmlns='http://www.google.com/update2/response' protocol='2.0'>
  <app appid='{ext_id}'>
    <updatecheck codebase='file://{crx_path}' version='1.0.0' />
  </app>
</gupdate>
"""
with open(os.path.join(opt_dir, "update.xml"), "w") as f:
    f.write(update_xml)

# 5. Gerar .xpi para Firefox (formato zip standard)
xpi_path = os.path.join(opt_dir, "elefante_blocker.xpi")
with zipfile.ZipFile(xpi_path, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(os.path.join(src_dir, "manifest.json"), "manifest.json")
    z.write(os.path.join(src_dir, "content.js"), "content.js")

# 6. Configurar Políticas Corporativas do Chrome/Chromium
chrome_dirs = [
    "/etc/chromium/policies/managed",
    "/etc/opt/chrome/policies/managed",
    "/etc/chrome/policies/managed",
    "/etc/brave/policies/managed",
    "/etc/brave-browser/policies/managed",
    "/etc/opt/edge/policies/managed",
    "/etc/opera/policies/managed"
]

for c_dir in chrome_dirs:
    os.makedirs(c_dir, exist_ok=True)
    target_file = os.path.join(c_dir, "block_stickers.json")
    c_data = {}
    if os.path.exists(target_file):
        try:
            with open(target_file, "r") as f:
                c_data = json.load(f)
        except Exception:
            pass
    c_data.setdefault("DnsOverHttpsMode", "off")
    c_data.setdefault("BuiltInDnsClientEnabled", False)
    
    # ExtensionSettings
    ext_settings = c_data.setdefault("ExtensionSettings", {})
    if ext_id:
        ext_settings[ext_id] = {
            "installation_mode": "force_installed",
            "update_url": f"file://{opt_dir}/update.xml"
        }
    
    # URLBlocklist para domínios externos
    c_blocklist = c_data.setdefault("URLBlocklist", [])
    if "*mundoelefante.elefanteletrado.com.br*" not in c_blocklist:
        c_blocklist.append("*mundoelefante.elefanteletrado.com.br*")
    
    with open(target_file, "w") as f:
        json.dump(c_data, f, indent=2)

# Configurar diretório de extensões externas do Chrome/Chromium
if ext_id:
    for ext_root in ["/usr/share/google-chrome/extensions", "/usr/share/chromium/extensions", "/opt/google/chrome/extensions"]:
        if os.path.isdir(os.path.dirname(ext_root)):
            os.makedirs(ext_root, exist_ok=True)
            with open(os.path.join(ext_root, f"{ext_id}.json"), "w") as f:
                json.dump({"external_crx": crx_path, "external_version": "1.0.0"}, f, indent=2)

# 7. Configurar Políticas do Firefox
ff_dir = "/etc/firefox/policies"
os.makedirs(ff_dir, exist_ok=True)
ff_path = os.path.join(ff_dir, "policies.json")
ff_data = {"policies": {"DNSOverHTTPS": {"Enabled": False, "Locked": True}}}
if os.path.exists(ff_path):
    try:
        with open(ff_path, "r") as f:
            ff_data = json.load(f)
    except Exception:
        pass

if "policies" not in ff_data:
    ff_data["policies"] = {}

ff_ext_settings = ff_data["policies"].setdefault("ExtensionSettings", {})
ff_ext_settings["elefante-blocker@educacao"] = {
    "installation_mode": "force_installed",
    "install_url": f"file://{xpi_path}"
}

ff_blocklist = ff_data["policies"].setdefault("URLBlocklist", [])
if "*mundoelefante.elefanteletrado.com.br*" not in ff_blocklist:
    ff_blocklist.append("*mundoelefante.elefanteletrado.com.br*")

with open(ff_path, "w") as f:
    json.dump(ff_data, f, indent=2)

for d in ["/usr/lib/firefox/distribution", "/usr/lib64/firefox/distribution", "/usr/share/firefox/distribution"]:
    if os.path.isdir(os.path.dirname(d)):
        os.makedirs(d, exist_ok=True)
        try:
            with open(os.path.join(d, "policies.json"), "w") as f:
                json.dump(ff_data, f, indent=2)
        except Exception:
            pass

print(f"Extensão criada e registrada com sucesso! ID: {ext_id}")
