# -*- coding: utf-8 -*-
# Test overlay script compilation test
import sys, os, subprocess, socket, math, time

msg_text = sys.argv[1] if len(sys.argv) > 1 else (
    "Atenção ao Professor!\n"
    "Esta é uma linha de teste.\n"
    "Linha 3 de instrução para a turma.\n"
    "Linha 4 com mais detalhes."
)
try:
    unlock_seconds = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 0
except Exception:
    unlock_seconds = 0
require_silence = bool(len(sys.argv) > 3 and str(sys.argv[3]).strip().lower() in ("1", "true", "yes", "sim"))

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

disp_env = os.environ.get('DISPLAY', ':0')
user_env = os.environ.get('USER', 'aluno')
disp_num_clean = disp_env.replace(':', '').split('.')[0]
try:
    seat_num = int(disp_num_clean) + 1
except Exception:
    seat_num = 1

seat_display_tag = f"🏷️ ASSENTO {seat_num} ({user_env} | {disp_env})"
info_badge_text = f"🖥️  {local_hostname.upper()}   •   {seat_display_tag}   •   IP: {local_ip}"

is_noise_mode = require_silence or any(w in msg_text.lower() for w in ["calma", "desafio", "silencio", "silêncio", "ruido", "ruído", "barulho", "som", "decibel"])

try:
    subprocess.run(["/bin/bash", "/tmp/restore_peripherals.sh"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except Exception:
    pass

# GTK3
try:
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    from gi.repository import Gtk, Gdk, Pango, GLib

    class FullscreenLockWindow(Gtk.Window):
        def __init__(self, message, unlock_sec=0, is_noise=False):
            super().__init__(type=Gtk.WindowType.TOPLEVEL)
            self.set_title("PAUSA PEDAGÓGICA")
            self.fullscreen()
            self.set_keep_above(True)
            self.set_decorated(False)
            self.remaining_sec = unlock_sec
            self.is_noise = is_noise
            self.calm_score = 0
            self.last_input_penalty_time = 0.0
            self.input_penalty_timer_id = None
            self.warn_blink_timer_id = None
            self.warn_blink_state = False
            self.countdown_running = False

            self.set_events(
                self.get_events()
                | Gdk.EventMask.KEY_PRESS_MASK
                | Gdk.EventMask.KEY_RELEASE_MASK
                | Gdk.EventMask.BUTTON_PRESS_MASK
                | Gdk.EventMask.BUTTON_RELEASE_MASK
                | Gdk.EventMask.SCROLL_MASK
                | Gdk.EventMask.POINTER_MOTION_MASK
                | Gdk.EventMask.TOUCH_MASK
            )
            self.set_can_focus(True)
            self.grab_focus()

            self.connect("delete-event", lambda w, e: True)
            self.connect("event", self.on_generic_event)
            self.connect("key-press-event", self.on_input_event)
            self.connect("button-press-event", self.on_input_event)
            self.connect("scroll-event", self.on_input_event)
            self.connect("key-release-event", lambda w, e: True)
            self.connect("button-release-event", lambda w, e: True)
            self.connect("motion-notify-event", lambda w, e: True)
            self.connect("window-state-event", self.on_window_state_event)
            self.connect("map", self.on_window_mapped)

            try:
                screen = Gdk.Screen.get_default()
                self.screen_w = screen.get_width() if screen else 1024
                self.screen_h = screen.get_height() if screen else 768
            except Exception:
                self.screen_w, self.screen_h = 1024, 768

            self.is_tiny_h = (self.screen_h <= 650 or self.screen_w <= 900)
            self.is_compact = (self.screen_h <= 820 or self.screen_w <= 1280) and not self.is_tiny_h

            if self.is_tiny_h:
                hdr_font = "13px"
                hdr_pad = "4px 8px"
                info_font = "10px"
                info_pad = "2px 8px"
                v_row_margin = "2px 10px"
                v_card_pad = "3px 8px"
                v_card_min_w = "110px"
                v_icon_font = "20px"
                v_title_font = "11px"
                v_sub_font = "9px"
                lock_card_pad = "5px 10px"
                lock_card_margin = "2px 10px"
                msg_font = "13px"
                msg_badge_font = "9px"
                timer_card_pad = "3px 8px"
                timer_hdr_font = "9px"
                timer_clock_font = "16px"
                timer_sub_font = "8px"
                warn_pad = "3px 8px"
                warn_title_font = "11px"
                warn_desc_font = "9px"
                main_title_font = "12px"
                sub_font = "9px"
                bottom_pad = "3px 8px"
                bottom_font = "10px"
            elif self.is_compact:
                hdr_font = "16px"
                hdr_pad = "6px 14px"
                info_font = "12px"
                info_pad = "4px 12px"
                v_row_margin = "4px 16px"
                v_card_pad = "6px 14px"
                v_card_min_w = "150px"
                v_icon_font = "28px"
                v_title_font = "13px"
                v_sub_font = "10px"
                lock_card_pad = "8px 16px"
                lock_card_margin = "3px 16px"
                msg_font = "15px"
                msg_badge_font = "10px"
                timer_card_pad = "4px 14px"
                timer_hdr_font = "10px"
                timer_clock_font = "22px"
                timer_sub_font = "10px"
                warn_pad = "5px 14px"
                warn_title_font = "13px"
                warn_desc_font = "11px"
                main_title_font = "15px"
                sub_font = "11px"
                bottom_pad = "5px 12px"
                bottom_font = "12px"
            else:
                hdr_font = "22px"
                hdr_pad = "12px 20px"
                info_font = "15px"
                info_pad = "8px 20px"
                v_row_margin = "8px 24px"
                v_card_pad = "12px 26px"
                v_card_min_w = "250px"
                v_icon_font = "50px"
                v_title_font = "18px"
                v_sub_font = "13px"
                lock_card_pad = "14px 28px"
                lock_card_margin = "4px 40px"
                msg_font = "19px"
                msg_badge_font = "12px"
                timer_card_pad = "8px 24px"
                timer_hdr_font = "12px"
                timer_clock_font = "30px"
                timer_sub_font = "12px"
                warn_pad = "8px 24px"
                warn_title_font = "18px"
                warn_desc_font = "13px"
                main_title_font = "20px"
                sub_font = "13px"
                bottom_pad = "10px 18px"
                bottom_font = "15px"

            css_tpl = '''
                window { background-color: #090d16; }
                scrolledwindow, viewport { background-color: transparent; }
                .header-bar { background: linear-gradient(135deg, #1e1b4b, #312e81); border-bottom: 2.5px solid #818cf8; padding: __HDR_PAD__; }
                .header-title { color: #fde047; font-size: __HDR_FONT__; font-weight: 900; letter-spacing: 0.5px; }
                .header-bar-noise { background: linear-gradient(135deg, #064e3b, #047857); border-bottom: 2.5px solid #34d399; padding: __HDR_PAD__; }
                .header-title-noise { color: #a7f3d0; font-size: __HDR_FONT__; font-weight: 900; letter-spacing: 0.5px; }
                .info-bar { background-color: #0f172a; border-bottom: 2px solid #38bdf8; padding: __INFO_PAD__; }
                .info-text { color: #38bdf8; font-size: __INFO_FONT__; font-weight: 800; letter-spacing: 0.5px; }
                .visual-row { margin: __V_ROW_MARGIN__; }
                .visual-card-blue { background-color: rgba(12, 74, 110, 0.90); border: 2.5px solid #38bdf8; border-radius: 14px; padding: __V_CARD_PAD__; min-width: __V_CARD_MIN_W__; box-shadow: 0 8px 25px rgba(0,0,0,0.5); }
                .visual-card-green { background-color: rgba(6, 78, 59, 0.90); border: 2.5px solid #34d399; border-radius: 14px; padding: __V_CARD_PAD__; min-width: __V_CARD_MIN_W__; box-shadow: 0 8px 25px rgba(0,0,0,0.5); }
                .visual-card-amber { background-color: rgba(120, 53, 15, 0.90); border: 2.5px solid #f59e0b; border-radius: 14px; padding: __V_CARD_PAD__; min-width: __V_CARD_MIN_W__; box-shadow: 0 8px 25px rgba(0,0,0,0.5); }
                .visual-icon { font-size: __V_ICON_FONT__; margin-bottom: 2px; }
                .visual-title { color: #ffffff; font-size: __V_TITLE_FONT__; font-weight: 900; letter-spacing: 0.5px; margin-top: 1px; }
                .visual-sub { color: #e0f2fe; font-size: __V_SUB_FONT__; font-weight: 700; margin-top: 1px; }
                .lock-card { background-color: #1e293b; border: 2.5px solid #38bdf8; border-radius: 14px; padding: __LOCK_CARD_PAD__; margin: __LOCK_CARD_MARGIN__; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
                .lock-card-noise { background-color: #064e3b; border: 2.5px solid #34d399; border-radius: 14px; padding: __LOCK_CARD_PAD__; margin: __LOCK_CARD_MARGIN__; box-shadow: 0 0 25px rgba(52, 211, 153, 0.35); }
                .msg-badge { color: #fde047; font-size: __MSG_BADGE_FONT__; font-weight: 900; letter-spacing: 0.8px; margin-bottom: 2px; }
                .msg-text { color: #ffffff; font-size: __MSG_FONT__; font-weight: bold; margin: 2px 0; }
                .input-warn-card { background: linear-gradient(135deg, #7f1d1d, #991b1b); border: 2.5px solid #ef4444; border-radius: 14px; padding: __WARN_PAD__; margin: __LOCK_CARD_MARGIN__; box-shadow: 0 0 25px rgba(239, 68, 68, 0.85); }
                .input-warn-card-flash { background: linear-gradient(135deg, #dc2626, #ef4444); border: 2.5px solid #ffffff; border-radius: 14px; padding: __WARN_PAD__; margin: __LOCK_CARD_MARGIN__; box-shadow: 0 0 40px rgba(255, 255, 255, 0.95); }
                .input-warn-title { color: #ffffff; font-size: __WARN_TITLE_FONT__; font-weight: 900; letter-spacing: 0.5px; }
                .input-warn-desc { color: #fef08a; font-size: __WARN_DESC_FONT__; font-weight: 800; margin-top: 1px; }
                .main-title { color: #ffffff; font-size: __MAIN_TITLE_FONT__; font-weight: bold; margin-top: 1px; }
                .main-title-noise { color: #34d399; font-size: __MAIN_TITLE_FONT__; font-weight: 900; margin-top: 1px; }
                .sub-text { color: #cbd5e1; font-size: __SUB_FONT__; }
                .timer-card { background-color: rgba(15, 23, 42, 0.95); border: 2px solid #10b981; border-radius: 12px; padding: __TIMER_CARD_PAD__; margin: __LOCK_CARD_MARGIN__; box-shadow: 0 0 20px rgba(16, 185, 129, 0.35); }
                .timer-card-noise { background-color: rgba(15, 23, 42, 0.95); border: 2.5px solid #10b981; border-radius: 14px; padding: __TIMER_CARD_PAD__; margin: __LOCK_CARD_MARGIN__; box-shadow: 0 0 25px rgba(16, 185, 129, 0.45); }
                .timer-header { color: #fbbf24; font-size: __TIMER_HDR_FONT__; font-weight: 900; letter-spacing: 0.5px; }
                .timer-clock { color: #34d399; font-size: __TIMER_CLOCK_FONT__; font-weight: 900; font-family: monospace; letter-spacing: 1.5px; }
                .timer-sub { color: #94a3b8; font-size: __TIMER_SUB_FONT__; font-weight: 600; }
                .bottom-bar { background-color: #312e81; border-top: 2.5px solid #818cf8; padding: __BOTTOM_PAD__; }
                .bottom-bar-noise { background-color: #064e3b; border-top: 2.5px solid #34d399; padding: __BOTTOM_PAD__; }
                .bottom-text { color: #ffffff; font-size: __BOTTOM_FONT__; font-weight: 900; }
            '''
            reps = {
                "__HDR_PAD__": hdr_pad, "__HDR_FONT__": hdr_font,
                "__INFO_PAD__": info_pad, "__INFO_FONT__": info_font,
                "__V_ROW_MARGIN__": v_row_margin, "__V_CARD_PAD__": v_card_pad,
                "__V_CARD_MIN_W__": v_card_min_w, "__V_ICON_FONT__": v_icon_font,
                "__V_TITLE_FONT__": v_title_font, "__V_SUB_FONT__": v_sub_font,
                "__LOCK_CARD_PAD__": lock_card_pad, "__LOCK_CARD_MARGIN__": lock_card_margin,
                "__MSG_BADGE_FONT__": msg_badge_font, "__MSG_FONT__": msg_font,
                "__WARN_PAD__": warn_pad, "__WARN_TITLE_FONT__": warn_title_font,
                "__WARN_DESC_FONT__": warn_desc_font, "__MAIN_TITLE_FONT__": main_title_font,
                "__SUB_FONT__": sub_font, "__TIMER_CARD_PAD__": timer_card_pad,
                "__TIMER_HDR_FONT__": timer_hdr_font, "__TIMER_CLOCK_FONT__": timer_clock_font,
                "__TIMER_SUB_FONT__": timer_sub_font, "__BOTTOM_PAD__": bottom_pad,
                "__BOTTOM_FONT__": bottom_font,
            }
            for k, v in reps.items():
                css_tpl = css_tpl.replace(k, v)

            provider = Gtk.CssProvider()
            provider.load_from_data(css_tpl.encode('utf-8'))
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

            main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            self.add(main_vbox)

            header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            if self.is_noise:
                header_box.get_style_context().add_class("header-bar-noise")
                header_lbl = Gtk.Label(label="🎮  DESAFIO DA CALMA COLETIVA  •  META 100%  🧊")
                header_lbl.get_style_context().add_class("header-title-noise")
            else:
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

            scrolled = Gtk.ScrolledWindow()
            scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scrolled.set_shadow_type(Gtk.ShadowType.NONE)

            center_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2 if self.is_tiny_h else (4 if self.is_compact else 6))
            if self.is_tiny_h or self.is_compact:
                center_vbox.set_valign(Gtk.Align.START)
            else:
                center_vbox.set_valign(Gtk.Align.CENTER)

            self.pulse_phase = 0.0
            self.darea = Gtk.DrawingArea()
            if self.is_tiny_h:
                self.darea.set_size_request(60, 26)
            elif self.is_compact:
                self.darea.set_size_request(80, 38)
            else:
                self.darea.set_size_request(130, 60)
            self.darea.connect("draw", self.on_draw_pulse)
            center_vbox.pack_start(self.darea, False, False, 0)
            GLib.timeout_add(30, self.on_pulse_tick)

            if self.is_noise:
                title_lbl = Gtk.Label(label="🤫  Barra de Energia da Calma Coletiva da Turma  🧘")
                title_lbl.get_style_context().add_class("main-title-noise")
            else:
                title_lbl = Gtk.Label(label="✨  Momento de Atenção ao Professor  🎓")
                title_lbl.get_style_context().add_class("main-title")
            center_vbox.pack_start(title_lbl, False, False, 0)

            visual_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10 if self.is_tiny_h else (16 if self.is_compact else 28))
            visual_row.get_style_context().add_class("visual-row")
            visual_row.set_halign(Gtk.Align.CENTER)

            vcard1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1 if self.is_tiny_h else 2)
            vcard1.get_style_context().add_class("visual-card-blue")
            vcard1_icon = Gtk.Label(label="✋ 🚫")
            vcard1_icon.get_style_context().add_class("visual-icon")
            vcard1_title = Gtk.Label(label="MÃOS LIVRES")
            vcard1_title.get_style_context().add_class("visual-title")
            vcard1_sub = Gtk.Label(label="Toque no teclado/mouse = +15s de bloqueio")
            vcard1_sub.get_style_context().add_class("visual-sub")
            vcard1.pack_start(vcard1_icon, False, False, 0)
            vcard1.pack_start(vcard1_title, False, False, 0)
            vcard1.pack_start(vcard1_sub, False, False, 0)
            visual_row.pack_start(vcard1, True, True, 0)

            vcard2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1 if self.is_tiny_h else 2)
            if self.is_noise:
                vcard2.get_style_context().add_class("visual-card-amber")
                vcard2_icon = Gtk.Label(label="🤫 👂")
                vcard2_title = Gtk.Label(label="SILÊNCIO = +5%/s")
                vcard2_sub = Gtk.Label(label="Conversas pausam | Barulho = -15%")
            else:
                vcard2.get_style_context().add_class("visual-card-green")
                vcard2_icon = Gtk.Label(label="🤫 👂")
                vcard2_title = Gtk.Label(label="OUVIR EM SILÊNCIO")
                vcard2_sub = Gtk.Label(label="Prestar atenção na aula")
            vcard2_icon.get_style_context().add_class("visual-icon")
            vcard2_title.get_style_context().add_class("visual-title")
            vcard2_sub.get_style_context().add_class("visual-sub")
            vcard2.pack_start(vcard2_icon, False, False, 0)
            vcard2.pack_start(vcard2_title, False, False, 0)
            vcard2.pack_start(vcard2_sub, False, False, 0)
            visual_row.pack_start(vcard2, True, True, 0)

            center_vbox.pack_start(visual_row, False, False, 0)

            self.input_warn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1 if self.is_tiny_h else 2)
            self.input_warn_box.get_style_context().add_class("input-warn-card")
            warn_title = Gtk.Label(label="⚠️ NÃO TOQUE NO TECLADO OU MOUSE! (+15s DE BLOQUEIO) 🚫")
            warn_title.get_style_context().add_class("input-warn-title")
            warn_desc = Gtk.Label(label="✋ MANTENHA AS MÃOS PARADAS! CADA TOQUE OU TECLA AUMENTA O BLOQUEIO EM +15 SEGUNDOS!")
            warn_desc.get_style_context().add_class("input-warn-desc")
            self.input_warn_box.pack_start(warn_title, False, False, 0)
            self.input_warn_box.pack_start(warn_desc, False, False, 0)
            self.input_warn_box.set_no_show_all(True)
            self.input_warn_box.hide()
            center_vbox.pack_start(self.input_warn_box, False, False, 0)

            card_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2 if self.is_tiny_h else (3 if self.is_compact else 5))
            if self.is_noise:
                card_box.get_style_context().add_class("lock-card-noise")
            else:
                card_box.get_style_context().add_class("lock-card")

            card_hdr = Gtk.Label(label="📢  MENSAGEM DE BLOQUEIO")
            card_hdr.get_style_context().add_class("msg-badge")
            card_box.pack_start(card_hdr, False, False, 0)

            msg_lbl = Gtk.Label()
            msg_lbl.set_text(message)
            msg_lbl.set_line_wrap(True)
            msg_lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            msg_lbl.set_justify(Gtk.Justification.CENTER)
            max_chars = max(34, min(95, int((self.screen_w - 60) / (9 if self.is_compact else 12))))
            msg_lbl.set_max_width_chars(max_chars)
            msg_lbl.get_style_context().add_class("msg-text")
            card_box.pack_start(msg_lbl, True, True, 0)
            center_vbox.pack_start(card_box, False, False, 0)

            self.timer_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1 if self.is_tiny_h else 2)
            self.timer_card.get_style_context().add_class("timer-card")

            self.timer_hdr = Gtk.Label(label="⏱️  CONTAGEM REGRESSIVA PARA DESBLOQUEIO")
            self.timer_hdr.get_style_context().add_class("timer-header")
            self.timer_card.pack_start(self.timer_hdr, False, False, 0)

            mins, secs = divmod(max(0, self.remaining_sec), 60)
            self.timer_lbl = Gtk.Label(label=f"{mins:02d}:{secs:02d}")
            self.timer_lbl.get_style_context().add_class("timer-clock")
            self.timer_card.pack_start(self.timer_lbl, False, False, 0)

            self.timer_sub = Gtk.Label(label="🤫 Mantenham as mãos longe do teclado/mouse para liberação")
            self.timer_sub.get_style_context().add_class("timer-sub")
            self.timer_card.pack_start(self.timer_sub, False, False, 0)

            center_vbox.pack_start(self.timer_card, False, False, 0)

            if self.is_noise:
                noise_timer_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2 if self.is_tiny_h else 4)
                noise_timer_card.get_style_context().add_class("timer-card-noise")
                timer_hdr = Gtk.Label(label="🧊  BARRA DE CALMA COLETIVA  •  META: 100%  🎮")
                timer_hdr.get_style_context().add_class("timer-header")
                noise_timer_card.pack_start(timer_hdr, False, False, 0)

                self.calm_status_lbl = Gtk.Label(label="🤫 MANTENHAM SILÊNCIO • ENERGIA: 0%")
                self.calm_status_lbl.get_style_context().add_class("timer-clock")
                noise_timer_card.pack_start(self.calm_status_lbl, False, False, 0)

                self.calm_bar_area = Gtk.DrawingArea()
                if self.is_tiny_h:
                    self.calm_bar_area.set_size_request(min(280, max(120, self.screen_w - 40)), 14)
                elif self.is_compact:
                    self.calm_bar_area.set_size_request(min(420, max(180, self.screen_w - 60)), 18)
                else:
                    self.calm_bar_area.set_size_request(min(600, max(240, self.screen_w - 80)), 28)
                self.calm_bar_area.connect("draw", self.on_draw_calm_bar)
                noise_timer_card.pack_start(self.calm_bar_area, False, False, 0)

                noise_timer_sub = Gtk.Label(label="🎯 Silêncio = +5%/s | Conversas = Pausa | Toques = +15s")
                noise_timer_sub.get_style_context().add_class("timer-sub")
                noise_timer_card.pack_start(noise_timer_sub, False, False, 0)
                center_vbox.pack_start(noise_timer_card, False, False, 0)

                GLib.timeout_add(1000, self.update_calm_loop)
                if self.remaining_sec > 0:
                    self.countdown_running = True
                    GLib.timeout_add(1000, self.update_countdown)
                else:
                    self.timer_card.set_no_show_all(True)
                    self.timer_card.hide()
            elif self.remaining_sec > 0:
                self.countdown_running = True
                GLib.timeout_add(1000, self.update_countdown)
            else:
                self.timer_card.set_no_show_all(True)
                self.timer_card.hide()

            if self.is_noise:
                sub_lbl = Gtk.Label(label="💡  Dica da Corujinha: Peçam silêncio aos colegas e soltem mouse e teclado!")
            else:
                sub_lbl = Gtk.Label(label="💡  Olhe para a frente e acompanhe a explicação do professor. Solte o mouse e o teclado!")
            sub_lbl.get_style_context().add_class("sub-text")
            center_vbox.pack_start(sub_lbl, False, False, 0)

            scrolled.add(center_vbox)
            main_vbox.pack_start(scrolled, True, True, 0)

            bottom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            if self.is_noise:
                bottom_box.get_style_context().add_class("bottom-bar-noise")
                bottom_lbl = Gtk.Label(label="🔇  Periféricos bloqueados   •   Toques aumentam o bloqueio em +15 segundos")
            else:
                bottom_box.get_style_context().add_class("bottom-bar")
                bottom_lbl = Gtk.Label(label="⌨️  Teclado e mouse bloqueados   •   Toques aumentam o bloqueio em +15 segundos")
            bottom_lbl.get_style_context().add_class("bottom-text")
            bottom_box.pack_start(bottom_lbl, True, True, 0)
            main_vbox.pack_start(bottom_box, False, False, 0)

            GLib.timeout_add(200, self.check_sentinel)

        def on_generic_event(self, widget, event):
            try:
                etype_str = str(event.type).upper()
                if any(k in etype_str for k in ["BUTTON_PRESS", "KEY_PRESS", "SCROLL", "TOUCH"]):
                    self.trigger_input_penalty()
                    return True
            except Exception:
                pass
            return False

        def on_input_event(self, widget, event):
            self.trigger_input_penalty()
            return True

        def trigger_input_penalty(self):
            now = time.time()
            if now - self.last_input_penalty_time >= 0.20:
                self.last_input_penalty_time = now
                self.remaining_sec += 15

                try:
                    with open("/tmp/lock_individual_penalty", "w") as f:
                        f.write(str(int(time.time() + self.remaining_sec)))
                except Exception:
                    pass

                if self.is_noise:
                    self.calm_score = max(0, self.calm_score - 10)
                    if hasattr(self, 'calm_status_lbl') and self.calm_status_lbl:
                        self.calm_status_lbl.set_text(f"🚫 TOQUE INDEVIDO DETECTADO! (+15s) • ENERGIA: {self.calm_score}%")
                    if hasattr(self, 'calm_bar_area') and self.calm_bar_area:
                        self.calm_bar_area.queue_draw()

                mins, secs = divmod(self.remaining_sec, 60)
                if hasattr(self, 'timer_lbl') and self.timer_lbl:
                    self.timer_lbl.set_text(f"{mins:02d}:{secs:02d}")
                if hasattr(self, 'timer_card') and self.timer_card:
                    self.timer_card.set_no_show_all(False)
                    self.timer_card.show_all()

                if not self.countdown_running and self.remaining_sec > 0:
                    self.countdown_running = True
                    GLib.timeout_add(1000, self.update_countdown)

                if hasattr(self, 'input_warn_box') and self.input_warn_box:
                    self.input_warn_box.show()
                    if not self.warn_blink_timer_id:
                        self.warn_blink_timer_id = GLib.timeout_add(200, self.on_blink_warning_tick)
                if self.input_penalty_timer_id:
                    GLib.source_remove(self.input_penalty_timer_id)
                self.input_penalty_timer_id = GLib.timeout_add(3500, self.hide_input_warning)

        def on_blink_warning_tick(self):
            if hasattr(self, 'input_warn_box') and self.input_warn_box and self.input_warn_box.get_visible():
                self.warn_blink_state = not self.warn_blink_state
                ctx = self.input_warn_box.get_style_context()
                if self.warn_blink_state:
                    ctx.add_class("input-warn-card-flash")
                else:
                    ctx.remove_class("input-warn-card-flash")
                return True
            return False

        def hide_input_warning(self):
            if self.warn_blink_timer_id:
                GLib.source_remove(self.warn_blink_timer_id)
                self.warn_blink_timer_id = None
            if hasattr(self, 'input_warn_box') and self.input_warn_box:
                self.input_warn_box.get_style_context().remove_class("input-warn-card-flash")
                self.input_warn_box.hide()
            self.input_penalty_timer_id = None
            return False

        def on_window_state_event(self, widget, event):
            if not (event.new_window_state & Gdk.WindowState.FULLSCREEN):
                self.fullscreen()
            if not (event.new_window_state & Gdk.WindowState.ABOVE):
                self.set_keep_above(True)
            return True

        def on_window_mapped(self, widget):
            try:
                self.grab_focus()
                self.present()
            except Exception:
                pass
            try:
                gdk_win = self.get_window()
                display = Gdk.Display.get_default()
                try:
                    cursor = Gdk.Cursor.new_for_display(display, Gdk.CursorType.BLANK_CURSOR)
                    gdk_win.set_cursor(cursor)
                except Exception:
                    pass
            except Exception:
                pass

        def restore_peripherals_and_quit(self):
            try:
                subprocess.run(["/bin/bash", "/tmp/restore_peripherals.sh"], check=False)
            except Exception:
                pass
            Gtk.main_quit()
            sys.exit(0)

        def update_countdown(self):
            if self.remaining_sec <= 0:
                self.countdown_running = False
                try:
                    if os.path.exists("/tmp/lock_individual_penalty"):
                        os.remove("/tmp/lock_individual_penalty")
                except Exception:
                    pass

                if hasattr(self, 'timer_lbl') and self.timer_lbl:
                    self.timer_lbl.set_text("00:00")

                if not self.is_noise or self.calm_score >= 100 or os.path.exists("/tmp/lock_calm_completed"):
                    if hasattr(self, 'calm_status_lbl') and self.calm_status_lbl:
                        self.calm_status_lbl.set_text("🎉 PUNIÇÃO FINALIZADA! • DESBLOQUEANDO TELA...")
                    GLib.timeout_add(1000, self.restore_peripherals_and_quit)
                    return False
                return False

            self.remaining_sec -= 1
            mins, secs = divmod(self.remaining_sec, 60)
            if hasattr(self, 'timer_lbl') and self.timer_lbl:
                self.timer_lbl.set_text(f"{mins:02d}:{secs:02d}")
            return True

        def update_calm_loop(self):
            PENALTY_FLAG = "/tmp/lock_noise_penalty"
            SCORE_FILE = "/tmp/lock_calm_score"
            STATE_FILE = "/tmp/lock_calm_state"
            COMPLETED_FLAG = "/tmp/lock_calm_completed"
            
            has_penalty = False
            if os.path.exists(PENALTY_FLAG):
                try:
                    os.remove(PENALTY_FLAG)
                except Exception:
                    pass
                has_penalty = True

            current_state = "silence"
            if os.path.exists(STATE_FILE):
                try:
                    with open(STATE_FILE, "r") as stf:
                        current_state = stf.read().strip().lower()
                except Exception:
                    pass

            now = time.time()
            recent_input_penalty = (now - self.last_input_penalty_time < 3.5)

            if os.path.exists(SCORE_FILE):
                try:
                    with open(SCORE_FILE, "r") as sf:
                        val = int(sf.read().strip())
                        if not recent_input_penalty:
                            self.calm_score = max(0, min(100, val))
                        else:
                            self.calm_score = min(self.calm_score, max(0, min(100, val)))
                    os.remove(SCORE_FILE)
                except Exception:
                    pass

            if os.path.exists(COMPLETED_FLAG):
                self.calm_score = 100

            now = time.time()
            recent_input_penalty = (now - self.last_input_penalty_time < 3.5)

            if self.calm_score >= 100:
                self.calm_score = 100
                if hasattr(self, 'calm_bar_area') and self.calm_bar_area:
                    self.calm_bar_area.queue_draw()

                if self.remaining_sec > 0:
                    mins, secs = divmod(self.remaining_sec, 60)
                    if hasattr(self, 'calm_status_lbl') and self.calm_status_lbl:
                        self.calm_status_lbl.set_text(f"⏳ A TURMA ATINGIU 100%! CUMPRA SUA PUNIÇÃO: {mins:02d}:{secs:02d}")
                    if hasattr(self, 'timer_card') and self.timer_card:
                        self.timer_card.set_no_show_all(False)
                        self.timer_card.show_all()
                    if not self.countdown_running:
                        self.countdown_running = True
                        GLib.timeout_add(1000, self.update_countdown)
                    return True
                else:
                    if hasattr(self, 'calm_status_lbl') and self.calm_status_lbl:
                        self.calm_status_lbl.set_text("🎉 META 100% ATINGIDA! • DESBLOQUEANDO TELA...")
                    GLib.timeout_add(1000, self.restore_peripherals_and_quit)
                    return False

            if has_penalty or current_state == "penalty":
                if has_penalty:
                    self.calm_score = max(0, self.calm_score - 15)
                if hasattr(self, 'calm_status_lbl') and self.calm_status_lbl and not recent_input_penalty:
                    self.calm_status_lbl.set_text(f"⚠️ BARULHO DETECTADO! (-15%) • ENERGIA: {self.calm_score}%")
            elif current_state == "pause":
                if hasattr(self, 'calm_status_lbl') and self.calm_status_lbl and not recent_input_penalty:
                    self.calm_status_lbl.set_text(f"⏸️ CONVERSAS DETECTADAS • ENERGIA: {self.calm_score}% (PAUSADA)")
            else:
                self.calm_score = min(100, self.calm_score + 5)
                if self.calm_score >= 100:
                    if hasattr(self, 'calm_bar_area') and self.calm_bar_area:
                        self.calm_bar_area.queue_draw()
                    if self.remaining_sec > 0:
                        mins, secs = divmod(self.remaining_sec, 60)
                        if hasattr(self, 'calm_status_lbl') and self.calm_status_lbl:
                            self.calm_status_lbl.set_text(f"⏳ A TURMA ATINGIU 100%! CUMPRA SUA PUNIÇÃO: {mins:02d}:{secs:02d}")
                        if hasattr(self, 'timer_card') and self.timer_card:
                            self.timer_card.set_no_show_all(False)
                            self.timer_card.show_all()
                        if not self.countdown_running:
                            self.countdown_running = True
                            GLib.timeout_add(1000, self.update_countdown)
                        return True
                    else:
                        if hasattr(self, 'calm_status_lbl') and self.calm_status_lbl:
                            self.calm_status_lbl.set_text("🎉 META 100% ATINGIDA! • DESBLOQUEANDO TELA...")
                        GLib.timeout_add(1000, self.restore_peripherals_and_quit)
                        return False
                elif hasattr(self, 'calm_status_lbl') and self.calm_status_lbl:
                    if recent_input_penalty:
                        self.calm_status_lbl.set_text(f"🚫 TOQUE INDEVIDO DETECTADO! (+15s) • ENERGIA: {self.calm_score}%")
                    elif self.calm_score > 0:
                        self.calm_status_lbl.set_text(f"🤫 ENERGIA DA CALMA: {self.calm_score}% (Meta: 100%)")
                    else:
                        self.calm_status_lbl.set_text("🤫 MANTENHAM SILÊNCIO • ENERGIA: 0%")

            if hasattr(self, 'calm_bar_area') and self.calm_bar_area:
                self.calm_bar_area.queue_draw()

            return True

        def on_draw_calm_bar(self, widget, cr):
            alloc = widget.get_allocation()
            w, h = alloc.width, alloc.height
            pad = 12 if self.is_compact else (8 if self.is_tiny_h else 20)
            bw = max(10, w - (pad * 2))
            bh = min(22, max(10, int(h - 4)))
            bx = pad
            by = (h - bh) / 2.0

            cr.set_source_rgba(0.06, 0.09, 0.16, 1.0)
            cr.rectangle(bx, by, bw, bh)
            cr.fill_preserve()
            cr.set_source_rgba(0.06, 0.73, 0.51, 0.5)
            cr.set_line_width(2.0)
            cr.stroke()

            fill_w = (self.calm_score / 100.0) * bw
            if fill_w > 0:
                cr.set_source_rgba(0.06, 0.73, 0.51, 1.0)
                cr.rectangle(bx + 2, by + 2, max(2.0, fill_w - 4), max(2, bh - 4))
                cr.fill()

        def on_pulse_tick(self):
            self.pulse_phase = (self.pulse_phase + 0.07) % (2 * math.pi)
            if hasattr(self, 'darea') and self.darea:
                self.darea.queue_draw()
            return True

        def on_draw_pulse(self, widget, cr):
            alloc = widget.get_allocation()
            cx, cy = alloc.width / 2.0, alloc.height / 2.0
            scale = min(alloc.width / 130.0, alloc.height / 60.0, 1.0)
            scale = max(0.35, scale)
            pulse_scale = 1.0 + 0.12 * math.sin(self.pulse_phase)
            ring_radius = 36 * scale * pulse_scale

            cr.set_source_rgba(0.22, 0.74, 0.97, 0.35 + 0.25 * math.sin(self.pulse_phase))
            cr.arc(cx, cy, ring_radius + (8 * scale), 0, 2 * math.pi)
            cr.set_line_width(max(1.5, 3.5 * scale))
            cr.stroke()

            cr.set_source_rgba(0.39, 0.40, 0.95, 0.85)
            cr.arc(cx, cy, 34 * scale, 0, 2 * math.pi)
            cr.set_line_width(max(1.5, 2.5 * scale))
            cr.stroke()

            cr.set_source_rgba(0.09, 0.13, 0.22, 1.0)
            cr.arc(cx, cy, 32 * scale, 0, 2 * math.pi)
            cr.fill()

            cr.set_source_rgba(0.22, 0.74, 0.97, 1.0)
            cr.set_line_width(max(2.0, 4.5 * scale))
            cr.arc(cx, cy - (5 * scale), 12 * scale, math.pi, 2 * math.pi)
            cr.stroke()

            cr.set_source_rgba(0.02, 0.52, 0.85, 1.0)
            cr.rectangle(cx - (15 * scale), cy - (5 * scale), 30 * scale, 22 * scale)
            cr.fill_preserve()
            cr.set_source_rgba(0.38, 0.85, 0.98, 1.0)
            cr.set_line_width(max(1.0, 2 * scale))
            cr.stroke()

            cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
            cr.arc(cx, cy + (4 * scale), max(1.5, 3 * scale), 0, 2 * math.pi)
            cr.fill()
            cr.move_to(cx - (2 * scale), cy + (5 * scale))
            cr.line_to(cx + (2 * scale), cy + (5 * scale))
            cr.line_to(cx + (2.5 * scale), cy + (11 * scale))
            cr.line_to(cx - (2.5 * scale), cy + (11 * scale))
            cr.close_path()
            cr.fill()

        def check_sentinel(self):
            FLAG_FILE = "/tmp/lock_overlay_active"
            if not os.path.exists(FLAG_FILE):
                self.restore_peripherals_and_quit()
                return False
            return True

    FLAG_FILE = "/tmp/lock_overlay_active"
    try:
        with open(FLAG_FILE, "w") as f:
            f.write("1")
    except Exception:
        pass

    win = FullscreenLockWindow(msg_text, unlock_seconds, is_noise=is_noise_mode)
    win.show_all()
    Gtk.main()
    sys.exit(0)
except Exception:
    pass

# Fallback Tkinter
try:
    import tkinter as tk
    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.config(cursor="none")

    last_tk_penalty_time = [0.0]
    tk_warn_timer = [None]
    tk_blink_timer = [None]
    tk_blink_state = [False]
    rem_sec = [unlock_seconds]
    tk_countdown_running = [unlock_seconds > 0]

    def restore_tk_and_quit():
        try:
            subprocess.run(["/bin/bash", "/tmp/restore_peripherals.sh"], check=False)
        except Exception:
            pass
        root.destroy()
        sys.exit(0)

    def check_tk_sentinel():
        FLAG_FILE = "/tmp/lock_overlay_active"
        if not os.path.exists(FLAG_FILE):
            restore_tk_and_quit()
            return
        root.after(500, check_tk_sentinel)

    root.after(500, check_tk_sentinel)

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    cx = sw // 2

    is_tk_compact = (sh <= 820 or sw <= 1280)
    is_tk_tiny = (sh <= 650 or sw <= 900)

    bg_color = "#090d16"
    canvas = tk.Canvas(root, width=sw, height=sh, bg=bg_color, highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    # 1. Cabeçalho
    hdr_h = 36 if is_tk_tiny else (46 if is_tk_compact else 65)
    hdr_fill = "#064e3b" if is_noise_mode else "#1e1b4b"
    hdr_border = "#34d399" if is_noise_mode else "#818cf8"
    canvas.create_rectangle(0, 0, sw, hdr_h, fill=hdr_fill, outline="")
    canvas.create_rectangle(0, hdr_h - 3, sw, hdr_h, fill=hdr_border, outline="")
    hdr_title = "🎮  DESAFIO DA CALMA COLETIVA  •  META 100%  🧊" if is_noise_mode else "🎓  PAUSA PEDAGÓGICA  •  HORA DE ATENÇÃO  ✨"
    hdr_font_size = 10 if is_tk_tiny else (12 if is_tk_compact else 17)
    hdr_font_color = "#a7f3d0" if is_noise_mode else "#fde047"
    canvas.create_text(cx, hdr_h // 2, text=hdr_title, font=("DejaVu Sans", hdr_font_size, "bold"), fill=hdr_font_color)

    # 2. Barra de informações
    info_h = 24 if is_tk_tiny else (28 if is_tk_compact else 36)
    info_y1 = hdr_h
    info_y2 = hdr_h + info_h
    canvas.create_rectangle(0, info_y1, sw, info_y2, fill="#0f172a", outline="")
    canvas.create_rectangle(0, info_y2 - 2, sw, info_y2, fill="#38bdf8", outline="")
    info_font_size = 8 if is_tk_tiny else (9 if is_tk_compact else 12)
    canvas.create_text(cx, (info_y1 + info_y2) // 2, text=info_badge_text, font=("DejaVu Sans", info_font_size, "bold"), fill="#38bdf8")

    # 3. Barra de rodapé
    btm_h = 28 if is_tk_tiny else (36 if is_tk_compact else 48)
    btm_y1 = sh - btm_h
    btm_y2 = sh
    btm_fill = "#064e3b" if is_noise_mode else "#1e1b4b"
    btm_border = "#34d399" if is_noise_mode else "#6366f1"
    canvas.create_rectangle(0, btm_y1, sw, btm_y2, fill=btm_fill, outline="")
    canvas.create_rectangle(0, btm_y1, sw, btm_y1 + 2, fill=btm_border, outline="")
    btm_text = "🔇  Periféricos bloqueados   •   Toques aumentam o bloqueio em +15 segundos" if is_noise_mode else "⌨️  Teclado e mouse bloqueados   •   Toques aumentam o bloqueio em +15 segundos"
    btm_font_size = 8 if is_tk_tiny else (10 if is_tk_compact else 12)
    btm_font_color = "#a7f3d0" if is_noise_mode else "#e0e7ff"
    canvas.create_text(cx, (btm_y1 + btm_y2) // 2, text=btm_text, font=("DejaVu Sans", btm_font_size, "bold"), fill=btm_font_color)

    # 4. Área Central Sequencial e Bounded
    y_cursor = info_y2 + (4 if is_tk_tiny else 8)
    y_max = btm_y1 - (4 if is_tk_tiny else 8)

    # Padlock
    if not is_tk_tiny and (y_max - y_cursor > 380):
        lock_y = y_cursor + 18
        canvas.create_oval(cx - 20, lock_y - 15, cx + 20, lock_y + 15, fill="#1e293b", outline="#38bdf8", width=2)
        canvas.create_arc(cx - 10, lock_y - 24, cx + 10, lock_y - 4, start=0, extent=180, outline="#38bdf8", width=3, style="arc")
        canvas.create_rectangle(cx - 11, lock_y - 6, cx + 11, lock_y + 10, fill="#0284c7", outline="#38bdf8", width=1)
        canvas.create_oval(cx - 2, lock_y, cx + 2, lock_y + 4, fill="#ffffff", outline="")
        y_cursor += 38

    # Título Principal
    main_title_txt = "🤫  Barra de Energia da Calma Coletiva da Turma  🧘" if is_noise_mode else "✨  Momento de Atenção ao Professor  🎓"
    main_title_color = "#34d399" if is_noise_mode else "#ffffff"
    main_title_size = 10 if is_tk_tiny else (12 if is_tk_compact else 15)
    canvas.create_text(cx, y_cursor + 6, text=main_title_txt, font=("DejaVu Sans", main_title_size, "bold"), fill=main_title_color)
    y_cursor += (18 if is_tk_compact else 24)

    # Cartões de Orientação dos Alunos (2 cartões compactos lado a lado)
    card_w = min(280, max(130, (sw - 50) // 2))
    card_h = 38 if is_tk_tiny else (52 if is_tk_compact else 70)
    x1 = cx - card_w - (6 if is_tk_compact else 12)
    x2 = cx + (6 if is_tk_compact else 12)

    canvas.create_rectangle(x1, y_cursor, x1 + card_w, y_cursor + card_h, fill="#0c4a6e", outline="#38bdf8", width=2)
    c1_icon_size = 16 if is_tk_tiny else (20 if is_tk_compact else 28)
    c1_title_size = 8 if is_tk_tiny else (10 if is_tk_compact else 12)
    c1_sub_size = 7 if is_tk_tiny else (8 if is_tk_compact else 9)
    canvas.create_text(x1 + 24, y_cursor + card_h // 2, text="✋🚫", font=("DejaVu Sans", c1_icon_size))
    canvas.create_text(x1 + 36 + (card_w - 36) // 2, y_cursor + card_h // 2 - 7, text="MÃOS LIVRES", font=("DejaVu Sans", c1_title_size, "bold"), fill="#ffffff")
    canvas.create_text(x1 + 36 + (card_w - 36) // 2, y_cursor + card_h // 2 + 7, text="Toque no mouse = +15s", font=("DejaVu Sans", c1_sub_size), fill="#e0f2fe")

    c2_fill = "#78350f" if is_noise_mode else "#064e3b"
    c2_border = "#f59e0b" if is_noise_mode else "#34d399"
    c2_title = "SILÊNCIO = +5%/s" if is_noise_mode else "OUVIR EM SILÊNCIO"
    c2_sub = "Barulho = -15%" if is_noise_mode else "Prestar atenção na aula"
    canvas.create_rectangle(x2, y_cursor, x2 + card_w, y_cursor + card_h, fill=c2_fill, outline=c2_border, width=2)
    canvas.create_text(x2 + 24, y_cursor + card_h // 2, text="🤫👂", font=("DejaVu Sans", c1_icon_size))
    canvas.create_text(x2 + 36 + (card_w - 36) // 2, y_cursor + card_h // 2 - 7, text=c2_title, font=("DejaVu Sans", c1_title_size, "bold"), fill="#ffffff")
    canvas.create_text(x2 + 36 + (card_w - 36) // 2, y_cursor + card_h // 2 + 7, text=c2_sub, font=("DejaVu Sans", c1_sub_size), fill="#fef3c7" if is_noise_mode else "#d1fae5")
    y_cursor += card_h + (6 if is_tk_compact else 10)

    # CARD DE MENSAGEM DINÂMICO
    raw_lines = msg_text.splitlines()
    approx_chars_per_line = max(30, int((sw - 80) / (7 if is_tk_compact else 10)))
    total_est_lines = sum(max(1, math.ceil(len(l) / approx_chars_per_line)) for l in raw_lines) if raw_lines else 1

    msg_font_size = 11 if is_tk_tiny else (13 if is_tk_compact else 15)
    line_spacing = 15 if is_tk_tiny else (18 if is_tk_compact else 22)
    msg_card_w = min(940, sw - (24 if is_tk_compact else 50))
    msg_card_h = max(42, min(200, 20 + total_est_lines * line_spacing))
    msg_card_x1 = cx - msg_card_w // 2
    msg_card_x2 = cx + msg_card_w // 2
    msg_card_y1 = y_cursor
    msg_card_y2 = y_cursor + msg_card_h

    card_fill = "#064e3b" if is_noise_mode else "#1e293b"
    card_border = "#34d399" if is_noise_mode else "#38bdf8"
    canvas.create_rectangle(msg_card_x1, msg_card_y1, msg_card_x2, msg_card_y2, fill=card_fill, outline=card_border, width=2)
    canvas.create_text(cx, msg_card_y1 + 8, text="📢  MENSAGEM DO PROFESSOR", font=("DejaVu Sans", 8 if is_tk_compact else 9, "bold"), fill="#fde047")
    canvas.create_text(cx, msg_card_y1 + 12 + (msg_card_h - 12) // 2, text=msg_text, font=("DejaVu Sans", msg_font_size, "bold"), fill="#ffffff", width=msg_card_w - 24)
    y_cursor += msg_card_h + (5 if is_tk_compact else 10)

    # Contagem Regressiva de Bloqueio (Tkinter)
    mins_init, secs_init = divmod(max(0, rem_sec[0]), 60)
    timer_state = "normal" if rem_sec[0] > 0 else "hidden"
    timer_hdr_id = canvas.create_text(cx, y_cursor + 6, text="⏱️  CONTAGEM REGRESSIVA PARA DESBLOQUEIO", font=("DejaVu Sans", 8 if is_tk_compact else 10, "bold"), fill="#fbbf24", state=timer_state)
    timer_text_id = canvas.create_text(cx, y_cursor + (20 if is_tk_compact else 28), text=f"{mins_init:02d}:{secs_init:02d}", font=("DejaVu Sans", 16 if is_tk_compact else 22, "bold"), fill="#34d399", state=timer_state)
    timer_sub_id = canvas.create_text(cx, y_cursor + (36 if is_tk_compact else 48), text="🤫 Mantenham as mãos longe do teclado/mouse para liberação", font=("DejaVu Sans", 7 if is_tk_compact else 9), fill="#94a3b8", state=timer_state)
    if rem_sec[0] > 0:
        y_cursor += (46 if is_tk_compact else 58)

    # Barra de Calma Coletiva (Tkinter)
    if is_noise_mode:
        tk_calm_score = [0]
        canvas.create_text(cx, y_cursor + 6, text="🧊  BARRA DE CALMA COLETIVA  •  META: 100%  🎮", font=("DejaVu Sans", 8 if is_tk_compact else 10, "bold"), fill="#fbbf24")
        tk_calm_text_id = canvas.create_text(cx, y_cursor + (20 if is_tk_compact else 26), text="🤫 MANTENHAM SILÊNCIO • ENERGIA: 0%", font=("DejaVu Sans", 12 if is_tk_compact else 16, "bold"), fill="#34d399")
        pbar_w = min(460, max(180, sw - 50))
        pbar_h = 12 if is_tk_compact else 18
        pbar_x1 = cx - pbar_w // 2
        pbar_y1 = y_cursor + (30 if is_tk_compact else 40)
        pbar_x2 = cx + pbar_w // 2
        pbar_y2 = pbar_y1 + pbar_h
        canvas.create_rectangle(pbar_x1, pbar_y1, pbar_x2, pbar_y2, fill="#0f172a", outline="#10b981", width=2)
        tk_fill_id = canvas.create_rectangle(pbar_x1 + 2, pbar_y1 + 2, pbar_x1 + 2, pbar_y2 - 2, fill="#10b981", outline="")
        canvas.create_text(cx, pbar_y2 + 8, text="🎯 Silêncio = +5%/s | Conversas = Pausa | Toques = +15s", font=("DejaVu Sans", 7 if is_tk_compact else 9), fill="#94a3b8")
        y_cursor = pbar_y2 + 16

    # Banner de aviso de toque indevido piscante (Tkinter)
    warn_h = 38 if is_tk_compact else 48
    warn_y1 = min(y_cursor + 2, y_max - warn_h - 14)
    warn_y2 = warn_y1 + warn_h
    warn_w = min(700, sw - 24)
    warn_rect_id = canvas.create_rectangle(cx - warn_w // 2, warn_y1, cx + warn_w // 2, warn_y2, fill="#7f1d1d", outline="#ef4444", width=2, state="hidden")
    warn_txt1_id = canvas.create_text(cx, warn_y1 + 12, text="⚠️ NÃO TOQUE NO TECLADO OU MOUSE! (+15s DE BLOQUEIO) 🚫", font=("DejaVu Sans", 9 if is_tk_compact else 11, "bold"), fill="#ffffff", state="hidden")
    warn_txt2_id = canvas.create_text(cx, warn_y1 + 28, text="✋ CADA TOQUE OU TECLA AUMENTA O BLOQUEIO EM +15 SEGUNDOS!", font=("DejaVu Sans", 8 if is_tk_compact else 9, "bold"), fill="#fef08a", state="hidden")

    # Dica educativa
    tip_text = "💡  Dica da Corujinha: Peçam silêncio aos colegas e soltem mouse e teclado!" if is_noise_mode else "💡  Olhe para a frente e acompanhe a explicação do professor. Solte o mouse e o teclado!"
    canvas.create_text(cx, y_max - 3, text=tip_text, font=("DejaVu Sans", 8 if is_tk_compact else 10), fill="#cbd5e1")

    def update_tk_timer():
        if rem_sec[0] <= 0:
            tk_countdown_running[0] = False
            try:
                if os.path.exists("/tmp/lock_individual_penalty"):
                    os.remove("/tmp/lock_individual_penalty")
            except Exception:
                pass
            canvas.itemconfig(timer_text_id, text="00:00")
            if not is_noise_mode or tk_calm_score[0] >= 100 or os.path.exists("/tmp/lock_calm_completed"):
                if is_noise_mode:
                    canvas.itemconfig(tk_calm_text_id, text="🎉 PUNIÇÃO FINALIZADA! • DESBLOQUEANDO TELA...", fill="#34d399")
                root.after(1000, restore_tk_and_quit)
                return
            return

        rem_sec[0] -= 1
        m, s = divmod(rem_sec[0], 60)
        canvas.itemconfig(timer_text_id, text=f"{m:02d}:{s:02d}")
        root.after(1000, update_tk_timer)

    if unlock_seconds > 0:
        root.after(1000, update_tk_timer)

    def blink_tk_warning():
        tk_blink_state[0] = not tk_blink_state[0]
        if tk_blink_state[0]:
            canvas.itemconfig(warn_rect_id, fill="#dc2626", outline="#ffffff", width=3)
            canvas.itemconfig(warn_txt1_id, fill="#ffffff")
            canvas.itemconfig(warn_txt2_id, fill="#fde047")
        else:
            canvas.itemconfig(warn_rect_id, fill="#7f1d1d", outline="#ef4444", width=2)
            canvas.itemconfig(warn_txt1_id, fill="#fecaca")
            canvas.itemconfig(warn_txt2_id, fill="#fef08a")
        tk_blink_timer[0] = root.after(200, blink_tk_warning)

    def hide_tk_warning():
        if tk_blink_timer[0]:
            root.after_cancel(tk_blink_timer[0])
            tk_blink_timer[0] = None
        canvas.itemconfig(warn_rect_id, state="hidden")
        canvas.itemconfig(warn_txt1_id, state="hidden")
        canvas.itemconfig(warn_txt2_id, state="hidden")
        tk_warn_timer[0] = None

    def on_tk_input(e=None):
        now = time.time()
        if now - last_tk_penalty_time[0] >= 0.20:
            last_tk_penalty_time[0] = now
            rem_sec[0] += 15

            try:
                with open("/tmp/lock_individual_penalty", "w") as f:
                    f.write(str(int(time.time() + rem_sec[0])))
            except Exception:
                pass

            if is_noise_mode and 'tk_calm_score' in globals():
                tk_calm_score[0] = max(0, tk_calm_score[0] - 10)
                canvas.itemconfig(tk_calm_text_id, text=f"🚫 TOQUE INDEVIDO DETECTADO! (+15s) • ENERGIA: {tk_calm_score[0]}%", fill="#ef4444")
                fill_width = int((tk_calm_score[0] / 100.0) * (pbar_w - 4))
                canvas.coords(tk_fill_id, pbar_x1 + 2, pbar_y1 + 2, pbar_x1 + 2 + max(0, fill_width), pbar_y2 - 2)

            m, s = divmod(rem_sec[0], 60)
            canvas.itemconfig(timer_text_id, text=f"{m:02d}:{s:02d}", state="normal")
            canvas.itemconfig(timer_hdr_id, state="normal")
            canvas.itemconfig(timer_sub_id, state="normal")

            if not tk_countdown_running[0] and rem_sec[0] > 0:
                tk_countdown_running[0] = True
                root.after(1000, update_tk_timer)

            canvas.itemconfig(warn_rect_id, state="normal")
            canvas.itemconfig(warn_txt1_id, state="normal")
            canvas.itemconfig(warn_txt2_id, state="normal")
            if not tk_blink_timer[0]:
                blink_tk_warning()
            if tk_warn_timer[0]:
                root.after_cancel(tk_warn_timer[0])
            tk_warn_timer[0] = root.after(3500, hide_tk_warning)
        return "break"

    for seq in ("<Key>", "<Button>", "<Button-1>", "<Button-2>", "<Button-3>", "<Button-4>", "<Button-5>", "<MouseWheel>"):
        root.bind_all(seq, on_tk_input)

    if is_noise_mode:
        def update_tk_calm():
            PENALTY_FLAG = "/tmp/lock_noise_penalty"
            SCORE_FILE = "/tmp/lock_calm_score"
            STATE_FILE = "/tmp/lock_calm_state"
            COMPLETED_FLAG = "/tmp/lock_calm_completed"

            has_penalty = False
            if os.path.exists(PENALTY_FLAG):
                try:
                    os.remove(PENALTY_FLAG)
                except Exception:
                    pass
                has_penalty = True

            current_state = "silence"
            if os.path.exists(STATE_FILE):
                try:
                    with open(STATE_FILE, "r") as stf:
                        current_state = stf.read().strip().lower()
                except Exception:
                    pass

            now = time.time()
            recent_input_penalty = (now - last_tk_penalty_time[0] < 3.5)

            if os.path.exists(SCORE_FILE):
                try:
                    with open(SCORE_FILE, "r") as sf:
                        val = int(sf.read().strip())
                        if not recent_input_penalty:
                            tk_calm_score[0] = max(0, min(100, val))
                        else:
                            tk_calm_score[0] = min(tk_calm_score[0], max(0, min(100, val)))
                    os.remove(SCORE_FILE)
                except Exception:
                    pass

            if os.path.exists(COMPLETED_FLAG):
                tk_calm_score[0] = 100

            if tk_calm_score[0] >= 100:
                tk_calm_score[0] = 100
                fill_width = int((tk_calm_score[0] / 100.0) * (pbar_w - 4))
                canvas.coords(tk_fill_id, pbar_x1 + 2, pbar_y1 + 2, pbar_x1 + 2 + max(0, fill_width), pbar_y2 - 2)
                if rem_sec[0] > 0:
                    m, s = divmod(rem_sec[0], 60)
                    canvas.itemconfig(tk_calm_text_id, text=f"⏳ A TURMA ATINGIU 100%! CUMPRA SUA PUNIÇÃO: {m:02d}:{s:02d}", fill="#fbbf24")
                    canvas.itemconfig(timer_text_id, state="normal")
                    canvas.itemconfig(timer_hdr_id, state="normal")
                    canvas.itemconfig(timer_sub_id, state="normal")
                    if not tk_countdown_running[0]:
                        tk_countdown_running[0] = True
                        root.after(1000, update_tk_timer)
                    root.after(1000, update_tk_calm)
                    return
                else:
                    canvas.itemconfig(tk_calm_text_id, text="🎉 META 100% ATINGIDA! • DESBLOQUEANDO TELA...", fill="#34d399")
                    root.after(1000, restore_tk_and_quit)
                    return

            if has_penalty or current_state == "penalty":
                if has_penalty:
                    tk_calm_score[0] = max(0, tk_calm_score[0] - 15)
                if not recent_input_penalty:
                    canvas.itemconfig(tk_calm_text_id, text=f"⚠️ BARULHO DETECTADO! (-15%) • ENERGIA: {tk_calm_score[0]}%", fill="#ef4444")
            elif current_state == "pause":
                if not recent_input_penalty:
                    canvas.itemconfig(tk_calm_text_id, text=f"⏸️ CONVERSAS DETECTADAS • ENERGIA: {tk_calm_score[0]}% (PAUSADA)", fill="#fbbf24")
            else:
                tk_calm_score[0] = min(100, tk_calm_score[0] + 5)
                if tk_calm_score[0] >= 100:
                    fill_width = int((tk_calm_score[0] / 100.0) * (pbar_w - 4))
                    canvas.coords(tk_fill_id, pbar_x1 + 2, pbar_y1 + 2, pbar_x1 + 2 + max(0, fill_width), pbar_y2 - 2)
                    if rem_sec[0] > 0:
                        m, s = divmod(rem_sec[0], 60)
                        canvas.itemconfig(tk_calm_text_id, text=f"⏳ A TURMA ATINGIU 100%! CUMPRA SUA PUNIÇÃO: {m:02d}:{s:02d}", fill="#fbbf24")
                        canvas.itemconfig(timer_text_id, state="normal")
                        canvas.itemconfig(timer_hdr_id, state="normal")
                        canvas.itemconfig(timer_sub_id, state="normal")
                        if not tk_countdown_running[0]:
                            tk_countdown_running[0] = True
                            root.after(1000, update_tk_timer)
                        root.after(1000, update_tk_calm)
                        return
                    else:
                        canvas.itemconfig(tk_calm_text_id, text="🎉 META 100% ATINGIDA! • DESBLOQUEANDO TELA...", fill="#34d399")
                        root.after(1000, restore_tk_and_quit)
                        return
                elif recent_input_penalty:
                    canvas.itemconfig(tk_calm_text_id, text=f"🚫 TOQUE INDEVIDO DETECTADO! (+15s) • ENERGIA: {tk_calm_score[0]}%", fill="#ef4444")
                elif tk_calm_score[0] > 0:
                    canvas.itemconfig(tk_calm_text_id, text=f"🤫 ENERGIA DA CALMA: {tk_calm_score[0]}% (Meta: 100%)", fill="#34d399")
                else:
                    canvas.itemconfig(tk_calm_text_id, text="🤫 MANTENHAM SILÊNCIO • ENERGIA: 0%", fill="#34d399")

            fill_width = int((tk_calm_score[0] / 100.0) * (pbar_w - 4))
            canvas.coords(tk_fill_id, pbar_x1 + 2, pbar_y1 + 2, pbar_x1 + 2 + max(0, fill_width), pbar_y2 - 2)
            root.after(1000, update_tk_calm)

        root.after(1000, update_tk_calm)

    root.mainloop()
    sys.exit(0)
except Exception:
    pass

# Fallbacks nativos (Zenity / Xmessage)
try:
    pango_zen = "<span font='18' weight='bold' foreground='#fbbf24'>🎓  PAUSA PEDAGÓGICA  •  HORA DE ATENÇÃO  ✨</span>\n\n<span font='36'>✋  🤫</span>\n\n<span font='15' weight='bold' foreground='#ffffff'>" + msg_text + "</span>\n\n<span font='12' foreground='#38bdf8'>💡 Olhe para a frente e acompanhe a explicação do professor.</span>"
    subprocess.run(["zenity", "--warning", "--title=🎓 PAUSA PEDAGÓGICA", "--text=" + pango_zen, "--width=640", "--height=320"], check=False)
    sys.exit(0)
except Exception:
    pass

try:
    subprocess.run(["xmessage", "-center", "PAUSA PEDAGÓGICA\n\n" + msg_text], check=False)
    sys.exit(0)
except Exception:
    pass
