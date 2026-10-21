# -*- coding: utf-8 -*-
import sys, os, subprocess, socket, time

# Parâmetros recebidos:
# argv[1]: Nome ou Apelido da Máquina (ex: "MÁQUINA 05" ou "LAB01-PC05")
# argv[2]: Duração em segundos (padrão: 8s)
# argv[3]: Observação / Mensagem opcional

custom_name = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() else ""
try:
    duration_secs = int(sys.argv[2]) if len(sys.argv) > 2 else 8
except Exception:
    duration_secs = 8

extra_note = sys.argv[3].strip() if len(sys.argv) > 3 and sys.argv[3].strip() else "Localização solicitada pelo painel do professor"

try:
    local_hostname = socket.gethostname()
except Exception:
    local_hostname = "Computador"

if not custom_name:
    custom_name = local_hostname.upper()

# Determina IP Local
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.1)
    s.connect(("10.255.255.255", 1))
    local_ip = s.getsockname()[0]
    s.close()
except Exception:
    try:
        local_ip = socket.gethostbyname(local_hostname)
    except Exception:
        local_ip = "127.0.0.1"

# Identificação do Assento e Sessão no Multiseat
disp_env = os.environ.get('DISPLAY', ':0')
user_env = os.environ.get('USER', 'aluno')
disp_num_clean = disp_env.replace(':', '').split('.')[0]
try:
    seat_num = int(disp_num_clean) + 1
except Exception:
    seat_num = 1

seat_display_tag = f"ASSENTO {seat_num}   •   USUÁRIO: {user_env}   •   DISPLAY: {disp_env}"
network_tag = f"IP: {local_ip}   •   HOST: {local_hostname.upper()}"

# Reproduz som de sino / aviso para localização acústica
try:
    subprocess.Popen(["paplay", "/usr/share/sounds/freedesktop/stereo/bell.oga"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except Exception:
    pass

# Tenta falar de forma breve o nome/número da máquina via espeak / spd-say em background se disponível
try:
    spoken_phrase = f"Máquina {custom_name}"
    subprocess.Popen(["spd-say", "-l", "pt-br", "-r", "0", spoken_phrase], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except Exception:
    try:
        subprocess.Popen(["espeak", "-v", "pt-br", "-s", "150", spoken_phrase], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════
# Método 1: PyGObject GTK3 com Borda Pulsante e Tipografia Gigante
# ══════════════════════════════════════════════════════════════════
try:
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    from gi.repository import Gtk, Gdk, GLib, Pango

    class IdentifyWindow(Gtk.Window):
        def __init__(self, name_text, seat_text, net_text, note_text, seconds):
            super().__init__(title="🎯 IDENTIFICAÇÃO DO COMPUTADOR")
            self.set_position(Gtk.WindowPosition.CENTER)
            
            try:
                screen = Gdk.Screen.get_default()
                sw = screen.get_width() if screen else 1024
                sh = screen.get_height() if screen else 768
            except Exception:
                sw, sh = 1024, 768

            win_w = min(1180, max(500, sw - 40))
            win_h = min(680, max(420, sh - 40))
            self.set_default_size(win_w, win_h)
            self.set_keep_above(True)
            self.set_decorated(False)
            self.set_accept_focus(False)
            self.set_can_focus(False)
            
            self.seconds_left = max(3, seconds)
            self.pulse_state = False

            # Ajusta dinamicamente a fonte para ser gigante (ex: 110px a 130px) e legível de muito longe
            name_len = len(name_text.strip())
            if name_len <= 6:
                self.giant_font_size = 130
            elif name_len <= 9:
                self.giant_font_size = 110
            elif name_len <= 14:
                self.giant_font_size = 85
            else:
                self.giant_font_size = 65

            # Fecha imediatamente com clique ou tecla
            self.connect("button-press-event", lambda w, e: Gtk.main_quit())
            self.connect("key-press-event", lambda w, e: Gtk.main_quit())

            self.provider = Gtk.CssProvider()
            self.update_css()
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

            main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            self.add(main_vbox)

            # Header com ícone de radar / alvo
            header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            header_box.get_style_context().add_class("header-box")
            header_box.set_halign(Gtk.Align.CENTER)
            
            h_icon = Gtk.Label(label="🎯")
            h_icon.get_style_context().add_class("header-icon")
            h_title = Gtk.Label(label="LOCALIZAÇÃO DA MÁQUINA")
            h_title.get_style_context().add_class("header-title")
            header_box.pack_start(h_icon, False, False, 0)
            header_box.pack_start(h_title, False, False, 0)
            main_vbox.pack_start(header_box, False, False, 0)

            # Subtítulo de aviso do professor
            note_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            note_box.get_style_context().add_class("note-box")
            note_lbl = Gtk.Label(label=f"📢 {note_text}")
            note_lbl.get_style_context().add_class("note-text")
            note_box.pack_start(note_lbl, True, True, 0)
            main_vbox.pack_start(note_box, False, False, 0)

            # Card Principal Gigante com o Nome / Número da Máquina
            giant_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            giant_card.get_style_context().add_class("giant-card")

            lbl_hint = Gtk.Label(label="ESTE COMPUTADOR É:")
            lbl_hint.get_style_context().add_class("hint-label")
            giant_card.pack_start(lbl_hint, False, False, 0)

            self.lbl_name = Gtk.Label(label=name_text)
            self.lbl_name.set_line_wrap(True)
            self.lbl_name.set_justify(Gtk.Justification.CENTER)
            self.lbl_name.get_style_context().add_class("name-giant")
            giant_card.pack_start(self.lbl_name, True, True, 0)

            main_vbox.pack_start(giant_card, True, True, 12)

            # Barra de Detalhes Técnicos (Assento Multiseat + IP + Host)
            details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            details_box.get_style_context().add_class("details-box")

            seat_lbl = Gtk.Label(label=f"🏷️  {seat_text}")
            seat_lbl.get_style_context().add_class("details-line-1")
            details_box.pack_start(seat_lbl, False, False, 0)

            net_lbl = Gtk.Label(label=f"🌐  {net_text}")
            net_lbl.get_style_context().add_class("details-line-2")
            details_box.pack_start(net_lbl, False, False, 0)

            main_vbox.pack_start(details_box, False, False, 0)

            # Rodapé com contador regressivo e botão fechar
            footer_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
            footer_box.get_style_context().add_class("footer-box")
            footer_box.set_halign(Gtk.Align.CENTER)

            self.countdown_lbl = Gtk.Label(label=f"⏳ Fechando em {self.seconds_left}s...")
            self.countdown_lbl.get_style_context().add_class("countdown-label")
            footer_box.pack_start(self.countdown_lbl, False, False, 0)

            btn_close = Gtk.Button(label="FECHAR (Clique Aqui)")
            btn_close.get_style_context().add_class("close-btn")
            btn_close.connect("clicked", lambda w: Gtk.main_quit())
            footer_box.pack_start(btn_close, False, False, 0)

            main_vbox.pack_start(footer_box, False, False, 10)

            # Timers: Pulso visual a cada 500ms e contagem regressiva a cada 1s
            GLib.timeout_add(500, self.tick_pulse)
            GLib.timeout_add_seconds(1, self.tick_countdown)

        def update_css(self):
            # Alterna borda entre amarelo beacon vibrante e ciano neon para máximo destaque à distância
            if self.pulse_state:
                border_color = "#f59e0b"
                glow_color = "rgba(245, 158, 11, 0.75)"
                title_color = "#fbbf24"
            else:
                border_color = "#06b6d4"
                glow_color = "rgba(6, 182, 212, 0.75)"
                title_color = "#38bdf8"

            css_str = f"""
                window {{
                    background-color: #020617;
                    border: 6px solid {border_color};
                    border-radius: 28px;
                    box-shadow: 0 0 45px {glow_color};
                }}
                .header-box {{
                    padding: 14px 24px 6px 24px;
                }}
                .header-icon {{
                    font-size: 32px;
                }}
                .header-title {{
                    color: {title_color};
                    font-size: 24px;
                    font-weight: 900;
                    letter-spacing: 2px;
                }}
                .note-box {{
                    background-color: rgba(15, 23, 42, 0.85);
                    padding: 4px 16px;
                }}
                .note-text {{
                    color: #94a3b8;
                    font-size: 13px;
                    font-weight: 700;
                }}
                .giant-card {{
                    background: linear-gradient(145deg, #0f172a, #1e293b);
                    border: 3.5px solid {border_color};
                    border-radius: 24px;
                    padding: 24px 30px;
                    margin: 8px 30px;
                }}
                .hint-label {{
                    color: #94a3b8;
                    font-size: 16px;
                    font-weight: 800;
                    letter-spacing: 3px;
                }}
                .name-giant {{
                    color: #fde047;
                    font-size: {self.giant_font_size}px;   /* <-- Texto gigante de alto impacto (110px a 130px) */
                    font-weight: 900;
                    letter-spacing: 2px;
                    text-shadow: 0 0 35px rgba(253, 224, 71, 0.45);
                }}
                .details-box {{
                    background-color: rgba(15, 23, 42, 0.95);
                    border-top: 2px solid rgba(255, 255, 255, 0.1);
                    border-bottom: 2px solid rgba(255, 255, 255, 0.1);
                    padding: 10px 20px;
                }}
                .details-line-1 {{
                    color: #38bdf8;
                    font-size: 17px;
                    font-weight: 900;
                    letter-spacing: 0.5px;
                }}
                .details-line-2 {{
                    color: #a7f3d0;
                    font-size: 14px;
                    font-weight: 800;
                }}
                .footer-box {{
                    padding-bottom: 12px;
                }}
                .countdown-label {{
                    color: #fde047;
                    font-size: 15px;
                    font-weight: 800;
                }}
                .close-btn {{
                    background: #2563eb;
                    color: #ffffff;
                    font-size: 14px;
                    font-weight: 900;
                    border-radius: 12px;
                    padding: 6px 24px;
                    border: none;
                }}
                .close-btn:hover {{
                    background: #3b82f6;
                }}
            """
            self.provider.load_from_data(css_str.encode('utf-8'))

        def tick_pulse(self):
            self.pulse_state = not self.pulse_state
            self.update_css()
            return True

        def tick_countdown(self):
            self.seconds_left -= 1
            if self.seconds_left <= 0:
                Gtk.main_quit()
                return False
            if hasattr(self, 'countdown_lbl') and self.countdown_lbl:
                self.countdown_lbl.set_text(f"⏳ Fechando em {self.seconds_left}s...")
            return True

    win = IdentifyWindow(custom_name, seat_display_tag, network_tag, extra_note, duration_secs)
    win.show_all()
    Gtk.main()
    sys.exit(0)
except Exception as e:
    pass

# ══════════════════════════════════════════════════════════════════
# Método 2: Fallback Tkinter Nativo de Alto Contraste
# ══════════════════════════════════════════════════════════════════
try:
    import tkinter as tk
    root = tk.Tk()
    root.title("IDENTIFICAÇÃO DO COMPUTADOR")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg="#020617")

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    w, h = min(1120, sw - 40), min(640, sh - 40)
    x, y = (sw - w) // 2, (sh - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    canvas = tk.Canvas(root, width=w, height=h, bg="#020617", highlightthickness=6, highlightbackground="#f59e0b")
    canvas.pack(fill="both", expand=True)

    canvas.create_text(w // 2, 40, text="🎯  LOCALIZAÇÃO DA MÁQUINA  🎯", font=("DejaVu Sans", 22, "bold"), fill="#fbbf24")
    canvas.create_text(w // 2, 75, text=f"📢 {extra_note}", font=("DejaVu Sans", 12, "bold"), fill="#94a3b8")

    # Card gigante
    card_x1, card_y1, card_x2, card_y2 = 40, 105, w - 40, h - 140
    canvas.create_rectangle(card_x1, card_y1, card_x2, card_y2, fill="#0f172a", outline="#f59e0b", width=4)
    canvas.create_text(w // 2, card_y1 + 30, text="ESTE COMPUTADOR É:", font=("DejaVu Sans", 15, "bold"), fill="#94a3b8")
    
    name_len = len(custom_name.strip())
    tk_font = 80 if name_len <= 7 else (65 if name_len <= 11 else 48)
    canvas.create_text(w // 2, (card_y1 + card_y2) // 2 + 10, text=custom_name, font=("DejaVu Sans", tk_font, "bold"), fill="#fde047")

    # Detalhes
    canvas.create_text(w // 2, h - 110, text=f"🏷️ {seat_display_tag}", font=("DejaVu Sans", 13, "bold"), fill="#38bdf8")
    canvas.create_text(w // 2, h - 85, text=f"🌐 {network_tag}", font=("DejaVu Sans", 11, "bold"), fill="#a7f3d0")

    btn = tk.Button(root, text="FECHAR  ✓", font=("DejaVu Sans", 12, "bold"), bg="#2563eb", fg="#ffffff", padx=25, pady=5, command=root.destroy, relief="flat")
    canvas.create_window(w // 2, h - 45, window=btn)

    root.bind("<Button-1>", lambda e: root.destroy())
    root.bind("<Key>", lambda e: root.destroy())

    root.after(duration_secs * 1000, root.destroy)
    root.mainloop()
    sys.exit(0)
except Exception:
    pass

# ══════════════════════════════════════════════════════════════════
# Método 3: Fallback Zenity
# ══════════════════════════════════════════════════════════════════
try:
    pango_text = (
        f"<span font='28' weight='bold' foreground='#fbbf24'>🎯 LOCALIZAÇÃO DA MÁQUINA</span>\n\n"
        f"<span font='48' weight='heavy' foreground='#fde047'>{custom_name}</span>\n\n"
        f"<span font='16' weight='bold' foreground='#38bdf8'>{seat_display_tag}</span>\n"
        f"<span font='13' foreground='#a7f3d0'>{network_tag}</span>"
    )
    subprocess.run(["zenity", "--info", f"--title=🎯 {custom_name}", f"--text={pango_text}", f"--width=720", f"--height=380", f"--timeout={duration_secs}", "--ok-label=ENTENDIDO  ✓"], check=False)
    sys.exit(0)
except Exception:
    pass
