import json
import re
from fastapi import FastAPI, Request
from datetime import datetime, timedelta, UTC, timezone
import time
from src.default_prompt import get_ai_prompt_template
from src.backend import generate_conversation
from src.helpers import enhance_pronunciation, remove_emojis, get_text, convert_to_international
import uuid
import boto3
import sentry_sdk
import yaml
from pathlib import Path

import os
from dotenv import load_dotenv

load_dotenv()

def load_config():
    config_path = Path("config.yaml")
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    # Replace environment variables
    # You might want to add more sophisticated environment variable handling
    if "${DYNAMO_DB_TABLE}" in config["database"]["table_name"]:
        config["database"]["table_name"] = os.getenv("DYNAMO_DB_TABLE")
    if "${LOCAL_DYNAMO_DB_URL}" in config["database"]["local"]["url"]:
        config["database"]["local"]["url"] = os.getenv("LOCAL_DYNAMO_DB_URL")
    
    return config

# Load configuration at startup
config = load_config()

# Then use it in your code like:
LANGUAGE = config["speech"]["default_language"]
VOICE_NAME = config["speech"]["default_voice"]

LOCAL_DYNAMO_DB_URL = config["database"]["local"]["url"]
DYNAMO_DB_TABLE = config["database"]["table_name"]
WHITE_LIST = config["call"]["whitelist"]

CALLER = None

app = FastAPI()


if LOCAL_DYNAMO_DB_URL:
    print("Using local DynamoDB ...")
    dynamodb = boto3.resource('dynamodb', endpoint_url=LOCAL_DYNAMO_DB_URL, region_name=config["database"]["local"]["region"])
else:
    print("Using remote DynamoDB ...")
    print(DYNAMO_DB_TABLE)
    dynamodb = boto3.resource('dynamodb', region_name=config["database"]["region"])

table = dynamodb.Table(DYNAMO_DB_TABLE)

@app.get("/onsei")
@app.post("/onsei")
@app.put("/onsei")
@app.delete("/onsei")
async def capture_request_test():
    print("Request received")
    return "Hello World!"

@app.get("/")
@app.post("/")
@app.put("/")
@app.delete("/")
async def capture_request(request: Request):
    print("Request received")
    request_json = await request.json()
    if LOCAL_DYNAMO_DB_URL:
        print(json.dumps(request_json, indent=4, sort_keys=True))
    else:
        print(request_json)

    # Response
    activitiesURL = config["api"]["conversation_paths"]["activities"] + request_json['conversation']
    refreshURL = config["api"]["conversation_paths"]["refresh"] + request_json['conversation']
    disconnectURL = config["api"]["conversation_paths"]["disconnect"] + request_json['conversation']

    response = {
        "activitiesURL": activitiesURL,
        "refreshURL": refreshURL,
        "disconnectURL": disconnectURL,
        "expiresSeconds": config["call"]["timeout"]["session_expiry_seconds"]
    }

    return response

@app.get("/conversation/activities/{conversation_id}")
@app.post("/conversation/activities/{conversation_id}")
@app.put("/conversation/activities/{conversation_id}")
@app.delete("/conversation/activities/{conversation_id}")
async def capture_activitie(conversation_id: str, request: Request):
    global LANGUAGE
    global VOICE_NAME
    global CALLER
    
    print("Activitie received")
    start_time = time.time()
    request_json = await request.json()
    current_time = datetime.now(timezone.utc)
    timestamp = current_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    if  LOCAL_DYNAMO_DB_URL:
        print(json.dumps(request_json, indent=4, sort_keys=True))
    else:
        print(request_json)

    try:
        caller = request_json['activities'][0]['parameters']['caller']
        CALLER = caller
    except (IndexError, KeyError):
        caller = None

    if not LOCAL_DYNAMO_DB_URL:
        try:
            # Calculate the timestamp for 15 minutes ago in ISO 8601 format
            current_time = datetime.utcnow()
            five_minutes_ago_iso = (current_time - timedelta(
                minutes=config["call"]["repeat_caller"]["window_minutes"]
            )).isoformat(timespec='seconds') + 'Z'

            response_gsi = table.query(
                IndexName=config["database"]["indexes"]["caller_timestamp"],
                KeyConditionExpression='#caller = :caller_value AND #ts > :ts',
                ExpressionAttributeNames={
                    '#caller': 'caller',      # The caller attribute name
                    '#ts': 'timestamp'        # The timestamp attribute name
                },
                ExpressionAttributeValues={
                    ':caller_value': caller,  # Replace with the caller value you are querying for
                    ':ts': five_minutes_ago_iso  # Timestamp for 5 minutes ago
                }
            )

            print("Response from the GSI: ")
            print(response_gsi)
            items = response_gsi['Items']
            
            print("Number of items in GSI in the last 5 minutes:")
            print(len(items))

            num_calls_in_last_5_minutes = len(items)
    

            if num_calls_in_last_5_minutes >= config["call"]["repeat_caller"]["max_calls"]:
                print("Transfer the call")
                activities = list()
                activities.append({
                    "id": str(uuid.uuid4()),
                    "timestamp": timestamp,
                    "language": config["speech"]["default_language"],
                    "type": "message",
                    "text": config["call"]["repeat_caller"]["transfer_message"],
                    "activityParams": {
                        "language": config["speech"]["default_language"],
                        "voiceName": config["speech"]["default_voice"]
                    }
                })
                activities.append({
                    "id": str(uuid.uuid4()),
                    "timestamp": timestamp,
                    "type": "event",
                    "name": "transfer",
                    "activityParams": {
                        "transferTarget": config["call"]["transfer"]["target"]
                    }
                })
                print(activities)
                system_response = {"activities": activities}
                return system_response
            
        except Exception as e:
            print("\n\nError in the GSI query")
            print(e)
            pass

    ## End of Call Redirection Part###

    item = table.get_item(Key={'id': conversation_id}).get("Item")
    print("\n\n\nItem")
    print(item)
    if item is None:
        print("New conversation")
        booking_data = {}
        # Set language at the beginning of the conversation to German
        LANGUAGE = config["speech"]["default_language"]
        VOICE_NAME = config["speech"]["default_voice"]
        try:
            parts = request_json['activities'][0]['parameters']['callerDisplayName'].split(":", 1)
            get_id = parts[0] if not parts[0].isdigit() else parts[1]
        except (IndexError, KeyError):
            get_id = None

        print("property_name ID: " + str(get_id))
    
        try:
            caller = request_json['activities'][0]['parameters']['caller']
        except (IndexError, KeyError) as e:
            caller = None

        print("Caller: " + str(caller))
        if caller in WHITE_LIST:
            white_list_transfer = {
                "id": str(uuid.uuid4()),
                "timestamp": timestamp,
                "type": "event",
                "name": "transfer",
                "activityParams": {
                    "transferTarget": config["call"]["transfer"]["target"]
                }
            }
            print(white_list_transfer)
            return json.dumps({"activities": [white_list_transfer]})

        # Get the hotel properties from the YAML configuration file
        properties = config.get("hotel_info", {}).get("properties", {})
        # Get the hotel name based on the get_id value
        property_name = next((hotel_name for hotel_name, id_value in properties.items() if id_value == get_id and get_id != None), None)
        property_name = "B_smart_Motel_Schaan" 
        table.put_item(Item={'id': conversation_id, 'messages': config["response"]["init_message"], "system_history": [], "timestamp": timestamp, "property_name": property_name, "caller": caller, "booking_data": booking_data, "voice_name": VOICE_NAME})
        bot_response = get_ai_prompt_template() # get the German AI prompt

    elif item.get('messages') == config["response"]["init_message"]:
        print(request_json)
        user_query = request_json['activities'][0]['text']
        property_name = item.get('property_name')
        location_data = item.get('location_data', {})
        booking_data = item.get('booking_data')
        if booking_data is None:
            booking_data = {}

        # Get the language from the user's input
        if (len(user_query.split(" ")) > 1):
            print("USER QUERY> 2 : " + user_query)
            LANGUAGE = str(request_json['activities'][0]['parameters']['recognitionOutput']['PrimaryLanguage']['Language'])
            print("Language: " + LANGUAGE)
        VOICE_NAME = config["speech"]["default_voice"]
        print("USER: " + user_query)


        if "guest_phone_number" not in booking_data:
                booking_data["guest_phone_number"] = (
                    convert_to_international(CALLER) if CALLER and CALLER.isdigit() else None
                )

        backend_respone = await generate_conversation(user_query, property_name=property_name, language=LANGUAGE, location_data=location_data, booking_data=booking_data)
        print(backend_respone)

        table.update_item(
            Key={'id': conversation_id}, 
            UpdateExpression="set messages=:m, property_name=:p, location_data=:l, offers=:o, booking_data=:b, voice_name=:v",
            ExpressionAttributeValues={
                ':m': backend_respone['history'], 
                ':p': backend_respone['property_name'],
                ':l': {"city": backend_respone.get('city', None), "location_attempts": backend_respone.get('location_attempts', 0)},
                ':o': backend_respone.get('offers', []),
                ':b': backend_respone.get('booking_data', {}),
                ':v': VOICE_NAME
            }
        )
        bot_response = backend_respone['gpt_response']
    else:   
        history = item.get('messages')
        property_name = item.get('property_name')
        system_history = item.get('system_history')
        system_history.append(history[0])
        offers = item.get('offers')
        booking_data = item.get('booking_data', {})
        location_data = item.get('location_data', {})
        VOICE_NAME = item.get('voice_name')
    

        if booking_data is None:
            booking_data = {}
        
        if "guest_phone_number" not in booking_data:
            booking_data["guest_phone_number"] = (
                    convert_to_international(CALLER) if CALLER and CALLER.isdigit() else None
                )

        print("GUEST'S PHONE NUMBER: ", booking_data.get("guest_phone_number"))        

        user_query = request_json['activities'][0]['text']
        print("USER: " + user_query)
        backend_respone = await generate_conversation(user_query, history=history, property_name=property_name, language=LANGUAGE, offers=offers, booking_data=booking_data, location_data=location_data)

        table.update_item(
            Key={'id': conversation_id}, 
            UpdateExpression="set messages=:m, property_name=:p, system_history=:s, location_data=:l, offers=:o, booking_data=:b",
            ExpressionAttributeValues={
                ':m': backend_respone['history'], 
                ':p': backend_respone['property_name'],
                ':s': system_history,
                ':l': {"city": backend_respone.get('city', None), "location_attempts": backend_respone.get('location_attempts', 0)},
                ':o': backend_respone['offers'],
                ':b': backend_respone['booking_data']
            }
        )      
        bot_response = backend_respone['gpt_response']

    activities = list()

    clean_bot_response = remove_emojis(bot_response)
    enhanced_bot_response = enhance_pronunciation(clean_bot_response, language=LANGUAGE)
   
    bot_response_ssml = config["response"]["bot_response_format"].format(
        speech_rate=config["voice"]["speech_rate"],
        message=enhanced_bot_response
    )

    print("\n\n\nBOT: " + bot_response_ssml)   

    activities.append({
    "id": str(uuid.uuid4()),
    "timestamp": timestamp,
    "language": LANGUAGE,
    "type": "message",
    "text": bot_response_ssml,
    "activityParams": {
        "language": LANGUAGE,
        "voiceName": VOICE_NAME
        }
    })

    try:
        if backend_respone.get('end_of_conversation'):
            activities.append({
                "id": str(uuid.uuid4()),
                "timestamp": timestamp,
                "type": "event",
                "name": "hangup"
            })
        phone_number = backend_respone.get('phone_number')
        print(phone_number)

        phone_number = config["call"]["transfer"]["default_extension"]

        if backend_respone.get('phone_number'):
            activities.append({
                "id": str(uuid.uuid4()),
                "timestamp": timestamp,
                "type": "event",
                "name": "transfer",
                "activityParams": {
                    "transferTarget": "sip:" + phone_number + config["call"]["transfer"]["sip_domain"],
                }
            })

        if backend_respone.get('hangup'):
            activities.append({
                "id": str(uuid.uuid4()),
                "timestamp": timestamp,
                "type": "event",
                "name": "hangup"
            })

    except:
        pass
    
    print(activities)
    end_time = time.time()  # get current time after the API call
    print("Time taken for phonecall response call: " + str(end_time - start_time))
    system_response = {"activities": activities}
    
    # If the response time exceeds the warning threshold, send a warning to Sentry
    if (end_time - start_time) > config["call"]["timeout"]["warning_threshold_seconds"]:
        exceeding_time_message = f"Phonetical response exceeds {config['call']['timeout']['warning_threshold_seconds']} seconds: {end_time - start_time}"
        sentry_sdk.capture_message(exceeding_time_message, "warning")
        print(exceeding_time_message)

    print("System Response")
    print(system_response)

    return system_response

@app.get("/conversation/disconnect/{conversation_id}")
@app.post("/conversation/disconnect/{conversation_id}")
@app.put("/conversation/disconnect/{conversation_id}")
@app.delete("/conversation/disconnect/{conversation_id}")
async def capture_disconnect(conversation_id: str, request: Request):
    print("Disconnect received")
    print(f"Disconnect received for conversation ID: {conversation_id}")
    request_json = await request.json()
    if  LOCAL_DYNAMO_DB_URL:
        print(json.dumps(request_json, indent=4, sort_keys=True))
    else:
        print(request_json)

    # Response
    response = {}

    return response

@app.get("/conversation/refresh/{conversation_id}")
@app.post("/conversation/refresh/{conversation_id}")
@app.put("/conversation/refresh/{conversation_id}")
@app.delete("/conversation/refresh/{conversation_id}")
async def capture_refresh(conversation_id: str, request: Request):
    print("Refresh received")
    request_json = await request.json()
    if  LOCAL_DYNAMO_DB_URL:
        print(json.dumps(request_json, indent=4, sort_keys=True))
    else:
        print(request_json)

    # Response
    response = { "expiresSeconds": config["call"]["timeout"]["refresh_expiry_seconds"]}

    return response