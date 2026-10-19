# -*- coding: utf-8 -*-
import sys, os, subprocess, socket

stars = int(sys.argv[1]) if len(sys.argv) > 1 else 3
period_title = sys.argv[2] if len(sys.argv) > 2 else "Aula"
celeb_msg = sys.argv[3] if len(sys.argv) > 3 else "Parabéns a todos pelo excelente comportamento!"

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

# Toca sino festivo
try:
    subprocess.Popen(["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except Exception:
    pass

# Método 1: PyGObject GTK3
try:
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    from gi.repository import Gtk, Gdk, GLib

    class CelebrateWindow(Gtk.Window):
        def __init__(self):
            super().__init__(title="🎉 TURMA NOTA 10!")
            self.set_position(Gtk.WindowPosition.CENTER)
            self.set_default_size(880, 520)
            self.set_keep_above(True)
            self.set_decorated(False)
            self.seconds_left = 8

            self.connect("button-press-event", lambda w, e: Gtk.main_quit())

            provider = Gtk.CssProvider()
            css_str = (
                "window { background-color: #0f172a; border: 5px solid #fbbf24; border-radius: 24px; } "
                ".celeb-header { background: linear-gradient(135deg, #78350f, #d97706); padding: 16px 28px; border-bottom: 3.5px solid #fde047; } "
                ".celeb-title { color: #ffffff; font-size: 26px; font-weight: 900; letter-spacing: 1px; } "
                ".seat-bar { background-color: rgba(15, 23, 42, 0.95); border-bottom: 2px solid #fbbf24; padding: 6px 16px; } "
                ".seat-text { color: #fde047; font-size: 13px; font-weight: 800; letter-spacing: 0.5px; } "
                ".stars-lbl { font-size: 48px; margin: 12px 0 4px 0; } "
                ".celeb-card { background-color: #1e293b; border: 2px solid #fbbf24; border-radius: 18px; padding: 18px 32px; margin: 10px 32px; } "
                ".msg-lbl { color: #ffffff; font-size: 20px; font-weight: 800; } "
                ".sub-lbl { color: #fde047; font-size: 14px; font-weight: 700; margin-top: 6px; } "
                ".countdown-lbl { color: #fbbf24; font-size: 13px; font-weight: 600; } "
                ".celeb-btn { background: #fbbf24; color: #000000; font-size: 18px; font-weight: 900; border-radius: 12px; padding: 12px 50px; border: none; }"
            )
            provider.load_from_data(css_str.encode('utf-8'))
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            self.add(vbox)

            header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            header_box.get_style_context().add_class("celeb-header")
            header_lbl = Gtk.Label(label="🎉  PARABÉNS! TURMA NOTA 10!  ⭐")
            header_lbl.get_style_context().add_class("celeb-title")
            header_box.pack_start(header_lbl, True, True, 0)
            vbox.pack_start(header_box, False, False, 0)

            seat_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            seat_box.get_style_context().add_class("seat-bar")
            seat_lbl = Gtk.Label(label=seat_info_text)
            seat_lbl.get_style_context().add_class("seat-text")
            seat_box.pack_start(seat_lbl, True, True, 0)
            vbox.pack_start(seat_box, False, False, 0)

            stars_str = "⭐ " * stars
            stars_lbl = Gtk.Label(label=stars_str.strip())
            stars_lbl.get_style_context().add_class("stars-lbl")
            vbox.pack_start(stars_lbl, False, False, 0)

            card_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card_box.get_style_context().add_class("celeb-card")
            msg_lbl = Gtk.Label(label=celeb_msg)
            msg_lbl.set_line_wrap(True)
            msg_lbl.set_justify(Gtk.Justification.CENTER)
            msg_lbl.get_style_context().add_class("msg-lbl")
            card_box.pack_start(msg_lbl, True, True, 0)

            sub_lbl = Gtk.Label(label=f"🏆 Disciplina e Foco Exemplares • {period_title}")
            sub_lbl.get_style_context().add_class("sub-lbl")
            card_box.pack_start(sub_lbl, False, False, 0)

            self.countdown_lbl = Gtk.Label(label=f"⏳ Fechando em {self.seconds_left}s...")
            self.countdown_lbl.get_style_context().add_class("countdown-lbl")
            card_box.pack_start(self.countdown_lbl, False, False, 0)

            vbox.pack_start(card_box, True, True, 0)

            btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            btn_box.set_margin_bottom(18)
            btn = Gtk.Button(label="VALEU, PROFESSOR!  🎉")
            btn.get_style_context().add_class("celeb-btn")
            btn.connect("clicked", lambda w: Gtk.main_quit())
            btn_box.pack_start(btn, True, False, 0)
            vbox.pack_start(btn_box, False, False, 0)

            GLib.timeout_add_seconds(1, self.tick_countdown)

        def tick_countdown(self):
            self.seconds_left -= 1
            if self.seconds_left <= 0:
                Gtk.main_quit()
                return False
            self.countdown_lbl.set_text(f"⏳ Fechando em {self.seconds_left}s...")
            return True

    win = CelebrateWindow()
    win.show_all()
    Gtk.main()
    sys.exit(0)
except Exception:
    pass

# Método 2: Fallback Tkinter Nativo
try:
    import tkinter as tk
    root = tk.Tk()
    root.title("🎉 TURMA NOTA 10!")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg="#0f172a")

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    w, h = min(860, sw - 40), min(500, sh - 40)
    x, y = (sw - w) // 2, (sh - h) // 2
    root.geometry(str(w) + "x" + str(h) + "+" + str(x) + "+" + str(y))

    canvas = tk.Canvas(root, width=w, height=h, bg="#0f172a", highlightthickness=4, highlightbackground="#fbbf24")
    canvas.pack(fill="both", expand=True)

    canvas.create_rectangle(0, 0, w, 55, fill="#78350f", outline="")
    canvas.create_text(w // 2, 28, text="🎉  PARABÉNS! TURMA NOTA 10!  ⭐", font=("DejaVu Sans", 16, "bold"), fill="#fde047")

    canvas.create_rectangle(0, 55, w, 85, fill="#1e293b", outline="")
    canvas.create_text(w // 2, 70, text=seat_info_text, font=("DejaVu Sans", 11, "bold"), fill="#fde047")

    stars_str = "⭐ " * stars
    canvas.create_text(w // 2, 130, text=stars_str.strip(), font=("DejaVu Sans", 38))

    card_x1, card_y1, card_x2, card_y2 = 40, 175, w - 40, h - 80
    canvas.create_rectangle(card_x1, card_y1, card_x2, card_y2, fill="#1e293b", outline="#fbbf24", width=2)
    canvas.create_text(w // 2, (card_y1 + card_y2) // 2 - 12, text=celeb_msg, font=("DejaVu Sans", 16, "bold"), fill="#ffffff", width=w - 120)
    canvas.create_text(w // 2, card_y2 - 18, text="🏆 Disciplina e Foco Exemplares • " + str(period_title), font=("DejaVu Sans", 12, "bold"), fill="#fde047")

    btn = tk.Button(root, text="VALEU, PROFESSOR!  🎉", font=("DejaVu Sans", 13, "bold"), bg="#fbbf24", fg="#000000", padx=30, pady=6, command=root.destroy, relief="flat")
    canvas.create_window(w // 2, h - 40, window=btn)

    root.after(8000, root.destroy)
    root.mainloop()
    sys.exit(0)
except Exception:
    pass

# Método 3: Zenity Fallback
try:
    pango_text = "<span font='28' weight='bold' foreground='#fbbf24'>🎉 TURMA NOTA 10! ⭐</span>\n<span font='13' weight='bold' foreground='#fde047'>" + str(seat_info_text) + "</span>\n\n<span font='48'>⭐ ⭐ ⭐</span>\n\n<span font='20' weight='bold' foreground='#ffffff'>" + str(celeb_msg) + "</span>\n\n<span font='14' foreground='#fde047'>🏆 " + str(period_title) + "</span>"
    subprocess.run(["zenity", "--info", "--title=🎉 TURMA NOTA 10!", "--text=" + pango_text, "--width=760", "--height=360", "--timeout=8", "--ok-label=VALEU, PROFESSOR!  🎉"], check=False)
    sys.exit(0)
except Exception:
    pass
