# -*- coding: utf-8 -*-
import sys, os, subprocess, socket

msg_text = sys.argv[1] if len(sys.argv) > 1 else "Atenção ao recado do professor!"

try:
    local_hostname = socket.gethostname()
except Exception:
    local_hostname = "Computador"

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

seat_display_tag = f"🏷️ ASSENTO {seat_num} ({user_env} | {disp_env})"
info_badge_text = f"🖥️  {local_hostname.upper()}   •   {seat_display_tag}   •   IP: {local_ip}"

# Método 1: PyGObject GTK3 - Overlay Glassmorphic Reutilizado do Grid VNC
try:
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    from gi.repository import Gtk, Gdk, GLib, Pango

    class NoticeWindow(Gtk.Window):
        def __init__(self, message):
            super().__init__(title="RECADO DO PROFESSOR")
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
            self.seconds_left = 6

            # Fecha imediatamente ao clicar em qualquer lugar da janela ou do card
            self.connect("button-press-event", lambda w, e: Gtk.main_quit())

            css = (
                b"window { background-color: #0b0f19; border: 4px solid #38bdf8; border-radius: 22px; } "
                b".header-box { background: linear-gradient(135deg, #1e1b4b, #312e81); border-bottom: 3.5px solid #818cf8; padding: 16px 24px; } "
                b".header-title { color: #fbbf24; font-size: 24px; font-weight: 900; letter-spacing: 0.5px; } "
                b".info-bar { background-color: rgba(15, 23, 42, 0.95); border-bottom: 2px solid #38bdf8; padding: 8px 18px; } "
                b".info-text { color: #38bdf8; font-size: 13px; font-weight: 700; letter-spacing: 0.5px; } "
                b".visual-row { margin: 10px 24px 2px 24px; } "
                b".visual-card { background-color: rgba(30, 41, 59, 0.9); border: 2px solid #6366f1; border-radius: 16px; padding: 10px 18px; } "
                b".visual-icon { font-size: 48px; } "
                b".visual-badge { color: #e0e7ff; font-size: 15px; font-weight: 900; margin-top: 4px; } "
                b".content-card { background-color: #1e293b; border: 2.5px solid #38bdf8; border-radius: 18px; padding: 18px 32px; margin: 8px 32px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); } "
                b".msg-label { color: #ffffff; font-size: 22px; font-weight: 800; } "
                b".status-tip { color: #34d399; font-size: 13px; font-weight: 700; margin-top: 4px; } "
                b".countdown-lbl { color: #38bdf8; font-size: 13px; font-weight: 600; } "
                b".confirm-btn { background: #2563eb; color: #ffffff; font-size: 18px; font-weight: 900; border-radius: 14px; padding: 12px 54px; border: none; box-shadow: 0 4px 14px rgba(37, 99, 235, 0.5); } "
                b".confirm-btn:hover { background: #3b82f6; }"
            )
            provider = Gtk.CssProvider()
            provider.load_from_data(css)
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

            main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            self.add(main_vbox)

            # Header Principal
            header_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            header_vbox.get_style_context().add_class("header-box")
            
            header_lbl = Gtk.Label(label="📢  RECADO IMPORTANTE DO PROFESSOR  ✨")
            header_lbl.get_style_context().add_class("header-title")
            header_vbox.pack_start(header_lbl, True, True, 0)
            main_vbox.pack_start(header_vbox, False, False, 0)

            # Barra de Informações de Rede e Identificação do Assento Multiseat
            info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            info_box.get_style_context().add_class("info-bar")
            info_lbl = Gtk.Label(label=info_badge_text)
            info_lbl.get_style_context().add_class("info-text")
            info_box.pack_start(info_lbl, True, True, 0)
            main_vbox.pack_start(info_box, False, False, 0)

            # Cartões Visuais Grandes para Alunos Menores (Educação Infantil / Não Leitores)
            visual_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
            visual_row.get_style_context().add_class("visual-row")
            visual_row.set_halign(Gtk.Align.CENTER)

            vcard1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            vcard1.get_style_context().add_class("visual-card")
            vcard1_icon = Gtk.Label(label="📢 👨‍🏫")
            vcard1_icon.get_style_context().add_class("visual-icon")
            vcard1_lbl = Gtk.Label(label="ATENÇÃO AO RECADO")
            vcard1_lbl.get_style_context().add_class("visual-badge")
            vcard1.pack_start(vcard1_icon, False, False, 0)
            vcard1.pack_start(vcard1_lbl, False, False, 0)
            visual_row.pack_start(vcard1, True, True, 0)

            vcard2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            vcard2.get_style_context().add_class("visual-card")
            vcard2_icon = Gtk.Label(label="👀 👂")
            vcard2_icon.get_style_context().add_class("visual-icon")
            vcard2_lbl = Gtk.Label(label="OLHAR E OUVIR")
            vcard2_lbl.get_style_context().add_class("visual-badge")
            vcard2.pack_start(vcard2_icon, False, False, 0)
            vcard2.pack_start(vcard2_lbl, False, False, 0)
            visual_row.pack_start(vcard2, True, True, 0)

            main_vbox.pack_start(visual_row, False, False, 0)

            # Card de Mensagem Central
            card_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card_box.get_style_context().add_class("content-card")
            msg_lbl = Gtk.Label()
            msg_lbl.set_text(message)
            msg_lbl.set_line_wrap(True)
            msg_lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            msg_lbl.set_justify(Gtk.Justification.CENTER)
            msg_lbl.get_style_context().add_class("msg-label")
            card_box.pack_start(msg_lbl, True, True, 0)

            status_tip_lbl = Gtk.Label(label="💡 Teclado e mouse liberados • Mantenham silêncio para evitar o bloqueio no 3º aviso")
            status_tip_lbl.get_style_context().add_class("status-tip")
            card_box.pack_start(status_tip_lbl, False, False, 0)

            self.countdown_lbl = Gtk.Label(label="⏳ Fechando aviso automaticamente em " + str(self.seconds_left) + "s...")
            self.countdown_lbl.get_style_context().add_class("countdown-lbl")
            card_box.pack_start(self.countdown_lbl, False, False, 0)

            main_vbox.pack_start(card_box, True, True, 0)

            # Rodapé com o botão "ENTENDIDO"
            footer_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            footer_box.set_margin_bottom(16)
            btn = Gtk.Button(label="ENTENDIDO  ✓")
            btn.get_style_context().add_class("confirm-btn")
            btn.connect("clicked", lambda w: Gtk.main_quit())
            footer_box.pack_start(btn, True, False, 0)
            main_vbox.pack_start(footer_box, False, False, 0)

            GLib.timeout_add_seconds(1, self.tick_countdown)

        def tick_countdown(self):
            self.seconds_left -= 1
            if self.seconds_left <= 0:
                Gtk.main_quit()
                return False
            if hasattr(self, 'countdown_lbl') and self.countdown_lbl:
                self.countdown_lbl.set_text("⏳ Fechando aviso automaticamente em " + str(self.seconds_left) + "s...")
            return True

    win = NoticeWindow(msg_text)
    win.show_all()
    Gtk.main()
    sys.exit(0)
except Exception:
    pass

# Método 2: Fallback Tkinter Nativo
try:
    import tkinter as tk
    root = tk.Tk()
    root.title("RECADO DO PROFESSOR")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg="#0b0f19")

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    w, h = min(860, sw - 40), min(520, sh - 40)
    x, y = (sw - w) // 2, (sh - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    canvas = tk.Canvas(root, width=w, height=h, bg="#0b0f19", highlightthickness=3, highlightbackground="#38bdf8")
    canvas.pack(fill="both", expand=True)

    canvas.create_rectangle(0, 0, w, 60, fill="#1e1b4b", outline="")
    canvas.create_text(w // 2, 30, text="📢  RECADO IMPORTANTE DO PROFESSOR  ✨", font=("DejaVu Sans", 16, "bold"), fill="#fbbf24")

    canvas.create_text(w // 2, 80, text=info_badge_text, font=("DejaVu Sans", 11, "bold"), fill="#38bdf8")

    canvas.create_text(w // 2 - 160, 130, text="📢 👨‍🏫", font=("DejaVu Sans", 32))
    canvas.create_text(w // 2 - 160, 175, text="ATENÇÃO AO RECADO", font=("DejaVu Sans", 11, "bold"), fill="#e0e7ff")

    canvas.create_text(w // 2 + 160, 130, text="👀 👂", font=("DejaVu Sans", 32))
    canvas.create_text(w // 2 + 160, 175, text="OLHAR E OUVIR", font=("DejaVu Sans", 11, "bold"), fill="#e0e7ff")

    card_x1, card_y1, card_x2, card_y2 = 40, 210, w - 40, h - 100
    canvas.create_rectangle(card_x1, card_y1, card_x2, card_y2, fill="#1e293b", outline="#38bdf8", width=2)
    canvas.create_text(w // 2, (card_y1 + card_y2) // 2 - 10, text=msg_text, font=("DejaVu Sans", 16, "bold"), fill="#ffffff", width=w - 120)
    canvas.create_text(w // 2, card_y2 - 20, text="💡 Teclado e mouse liberados • Mantenham silêncio", font=("DejaVu Sans", 11, "bold"), fill="#34d399")

    btn = tk.Button(root, text="ENTENDIDO  ✓", font=("DejaVu Sans", 13, "bold"), bg="#2563eb", fg="#ffffff", padx=30, pady=6, command=root.destroy, relief="flat")
    canvas.create_window(w // 2, h - 50, window=btn)

    root.after(6000, root.destroy)
    root.mainloop()
    sys.exit(0)
except Exception:
    pass

# Método 3: Fallback Zenity Estilizado com Pango Markup
try:
    pango_text = f"<span font='28' weight='bold' foreground='#fbbf24'>📢  RECADO DO PROFESSOR  ✨</span>\n\n<span font='48'>👀  👨‍🏫  👂</span>\n\n<span font='20' weight='bold' foreground='#38bdf8'>{msg_text}</span>\n\n<span font='13' foreground='#34d399'>💡 Teclado e mouse liberados • Mantenham silêncio</span>"
    subprocess.run(["zenity", "--info", "--title=📢 RECADO DO PROFESSOR", "--text=" + pango_text, "--width=760", "--height=360", "--timeout=6", "--ok-label=ENTENDIDO  ✓"], check=False)
    sys.exit(0)
except Exception:
    pass
