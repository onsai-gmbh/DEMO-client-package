from src.backend import generate_conversation
from src.default_prompt import get_ai_prompt_template
from src.server import LANGUAGE

print("Initializing conversation...")
print(get_ai_prompt_template(language=LANGUAGE))
history = None
while True:
    user_query = input("USER:")
    respone = generate_conversation(user_query, history=history, language=LANGUAGE)
    history = respone['history']
    print("BOT: " + respone['gpt_response'])
 
