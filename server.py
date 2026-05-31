"""
TTS Studio - Backend FastAPI
Moteur : Gemini TTS
Lancer avec : uvicorn server:app --host 0.0.0.0 --port 8000
"""

import os
import io
import uuid
import base64
import wave
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="TTS Studio API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="."), name="static")

OUTPUT_DIR = Path("./outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

@app.get("/")
def index():
    return FileResponse("index.html")

@app.get("/status")
def status():
    gemini_ok = False
    try:
        import google.genai
        if os.environ.get("GEMINI_API_KEY"):
            gemini_ok = True
    except ImportError:
        pass

    return JSONResponse({
        "gemini": gemini_ok,
    })

# ─── LOGIQUE DE GÉNÉRATION ───────────────────────────────────────────────────

def generate_audio_bytes(input_text, voice):
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise HTTPException(500, "Le package google-genai n'est pas installé. Lancez: pip install google-genai")
        
    if not os.environ.get("GEMINI_API_KEY"):
        raise HTTPException(401, "Clé API Gemini non configurée (GEMINI_API_KEY)")
        
    client = genai.Client()
    
    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=input_text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice
                    )
                )
            )
        )
    )
    
    raw_pcm_data = response.candidates[0].content.parts[0].inline_data.data
    
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit s16le
        wav_file.setframerate(24000)
        wav_file.writeframes(raw_pcm_data)
        
    audio_bytes = wav_io.getvalue()
    
    import tempfile
    import subprocess
    import shutil
    
    final_bytes = audio_bytes
    is_mp3 = False
    
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
            tmp_wav.write(audio_bytes)
            tmp_wav_path = tmp_wav.name
            
        tmp_mp3_path = tmp_wav_path.replace(".wav", ".mp3")
        
        ffmpeg_cmd = "ffmpeg"
        winget_ffmpeg = r"C:\Users\cheri\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe"
        
        if not shutil.which("ffmpeg"):
            if os.path.exists(winget_ffmpeg):
                ffmpeg_cmd = winget_ffmpeg
            else:
                raise FileNotFoundError("ffmpeg introuvable dans le PATH.")
        
        result = subprocess.run(
            [ffmpeg_cmd, "-y", "-i", tmp_wav_path, "-b:a", "128k", tmp_mp3_path],
            capture_output=True,
            check=False
        )
        
        if result.returncode == 0 and os.path.exists(tmp_mp3_path):
            with open(tmp_mp3_path, "rb") as f:
                final_bytes = f.read()
            is_mp3 = True
            os.remove(tmp_mp3_path)
            
        os.remove(tmp_wav_path)
    except Exception:
        pass # Fallback to WAV if ffmpeg is missing
        
    return final_bytes, is_mp3

# ─── GEMINI TTS SINGLE ──────────────────────────────────────────────────────

@app.post("/tts/gemini")
async def tts_gemini(
    text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    voice: str = Form("Kore"),
):
    if not text and not file:
        raise HTTPException(400, "Fournir du texte ou un fichier")

    if file:
        raw = await file.read()
        input_text = raw.decode("utf-8")
    else:
        input_text = text

    try:
        final_bytes, is_mp3 = generate_audio_bytes(input_text, voice)
        
        output_id = uuid.uuid4().hex[:8]
        media_type = "audio/mpeg" if is_mp3 else "audio/wav"
        ext = "mp3" if is_mp3 else "wav"
        filename = f"gemini_{output_id}.{ext}"
        
        audio_b64 = base64.b64encode(final_bytes).decode("utf-8")
        
        return JSONResponse({
            "audio": audio_b64,
            "media_type": media_type,
            "filename": filename,
            "engine": "gemini",
        })
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        err_str = str(e)
        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
            raise HTTPException(429, f"Rate limit Google: {err_str}")
        raise HTTPException(500, f"Erreur Gemini: {err_str}")

# ─── GEMINI TTS BATCH (JSON) ────────────────────────────────────────────────

@app.post("/tts/batch")
async def tts_batch(
    file: UploadFile = File(...),
    voice: str = Form("Kore"),
):
    import json
    import zipfile
    import re
    import time
    
    def clean_html(raw_html):
        cleanr = re.compile('<.*?>')
        return re.sub(cleanr, '', raw_html)

    def extract_lesson_text(lecon):
        lines = []
        titre = lecon.get('titre', '')
        if titre:
            lines.append(f"Titre de la leçon : {titre}")
            
        for bloc in lecon.get('blocs', []):
            if bloc.get('type') == 'texte':
                lines.append(clean_html(bloc.get('valeur', '')))
            elif bloc.get('type') == 'liste':
                for item in bloc.get('items', []):
                    lines.append(f"- {clean_html(item)}")
        return "\n".join(lines)
    
    raw = await file.read()
    data = json.loads(raw.decode("utf-8"))
    lecons = data.get("lecons", [])
    
    if not lecons:
        raise HTTPException(400, "Aucune leçon trouvée dans le fichier JSON.")
    
    from fastapi.responses import StreamingResponse
    
    def generate_stream():
        total = len(lecons)
        zip_buffer = io.BytesIO()
        elapsed_times = []
        
        # Envoyer l'événement d'initialisation
        init_data = json.dumps({"total": total}, ensure_ascii=False)
        yield f"event: init\ndata: {init_data}\n\n"
        
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for i, lecon in enumerate(lecons, 1):
                texte = extract_lesson_text(lecon)
                if not texte.strip():
                    continue
                    
                raw_title = lecon.get('titre', '')
                safe_title = re.sub(r'[\\/*?:"<>|]', '', raw_title).strip()
                if not safe_title:
                    safe_title = "Lecon"
                
                # Envoyer la progression : en cours
                progress_data = json.dumps({
                    "current": i,
                    "total": total,
                    "title": raw_title,
                    "status": "generating",
                }, ensure_ascii=False)
                yield f"event: progress\ndata: {progress_data}\n\n"
                
                start_time = time.time()
                
                # Génération audio avec gestion du Rate Limit (429)
                audio_bytes = None
                is_mp3 = False
                
                max_retries = 10
                for attempt in range(max_retries):
                    try:
                        audio_bytes, is_mp3 = generate_audio_bytes(texte, voice)
                        break
                    except Exception as e:
                        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                            if attempt < max_retries - 1:
                                # Informer le client qu'on attend
                                wait_data = json.dumps({
                                    "current": i,
                                    "total": total,
                                    "title": raw_title,
                                    "status": "waiting",
                                    "message": f"Limite API atteinte, pause de 65s... (tentative {attempt+1})",
                                }, ensure_ascii=False)
                                yield f"event: progress\ndata: {wait_data}\n\n"
                                time.sleep(65)
                            else:
                                error_data = json.dumps({"message": f"Échec après {max_retries} tentatives pour: {raw_title}"}, ensure_ascii=False)
                                yield f"event: error\ndata: {error_data}\n\n"
                                return
                        else:
                            error_data = json.dumps({"message": str(e)}, ensure_ascii=False)
                            yield f"event: error\ndata: {error_data}\n\n"
                            return
                
                elapsed = time.time() - start_time
                elapsed_times.append(elapsed)
                
                ext = "mp3" if is_mp3 else "wav"
                filename = f"{i:02d}_{safe_title}.{ext}"
                zip_file.writestr(filename, audio_bytes)
                
                # Calculer le temps restant estimé
                avg_time = sum(elapsed_times) / len(elapsed_times)
                remaining = int(avg_time * (total - i))
                
                # Envoyer la progression : terminé
                done_data = json.dumps({
                    "current": i,
                    "total": total,
                    "title": raw_title,
                    "status": "done",
                    "elapsed": round(elapsed, 1),
                    "remaining": remaining,
                }, ensure_ascii=False)
                yield f"event: progress\ndata: {done_data}\n\n"
                
                # Pause entre les requêtes
                if i < total:
                    time.sleep(8)
        
        # Envoyer le ZIP final
        zip_buffer.seek(0)
        zip_bytes = zip_buffer.getvalue()
        audio_b64 = base64.b64encode(zip_bytes).decode("utf-8")
        
        complete_data = json.dumps({
            "audio": audio_b64,
            "media_type": "application/zip",
            "filename": "lecons_audio_batch.zip",
            "engine": "gemini",
        })
        yield f"event: complete\ndata: {complete_data}\n\n"
    
    return StreamingResponse(generate_stream(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)