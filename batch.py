import json
import requests
import base64
import re
import os

# Configuration
JSON_FILE = "maths.json"
API_URL = "http://localhost:8000/tts/gemini"
OUTPUT_DIR = "outputs_batch"
VOICE = "Kore"

# Créer le dossier de sortie s'il n'existe pas
os.makedirs(OUTPUT_DIR, exist_ok=True)

def clean_html(raw_html):
    """Supprime les balises HTML comme <b> ou </b>"""
    cleanr = re.compile('<.*?>')
    return re.sub(cleanr, '', raw_html)

def extract_lesson_text(lecon):
    """Extrait tout le texte d'une leçon en le formatant bien"""
    lines = []
    lines.append(f"Titre de la leçon : {lecon.get('titre', '')}")
    
    for bloc in lecon.get('blocs', []):
        if bloc['type'] == 'texte':
            lines.append(clean_html(bloc['valeur']))
        elif bloc['type'] == 'liste':
            for item in bloc['items']:
                lines.append(f"- {clean_html(item)}")
    
    return "\n".join(lines)

def main():
    print(f"Chargement de {JSON_FILE}...")
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    lecons = data.get("lecons", [])
    print(f"{len(lecons)} leçons trouvées. Début de la génération...\n")
    
    for i, lecon in enumerate(lecons, 1):
        # 1. Préparer le texte
        texte = extract_lesson_text(lecon)
        
        # Nom de fichier propre (on garde juste les 30 premiers caractères du titre)
        safe_title = re.sub(r'[^a-zA-Z0-9_\- ]', '', lecon.get('titre', ''))[:30].strip()
        safe_title = safe_title.replace(' ', '_')
        filename = f"Lecon_{i}_{safe_title}.mp3"
        filepath = os.path.join(OUTPUT_DIR, filename)
        
        print(f"[{i}/{len(lecons)}] Génération de {filename}...")
        
        # 2. Envoyer à l'API locale
        try:
            response = requests.post(API_URL, data={"text": texte, "voice": VOICE})
            if response.status_code == 200:
                res_data = response.json()
                audio_b64 = res_data.get("audio")
                
                # 3. Sauvegarder le fichier MP3
                with open(filepath, "wb") as audio_file:
                    audio_file.write(base64.b64decode(audio_b64))
                print(f"  -> Sauvegardé avec succès : {filepath}")
            else:
                print(f"  -> ERREUR API : {response.text}")
        except Exception as e:
            print(f"  -> ERREUR DE CONNEXION : {e}")
            print("  (Avez-vous bien lancé 'python server.py' dans un autre terminal ?)")

if __name__ == "__main__":
    main()
