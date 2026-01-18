import openai
import json
import os
from typing import List

# Load env from sibling directory if not found locally (similar to s3_client)
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'auth', '.env')
load_dotenv(env_path)

# You can also set OPENAI_API_KEY in backend/api/.env or export it
api_key = os.getenv("OPENAI_API_KEY")
client = openai.OpenAI(api_key=api_key)

def generate_questions(system_prompt: str, existing_questions: List[str] = [], count: int = 10) -> List[str]:
    """
    Generates unique questions based on the system_prompt.
    Tries to avoid questions in `existing_questions` (though context window might limit this).
    """
    
    prompt = f"""
    Generate {count} unique, engaging, and thoughtful items for the game.
    
    Context/Rules: {system_prompt}
    
    The output must be a valid JSON array. 
    It can be an array of strings OR an array of JSON objects, depending on the rules above.
    Do not output anything else.
    """

    # If we have a lot of existing questions, we might want to mention them to avoid duplicates, 
    # but for now let's rely on the temperature and variations.
    if existing_questions:
        # Taking a random sample of existing questions to tell the LLM what NOT to generate might help
        # but keep it brief to save tokens.
        pass

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo", # Or gpt-4o if available/preferred
            messages=[
                {"role": "system", "content": "You are a helpful relationship coach assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
        )
        
        content = response.choices[0].message.content
        # Clean up code blocks if present
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "")
        
        questions = json.loads(content)
        return questions
        
    except Exception as e:
        print(f"Error generating questions: {e}")
        return []
