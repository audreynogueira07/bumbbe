from google import genai
import os

# Defina sua API KEY diretamente aqui ou garanta que ela esteja nas variáveis de ambiente
API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyBm989hbQG_il8Bbd2ElPGL_2txTTp3-0E")

try:
    client = genai.Client(api_key=API_KEY)
    
    print("--- Modelos Disponíveis (SDK google-genai) ---")
    # Lista os modelos
    pager = client.models.list()
    
    found_flash = False
    for model in pager:
        # Filtra apenas modelos que geram conteúdo (chat)
        if "generateContent" in model.supported_actions:
            print(f"Nome: {model.name} | Display: {model.display_name}")
            if "flash" in model.name.lower():
                found_flash = True

    if not found_flash:
        print("\nALERTA: Nenhum modelo 'Flash' encontrado. Verifique sua API Key ou Região.")

except Exception as e:
    print(f"Erro ao listar modelos: {e}")