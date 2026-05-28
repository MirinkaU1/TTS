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

# ─── GEMINI TTS ────────────────────────────────────────────────────────────

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
        from google import genai
        from google.genai import types
        
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
        output_id = uuid.uuid4().hex[:8]
        
        import tempfile
        import subprocess
        
        media_type = "audio/wav"
        filename = f"gemini_{output_id}.wav"
        final_bytes = audio_bytes
        
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
                tmp_wav.write(audio_bytes)
                tmp_wav_path = tmp_wav.name
                
            tmp_mp3_path = tmp_wav_path.replace(".wav", ".mp3")
            
            import shutil
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
                media_type = "audio/mpeg"
                filename = f"gemini_{output_id}.mp3"
                os.remove(tmp_mp3_path)
                
            os.remove(tmp_wav_path)
        except Exception:
            pass # Fallback to WAV if ffmpeg is missing
            
        audio_b64 = base64.b64encode(final_bytes).decode("utf-8")
        
        return JSONResponse({
            "audio": audio_b64,
            "media_type": media_type,
            "filename": filename,
            "engine": "gemini",
        })
    except ImportError:
        raise HTTPException(500, "Le package google-genai n'est pas installé. Lancez: pip install google-genai")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Erreur Gemini: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)