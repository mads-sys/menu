import sys
import os
import urllib.parse
import urllib.request
import subprocess
import tempfile
import time

def play_audio(file_path):
    for cmd in [
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", file_path],
        ["mpv", "--no-video", "--really-quiet", file_path],
        ["cvlc", "--play-and-exit", file_path],
        ["mpg123", "-q", file_path],
        ["paplay", file_path],
        ["aplay", "-q", file_path]
    ]:
        try:
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25)
            if res.returncode == 0:
                return True
        except Exception:
            continue
    return False

def speak_online(text):
    try:
        encoded = urllib.parse.quote(text)
        url = f"https://translate.google.com/translate_tts?ie=UTF-8&tl=pt-BR&client=tw-ob&q={encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            audio_data = resp.read()
        
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_data)
            temp_path = f.name

        ok = play_audio(temp_path)
        try:
            os.remove(temp_path)
        except Exception:
            pass
        return ok
    except Exception:
        return False

def speak_offline(text):
    # 1. Speech Dispatcher
    try:
        res = subprocess.run(["spd-say", "-l", "pt-br", "-r", "-5", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        if res.returncode == 0:
            return True
    except Exception:
        pass

    # 2. espeak-ng / espeak
    for espeak_cmd in [["espeak-ng", "-v", "pt-br", "-s", "140", text], ["espeak", "-v", "pt-br", "-s", "140", text]]:
        try:
            res = subprocess.run(espeak_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            if res.returncode == 0:
                return True
        except Exception:
            continue
    return False

def unmute_audio():
    for cmd in [
        ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
        ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "95%"],
        ["amixer", "set", "Master", "unmute"],
        ["amixer", "set", "Master", "95%"]
    ]:
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        except Exception:
            pass

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(0)
    msg = sys.argv[1].strip()
    if not msg:
        sys.exit(0)
    unmute_audio()
    if not speak_online(msg):
        speak_offline(msg)
