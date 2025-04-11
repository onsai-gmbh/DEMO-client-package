import os
from dotenv import load_dotenv
import boto3
import json
from azure.ai.inference import ChatCompletionsClient
from azure.core.credentials import AzureKeyCredential
from rapidfuzz import process, fuzz
from src.helpers import get_text
import re

load_dotenv()

# Initialize the Azure LLM client for chat completions
azure_client = ChatCompletionsClient(
    endpoint=os.getenv("AZURE_LLM_URL"),
    credential=AzureKeyCredential(os.getenv("AZURE_LLM_KEY"))
)


prompt_de_location = """
    ## Analysiere den folgenden Benutzereingabentext {user_query} und bestimme den Standort aus der Liste der Standorte: {locations}

    ## Gib den erkannten Standort im folgenden JSON-Format zurück:
    json
        "location": "Name des erkannten Standorts",
        "location_confirmed": true,
        "message": null oder "Welchen Standort meinst du? Wir haben folgende Standorte zur Auswahl: {locations}. Bitte nenne mir den Namen des Standorts."

    ### Besondere Regeln:
    - Die Standorte in Benutzereingabetext können sowohl in Deutsch als auch in Englisch geschrieben sein, und der Benutzereingabetext kann falsche Bezeichnungen, Rechtschreibfehler usw. enthalten.
    - Die Standortnamen in der Liste der Standorte sind korrekt. 
    - Der User kann auch "der erste Standort" oder "der zweite Standort" sagen oder Ähnliches, um den Standort zu nennen. In diesem Fall beziehen sich "der erste Standort" und "der zweite Standort" auf die Standortposition des Standorts in der Liste der Standorte.
    """


prompt_en_location = """
    ## Analyze the following user input text {user_query} and determine the location from the list of locations: {locations}

    ## Return the recognized location in the following JSON format:
    json
        "location": "Name of the recognized location",
        "location_confirmed": true,
        "message": null or "Which location do you mean? We have the following locations to choose from: {locations}. Please tell me the name of the location."

    ### Special rules:
    - The locations in user input text are the german locations and can be written in both German and English. 
    - The user input text can contain incorrect names, spelling errors, etc. but the location names in the list are correct.
    - The user can also say "the first location" or "the second location" or similar to name the location. In this case, "the first location" and "the second location" refer to the location position of the location in the list of locations.
    - You need to determine the location the user means based on the available locations from the list of locations by the way the user input sounds. Example: Dusseldorf Appartments an der KÖ can be misspelled as Dusseldorf Apartments under KÖ or something similar. Or München Laim can be misspelled as Munckhen Lime or something similar.
    """
    

KNOWN_LOCATIONS = {
       "Altdorf": "Altdorf",
       "Landshut": "Landshut",
       "Unterhaching": "Unterhaching",
    }

def get_location(user_query, language, city=None):

    history = []

    # Preprocess the user query to replace English city names with German city names
    user_query = preprocess_user_query(user_query)


    SCORE_THRESHOLD = 90

    DISPLAY_NAMES = list(KNOWN_LOCATIONS.keys())
    match, score, _ = process.extractOne(
        user_query, 
        DISPLAY_NAMES, 
        scorer=fuzz.WRatio
    )
    if score >= SCORE_THRESHOLD:
        confirmed_location = KNOWN_LOCATIONS[match]
        print("confirmed_location")
        print(confirmed_location)
        return {
            "location": confirmed_location,
            "location_confirmed": True,
            "message": None
        }
    
    prompt = prompt_de_location if language == "de-DE" else prompt_en_location
    # Add the system prompt to the history
    history.append({"role": "system", "content": prompt.format(user_query=user_query, locations=KNOWN_LOCATIONS.values())})
    history.append({"role": "user", "content": user_query.strip()})

    try:
        response = azure_client.complete(
            messages=history,
            response_format="json_object",
            temperature=0, 
            max_tokens=4000,
        )
        # response = groq_client.chat.completions.create(
        #     messages=history,
        #     model="llama-3.3-70b-versatile",  # Modell 
        #     response_format={"type": "json_object"}
        # )

        assistant_response = response.choices[0].message.content.strip()

        print("Assistant Response:", assistant_response)
        location_data = json.loads(assistant_response)
    
        if not isinstance(location_data, dict):
            raise ValueError("Die Antwort ist kein gültiges JSON-Objekt.")
        
        # If location is confirmed, standardize it
        if location_data.get("location_confirmed"):
            standardized_location = standardize_location(location_data.get("location", ""))
            if standardized_location:
                location_data["location"] = standardized_location
            else:
                location_data["location_confirmed"] = False
                location_data["message"] = get_text("no_property_found", language=language)
                location_data = None
        
        return location_data

    except json.JSONDecodeError as json_err:
        print(f"Ungültiges JSON-Format: {json_err}")
        
    except Exception as e:
        print(f"Anfragefehler: {e}")


def standardize_location(location):
    """
    Standardize the location name using fuzzy matching against KNOWN_LOCATIONS.
    
    Args:
        location (str): The location string to standardize.
        threshold (int): The minimum score for a match to be considered valid.
    
    Returns:
        str: The standardized location name or None if no match is found.
    """

    match, score, _ = process.extractOne(
        location, 
        list(KNOWN_LOCATIONS.keys()), 
        scorer=fuzz.WRatio
    )

    if score >= 95:
        print("match known locations")
        print(KNOWN_LOCATIONS[match])
        return KNOWN_LOCATIONS[match]
    
    # No match found
    return None

def preprocess_user_query(user_input):
    """
    Preprocess the user input by replacing English city names with their German counterparts.

    Args:
        user_input (str): The raw user input.

    Returns:
        str: The preprocessed user input with standardized city names.
    """
    if not user_input:
        return ""
    
    for alias, standard_name in KNOWN_LOCATIONS.items():
        # Use regex to match the alias in a case-insensitive manner
        # and replace it with the standard name
        # This allows for partial matches and ignores case
        # Use re.escape to escape any special characters in the alias
        # and standard_name to avoid regex errors
        pattern = re.compile(re.escape(alias), re.IGNORECASE)
        user_input = pattern.sub(standard_name, user_input)
    
    return user_input