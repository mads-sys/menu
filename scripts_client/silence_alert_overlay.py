# -*- coding: utf-8 -*-
import sys, os, subprocess, socket, time

strike_count = 1
custom_text = sys.argv[1] if len(sys.argv) > 1 else "O professor solicitou silêncio imediato e atenção de todos na sala de aula."

try:
    local_hostname = socket.gethostname()
except Exception:
    local_hostname = "Computador"

# Identificação do Assento e Sessão no Multiseat
disp_env = os.environ.get('DISPLAY', ':0')
user_env = os.environ.get('USER', 'aluno')
disp_num_clean = disp_env.replace(':', '').split('.')[0]
try:
    seat_num = int(disp_num_clean) + 1
except Exception:
    seat_num = 1

seat_info_text = f"🖥️ {local_hostname.upper()}   •   🏷️ ASSENTO {seat_num} ({user_env} | {disp_env})"

# Toca som de alerta suave
try:
    subprocess.Popen(["paplay", "/usr/share/sounds/freedesktop/stereo/bell.oga"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except Exception:
    pass

# Método 1: PyGObject GTK3 com Borda e Brilho Piscante Alternado + Grandes Desenhos Visuais
try:
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    from gi.repository import Gtk, Gdk, GLib, Pango

    class SilenceWindow(Gtk.Window):
        def __init__(self, message):
            super().__init__(title="🤫 MOMENTO DE SILÊNCIO!")
            self.set_position(Gtk.WindowPosition.CENTER)
            try:
                screen = Gdk.Screen.get_default()
                sw = screen.get_width() if screen else 1024
                sh = screen.get_height() if screen else 768
            except Exception:
                sw, sh = 1024, 768
            win_w = min(880, max(360, sw - 30))
            win_h = min(540, max(280, sh - 30))
            self.set_default_size(win_w, win_h)
            self.set_keep_above(True)
            self.set_decorated(False)
            self.set_accept_focus(False)
            self.set_can_focus(False)
            self.state_toggle = False
            self.seconds_left = 6

            # Fecha imediatamente ao clicar em qualquer lugar da janela ou do card
            self.connect("button-press-event", lambda w, e: Gtk.main_quit())

            self.provider = Gtk.CssProvider()
            self.update_css()
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            self.add(vbox)

            # Header com ícone grande
            header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=15)
            header_box.get_style_context().add_class("header-box")
            header_box.set_halign(Gtk.Align.CENTER)
            
            icon_lbl = Gtk.Label(label="🤫 🔇 ✨")
            icon_lbl.get_style_context().add_class("big-icon")
            title_lbl = Gtk.Label(label="SILÊNCIO, POR FAVOR!  •  HORA DE ATENÇÃO")
            title_lbl.get_style_context().add_class("header-title")
            header_box.pack_start(icon_lbl, False, False, 0)
            header_box.pack_start(title_lbl, False, False, 0)
            vbox.pack_start(header_box, False, False, 0)

            # Barra de Identificação do Assento Multiseat
            seat_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            seat_box.get_style_context().add_class("seat-bar")
            seat_lbl = Gtk.Label(label=seat_info_text)
            seat_lbl.get_style_context().add_class("seat-text")
            seat_box.pack_start(seat_lbl, True, True, 0)
            vbox.pack_start(seat_box, False, False, 0)

            # Grandes Desenhos e Objetos Visuais para Alunos Menores (Não Leitores)
            visual_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
            visual_row.get_style_context().add_class("visual-row")
            visual_row.set_halign(Gtk.Align.CENTER)

            cards_data = [
                ("🤫 🤐", "FAZER SILÊNCIO", "Boca fechadinha"),
                ("👂 👨‍🏫", "OUVIR O PROFESSOR", "Atenção na explicação"),
                ("✨ 🧘", "SALA TRANQUILA", "Foco nas atividades")
            ]

            for icon_text, title_text_c, sub_text_c in cards_data:
                vcard = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                vcard.get_style_context().add_class("visual-card")
                
                v_icon = Gtk.Label(label=icon_text)
                v_icon.get_style_context().add_class("visual-icon")
                
                v_title = Gtk.Label(label=title_text_c)
                v_title.get_style_context().add_class("visual-title")
                
                v_sub = Gtk.Label(label=sub_text_c)
                v_sub.get_style_context().add_class("visual-sub")
                
                vcard.pack_start(v_icon, False, False, 0)
                vcard.pack_start(v_title, False, False, 0)
                vcard.pack_start(v_sub, False, False, 0)
                visual_row.pack_start(vcard, True, True, 0)

            vbox.pack_start(visual_row, False, False, 0)

            # Card de Mensagem
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            card.get_style_context().add_class("content-card")
            
            msg_lbl = Gtk.Label()
            msg_lbl.set_text(message)
            msg_lbl.set_line_wrap(True)
            msg_lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            msg_lbl.set_justify(Gtk.Justification.CENTER)
            msg_lbl.get_style_context().add_class("msg-label")
            card.pack_start(msg_lbl, True, True, 0)

            # Box de alerta educativo
            warn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            warn_box.get_style_context().add_class("warn-box")
            warn_lbl = Gtk.Label(label="💡 Mantenham o silêncio para que toda a turma consiga aprender melhor!")
            warn_lbl.get_style_context().add_class("warn-text")
            warn_lbl.set_line_wrap(True)
            warn_lbl.set_justify(Gtk.Justification.CENTER)
            warn_box.pack_start(warn_lbl, True, True, 0)
            card.pack_start(warn_box, False, False, 0)

            self.countdown_lbl = Gtk.Label(label="⏳ Fechando aviso em " + str(self.seconds_left) + "s...")
            self.countdown_lbl.get_style_context().add_class("countdown-label")
            card.pack_start(self.countdown_lbl, False, False, 0)

            vbox.pack_start(card, True, True, 0)

            # Botão
            btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            btn_box.set_margin_bottom(20)
            btn = Gtk.Button(label="OK, ENTENDIDO  ✓")
            btn.get_style_context().add_class("confirm-btn")
            btn.connect("clicked", lambda w: Gtk.main_quit())
            btn_box.pack_start(btn, True, False, 0)
            vbox.pack_start(btn_box, False, False, 0)

            # Temporizador de pulso visual piscante (a cada 350ms)
            GLib.timeout_add(350, self.toggle_pulse)
            # Temporizador de contagem regressiva (a cada 1s)
            GLib.timeout_add_seconds(1, self.tick_countdown)

        def update_css(self):
            if self.state_toggle:
                css_str = (
                    "window { background-color: #0f172a; border: 5px solid #f59e0b; border-radius: 22px; } "
                    ".header-box { background: linear-gradient(135deg, #78350f, #b45309); padding: 14px 28px; border-bottom: 3px solid #f59e0b; } "
                    ".seat-bar { background-color: rgba(15, 23, 42, 0.95); border-bottom: 2px solid #f59e0b; padding: 6px 16px; } "
                    ".seat-text { color: #fde047; font-size: 13px; font-weight: 800; letter-spacing: 0.5px; } "
                    ".big-icon { font-size: 36px; } "
                    ".header-title { color: #fef08a; font-size: 24px; font-weight: 900; letter-spacing: 1px; } "
                    ".visual-row { margin: 12px 24px 2px 24px; } "
                    ".visual-card { background-color: rgba(30, 41, 59, 0.85); border: 2px solid #f59e0b; border-radius: 14px; padding: 10px 16px; min-width: 200px; } "
                    ".visual-icon { font-size: 44px; } "
                    ".visual-title { color: #fef08a; font-size: 15px; font-weight: 900; margin-top: 2px; } "
                    ".visual-sub { color: #cbd5e1; font-size: 12px; font-weight: 700; } "
                    ".content-card { background-color: #1e293b; border: 2px solid #f59e0b; border-radius: 16px; padding: 16px 32px; margin: 10px 28px; } "
                    ".msg-label { color: #ffffff; font-size: 20px; font-weight: 800; } "
                    ".warn-box { background-color: rgba(245, 158, 11, 0.2); border: 2px solid #f59e0b; border-radius: 10px; padding: 8px 16px; margin: 4px 0; } "
                    ".warn-text { color: #fbbf24; font-size: 14px; font-weight: 800; } "
                    ".countdown-label { color: #fbbf24; font-size: 14px; font-weight: 600; } "
                    ".confirm-btn { background: #f59e0b; color: #000000; font-size: 18px; font-weight: 900; border-radius: 12px; padding: 12px 50px; border: none; }"
                )
            else:
                css_str = (
                    "window { background-color: #090d16; border: 5px solid #fbbf24; border-radius: 22px; } "
                    ".header-box { background: linear-gradient(135deg, #92400e, #d97706); padding: 14px 28px; border-bottom: 3px solid #fbbf24; } "
                    ".seat-bar { background-color: rgba(30, 41, 59, 0.95); border-bottom: 2px solid #fbbf24; padding: 6px 16px; } "
                    ".seat-text { color: #ffffff; font-size: 13px; font-weight: 800; letter-spacing: 0.5px; } "
                    ".big-icon { font-size: 36px; } "
                    ".header-title { color: #ffffff; font-size: 24px; font-weight: 900; letter-spacing: 1px; } "
                    ".visual-row { margin: 12px 24px 2px 24px; } "
                    ".visual-card { background-color: rgba(40, 50, 70, 0.95); border: 2px solid #fbbf24; border-radius: 14px; padding: 10px 16px; min-width: 200px; } "
                    ".visual-icon { font-size: 44px; } "
                    ".visual-title { color: #ffffff; font-size: 15px; font-weight: 900; margin-top: 2px; } "
                    ".visual-sub { color: #fef08a; font-size: 12px; font-weight: 700; } "
                    ".content-card { background-color: #1e2433; border: 2px solid #fbbf24; border-radius: 16px; padding: 16px 32px; margin: 10px 28px; } "
                    ".msg-label { color: #ffffff; font-size: 20px; font-weight: 800; } "
                    ".warn-box { background-color: rgba(251, 191, 36, 0.25); border: 2px solid #fbbf24; border-radius: 10px; padding: 8px 16px; margin: 4px 0; } "
                    ".warn-text { color: #fef08a; font-size: 14px; font-weight: 800; } "
                    ".countdown-label { color: #fde047; font-size: 14px; font-weight: 600; } "
                    ".confirm-btn { background: #d97706; color: #ffffff; font-size: 18px; font-weight: 900; border-radius: 12px; padding: 12px 50px; border: none; }"
                )
            self.provider.load_from_data(css_str.encode('utf-8'))

        def toggle_pulse(self):
            self.state_toggle = not self.state_toggle
            self.update_css()
            return True

        def tick_countdown(self):
            self.seconds_left -= 1
            if self.seconds_left <= 0:
                Gtk.main_quit()
                return False
            self.countdown_lbl.set_text("⏳ Fechando aviso em " + str(self.seconds_left) + "s...")
            return True

    win = SilenceWindow(custom_text)
    win.show_all()
    Gtk.main()
    sys.exit(0)
except Exception:
    pass

# Método 2: Fallback Tkinter Nativo
try:
    import tkinter as tk
    root = tk.Tk()
    root.title("🤫 MOMENTO DE SILÊNCIO!")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg="#0f172a")

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    w, h = min(860, sw - 40), min(520, sh - 40)
    x, y = (sw - w) // 2, (sh - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    canvas = tk.Canvas(root, width=w, height=h, bg="#0f172a", highlightthickness=4, highlightbackground="#f59e0b")
    canvas.pack(fill="both", expand=True)

    canvas.create_rectangle(0, 0, w, 55, fill="#78350f", outline="")
    canvas.create_text(w // 2, 28, text="🤫 🔇 ✨   SILÊNCIO, POR FAVOR!  •  HORA DE ATENÇÃO", font=("DejaVu Sans", 15, "bold"), fill="#fef08a")

    canvas.create_rectangle(0, 55, w, 85, fill="#1e293b", outline="")
    canvas.create_text(w // 2, 70, text=seat_info_text, font=("DejaVu Sans", 11, "bold"), fill="#fde047")

    canvas.create_text(w // 2 - 200, 130, text="🤫 🤐", font=("DejaVu Sans", 32))
    canvas.create_text(w // 2 - 200, 170, text="FAZER SILÊNCIO", font=("DejaVu Sans", 11, "bold"), fill="#fef08a")

    canvas.create_text(w // 2, 130, text="👂 👨‍🏫", font=("DejaVu Sans", 32))
    canvas.create_text(w // 2, 170, text="OUVIR O PROFESSOR", font=("DejaVu Sans", 11, "bold"), fill="#fef08a")

    canvas.create_text(w // 2 + 200, 130, text="✨ 🧘", font=("DejaVu Sans", 32))
    canvas.create_text(w // 2 + 200, 170, text="SALA TRANQUILA", font=("DejaVu Sans", 11, "bold"), fill="#fef08a")

    card_x1, card_y1, card_x2, card_y2 = 40, 205, w - 40, h - 85
    canvas.create_rectangle(card_x1, card_y1, card_x2, card_y2, fill="#1e293b", outline="#f59e0b", width=2)
    canvas.create_text(w // 2, (card_y1 + card_y2) // 2 - 12, text=custom_text, font=("DejaVu Sans", 16, "bold"), fill="#ffffff", width=w - 120)
    canvas.create_text(w // 2, card_y2 - 18, text="💡 Mantenham o silêncio para que toda a turma consiga aprender melhor!", font=("DejaVu Sans", 11, "bold"), fill="#fbbf24")

    btn = tk.Button(root, text="OK, ENTENDIDO  ✓", font=("DejaVu Sans", 13, "bold"), bg="#f59e0b", fg="#000000", padx=30, pady=6, command=root.destroy, relief="flat")
    canvas.create_window(w // 2, h - 42, window=btn)

    # Animação de pulso da borda
    colors = ["#f59e0b", "#fbbf24", "#d97706", "#fde047"]
    c_idx = [0]
    def pulse_border():
        c_idx[0] = (c_idx[0] + 1) % len(colors)
        canvas.config(highlightbackground=colors[c_idx[0]])
        root.after(400, pulse_border)
    pulse_border()

    root.after(6000, root.destroy)
    root.mainloop()
    sys.exit(0)
except Exception:
    pass

# Método 3: Fallback Zenity Estilizado com Pango Markup
try:
    pango_text = f"<span font='26' weight='bold' foreground='#fbbf24'>🤫 SILÊNCIO, POR FAVOR! ✨</span>\\n<span font='13' weight='bold' foreground='#fde047'>{seat_info_text}</span>\\n\\n<span font='48'>🤫  🤐  👂</span>\\n\\n<span font='20' weight='bold' foreground='#ffffff'>{custom_text}</span>\\n\\n<span font='13' foreground='#fbbf24'>💡 Mantenham o silêncio para aprender melhor!</span>"
    subprocess.run(["zenity", "--info", "--title=🤫 SILÊNCIO", "--text=" + pango_text, "--width=760", "--height=360", "--timeout=6", "--ok-label=OK, ENTENDIDO  ✓"], check=False)
    sys.exit(0)
except Exception:
    pass
