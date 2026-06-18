# config.py

SITE_CATEGORIES_CONFIG = {
    'redes_sociais': {
        'label': 'Redes Sociais',
        'icon': 'users',
        'domains': [
            'facebook.com', 'instagram.com', 'twitter.com', 'x.com', 'tiktok.com',
            'linkedin.com', 'pinterest.com', 'snapchat.com', 'reddit.com', 'vk.com'
        ]
    },
    'jogos_populares': {
        'label': 'Jogos Populares',
        'icon': 'gamepad',
        'domains': [
            'roblox.com', 'minecraft.net', 'fortnite.com', 'steamcommunity.com',
            'leagueoflegends.com', 'valorant.com', 'twitch.tv'
        ]
    },
    'chatbots_ia': {
        'label': 'Chatbots de IA',
        'icon': 'cpu',
        'domains': [
            "openai.com", "chat.openai.com", "bard.google.com", "gemini.google.com",
            "perplexity.ai", "claude.ai", "copilot.microsoft.com", "bing.com",
            "you.com", "phind.com", "huggingface.co", "poe.com", "character.ai",
            "writesonic.com", "jasper.ai", "rytr.me", "copy.ai", "midjourney.com",
            "stable-diffusion-web.com", "dall-e.com", "chatgpt.com", "coze.com",
            "pi.ai", "elicit.org", "semantic-scholar.org", "scispace.com",
            "researchrabbit.ai", "connectedpapers.com", "consensus.app", "genei.io",
            "trinka.ai", "grammarly.com", "quillbot.com", "wordtune.com", "deepL.com",
            "smodin.me", "writesonic.com", "rytr.me", "copy.ai", "anyword.com",
            "surferseo.com", "frase.io", "closerscopy.com", "peppertype.ai", "longshot.ai"
        ]
    },
    'noticias_falsas': {
        'label': 'Sites de Notícias Falsas',
        'icon': 'alert-triangle',
        'domains': [] # This will be populated dynamically from a file in app.py
    }
}

# Lista de nomes de processos de aplicativos de IA a serem encerrados
AI_APPLICATION_PROCESSES = [
    "chatgpt-desktop",
    "ollama",
    "lmstudio",
    "stable-diffusion-ui",
    "invokeai",
    "diffusionbee",
    "fooocus",
    "comfyui",
    "automatic1111",
    "webui-user",
    "text-generation-webui",
    "gpt4all",
    "privategpt",
    "jan",
    "open-webui",
    "lobe-chat",
    "vscodium", # VS Codium (se extensões de IA forem uma preocupação)
    "code",     # VS Code (se extensões de IA forem uma preocupação)
    "jetbrains-idea", # JetBrains IDEs (se extensões de IA forem uma preocupação)
    "pycharm",
    "webstorm",
    "clion",
    "rider",
    "datagrip",
    "goland",
    "phpstorm",
    "rubymine",
    "rustrover",
    "fleet",
    "cursor",   # IDE focado em IA
    "github-copilot",
    "tabnine",
    "codeium",
    "aider",
    "smol-developer",
    "autogen",
    "crewai",
    "langchain",
    "llama_cpp",
    "whisper_cpp",
    "sd_webui",
    "automatic",
    "invokeai",
    "diffusers",
    "huggingface_hub",
    "transformers",
    "bitsandbytes",
    "trl",
    "peft",
    "accelerate",
    "deepspeed",
    "vllm",
    "exllama",
    "text-generation-launcher",
    "oobabooga",
    "gpt-engineer",
    "openinterpreter",
    "agent-gpt",
    "babyagi",
    "autogpt",
    "superagent",
    "cognosys",
    "godmode",
    "miniagi",
    "camel-ai",
    "metagpt",
    "gpt-pilot",
    "smol-ai",
    "swe-agent",
    "devin",
    "cognition-labs",
    "midjourney-bot",
    "stable-diffusion-bot",
    "dalle-bot",
    "krea-ai",
    "runwayml",
    "pika-labs",
    "elevenlabs",
    "whisper",
    "bark",
    "tortoise-tts",
    "xtts",
    "coqui-tts",
    "rvc",
    "so-vits-svc",
    "voice-changer",
    "deepfake",
    "facefusion",
    "roop",
    "insightface",
    "deepfacelab",
    "faceswap",
    "deepmotion",
    "plask",
    "cascadeur",
    "move.ai",
    "wonderdynamics",
    "synthesia",
    "heygen",
    "d-id",
    "runway-ml",
    "pictory",
    "invideo",
    "flexclip",
    "kapwing",
    "descript",
    "adobe-podcast",
    "audacity",
    "davinci-resolve",
    "premiere-pro",
    "photoshop",
    "gimp",
    "krita",
    "blender",
    "autodesk-maya",
    "zbrush",
    "substance-painter",
]

# Lista de caminhos comuns para binários de aplicativos de IA a serem desabilitados
# Isso é mais agressivo e pode exigir conhecimento dos caminhos de instalação.
# Use com cautela.
AI_APPLICATION_BINARIES = [
    "/usr/bin/ollama",
    "/usr/local/bin/ollama",
    "/opt/ollama/ollama",
    "/snap/bin/chatgpt-desktop",
    "/snap/bin/ollama",
    # Adicione outros caminhos de binários conhecidos aqui
]