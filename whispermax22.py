import os
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import whisper
import re
import time
from datetime import timedelta
import traceback

# Constantes globales
RATE = 16000
CHANNELS = 2
SRT_OUTPUT_BASE = "subtitles"
MKV_OUTPUT_BASE = "output"
WHISPER_MODELS = ["tiny", "base", "small", "medium", "large"]
LANGUAGES = ["fr"]
transcriptions = {}
running = False
gui_log = None
progress_label = None
print_lock = threading.Lock()
model = None

def get_unique_filename(filepath):
    """Génère un nom de fichier unique en ajoutant un suffixe numérique si le fichier existe."""
    base, ext = os.path.splitext(filepath)
    counter = 1
    new_filepath = filepath
    while os.path.exists(new_filepath):
        new_filepath = f"{base}_{counter}{ext}"
        counter += 1
    return new_filepath

def get_audio_devices():
    """Récupère la liste des périphériques audio disponibles."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        return [(device["name"], i) for i, device in enumerate(devices) if device["max_input_channels"] > 0]
    except ImportError:
        return []

def sanitize_filename(filename):
    """Nettoie le nom de fichier pour éviter les caractères invalides."""
    return re.sub(r'[<>:"/\\|?*]', '', filename.replace(" ", "_"))

def format_timestamp(seconds):
    """Formate un temps en secondes en format SRT (HH:MM:SS,mmm)."""
    ms = int((seconds % 1) * 1000)
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"

def extract_audio_from_video(video_file):
    """Extrait l'audio d'un fichier vidéo en WAV avec un nom unique."""
    video_file = os.path.normpath(video_file)
    base_audio_file = os.path.normpath(f"audio_{os.path.splitext(os.path.basename(video_file))[0]}.wav")
    audio_file = get_unique_filename(base_audio_file)
    with print_lock:
        print(f"Extraction audio de {video_file} vers {audio_file}, RATE={RATE}, type={type(RATE)}, CHANNELS={CHANNELS}, type={type(CHANNELS)}")
    if gui_log:
        gui_log.insert(tk.END, f"Extraction audio de {video_file} vers {audio_file}, RATE={RATE}, type={type(RATE)}, CHANNELS={CHANNELS}, type={type(CHANNELS)}\n")
        gui_log.see(tk.END)
    
    if not isinstance(video_file, str):
        raise TypeError(f"video_file doit être une chaîne, reçu : {type(video_file)}, valeur : {video_file}")
    if not isinstance(audio_file, str):
        raise TypeError(f"audio_file doit être une chaîne, reçu : {type(audio_file)}, valeur : {audio_file}")
    
    cmd = ["ffmpeg", "-i", video_file, "-vn", "-acodec", "pcm_s16le", "-ar", str(RATE), "-ac", str(CHANNELS), audio_file]
    with print_lock:
        print(f"Commande ffmpeg : {' '.join(cmd)}")
    if gui_log:
        gui_log.insert(tk.END, f"Commande ffmpeg : {' '.join(cmd)}\n")
        gui_log.see(tk.END)
    try:
        result = subprocess.run(cmd, capture_output=True, check=True, text=True, timeout=60)
        if os.path.exists(audio_file):
            with print_lock:
                print(f"Audio extrait : {audio_file}, taille={os.path.getsize(audio_file)} bytes")
            if gui_log:
                gui_log.insert(tk.END, f"Audio extrait : {audio_file}, taille={os.path.getsize(audio_file)} bytes\n")
                gui_log.see(tk.END)
            return audio_file
        else:
            with print_lock:
                print(f"Erreur : Fichier audio {audio_file} non créé")
            if gui_log:
                gui_log.insert(tk.END, f"Erreur : Fichier audio {audio_file} non créé\n")
                gui_log.see(tk.END)
            return None
    except subprocess.TimeoutExpired as e:
        with print_lock:
            print(f"Erreur : Timeout lors de l'extraction audio : {e}")
        if gui_log:
            gui_log.insert(tk.END, f"Erreur : Timeout lors de l'extraction audio : {e}\n")
            gui_log.see(tk.END)
        return None
    except subprocess.CalledProcessError as e:
        with print_lock:
            print(f"Erreur extraction audio : {e.stderr}")
        if gui_log:
            gui_log.insert(tk.END, f"Erreur extraction audio : {e.stderr}\n")
            gui_log.see(tk.END)
        return None
    except Exception as e:
        with print_lock:
            print(f"Erreur inattendue lors de l'extraction audio : {e}")
            traceback.print_exc()
        if gui_log:
            gui_log.insert(tk.END, f"Erreur inattendue lors de l'extraction audio : {e}\n")
            gui_log.see(tk.END)
        return None

def record_audio(device_index=None, audio_file=None):
    """Simule l'enregistrement ou utilise un fichier audio existant."""
    temp_wav_files = []
    if audio_file:
        temp_wav_file = os.path.normpath(audio_file)
        with print_lock:
            print(f"Utilisation du fichier audio existant : {temp_wav_file}")
        if gui_log:
            gui_log.insert(tk.END, f"Utilisation du fichier audio existant : {temp_wav_file}\n")
            gui_log.see(tk.END)
        temp_wav_files.append(temp_wav_file)
        return temp_wav_files
    return temp_wav_files

def transcribe_audio(lang, video_id, video_title, temp_wav_files=None):
    """Transcrit un fichier audio et génère un fichier texte/SRT."""
    global transcriptions
    transcription = []
    for temp_wav in temp_wav_files or []:
        with print_lock:
            print(f"Transcription {temp_wav} en {lang}")
        if gui_log:
            gui_log.insert(tk.END, f"Transcription {temp_wav} en {lang}\n")
            gui_log.see(tk.END)
        try:
            result = model.transcribe(temp_wav, language=None if lang == "auto" else lang)
            transcription.extend(result["segments"])
        except Exception as e:
            with print_lock:
                print(f"Erreur transcription {temp_wav} : {e}")
            if gui_log:
                gui_log.insert(tk.END, f"Erreur transcription {temp_wav} : {e}\n")
                gui_log.see(tk.END)
    transcriptions[lang].append((video_id, transcription))
    output_file = os.path.normpath(f"transcriptions_{sanitize_filename(video_title)}_{lang}.txt")
    with open(output_file, "w", encoding="utf-8") as f:
        for segment in transcription:
            f.write(f"{segment['start']} --> {segment['end']}\n{segment['text']}\n\n")
    srt_file = os.path.normpath(f"{SRT_OUTPUT_BASE}_{lang}.srt")
    with open(srt_file, "w", encoding="utf-8") as f:
        for i, segment in enumerate(transcription, 1):
            start = format_timestamp(segment["start"])
            end = format_timestamp(segment["end"])
            f.write(f"{i}\n{start} --> {end}\n{segment['text']}\n\n")
    with print_lock:
        print(f"Fichiers générés : {output_file}, {srt_file}")
    if gui_log:
        gui_log.insert(tk.END, f"Fichiers générés : {output_file}, {srt_file}\n")
        gui_log.see(tk.END)

def embed_multiple_subtitles(video_file, srt_files, title, burn_subtitles):
    """Intègre les sous-titres dans une vidéo MKV, soit incrustés (burned-in), soit comme pistes séparées."""
    video_file = os.path.normpath(video_file)
    title = sanitize_filename(title)
    base_output_file = os.path.normpath(f"{MKV_OUTPUT_BASE}_{title}.mkv")
    output_file = get_unique_filename(base_output_file)
    with print_lock:
        print(f"Intégration des sous-titres pour video_file={video_file}, type={type(video_file)}, title={title}, type={type(title)}, output_file={output_file}, burn_subtitles={burn_subtitles}")
    if gui_log:
        gui_log.insert(tk.END, f"Intégration des sous-titres pour video_file={video_file}, type={type(video_file)}, title={title}, type={type(title)}, output_file={output_file}, burn_subtitles={burn_subtitles}\n")
        gui_log.see(tk.END)

    if not isinstance(video_file, str):
        raise TypeError(f"video_file doit être une chaîne, reçu : {type(video_file)}, valeur : {video_file}")
    if not isinstance(title, str):
        raise TypeError(f"title doit être une chaîne, reçu : {type(title)}, valeur : {title}")

    cmd = ["ffmpeg", "-i", video_file]
    subtitle_index = 0

    if burn_subtitles:
        # Incrustation des sous-titres (uniquement la première langue)
        if srt_files:
            srt = os.path.normpath(srt_files[0])  # Utiliser le premier fichier SRT
            if not os.path.exists(srt):
                with print_lock:
                    print(f"Fichier SRT manquant : {srt}, aucun sous-titre incrusté")
                if gui_log:
                    gui_log.insert(tk.END, f"Fichier SRT manquant : {srt}, aucun sous-titre incrusté\n")
                    gui_log.see(tk.END)
            else:
                cmd.extend(["-vf", f"subtitles={srt}:force_style='FontSize=24'"])
                subtitle_index = 1
                with print_lock:
                    print(f"Incrustation des sous-titres de {srt} dans la vidéo")
                if gui_log:
                    gui_log.insert(tk.END, f"Incrustation des sous-titres de {srt} dans la vidéo\n")
                    gui_log.see(tk.END)
                if len(srt_files) > 1:
                    with print_lock:
                        print("Avertissement : Seuls les sous-titres de la première langue sont incrustés")
                    if gui_log:
                        gui_log.insert(tk.END, "Avertissement : Seuls les sous-titres de la première langue sont incrustés\n")
                        gui_log.see(tk.END)
    else:
        # Inclusion des sous-titres comme pistes séparées
        for i, srt in enumerate(srt_files):
            srt = os.path.normpath(srt)
            if not os.path.exists(srt):
                with print_lock:
                    print(f"Fichier SRT manquant : {srt}, ignoré")
                if gui_log:
                    gui_log.insert(tk.END, f"Fichier SRT manquant : {srt}, ignoré\n")
                    gui_log.see(tk.END)
                continue
            cmd.extend(["-i", srt])
            subtitle_index += 1

    cmd.extend(["-c:v", "libx264", "-c:a", "aac"])
    if not burn_subtitles and subtitle_index > 0:
        # Ajouter les pistes de sous-titres
        cmd.extend(["-map", "0:v", "-map", "0:a"] + [item for i in range(subtitle_index) for item in ["-map", f"{i+1}:s"]])
        cmd.extend(["-c:s", "copy"])
        for i, lang in enumerate(LANGUAGES[:subtitle_index]):
            cmd.extend([f"-metadata:s:s:{i}", f"language={lang}"])
            with print_lock:
                print(f"Ajout métadonnée pour langue {lang}, index {i}, type index={type(i)}")
            if gui_log:
                gui_log.insert(tk.END, f"Ajout métadonnée pour langue {lang}, index {i}, type index={type(i)}\n")
                gui_log.see(tk.END)
    elif burn_subtitles and subtitle_index > 0:
        # Pas besoin de pistes de sous-titres supplémentaires si incrustés
        cmd.extend(["-map", "0:v", "-map", "0:a"])
    else:
        # Pas de sous-titres, mapper uniquement vidéo et audio
        cmd.extend(["-map", "0:v", "-map", "0:a"])

    cmd.append(output_file)
    with print_lock:
        print(f"Commande ffmpeg : {' '.join(cmd)}")
    if gui_log:
        gui_log.insert(tk.END, f"Commande ffmpeg : {' '.join(cmd)}\n")
        gui_log.see(tk.END)
    try:
        subprocess.run(cmd, capture_output=True, check=True, text=True)
        with print_lock:
            print(f"Fichier MKV généré : {output_file}")
        if gui_log:
            gui_log.insert(tk.END, f"Fichier MKV généré : {output_file}\n")
            gui_log.see(tk.END)
    except subprocess.CalledProcessError as e:
        with print_lock:
            print(f"Erreur incrustation sous-titres : {e.stderr}")
        if gui_log:
            gui_log.insert(tk.END, f"Erreur incrustation sous-titres : {e.stderr}\n")
            gui_log.see(tk.END)
        raise

def process_local_video(video_file, languages, quality, cleanup_files, burn_subtitles, model):
    """Traite un fichier vidéo local pour générer un MKV avec sous-titres."""
    global transcriptions, gui_log
    try:
        video_file = os.path.normpath(video_file)
        with print_lock:
            print(f"Traitement du fichier local (normalisé) : {video_file}, type : {type(video_file)}")
        if gui_log:
            gui_log.insert(tk.END, f"Traitement du fichier local (normalisé) : {video_file}, type : {type(video_file)}\n")
            gui_log.see(tk.END)

        if not isinstance(video_file, str):
            raise TypeError(f"video_file doit être une chaîne, reçu : {type(video_file)}, valeur : {video_file}")

        video_title = os.path.splitext(os.path.basename(video_file))[0]
        video_title = sanitize_filename(video_title)
        with print_lock:
            print(f"Titre extrait : {video_title}, type : {type(video_title)}")
        if gui_log:
            gui_log.insert(tk.END, f"Titre extrait : {video_title}, type : {type(video_title)}\n")
            gui_log.see(tk.END)

        with print_lock:
            print(f"Appel extract_audio_from_video avec video_file={video_file}")
        if gui_log:
            gui_log.insert(tk.END, f"Appel extract_audio_from_video avec video_file={video_file}\n")
            gui_log.see(tk.END)
        audio_file = extract_audio_from_video(video_file)
        if not audio_file:
            with print_lock:
                print(f"Erreur : Échec de l'extraction audio pour {video_file}")
            if gui_log:
                gui_log.insert(tk.END, f"Erreur : Échec de l'extraction audio pour {video_file}\n")
                gui_log.see(tk.END)
            return

        with print_lock:
            print(f"Appel record_audio avec audio_file={audio_file}")
        if gui_log:
            gui_log.insert(tk.END, f"Appel record_audio avec audio_file={audio_file}\n")
            gui_log.see(tk.END)
        temp_wav_files = record_audio(audio_file=audio_file)
        for lang in languages:
            with print_lock:
                print(f"Transcription pour la langue : {lang}, video_file={video_file}, video_title={video_title}")
            if gui_log:
                gui_log.insert(tk.END, f"Transcription pour la langue : {lang}, video_file={video_file}, video_title={video_title}\n")
                gui_log.see(tk.END)
            transcribe_audio(lang, video_file, video_title, temp_wav_files=temp_wav_files)
        
        srt_files = [os.path.normpath(f"{SRT_OUTPUT_BASE}_{lang}.srt") for lang in languages]
        with print_lock:
            print(f"Fichiers SRT à intégrer : {srt_files}, burn_subtitles={burn_subtitles}")
        if gui_log:
            gui_log.insert(tk.END, f"Fichiers SRT à intégrer : {srt_files}, burn_subtitles={burn_subtitles}\n")
            gui_log.see(tk.END)
        embed_multiple_subtitles(video_file, srt_files, video_title, burn_subtitles)

        if cleanup_files:
            if os.path.exists(audio_file):
                os.remove(audio_file)
                with print_lock:
                    print(f"Fichier audio supprimé : {audio_file}")
                if gui_log:
                    gui_log.insert(tk.END, f"Fichier audio supprimé : {audio_file}\n")
                    gui_log.see(tk.END)
            for srt in srt_files:
                if os.path.exists(srt):
                    os.remove(srt)
                    with print_lock:
                        print(f"Fichier SRT supprimé : {srt}")
                    if gui_log:
                        gui_log.insert(tk.END, f"Fichier SRT supprimé : {srt}\n")
                        gui_log.see(tk.END)
            with print_lock:
                print(f"Fichiers temporaires nettoyés (audio et SRT)")
            if gui_log:
                gui_log.insert(tk.END, f"Fichiers temporaires nettoyés (audio et SRT)\n")
                gui_log.see(tk.END)

    except Exception as e:
        with print_lock:
            print(f"Erreur lors du traitement du fichier local {video_file} : {e}")
            traceback.print_exc()
        if gui_log:
            gui_log.insert(tk.END, f"Erreur lors du traitement du fichier local {video_file} : {e}\n")
            gui_log.see(tk.END)
        raise

def download_youtube_content(url, quality, browser, cookies_file, content_type, max_videos, pause_seconds, cleanup_files, burn_subtitles, model):
    """Simule le téléchargement de contenu YouTube (non implémenté ici)."""
    return []

def console_main():
    """Mode console (non implémenté ici)."""
    print("Mode console non implémenté.")

def gui_main():
    """Interface graphique."""
    global running, model, gui_log, LANGUAGES, transcriptions, progress_label
    print("GUI démarrée. Si les boutons ne s'affichent pas, redimensionnez la fenêtre ou vérifiez Tkinter.")
    try:
        root = tk.Tk()
        root.title("WhisperMax")
        root.geometry("1200x800")

        is_night_mode = tk.BooleanVar(value=False)

        style = ttk.Style()
        style.theme_create("day", settings={
            "TLabelFrame": {"configure": {"background": "white", "foreground": "black"}},
            "TLabel": {"configure": {"background": "white", "foreground": "black"}},
            "TCombobox": {"configure": {"fieldbackground": "white", "background": "white", "foreground": "black"}},
            "TEntry": {"configure": {"fieldbackground": "white", "background": "white", "foreground": "black"}},
            "TCheckbutton": {"configure": {"background": "white", "foreground": "black"}},
            "TButton": {"configure": {"background": "white", "foreground": "black"}}
        })
        style.theme_create("night", settings={
            "TLabelFrame": {"configure": {"background": "#2E2E2E", "foreground": "#E0E0E0"}},
            "TLabel": {"configure": {"background": "#2E2E2E", "foreground": "#E0E0E0"}},
            "TCombobox": {"configure": {"fieldbackground": "#3C3C3C", "background": "#3C3C3C", "foreground": "#E0E0E0"}},
            "TEntry": {"configure": {"fieldbackground": "#3C3C3C", "background": "#3C3C3C", "foreground": "#E0E0E0"}},
            "TCheckbutton": {"configure": {"background": "#2E2E2E", "foreground": "#E0E0E0"}},
            "TButton": {"configure": {"background": "#3C3C3C", "foreground": "#E0E0E0"}}
        })
        style.theme_use("day")

        def toggle_theme():
            if is_night_mode.get():
                style.theme_use("day")
                root.configure(bg="white")
                main_frame.configure(bg="white")
                left_frame.configure(bg="white")
                log_frame.configure(bg="white")
                log_text.configure(bg="white", fg="black")
                canvas.configure(bg="white")
                scrollable_frame.configure(bg="white")
                is_night_mode.set(False)
                theme_button.configure(text="Mode Nuit")
            else:
                style.theme_use("night")
                root.configure(bg="#2E2E2E")
                main_frame.configure(bg="#2E2E2E")
                left_frame.configure(bg="#2E2E2E")
                log_frame.configure(bg="#2E2E2E")
                log_text.configure(bg="#3C3C3C", fg="#E0E0E0")
                canvas.configure(bg="#2E2E2E")
                scrollable_frame.configure(bg="#2E2E2E")
                is_night_mode.set(True)
                theme_button.configure(text="Mode Jour")
            # Forcer la mise à jour de l'affichage de la case à cocher
            burn_checkbutton.update()

        main_frame = ttk.Frame(root)
        main_frame.pack(fill="both", expand=True)
        print("main_frame créé")

        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        print("left_frame créé")

        log_frame = ttk.LabelFrame(main_frame, text="Logs", borderwidth=2, relief="groove")
        log_frame.pack(side="right", fill="both", expand=True, padx=10, pady=10)
        print("log_frame créé")

        log_text = scrolledtext.ScrolledText(log_frame, height=50, bg="white", fg="black")
        log_text.pack(padx=5, pady=5, fill="both", expand=True)
        gui_log = log_text
        print("log_text créé")

        canvas = tk.Canvas(left_frame, bg="white")
        scrollbar = ttk.Scrollbar(left_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        print("canvas et scrollbar créés")

        def on_mouse_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", on_mouse_wheel)

        content_type_var = tk.StringVar(value="video")
        url_var = tk.StringVar()
        browser_var = tk.StringVar()
        cookies_var = tk.StringVar()
        languages_var = tk.StringVar(value="fr")
        quality_var = tk.StringVar(value="best")
        max_videos_var = tk.StringVar()
        pause_var = tk.StringVar(value="0")
        cleanup_var = tk.BooleanVar(value=True)
        burn_var = tk.BooleanVar(value=False)
        model_var = tk.StringVar(value="small")
        device_var = tk.StringVar()
        local_file_var = tk.StringVar()
        devices = get_audio_devices()
        device_names = [name for name, _ in devices] or ["Aucun périphérique"]
        device_var.set(device_names[0])

        input_frame = ttk.LabelFrame(scrollable_frame, text="Paramètres", borderwidth=2, relief="groove")
        input_frame.pack(padx=10, pady=10, fill="x")
        print("input_frame créé")

        ttk.Label(input_frame, text="Type de contenu :").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        content_type_combo = ttk.Combobox(input_frame, textvariable=content_type_var, values=["video", "playlist", "channel", "direct", "fichier local"], width=30)
        content_type_combo.grid(row=0, column=1, columnspan=2, padx=5, pady=5, sticky="w")
        def on_content_type_change(event):
            if content_type_var.get() == "fichier local":
                select_local_file(local_file_var)
        content_type_combo.bind("<<ComboboxSelected>>", on_content_type_change)
        print("content_type_combo créé")

        ttk.Label(input_frame, text="URL YouTube :").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        ttk.Entry(input_frame, textvariable=url_var, width=50).grid(row=1, column=1, columnspan=2, padx=5, pady=5, sticky="w")
        print("url_var créé")

        ttk.Label(input_frame, text="Fichier vidéo :").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        ttk.Entry(input_frame, textvariable=local_file_var, width=40).grid(row=2, column=1, padx=5, pady=5, sticky="w")
        browse_button = ttk.Button(input_frame, text="Parcourir", command=lambda: select_local_file(local_file_var), width=10)
        browse_button.grid(row=2, column=2, padx=5, pady=5, sticky="w")
        print("Bouton Parcourir créé")

        ttk.Label(input_frame, text="Navigateur cookies (firefox, chrome, brave, opera, etc.) :").grid(row=3, column=0, padx=5, pady=5, sticky="e")
        ttk.Entry(input_frame, textvariable=browser_var, width=50).grid(row=3, column=1, columnspan=2, padx=5, pady=5, sticky="w")
        ttk.Label(input_frame, text="Cookies.txt :").grid(row=4, column=0, padx=5, pady=5, sticky="e")
        ttk.Entry(input_frame, textvariable=cookies_var, width=50).grid(row=4, column=1, columnspan=2, padx=5, pady=5, sticky="w")
        ttk.Label(input_frame, text="Langues (ex. fr,en) :").grid(row=5, column=0, padx=5, pady=5, sticky="e")
        ttk.Entry(input_frame, textvariable=languages_var, width=50).grid(row=5, column=1, columnspan=2, padx=5, pady=5, sticky="w")
        ttk.Label(input_frame, text="Qualité vidéo :").grid(row=6, column=0, padx=5, pady=5, sticky="e")
        quality_combo = ttk.Combobox(input_frame, textvariable=quality_var, values=["best", "worst", "360p", "720p", "1080p"], width=47)
        quality_combo.grid(row=6, column=1, columnspan=2, padx=5, pady=5, sticky="w")
        ttk.Label(input_frame, text="Max vidéos :").grid(row=7, column=0, padx=5, pady=5, sticky="e")
        ttk.Entry(input_frame, textvariable=max_videos_var, width=50).grid(row=7, column=1, columnspan=2, padx=5, pady=5, sticky="w")
        ttk.Label(input_frame, text="Pause (secondes) :").grid(row=8, column=0, padx=5, pady=5, sticky="e")
        ttk.Entry(input_frame, textvariable=pause_var, width=50).grid(row=8, column=1, columnspan=2, padx=5, pady=5, sticky="w")
        ttk.Label(input_frame, text="Modèle Whisper :").grid(row=9, column=0, padx=5, pady=5, sticky="e")
        model_combo = ttk.Combobox(input_frame, textvariable=model_var, values=WHISPER_MODELS, width=47)
        model_combo.grid(row=9, column=1, columnspan=2, padx=5, pady=5, sticky="w")
        def check_model(event):
            if model_var.get() in ["tiny", "base"]:
                messagebox.showwarning("Avertissement", "Le modèle tiny/base peut avoir une précision limitée. Envisagez 'medium' pour de meilleurs résultats.")
        model_combo.bind("<<ComboboxSelected>>", check_model)
        ttk.Label(input_frame, text="Périphérique audio :").grid(row=10, column=0, padx=5, pady=5, sticky="e")
        ttk.Combobox(input_frame, textvariable=device_var, values=device_names, width=47).grid(row=10, column=1, columnspan=2, padx=5, pady=5, sticky="w")
        ttk.Checkbutton(input_frame, text="Supprimer MP4/SRT", variable=cleanup_var).grid(row=11, column=0, columnspan=3, padx=5, pady=5)
        
        # Case à cocher pour incruster les sous-titres avec fonction de rappel
        def on_burn_toggle():
            state = "activée" if burn_var.get() else "désactivée"
            with print_lock:
                print(f"Option 'Incruster les sous-titres' {state}")
            if gui_log:
                gui_log.insert(tk.END, f"Option 'Incruster les sous-titres' {state}\n")
                gui_log.see(tk.END)
        
        burn_checkbutton = ttk.Checkbutton(input_frame, text="Incruster les sous-titres dans la vidéo (pour YouTube)", variable=burn_var, command=on_burn_toggle)
        burn_checkbutton.grid(row=12, column=0, columnspan=3, padx=5, pady=5)

        button_subframe = ttk.Frame(input_frame)
        button_subframe.grid(row=13, column=0, columnspan=3, pady=10)
        ttk.Button(button_subframe, text="Démarrer", command=lambda: start_script(), width=15).pack(side=tk.LEFT, padx=20)
        ttk.Button(button_subframe, text="Arrêter", command=lambda: stop_script(), width=15).pack(side=tk.LEFT, padx=20)

        theme_button = ttk.Button(input_frame, text="Mode Nuit", command=toggle_theme, width=15)
        theme_button.grid(row=14, column=0, columnspan=3, pady=5)

        progress_frame = ttk.LabelFrame(scrollable_frame, text="Progression", borderwidth=2, relief="groove")
        progress_frame.pack(padx=10, pady=10, fill="x")
        progress_label = ttk.Label(progress_frame, text="Transcription : En attente")
        progress_label.pack(pady=5)

        mkv_frame = ttk.LabelFrame(scrollable_frame, text="Fichiers MKV", borderwidth=2, relief="groove")
        mkv_frame.pack(padx=10, pady=10, fill="both", expand=True)

        mkv_list = tk.Listbox(mkv_frame, height=8, bg="white", fg="black")
        mkv_list.pack(padx=5, pady=5, fill="both", expand=True)

        def update_mkv_list():
            mkv_list.delete(0, tk.END)
            for file in os.listdir("."):
                if file.endswith(".mkv"):
                    mkv_list.insert(tk.END, file)
            root.after(5000, update_mkv_list)

        def play_mkv():
            selected = mkv_list.curselection()
            if selected:
                file = mkv_list.get(selected[0])
                os.startfile(file)

        ttk.Button(mkv_frame, text="Play", command=play_mkv).pack(pady=5)

        text_frame = ttk.LabelFrame(scrollable_frame, text="Fichiers Texte (Direct)", borderwidth=2, relief="groove")
        text_frame.pack(padx=10, pady=10, fill="both", expand=True)

        text_list = tk.Listbox(text_frame, height=8, bg="white", fg="black")
        text_list.pack(padx=5, pady=5, fill="both", expand=True)

        def update_text_list():
            text_list.delete(0, tk.END)
            for file in os.listdir("."):
                if (file.startswith("live_") and file.endswith(".txt")) or (file.startswith("transcriptions_") and file.endswith(".txt")):
                    text_list.insert(tk.END, file)
            root.after(5000, update_text_list)

        def open_text():
            selected = text_list.curselection()
            if selected:
                file = text_list.get(selected[0])
                os.startfile(file)

        ttk.Button(text_frame, text="Ouvrir", command=open_text).pack(pady=5)

        def select_local_file(file_var):
            file_path = filedialog.askopenfilename(
                title="Sélectionner un fichier vidéo",
                filetypes=[("Fichiers vidéo", "*.mp4 *.mkv *.avi *.mov *.wmv")]
            )
            if file_path:
                file_path = os.path.normpath(file_path)
                file_var.set(file_path)
                log_text.insert(tk.END, f"Fichier sélectionné : {file_path}\n")
                log_text.see(tk.END)

        def start_script():
            global running
            if not running:
                running = True
                burn_state = "activée" if burn_var.get() else "désactivée"
                log_text.insert(tk.END, f"Démarrage du script... Option 'Incruster les sous-titres' {burn_state}\n")
                log_text.see(tk.END)
                # Vérifier si plusieurs langues sont sélectionnées avec burn_subtitles
                languages_input = languages_var.get()
                languages = [l.strip().lower() for l in languages_input.split(",")] if languages_input else ["fr"]
                if burn_var.get() and len(languages) > 1:
                    messagebox.showwarning("Avertissement", "L'incrustation des sous-titres utilise uniquement la première langue (par ex., 'fr').")
                threading.Thread(target=run_script, daemon=True).start()

        def stop_script():
            global running
            running = False
            with print_lock:
                print("Arrêt du script...")
            log_text.insert(tk.END, "Arrêt du script...\n")
            log_text.see(tk.END)

        def run_script():
            global running, LANGUAGES, transcriptions, model, gui_log, progress_label
            content_type = content_type_var.get()
            youtube_url = url_var.get()
            browser = browser_var.get() or None
            cookies_file = cookies_var.get() or None
            languages_input = languages_var.get()
            quality_input = quality_var.get()
            max_videos = max_videos_var.get()
            max_videos = int(max_videos) if max_videos.isdigit() else None
            pause_seconds = float(pause_var.get()) if pause_var.get().replace('.', '', 1).isdigit() else 0
            cleanup_files = cleanup_var.get()
            burn_subtitles = burn_var.get()
            model_name = model_var.get()
            device_name = device_var.get()
            local_file = local_file_var.get()
            device_index = None
            if content_type == "direct":
                device_index = next((idx for name, idx in devices if name == device_name), None)

            LANGUAGES = [l.strip().lower() for l in languages_input.split(",")] if languages_input else ["fr"]
            if "auto" in LANGUAGES:
                LANGUAGES = ["auto"]
            transcriptions = {lang: [] for lang in LANGUAGES}

            if model_name in ["tiny", "base"]:
                log_text.insert(tk.END, "Avertissement : Modèle tiny/base peut avoir une précision limitée. Envisagez 'medium'.\n")
                log_text.see(tk.END)
            model = whisper.load_model(model_name)
            log_text.insert(tk.END, f"Modèle Whisper chargé : {model_name}\n")
            log_text.see(tk.END)

            if content_type == "direct":
                temp_wav_files = record_audio(device_index=device_index)
            elif content_type == "fichier local":
                if not local_file or not os.path.exists(local_file):
                    log_text.insert(tk.END, "Erreur : Aucun fichier vidéo sélectionné ou fichier introuvable.\n")
                    log_text.see(tk.END)
                    running = False
                    return
                process_local_video(local_file, LANGUAGES, quality_input, cleanup_files, burn_subtitles, model)
            else:
                video_files = download_youtube_content(
                    youtube_url, quality_input, browser, cookies_file, content_type,
                    max_videos, pause_seconds, cleanup_files, burn_subtitles, model
                )
                if content_type == "video" and video_files:
                    audio_file = extract_audio_from_video(video_files[0][0])
                    temp_wav_files = record_audio(audio_file)
                    for lang in LANGUAGES:
                        transcribe_audio(lang, video_files[0][0], video_files[0][1], temp_wav_files=temp_wav_files)
                    srt_files = [f"{SRT_OUTPUT_BASE}_{lang}.srt" for lang in LANGUAGES]
                    embed_multiple_subtitles(video_files[0][0], srt_files, video_files[0][1], burn_subtitles)
                    if cleanup_files:
                        if os.path.exists(audio_file):
                            os.remove(audio_file)
                        if os.path.exists(video_files[0][0]):
                            os.remove(video_files[0][0])
                        for srt in srt_files:
                            if os.path.exists(srt):
                                os.remove(srt)

        update_mkv_list()
        update_text_list()
        root.mainloop()
    except ImportError as e:
        print(f"Erreur Tkinter : {e}. Utilisez le mode console.")
        console_main()
    except Exception as e:
        print(f"Erreur GUI : {e}. Passage au mode console.")
        console_main()

if __name__ == "__main__":
    print(f"Constantes globales : RATE={RATE}, type={type(RATE)}, CHANNELS={CHANNELS}, type={type(CHANNELS)}")
    gui_main()