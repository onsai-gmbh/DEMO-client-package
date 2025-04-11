from datetime import datetime, time, date
import json
import pytz
import re
from datetime import datetime
from decimal import Decimal
import random
import re
import requests
from dotenv import load_dotenv


load_dotenv()


# Laden der JSON-Daten beim Start des Programms
def load_texts(file_path='src/texts.json'):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"Die Datei {file_path} wurde nicht gefunden.")
        return {}
    except json.JSONDecodeError as e:
        print(f"Fehler beim Parsen der JSON-Datei: {e}")
        return {}

# Globale Variable zur Speicherung der Textdaten
TEXTS_DATA = load_texts()

def get_text(scenario, language, fallback_language='de-DE'):
    """
    Get a text based on scenario and language.
    If the desired language is not available, it falls back to the fallback language.

    :param scenario: The key for the desired scenario.
    :param language: The language identifier (e.g., 'de-DE', 'en-US').
    :param fallback_language: The language identifier for the fallback.
    :return: A text string or an error message


    """
    try:
        texts = TEXTS_DATA[scenario][language]
        print(f"Text für Szenario '{scenario}' und Sprache '{language}' gefunden.")
    except KeyError:
        # Fallback auf alternative Sprache
        try:
            texts = TEXTS_DATA[scenario][fallback_language]
            print(f"Sprache '{language}' nicht gefunden für Szenario '{scenario}'. Fallback auf '{fallback_language}'.")
        except KeyError:
            return f"Text für Szenario '{scenario}' und Sprache '{language}' nicht gefunden."

    if isinstance(texts, list):
        return random.choice(texts)
    elif isinstance(texts, str):
        return texts
    else:
        return f"Unerwartetes Datenformat für Szenario '{scenario}' und Sprache '{language}'."

def get_text_with_variables(scenario, language, fallback_language='en-US', **kwargs):
    """
    Get a text based on scenario and language with dynamic variables.
    If the desired language is not available, it falls back to the fallback language.

    :param scenario: The key for the desired scenario.
    :param language: The language identifier (e.g., 'de-DE', 'en-US').
    :param fallback_language: The language identifier for the fallback.
    :param kwargs: Dynamic variables to be inserted into the text.
    :return: A formatted text string or an error message

    """
    text = get_text(scenario, language, fallback_language)
    if not isinstance(text, str):
        # Fehlernachricht wurde zurückgegeben
        return text
    try:
        return text.format(**kwargs)
    except KeyError as e:
        missing_key = e.args[0]
        default = "Mitarbeiter" if language.startswith('de') else "Employee"
        print(f"Platzhalter '{missing_key}' nicht gefunden. Verwende Standardwert '{default}'.")
        return text.replace(f"{{{missing_key}}}", default)
    except Exception as e:
        print(f"Fehler beim Formatieren des Textes: {e}")
        return ""

def time_checker():
    """Check if the service desk is open or closed."""
    # Define office hours
    office_start_hour = time(0, 0)
    office_end_hour = time(23, 59)
    office_days = {0, 1, 2, 3, 4, 5, 6}  # Monday to Friday, where Monday is 0 and Sunday is 6

    # Get current time and weekday in the Germany timezone
    time_zone = pytz.timezone('Europe/Berlin')
    now = datetime.now(time_zone)
    current_hour = now.time()
    current_weekday = now.weekday()

    # Check if current time is within office hours
    if current_weekday in office_days and office_start_hour <= current_hour < office_end_hour:
        return True
    else:
        return False
    
def no_property_info(results_with_confidence):
    """Check if the vector search results are hotel-specific."""
    unique = False
    for index, item in enumerate(results_with_confidence):
        if item[2] == True:
            results_with_confidence.pop(index)
            unique = True

    return results_with_confidence, unique

def remove_emojis(text):
    if text is None:
        return text
    else:
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # Emoticons
            "\U0001F300-\U0001F5FF"  # Symbols & Pictographs
            "\U0001F680-\U0001F6FF"  # Transport & Map Symbols
            "\U0001F1E0-\U0001F1FF"  # Flags
            "\U00002700-\U000027BF"  # Dingbats
            "\U0001F900-\U0001F9FF"  # Supplemental Symbols & Pictographs
            "\U00002600-\U000026FF"  # Miscellaneous Symbols
            "\U00002B00-\U00002BFF"  # Miscellaneous Symbols and Arrows
            "\U0001FA70-\U0001FAFF"  # Symbols & Pictographs Extended-A
            "\U0001F700-\U0001F77F"  # Alchemical Symbols
            "\U00002300-\U000023FF"  # Miscellaneous Technical
            "]+",
            flags=re.UNICODE
        )
        return emoji_pattern.sub(r'', text)


def convert_decimals_to_floats(obj):
    """
    Recursively convert all Decimal values in a JSON-like dictionary to floats.
    
    Args:
    obj (any): The JSON-like dictionary or list.
    
    Returns:
    any: The JSON-like dictionary or list with Decimals converted to floats.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            obj[key] = convert_decimals_to_floats(value)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            obj[index] = convert_decimals_to_floats(value)
    elif isinstance(obj, Decimal):
        return float(obj)
    return obj

def convert_floats_to_decimals(obj):
    """
    Recursively convert all float values in a JSON-like dictionary to Decimals.
    
    Args:
    obj (any): The JSON-like dictionary or list.
    
    Returns:
    any: The JSON-like dictionary or list with floats converted to Decimals.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            obj[key] = convert_floats_to_decimals(value)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            obj[index] = convert_floats_to_decimals(value)
    elif isinstance(obj, float):
        return Decimal(str(obj))
    return obj


def send_teams_message(webhook_url, title, message, details=None, is_error=False):
    """
    Send a message to a Microsoft Teams channel via webhook using Adaptive Cards.

    :param webhook_url: The Incoming Webhook URL from Teams
    :param title: The title of the message
    :param message: The main message content
    :param details: (Optional) A dictionary containing additional details
    :param is_error: (Optional) Boolean indicating if the message is an error
    """
    headers = {
        "Content-Type": "application/json"
    }

    # Define the Adaptive Card template
    adaptive_card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": title,
                "weight": "Bolder",
                "size": "Large",
                "color": "Attention" if is_error else "Accent"
            },
            {
                "type": "TextBlock",
                "text": message,
                "wrap": True
            }
        ],
        "actions": []  # Initialize with an empty list; will conditionally add actions
    }

    # If there are additional details, add them as a FactSet
    if details:
        # Convert all values to strings to ensure compatibility
        facts = [{"title": f"{key}:", "value": str(value)} for key, value in details.items()]
        adaptive_card["body"].append({
            "type": "FactSet",
            "facts": facts
        })

    # No buttons are added regardless of is_error

    payload = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": adaptive_card
            }
        ]
    }

    try:
        response = requests.post(webhook_url, headers=headers, data=json.dumps(payload))
        if response.status_code == 200:
            print("Message posted successfully to Teams.")
        else:
            print(f"Failed to send message to Teams. Status code: {response.status_code}, Response: {response.text}")
    except Exception as e:
        print(f"Exception occurred while sending message to Teams: {e}")

def correct_data_year(arrival_date:str, departure_date:str):
    """
    Change the year of the dates to +1 year if the arrival/departure date lies before the current date.

    Args:
    arrival_date (str): The arrival date in the format "YYYY-MM-DD".
    departure_date (str): The departure date in the format "YYYY-MM-DD".

    """
    # Get the current date
    current_date = datetime.now().strftime("%Y-%m-%d")
    # Check if the arrival date is before the current date
    if arrival_date < current_date and departure_date <= current_date:
        print("Arrival and departure date lies before the current date, INCREMENTING", str(arrival_date), str(departure_date))
        arrival_date = f"{int(arrival_date[:4])+1}{arrival_date[4:]}"
        departure_date = f"{int(departure_date[:4])+1}{departure_date[4:]}"
    elif arrival_date < current_date:
        print("Arrival date lies before the current date, INCREMENTING", str(arrival_date))
        arrival_date = f"{int(arrival_date[:4])+1}{arrival_date[4:]}" # Increment the year by 1
        # departure_date = f"{int(departure_date[:4])+1}{departure_date[4:]}"
    elif departure_date <= current_date:
        print("Departure date lies before the current date, INCREMENTING", str(departure_date))
        departure_date = f"{int(departure_date[:4])+1}{departure_date[4:]}"
    return arrival_date, departure_date

def get_current_date_with_weekday(language="de-DE"):
    """
    Get the current date and weekday in the specified language.
    
    Parameters:
    - language (str): Language code for the weekday.

    Returns:
    - str: Current date and weekday in the format "YYYY-MM-DD, Weekday".

    """ 
    # Get current time and weekday in the Germany timezone
    germany_zone = pytz.timezone('Europe/Berlin')
    current_date_str = datetime.now(germany_zone).strftime("%Y-%m-%d")
    now = datetime.now(germany_zone)
    current_weekday = now.weekday()
    if language == "en-US":
        weekday = now.strftime("%A")
    else:
        # German weekday
        weekdays = {
            0: "Montag", 1: "Dienstag", 2: "Mittwoch", 3: "Donnerstag",
            4: "Freitag", 5: "Samstag", 6: "Sonntag"
        }
        weekday = weekdays[current_weekday]
    return f"{current_date_str}, {weekday}"

def process_dates_pronunciation(arrival, departure, language="de-DE", current_date=None):
    """
    Processes arrival and departure dates based on specific rules:
    
    1. If both dates are in the same year and it's not the current year:
       - Remove the year from the arrival date.
       - Keep the year on the departure date.
       
    2. If both dates are in the same year and it is the current year:
       - Remove the year from both dates.
       
    3. If both dates are in the same month (regardless of the year):
       - Remove the month from the arrival date.
       
    4. If the year of arrival and the year of departure are different:
       - Keep both years.
       
    Parameters:
    - arrival (str): Arrival date in 'YYYY-MM-DD' format.
    - departure (str): Departure date in 'YYYY-MM-DD' format.
    - language (str, optional): Language code ('en-US' for English, others default to German). Defaults to 'de-DE'.
    - current_date (str, optional): Current date in 'YYYY-MM-DD' format.
      If not provided, the current system date is used.
    
    Returns:
    - tuple: Formatted (arrival_str, departure_str)
    """
    # Define month names for supported languages
    month_names = {
        "en-US": {
            1: "January", 2: "February", 3: "March", 4: "April",
            5: "May", 6: "June", 7: "July", 8: "August",
            9: "September", 10: "October", 11: "November", 12: "December"
        },
        "de-DE": {
            1: "Januar", 2: "Februar", 3: "März", 4: "April",
            5: "Mai", 6: "Juni", 7: "Juli", 8: "August",
            9: "September", 10: "Oktober", 11: "November", 12: "Dezember"
        }
    }
    
    # Determine the language to use for month names
    selected_language = language if language in month_names else "de-DE"
    
    # If current_date is not provided, use today's date in Europe/Berlin timezone
    if current_date is None:
        germany_zone = pytz.timezone('Europe/Berlin')
        current_date_obj = datetime.now(germany_zone)
    else:
        try:
            current_date_obj = datetime.strptime(current_date, "%Y-%m-%d")
        except ValueError as e:
            print(f"Error parsing current_date: {e}")
            return arrival, departure
    
    # Parse arrival and departure dates
    try:
        arrival_date = datetime.strptime(arrival, "%Y-%m-%d")
        departure_date = datetime.strptime(departure, "%Y-%m-%d")
    except ValueError as e:
        print(f"Error parsing dates: {e}")
        return arrival, departure
    
    # Extract year and month for comparison
    arrival_year = arrival_date.year
    departure_year = departure_date.year
    current_year = current_date_obj.year
    
    arrival_month = arrival_date.month
    departure_month = departure_date.month
    
    # Initialize formatted strings with default full date
    if selected_language == "en-US":
        arrival_str = f"{month_names[selected_language][arrival_month]} {arrival_date.day} {arrival_year}"
        departure_str = f"{month_names[selected_language][departure_month]} {departure_date.day} {departure_year}"
    else:
        arrival_str = f"{arrival_date.day}. {month_names[selected_language][arrival_month]} {arrival_year}"
        departure_str = f"{departure_date.day}. {month_names[selected_language][departure_month]} {departure_year}"
    
    # Determine if both dates are in the same year
    same_year = arrival_year == departure_year
    
    # Determine if both dates are in the same month
    same_month = arrival_month == departure_month
    
    if same_year:
        print("same year, diff months")
        if arrival_year != current_year:
            # Rule 1: Same year, not current year
            print("Not current year")
            if selected_language == "en-US":
                arrival_str = f"{month_names[selected_language][arrival_month]} {arrival_date.day}" # e.g., January 01
            else:
                if same_month:
                    arrival_str = f"{arrival_date.day}." # e.g., 01.

                else: # not same month
                    arrival_str = f"{arrival_date.day}. {month_names[selected_language][arrival_month]} " # e.g., 01. Januar
        else:
            # Rule 2: Same year, current year
            if selected_language == "en-US":
                arrival_str = f"{month_names[selected_language][arrival_month]} {arrival_date.day}"
                departure_str = f"{month_names[selected_language][departure_month]} {departure_date.day}"
            else:
                if same_month:
                    arrival_str = f"{arrival_date.day}."
                    departure_str = f"{departure_date.day}. {month_names[selected_language][departure_month]}"
                else: # not same month
                    arrival_str = f"{month_names[selected_language][arrival_month]} {arrival_date.day}"
                    departure_str = f"{month_names[selected_language][departure_month]} {departure_date.day}"
    else:
        # Rule 4: Different years
        if selected_language == "en-US":
            arrival_str = f"{month_names[selected_language][arrival_month]} {arrival_date.day} {arrival_year}"
            departure_str = f"{month_names[selected_language][departure_month]} {departure_date.day} {departure_year}"
        else:
            arrival_str = f"{arrival_date.day}. {month_names[selected_language][arrival_month]} {arrival_year}"
            departure_str = f"{departure_date.day}. {month_names[selected_language][departure_month]} {departure_year}"
    
    return arrival_str, departure_str


def check_call_redirect_condition(results_with_confidence, language, user_query):
    # Define the keywords based on language
    # if language == "de-DE":
    #     # German keywords
    #     # longshot: add emergency category to the metadata
    #     hotline_keywords = ["telefonzentrale", "notfall", "feuer", "polizei", "arzt", "todesfall", "ordnungsamt", "schlägerei", "krankenwagen"]
    # else:
    #     # English keywords
    #     hotline_keywords = ["switchboard", "emergency", "fire", "police", "ambulance", "death", "public order office", "fight"]
    
    # # Check if there is an embedding with a call transer keyword and confidence score > 0.9
    # highest_confidence_hotline = any(
    #     any(keyword in result[0].lower() or keyword in user_query.lower() for keyword in hotline_keywords) and float(result[-1]) > 0.9
    #     for result in results_with_confidence
    # )

    # # Redirect logic
    # if highest_confidence_hotline:
    #     print("Transfer the call to the hotline")
    #     return ("Telefonzentrale", True) if language == "de-DE" else ("Switchboard", True)
    
    print("No redirect conditions met.")
    return False

def enhance_pronunciation(text, language):
    current_year = datetime.now().year

    text = re.sub(r'metropolraduhr', 'metropol raduhr ', text, flags=re.IGNORECASE)
    text = re.sub(r'sleepinroomz', 'sleep in roomz ', text, flags=re.IGNORECASE)

    # Replace ampersand symbol & with a spoken word
    and_word = "and" if language == "en-US" else "und"
    text = re.sub(r'\s*&\s*', f' {and_word} ', text)

    digit_sequence_pattern = r'\b(\d{5,})\b' # Matches 4 or more consecutive digits
    # Replace digit sequences with SSML
    digit_sequences = re.findall(digit_sequence_pattern, text)
    for digit_sequence in digit_sequences:
        # Convert to SSML
        ssml_digit_sequence = f'<say-as interpret-as="digits">{digit_sequence}</say-as>'
        # Replace all occurrences of the digit sequence with SSML
        text = text.replace(digit_sequence, ssml_digit_sequence)

    # Date patterns to match different date formats
    date_patterns = [
        r'\b(\d{1,2}\.\d{1,2}\.\d{2,4})\b',       # Matches dd.mm.yyyy or dd.mm.yy
        r'\b(\d{1,2}-\d{1,2}-\d{2,4})\b',         # Matches dd-mm-yyyy or dd-mm-yy
        r'\b(\d{4}\.\d{1,2}\.\d{1,2})\b',         # Matches yyyy.mm.dd
        r'\b(\d{4}-\d{1,2}-\d{1,2})\b'            # Matches yyyy-mm-dd
    ]

    # Process dates in the text
    for pattern in date_patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            # Handle tuples from patterns with multiple groups
            if isinstance(match, tuple):
                date_str = " ".join(match)
            else:
                date_str = match

            # Parse other date formats
            for fmt in ('%d.%m.%Y', '%d.%m.%y', '%d-%m-%Y', '%d-%m-%y', '%Y.%m.%d', '%Y-%m-%d'):
                try:
                    date_obj = datetime.strptime(date_str, fmt)  # Parse the date string
                    
                    # Extract day, month, and year without leading zeros
                    day = date_obj.day
                    month = date_obj.month
                    year = date_obj.year
                    
                    # Generate SSML date format
                    if language == 'de-DE':
                        if year == current_year:
                            ssml_date = f'<say-as interpret-as="date" format="dm">{day}-{month}</say-as>'
                        else:
                            ssml_date = f'<say-as interpret-as="date" format="dmy">{day}-{month}-{year}</say-as>'
                    else:
                        if year == current_year:
                            ssml_date = f'<say-as interpret-as="date" format="dm">{day}-{month}</say-as>'
                        else:
                            ssml_date = f'<say-as interpret-as="date" format="dmy">{day}-{month}-{year}</say-as>'

                    # Replace only the first occurrence of the date
                    text = text.replace(date_str, ssml_date, 1)
                    break

                except ValueError:
                    continue  # Try the next format if parsing fails

    # Process time in hh:mm format
    time_pattern = r'\b(\d{1,2}:\d{2})\b'
    time_markers_pattern = r'\b(uhr|am|a\.m\.?|pm|p\.m\.?|A\.M\.?|P\.M\.?)\b'
    matches = re.findall(time_pattern, text)

    for time_str in matches:
        # Check for a nearby time marker
        time_with_marker_pattern = rf'{time_str}\s*({time_markers_pattern})?'
        match_with_marker = re.search(time_with_marker_pattern, text, re.IGNORECASE)
        if match_with_marker and match_with_marker.group(1):
            continue
        # Extract hours and minutes
        hours, minutes = map(int, time_str.split(':'))
        if language == 'de-DE':
            spoken_time = f"{hours}" if minutes == 0 else f"{hours} {minutes}"
        elif language == 'en-US':
            spoken_time = f"{hours}" if minutes == 0 else f"{hours} {minutes}"
        ssml_time = f'<say-as interpret-as="time">{spoken_time}</say-as>'
        text = re.sub(rf'\b{time_str}\b', ssml_time, text)

    # Process time expressions with specific context (avoid prices)
    time_patterns = [
        r'\b(\d{1,2}[:.]\d{2})\s?(am|pm|Uhr)\b',
    ]
    for pattern in time_patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        for time_str, marker in matches:
            try:
                if "am" in marker.lower() or "pm" in marker.lower():
                    time_obj = datetime.strptime(time_str.strip(), '%I.%M' if '.' in time_str else '%I:%M').time()
                    if 'pm' in marker.lower() and time_obj.hour < 12:
                        hour = time_obj.hour + 12
                    elif 'am' in marker.lower() and time_obj.hour == 12:
                        hour = 0
                    else:
                        hour = time_obj.hour
                    spoken_time = f"{hour % 12 or 12}:{time_obj.minute:02} {'PM' if hour >= 12 else 'AM'}"
                elif "Uhr" in marker:
                    time_obj = datetime.strptime(time_str.strip(), '%H.%M' if '.' in time_str else '%H:%M').time()
                    spoken_time = f"{time_obj.hour} Uhr {time_obj.minute}" if time_obj.minute else f"{time_obj.hour} Uhr"
                else:
                    time_obj = datetime.strptime(time_str.strip(), '%H.%M' if '.' in time_str else '%H:%M').time()
                    if language == 'de-DE':
                        spoken_time = f"{time_obj.hour} Uhr {time_obj.minute}" if time_obj.minute else f"{time_obj.hour} Uhr"
                    else:
                        spoken_time = time_obj.strftime("%I:%M %p").lstrip('0')
                        if spoken_time.endswith(":00"):
                            spoken_time = spoken_time.replace(":00", "")
                ssml_time = f'<say-as interpret-as="time">{spoken_time}</say-as>'
                text = text.replace(f"{time_str} {marker}".strip(), ssml_time)
            except ValueError:
                continue

    # Process email addresses
    email_pattern = r'([\w\.-]+)@([\w\.-]+\.\w+)'
    emails = re.findall(email_pattern, text)
    for username, domain_tld in emails:
        # Split domain and TLD
        if '.' in domain_tld:
            domain, tld = domain_tld.rsplit('.', 1)
        else:
            domain, tld = domain_tld, ''
        # Define spoken words for symbols
        dot_word = 'dot' if language == 'en-US' else 'Punkt'
        dash_word = 'dash' if language == 'en-US' else 'Minus'

        # Process the username: replace dots and hyphens
        username_processed = username.replace('.', f' {dot_word} ')
        username_processed = username_processed.replace('-', f' {dash_word} ')

        # Process the domain (before the TLD): replace dots and hyphens
        domain_processed = domain.replace('.', f' {dot_word} ')
        domain_processed = domain_processed.replace('-', f' {dash_word} ')

        # Process the TLD as individual characters
        ssml_tld = f'<say-as interpret-as="characters">{tld}</say-as>' if tld else ''

        # Reconstruct the email for pronunciation
        modified_email = f'{username_processed} @ {domain_processed}'
        if ssml_tld:
            modified_email += f' {dot_word} {ssml_tld}'

        # Replace the original email (exact match) with the modified version
        email_full = f'{username}@{domain_tld}'
        text = text.replace(email_full, modified_email)


    # PRONUNCIATION of GERMAN WORDS in ENGLISH and vice versa
    pronunciation_lang = None
    if language == 'en-US':
        # German words to be pronounced as German words in English
        words = [
            "tanke", "Blaubach", "Waidmarkt", "hallo", "Vringsveedel", "Barbarossaplatz", "Poststraße",
            "Messe Deutz", "Blocklemünd", "Pragfriedhof", "Rhein", "Stadium", "Neumarkt", "Severinstraße", 
            "Rewe", "Airbnb", 
            ]
        pronunciation_lang = 'de-DE'
    elif language == 'de-DE':
        # English words to be pronounced as English words in German
        words = ["Suites", "Late", "Early", "Flexible", "Bumbee", "Call a bike", "nextbike", "Do-not-disturb", 
                 "King-Size", "quality", "Dream", "KONCEPT", "koncept", "Hi", 'Hey']
        pronunciation_lang = 'en-US'

    # Wrap the entire text in a default language tag
    text = f'<lang xml:lang="{language}">{text}</lang>'

    if words:
        # Create a regex pattern for the desired words (case-insensitive)
        words_pattern = r'\b(' + '|'.join(map(re.escape, words)) + r')\b'
        def replace_with_lang(match):
            word = match.group(0)
            return f'</lang><lang xml:lang="{pronunciation_lang}">{word}</lang><lang xml:lang="{language}">'
        text = re.sub(words_pattern, replace_with_lang, text, flags=re.IGNORECASE)

    return text

def convert_to_international(number):
    # Remove any non-digit characters
    number = re.sub(r'\D', '', number)
    if number.startswith("0"):
        return "+49" + number[1:]
    else:
        return number
    
