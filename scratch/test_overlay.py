# -*- coding: utf-8 -*-
import sys, os, subprocess, socket

msg_text = sys.argv[1] if len(sys.argv) > 1 else "Atenção ao Professor!"
try:
    unlock_seconds = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 0
except Exception:
    unlock_seconds = 0

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

info_badge_text = f"🖥️  COMPUTADOR: {local_hostname}   •   IP: {local_ip}   •   🟢 CONECTADO AO PAINEL DO PROFESSOR"

# Método 1: PyGObject / GTK3
try:
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    from gi.repository import Gtk, Gdk, Pango, GLib

    class FullscreenLockWindow(Gtk.Window):
        def __init__(self, message, unlock_sec=0):
            super().__init__(title="PAUSA PEDAGÓGICA")
            self.fullscreen()
            self.set_keep_above(True)
            self.set_decorated(False)
            self.remaining_sec = unlock_sec

            css = b"window { background-color: #090d16; } .header-bar { background-color: #312e81; border-bottom: 3.5px solid #818cf8; padding: 16px; } .header-title { color: #fde047; font-size: 24px; font-weight: 900; letter-spacing: 0.5px; } .info-bar { background-color: #0f172a; border-bottom: 2.5px solid #38bdf8; padding: 14px 24px; } .info-text { color: #38bdf8; font-size: 20px; font-weight: 800; letter-spacing: 0.5px; } .lock-card { background-color: #1e293b; border: 2.5px solid #38bdf8; border-radius: 20px; padding: 35px 60px; margin: 15px 80px; box-shadow: 0 15px 35px rgba(0,0,0,0.5); } .main-title { color: #ffffff; font-size: 32px; font-weight: bold; margin-top: 10px; } .msg-text { color: #ffffff; font-size: 26px; font-weight: bold; margin: 15px 0; } .sub-text { color: #cbd5e1; font-size: 18px; } .timer-card { background-color: rgba(16, 185, 129, 0.18); border: 2.5px solid #10b981; border-radius: 16px; padding: 12px 28px; margin: 10px 80px; } .timer-text { color: #34d399; font-size: 24px; font-weight: 900; letter-spacing: 0.8px; } .bottom-bar { background-color: #312e81; border-top: 3.5px solid #818cf8; padding: 18px 24px; } .bottom-text { color: #ffffff; font-size: 20px; font-weight: 900; }"
            provider = Gtk.CssProvider()
            provider.load_from_data(css)
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

            main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            self.add(main_vbox)

            header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            header_box.get_style_context().add_class("header-bar")
            header_lbl = Gtk.Label(label="🎓  PAUSA PEDAGÓGICA  •  HORA DE ATENÇÃO  ✨")
            header_lbl.get_style_context().add_class("header-title")
            header_box.pack_start(header_lbl, True, True, 0)
            main_vbox.pack_start(header_box, False, False, 0)

            info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            info_box.get_style_context().add_class("info-bar")
            info_lbl = Gtk.Label(label=info_badge_text)
            info_lbl.get_style_context().add_class("info-text")
            info_box.pack_start(info_lbl, True, True, 0)
            main_vbox.pack_start(info_box, False, False, 0)

            center_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            center_vbox.set_valign(Gtk.Align.CENTER)

            self.pulse_phase = 0.0
            self.darea = Gtk.DrawingArea()
            self.darea.set_size_request(240, 160)
            self.darea.connect("draw", self.on_draw_pulse)
            center_vbox.pack_start(self.darea, False, False, 0)
            GLib.timeout_add(30, self.on_pulse_tick)

            title_lbl = Gtk.Label(label="✨  Momento de Atenção ao Professor  🎓")
            title_lbl.get_style_context().add_class("main-title")
            center_vbox.pack_start(title_lbl, False, False, 0)

            card_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            card_box.get_style_context().add_class("lock-card")

            msg_lbl = Gtk.Label()
            msg_lbl.set_text(message)
            msg_lbl.set_line_wrap(True)
            msg_lbl.set_justify(Gtk.Justification.CENTER)
            msg_lbl.get_style_context().add_class("msg-text")
            card_box.pack_start(msg_lbl, True, True, 0)
            center_vbox.pack_start(card_box, False, False, 0)

            if self.remaining_sec > 0:
                timer_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
                timer_card.get_style_context().add_class("timer-card")
                mins, secs = divmod(self.remaining_sec, 60)
                self.timer_lbl = Gtk.Label(label=f"🔒  Tela temporariamente pausada. Desbloqueio automático em: {mins:02d}:{secs:02d}")
                self.timer_lbl.get_style_context().add_class("timer-text")
                timer_card.pack_start(self.timer_lbl, True, True, 0)
                center_vbox.pack_start(timer_card, False, False, 0)
                GLib.timeout_add(1000, self.update_countdown)

            sub_lbl = Gtk.Label(label="💡  Olhe para a frente e acompanhe a explicação do professor. A aula já vai continuar!")
            sub_lbl.get_style_context().add_class("sub-text")
            center_vbox.pack_start(sub_lbl, False, False, 0)

            main_vbox.pack_start(center_vbox, True, True, 0)

            bottom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            bottom_box.get_style_context().add_class("bottom-bar")
            bottom_lbl = Gtk.Label(label="⌨️  Teclado e mouse em pausa temporária   •   O professor liberará sua tela em breve")
            bottom_lbl.get_style_context().add_class("bottom-text")
            bottom_box.pack_start(bottom_lbl, True, True, 0)
            main_vbox.pack_start(bottom_box, False, False, 0)

            GLib.timeout_add(200, self.check_sentinel)

        def update_countdown(self):
            self.remaining_sec -= 1
            if self.remaining_sec <= 0:
                try:
                    subprocess.run("for id in $(xinput list --id-only 2>/dev/null); do xinput enable '$id' 2>/dev/null; done; udevadm trigger --subsystem-match=input --action=change 2>/dev/null || true", shell=True, check=False)
                except Exception:
                    pass
                Gtk.main_quit()
                sys.exit(0)
                return False
            mins, secs = divmod(self.remaining_sec, 60)
            if hasattr(self, 'timer_lbl') and self.timer_lbl:
                self.timer_lbl.set_text(f"🔒  Tela temporariamente pausada. Desbloqueio automático em: {mins:02d}:{secs:02d}")
            return True

        def on_pulse_tick(self):
            import math
            self.pulse_phase = (self.pulse_phase + 0.07) % (2 * math.pi)
            if hasattr(self, 'darea') and self.darea:
                self.darea.queue_draw()
            return True

        def on_draw_pulse(self, widget, cr):
            import math
            alloc = widget.get_allocation()
            cx, cy = alloc.width / 2.0, alloc.height / 2.0
            pulse_scale = 1.0 + 0.12 * math.sin(self.pulse_phase)
            ring_radius = 60 * pulse_scale

            cr.set_source_rgba(0.22, 0.74, 0.97, 0.35 + 0.25 * math.sin(self.pulse_phase))
            cr.arc(cx, cy, ring_radius + 12, 0, 2 * math.pi)
            cr.set_line_width(5)
            cr.stroke()

            cr.set_source_rgba(0.39, 0.40, 0.95, 0.85)
            cr.arc(cx, cy, 58, 0, 2 * math.pi)
            cr.set_line_width(3.5)
            cr.stroke()

            cr.set_source_rgba(0.09, 0.13, 0.22, 1.0)
            cr.arc(cx, cy, 56, 0, 2 * math.pi)
            cr.fill()

            cr.set_source_rgba(0.22, 0.74, 0.97, 1.0)
            cr.set_line_width(7.5)
            cr.arc(cx, cy - 8, 19, math.pi, 2 * math.pi)
            cr.stroke()

            cr.set_source_rgba(0.02, 0.52, 0.85, 1.0)
            cr.rectangle(cx - 24, cy - 8, 48, 38)
            cr.fill_preserve()
            cr.set_source_rgba(0.38, 0.85, 0.98, 1.0)
            cr.set_line_width(2.5)
            cr.stroke()

            cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
            cr.arc(cx, cy + 8, 5, 0, 2 * math.pi)
            cr.fill()
            cr.move_to(cx - 3, cy + 10)
            cr.line_to(cx + 3, cy + 10)
            cr.line_to(cx + 4, cy + 20)
            cr.line_to(cx - 4, cy + 20)
            cr.close_path()
            cr.fill()

        def check_sentinel(self):
            FLAG_FILE = "/tmp/lock_overlay_active"
            if not os.path.exists(FLAG_FILE):
                Gtk.main_quit()
                sys.exit(0)
                return False
            return True

    FLAG_FILE = "/tmp/lock_overlay_active"
    try:
        with open(FLAG_FILE, "w") as f:
            f.write("1")
    except Exception:
        pass

    win = FullscreenLockWindow(msg_text, unlock_seconds)
    win.show_all()
    Gtk.main()
    sys.exit(0)
except Exception:
    pass

# Método 2: Fallback Tkinter
try:
    import tkinter as tk
    root = tk.Tk()
    root.title("PAUSA PEDAGÓGICA")
    root.attributes("-fullscreen", True)
    root.configure(bg="#090d16")
    root.attributes("-topmost", True)
    root.overrideredirect(True)
    root.protocol("WM_DELETE_WINDOW", lambda: None)
    
    for key in ["<Alt-F4>", "<Escape>", "<Control-Alt-Delete>", "<Control-q>", "<Alt-Tab>", "<Control-Escape>"]:
        root.bind(key, lambda e: "break")
    
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    
    canvas = tk.Canvas(root, width=sw, height=sh, bg="#090d16", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    
    for y in range(0, sh, 4):
        r_val = int(9 + (y / sh) * 15)
        g_val = int(13 + (y / sh) * 20)
        b_val = int(22 + (y / sh) * 35)
        hex_color = f"#{r_val:02x}{g_val:02x}{b_val:02x}"
        canvas.create_line(0, y, sw, y, fill=hex_color, width=4)

    canvas.create_rectangle(0, 0, sw, 60, fill="#1e1b4b", outline="")
    canvas.create_rectangle(0, 58, sw, 60, fill="#6366f1", outline="")
    canvas.create_text(sw // 2, 30, text="🎓  PAUSA PEDAGÓGICA  •  HORA DE ATENÇÃO  ✨", font=("DejaVu Sans", 16, "bold"), fill="#fbbf24")
    
    canvas.create_rectangle(0, 60, sw, 105, fill="#0f172a", outline="")
    canvas.create_rectangle(0, 103, sw, 105, fill="#38bdf8", outline="")
    canvas.create_text(sw // 2, 82, text=info_badge_text, font=("DejaVu Sans", 16, "bold"), fill="#38bdf8")

    cx, cy = sw // 2, sh // 2 - 40
    
    FLAG_FILE = "/tmp/lock_overlay_active"
    with open(FLAG_FILE, "w") as f:
        f.write("1")

    def check_sentinel():
        if not os.path.exists(FLAG_FILE):
            root.destroy()
            sys.exit(0)
        root.after(200, check_sentinel)

    check_sentinel()
    
    canvas.create_text(cx, cy + 135, text="✨  Momento de Atenção ao Professor  🎓", font=("DejaVu Sans", 28, "bold"), fill="#ffffff")
    
    card_w = min(860, sw - 100)
    card_h = 120
    card_x1 = cx - card_w // 2
    card_y1 = cy + 180
    card_x2 = cx + card_w // 2
    card_y2 = card_y1 + card_h
    
    canvas.create_rectangle(card_x1, card_y1, card_x2, card_y2, fill="#1e293b", outline="#38bdf8", width=2)
    canvas.create_text(cx, card_y1 + 60, text=msg_text, font=("DejaVu Sans", 22, "bold"), fill="#ffffff", width=card_w - 50)
    
    if unlock_seconds > 0:
        rem_sec = [unlock_seconds]
        mins, secs = divmod(rem_sec[0], 60)
        timer_text_id = canvas.create_text(cx, cy + 290, text=f"🔒 Tela temporariamente pausada. Desbloqueio automático em: {mins:02d}:{secs:02d}", font=("DejaVu Sans", 18, "bold"), fill="#34d399")
        def update_tk_timer():
            rem_sec[0] -= 1
            if rem_sec[0] <= 0:
                try:
                    subprocess.run("for id in $(xinput list --id-only 2>/dev/null); do xinput enable '$id' 2>/dev/null; done; udevadm trigger --subsystem-match=input --action=change 2>/dev/null || true", shell=True, check=False)
                except Exception:
                    pass
                root.destroy()
                sys.exit(0)
            m, s = divmod(rem_sec[0], 60)
            canvas.itemconfig(timer_text_id, text=f"🔒 Tela temporariamente pausada. Desbloqueio automático em: {m:02d}:{s:02d}")
            root.after(1000, update_tk_timer)
        root.after(1000, update_tk_timer)

    canvas.create_text(cx, cy + 330, text="💡  Olhe para a frente e acompanhe a explicação do professor. A aula já vai continuar!", font=("DejaVu Sans", 16), fill="#cbd5e1")
    
    canvas.create_rectangle(0, sh - 75, sw, sh, fill="#1e1b4b", outline="")
    canvas.create_rectangle(0, sh - 75, sw, sh - 72, fill="#6366f1", outline="")
    canvas.create_text(sw // 2, sh - 37, text="⌨️  Teclado e mouse em pausa temporária   •   O professor liberará sua tela em breve", font=("DejaVu Sans", 16, "bold"), fill="#e0e7ff")
    
    root.mainloop()
    sys.exit(0)
except Exception:
    pass

# Fallbacks nativos (Zenity / Xmessage)
try:
    subprocess.run(["zenity", "--warning", "--title=🎓 PAUSA PEDAGÓGICA", "--text=\n\n✨ Momento de Atenção ao Professor 🎓\n\n" + msg_text + "\n\n", "--width=550"], check=False)
    sys.exit(0)
except Exception:
    pass

try:
    subprocess.run(["xmessage", "-center", "PAUSA PEDAGÓGICA\n\n" + msg_text], check=False)
    sys.exit(0)
except Exception:
    pass