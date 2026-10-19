# -*- coding: utf-8 -*-
import sys, os, subprocess, socket, json

cur_level = sys.argv[1] if len(sys.argv) > 1 else "green"
cur_db = float(sys.argv[2]) if len(sys.argv) > 2 else 55.0
thresh_db = int(sys.argv[3]) if len(sys.argv) > 3 else 75

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

seat_tag = "Assento " + str(seat_num)

# Atualiza arquivo de estado para atualização dinâmica de instâncias já abertas
state_data = {"level": cur_level, "db": cur_db, "threshold": thresh_db}
with open("/tmp/semaforo_state.json", "w") as f:
    json.dump(state_data, f)

# Método 1: PyGObject GTK3 Widget Flutuante Superior Direito
try:
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    from gi.repository import Gtk, Gdk, GLib

    class TrafficLightWindow(Gtk.Window):
        def __init__(self):
            super().__init__(type=Gtk.WindowType.TOPLEVEL)
            self.set_title("Semáforo Pedagógico de Ruído")
            self.set_default_size(240, 52)
            self.set_keep_above(True)
            self.set_decorated(False)
            self.set_accept_focus(False)
            self.set_can_focus(False)

            # Posiciona no canto superior direito da tela
            screen = Gdk.Screen.get_default()
            if screen:
                sw = screen.get_width()
                self.move(max(20, sw - 270), 20)

            self.provider = Gtk.CssProvider()
            self.update_widget_css(cur_level)
            Gtk.StyleContext.add_provider_for_screen(screen, self.provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

            main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            main_box.get_style_context().add_class("tf-container")
            self.add(main_box)

            # Ícone com cor do semáforo
            self.icon_lbl = Gtk.Label(label="🟢" if cur_level == "green" else ("🟡" if cur_level == "yellow" else "🔴"))
            self.icon_lbl.get_style_context().add_class("tf-icon")
            main_box.pack_start(self.icon_lbl, False, False, 0)

            # Informações de Texto e Assento
            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            self.status_lbl = Gtk.Label(label="SILÊNCIO" if cur_level == "green" else ("ATENÇÃO" if cur_level == "yellow" else "LIMITE DE RUÍDO"))
            self.status_lbl.get_style_context().add_class("tf-title")
            self.status_lbl.set_halign(Gtk.Align.START)

            self.sub_lbl = Gtk.Label(label=f"{cur_db:.1f} dB • {seat_tag}")
            self.sub_lbl.get_style_context().add_class("tf-sub")
            self.sub_lbl.set_halign(Gtk.Align.START)

            text_box.pack_start(self.status_lbl, False, False, 0)
            text_box.pack_start(self.sub_lbl, False, False, 0)
            main_box.pack_start(text_box, True, True, 0)

            # Checa alterações de estado a cada 500ms
            GLib.timeout_add(500, self.check_state_update)

        def update_widget_css(self, lvl):
            if lvl == "green":
                css_str = (
                    "window { background-color: rgba(6, 78, 59, 0.95); border: 2.5px solid #10b981; border-radius: 16px; } "
                    ".tf-container { padding: 8px 14px; } "
                    ".tf-icon { font-size: 24px; } "
                    ".tf-title { color: #34d399; font-size: 13px; font-weight: 900; letter-spacing: 0.5px; } "
                    ".tf-sub { color: #a7f3d0; font-size: 11px; font-weight: 700; }"
                )
            elif lvl == "yellow":
                css_str = (
                    "window { background-color: rgba(120, 53, 15, 0.95); border: 2.5px solid #f59e0b; border-radius: 16px; } "
                    ".tf-container { padding: 8px 14px; } "
                    ".tf-icon { font-size: 24px; } "
                    ".tf-title { color: #fde047; font-size: 13px; font-weight: 900; letter-spacing: 0.5px; } "
                    ".tf-sub { color: #fef08a; font-size: 11px; font-weight: 700; }"
                )
            else:
                css_str = (
                    "window { background-color: rgba(127, 29, 29, 0.95); border: 2.5px solid #ef4444; border-radius: 16px; } "
                    ".tf-container { padding: 8px 14px; } "
                    ".tf-icon { font-size: 24px; } "
                    ".tf-title { color: #fca5a5; font-size: 13px; font-weight: 900; letter-spacing: 0.5px; } "
                    ".tf-sub { color: #fee2e2; font-size: 11px; font-weight: 700; }"
                )
            self.provider.load_from_data(css_str.encode('utf-8'))

        def check_state_update(self):
            try:
                if os.path.exists("/tmp/semaforo_state.json"):
                    with open("/tmp/semaforo_state.json", "r") as f:
                        data = json.load(f)
                    lvl = data.get("level", "green")
                    db_v = float(data.get("db", 55.0))
                    self.update_widget_css(lvl)
                    self.icon_lbl.set_text("🟢" if lvl == "green" else ("🟡" if lvl == "yellow" else "🔴"))
                    self.status_lbl.set_text("SILÊNCIO" if lvl == "green" else ("ATENÇÃO" if lvl == "yellow" else "LIMITE DE RUÍDO"))
                    self.sub_lbl.set_text(f"{db_v:.1f} dB • {seat_tag}")
            except Exception:
                pass
            return True

    win = TrafficLightWindow()
    win.show_all()
    Gtk.main()
    sys.exit(0)
except Exception:
    pass

# Método 2: Fallback Tkinter Nativo
try:
    import tkinter as tk
    root = tk.Tk()
    root.title("Semáforo de Ruído")
    root.overrideredirect(True)
    root.attributes("-topmost", True)

    sw = root.winfo_screenwidth()
    root.geometry("250x54+" + str(sw - 270) + "+20")

    bg_c = "#064e3b" if cur_level == "green" else ("#78350f" if cur_level == "yellow" else "#7f1d1d")
    fg_c = "#34d399" if cur_level == "green" else ("#fde047" if cur_level == "yellow" else "#fca5a5")
    root.configure(bg=bg_c)

    lbl1 = tk.Label(root, text="🟢" if cur_level == "green" else ("🟡" if cur_level == "yellow" else "🔴"), font=("DejaVu Sans", 18), bg=bg_c)
    lbl1.pack(side="left", padx=10)

    txt_frame = tk.Frame(root, bg=bg_c)
    txt_frame.pack(side="left", fill="both", expand=True)

    title_l = tk.Label(txt_frame, text="SILÊNCIO" if cur_level == "green" else ("ATENÇÃO" if cur_level == "yellow" else "LIMITE"), font=("DejaVu Sans", 10, "bold"), fg=fg_c, bg=bg_c, anchor="w")
    title_l.pack(fill="x")

    sub_l = tk.Label(txt_frame, text=str(round(cur_db, 1)) + " dB • " + str(seat_tag), font=("DejaVu Sans", 9, "bold"), fg="#ffffff", bg=bg_c, anchor="w")
    sub_l.pack(fill="x")

    root.mainloop()
    sys.exit(0)
except Exception:
    pass
