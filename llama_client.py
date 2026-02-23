# llama_client.py (HOSTED - OpenRouter)

import os
import requests
from dotenv import load_dotenv

load_dotenv()  # load .env file

API_KEY = os.getenv("OPENROUTER_API_KEY")
API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "meta-llama/llama-3-8b-instruct"

if not API_KEY:
    raise ValueError("❌ OPENROUTER_API_KEY not found in .env")

def call_llama(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",   # REQUIRED by OpenRouter
        "X-Title": "final-project"             # REQUIRED by OpenRouter
    }

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You extract structured scientific facts from research papers. "
                    "Return ONLY valid JSON."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0
    }

    response = requests.post(API_URL, headers=headers, json=payload)

    if response.status_code != 200:
        print("❌ STATUS:", response.status_code)
        print("❌ RESPONSE:", response.text)

    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]
