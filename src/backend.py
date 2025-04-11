import os
import json
import time
import boto3
from dotenv import load_dotenv
from src.default_prompt import get_system_prompt_template, get_ai_prompt_template
from src.bot_embeddings import get_embeddings, search_results, confidence_score_filter
from src.location_recognition import get_location
from src.helpers import time_checker, no_property_info, get_text, get_text_with_variables, convert_decimals_to_floats, convert_floats_to_decimals, send_teams_message, check_call_redirect_condition
from src.helpers import convert_to_international, correct_data_year, process_dates_pronunciation
from src.api_connection import check_apaleo_offers, get_booking_data, create_booking, get_folio_id_by_booking_id, find_folio_by_id, create_payment_link, get_payment_link_data
from pydantic import BaseModel
import sentry_sdk
import asyncio
from src.pydantic_models import BookingValidator
from pydantic import ValidationError
from azure.ai.inference import ChatCompletionsClient
from azure.core.credentials import AzureKeyCredential
import pytz
from collections import defaultdict
from twilio.rest import Client
from datetime import datetime
import yaml

load_dotenv()

# Load configuration from YAML
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

LOCAL_DYNAMO_DB_URL = os.getenv('LOCAL_DYNAMO_DB_URL')
WEBHOOK_URL = os.getenv("MS_TEAMS_WEBHOOK_URL")
account_sid=os.environ["TWILIO_ACCOUNT_SID"]
auth_token=os.environ["TWILIO_AUTH_TOKEN"]
twillio_client = Client(account_sid, auth_token)

async def background_task(booking_data, offers):
    """
    Background task to create a reservation and send the details to Teams.
    """
    print("background_task "*10)
    # Some long-running process
    try:
        print("Booking data: ", booking_data)
        print("Choice: ", offers)
        print("Offers: ", offers)
        offers = convert_decimals_to_floats(offers)
        print("Adults: ", booking_data["number_of_adults"])
        whatsapp_number = convert_to_international(booking_data["guest_whatsapp_number"])
        print("Whatsapp Phone Number: ", whatsapp_number)
        print("First Name: ", booking_data["first_name"])
        print("Last Name: ", booking_data["last_name"])
        fill_booking_data = get_booking_data(
            booking_data["first_name"],
            booking_data["last_name"],
            whatsapp_number,
            offers[0],
            int(booking_data["number_of_adults"])
        )
        print("Booking data: ", fill_booking_data)
        booking_response = await create_booking(fill_booking_data)
        booking_id = booking_response.get('id')
        description = f"Payment link for booking {booking_id}"
        country_code = "DE"
        folio_id = get_folio_id_by_booking_id(booking_id)
        folio_data = find_folio_by_id(folio_id)
        payment_id = create_payment_link(folio_data, country_code, description)
        print("Payment ID: ", payment_id)
        time.sleep(10)
        payment_link_data = get_payment_link_data(folio_data, payment_id)
        print("Payment Link: ", payment_link_data['url'])

        url = payment_link_data['url']
        # converted_number = convert_to_international(booking_data["caller"])
        cleaned_url = url.replace("https://test.adyen.link/", "")
        whatsapp = "whatsapp:" + whatsapp_number
        print("Whatsapp: ", whatsapp)
        message = twillio_client.messages.create(
            content_sid="HX60be4a148ae7982d794064fc0c653111",
            content_variables=json.dumps({"1": cleaned_url}),
            from_='whatsapp:+4930585847900',  # Twilio Sandbox WhatsApp number
            to=whatsapp
        )
        print(f"Message sent with SID: {message.sid}")

        # Prepare booking details
        booking_details = {
            "Booking ID": booking_id if booking_id else "N/A",
            "First Name": booking_data.get("first_name") if booking_data.get("first_name") else "N/A",
            "Last Name": booking_data.get("last_name") if booking_data.get("last_name") else "N/A",
            "Whatsapp Phone Number": whatsapp_number if whatsapp_number else "N/A",
            "Adults": str(booking_data.get("number_of_adults")) if booking_data.get("number_of_adults") else "N/A",
            "Offer Chosen": offers[0]['unitGroup']['name'] if offers else "N/A",
            "Price": f"{offers[0]['totalGrossAmount']['amount']} {offers[0]['totalGrossAmount']['currency']} " if offers else "N/A",
            "Arrival Date": booking_data.get("arrival_date") if booking_data.get("arrival_date") else "N/A",
            "Departure Date": booking_data.get("departure_date") if booking_data.get("arrival_date") else "N/A",
        }

        # Send success message to Teams
        send_teams_message(
            webhook_url=WEBHOOK_URL,
            title=f"📅 {config["hotel_info"]["hotel_brand"]} Reservation Created Successfully", # TO DO: add property name
            message=config["microsoft_teams_channel"]["success_message"],
            details=booking_details,
            is_error=False  # Indicates a successful operation
        )
    
    except Exception as e:
        # Handle exceptions and send error message to Teams
        booking_data['error'] = str(e)
        error_details = {
            "Error Message": str(e),
            "Reservation Data": str(booking_data)
            # Add more contextual information if available
        }
        print("ERROR IN BACKGROUND TASK: " * 100, str(e))
        
        send_teams_message(
            webhook_url=config["microsoft_teams_channel"]["webhook_url"],
            title=f"❌ {config["hotel_info"]["hotel_brand"]} Reservation Failed",
            message=config["microsoft_teams_channel"]["failure_message"],
            details=error_details,
            is_error=True
        )
        sentry_sdk.capture_message(f"Error in background task {config["hotel_info"]["hotel_brand"]}: " + str(e), "error")

# Initialize the Azure LLM client for chat completions
azure_client = ChatCompletionsClient(
    endpoint=os.getenv("AZURE_LLM_URL"),
    credential=AzureKeyCredential(os.getenv("AZURE_LLM_KEY"))
)

async def handle_results(embedded_query, update_system_prompt=False, history=None, property_name=None, user_query=None, language=None, offers=None, guest_phone_number=None):
    """
    Handle the results from the embeddings search, add the assistant response to the history, and update the system prompt.
    """
    if language is None:
        language = "de-DE"

    results = search_results(embedded_query, property_name=property_name, language=language)
    results_with_confidence = confidence_score_filter(results)
    print("Results with confidence score:")
    print(results_with_confidence)

    # if both results have either "Switchboard" or "Telefonzentrale" in them, then redirect to service desk
    call_redirect_condition = check_call_redirect_condition(results_with_confidence, language, user_query)

    if property_name is None:
        # check if results are unique (hotel-specific)
        results_with_confidence, unique = no_property_info(results_with_confidence)
    else:
        unique = False
    print(history)
    if offers:
        print("Offers" * 50)
        print(offers)

    if not offers:
        offers = ""
    paragraphs = "" # paragraphs are the search results form the database
    if results_with_confidence:
        for index, x in enumerate(results_with_confidence): 
            result = x[0]
            paragraphs = paragraphs +  "\nContext " + str(index + 1) + ": " + result 
    else:
        paragraphs = ""

    # Get the system prompt template
    prompt_system = get_system_prompt_template(paragraphs, language=language, offers=offers, guest_phone_number=guest_phone_number)

    prompt_dict = {
        "role": "system", 
        "content": prompt_system
    }
    # add the system prompt to the history
    if update_system_prompt:
        history[0] = prompt_dict
    else:
        # add the ai prompt to the history (welcome message)
        prompt_ai = get_ai_prompt_template(language=language)
        history.append(prompt_dict)
        history.append({"role": "assistant", "content": prompt_ai})

    return history, unique, call_redirect_condition

async def generate_conversation(user_query, history=None, property_name=None, language=None, offers=None, booking_data=None, location_data=None):
    # Function to handle the repeated process of getting results and updating history

    # Initialize history if not present
    print("User query: " + user_query)
    print("History:")
    print(json.dumps(history, indent=4))

    if booking_data is None or not booking_data:
        booking_data = {}

    if location_data is None or not location_data:
        location_data = {}
    if "location_attempts" not in location_data:
        location_data["location_attempts"] = 0
    if "city" in location_data:
        city = location_data["city"]
    else:   
        city = None

    if history is None:
        history = []
    # if location recognition needed, get the location, counting the attempts
    elif history[-1]['role'] == "onsai" and history[-1]['content'] == "location":
        try:
            if location_data["location_attempts"] < 2:
                    location_data["location_attempts"] += 1
                    property_name_json = get_location(user_query=user_query, language=language, city=city)
                    print("property_name JSON:")
                    print(property_name_json)
                    # location detected
                    if property_name_json.get("location", None) and property_name_json.get("location_confirmed", False) == True: 
                        print("property_name location confirmed")
                        property_name = property_name_json["location"]
                        user_query = history[-2]['content']
                        history = history[:-2]
                        property_name_json = None
                    # city detected, but not the exact location
                    elif property_name_json.get("city", None) in property_name_json and property_name_json.get("city_confirmed", False) == True:
                        print("City recognized")
                        assistant = property_name_json.get("message")        
                        response = {
                            "gpt_response" : assistant,
                            "history": history, 
                            "property_name": None,
                            "city": property_name_json.get("city", None),
                            "location_attempts": location_data["location_attempts"],
                            "offers": offers,
                            "booking_data": booking_data
                        }
                        return response
                    else: 
                        assistant = property_name_json.get("message")
                        response = {
                            "gpt_response" : assistant,
                            "history": history, 
                            "property_name": None,
                            "city": property_name_json.get("city", None),
                            "location_attempts": location_data["location_attempts"],
                            "offers": offers,
                            "booking_data": booking_data
                        }
                        print("Location attempts: " + str(location_data["location_attempts"]))
                        return response
            else: # location attempts exceeded, transfer to service desk
                phone_number = config["call"]["transfer"]["default_extension"]
                # transfer to service desk
                assistant = get_text("service_hotline_open", language)
                offers = None
                booking_data = None
                response = {
                    "gpt_response" : assistant,
                    "history": history, 
                    "phone_number": phone_number, 
                    "property_name": property_name,
                    "hangup": False ,
                    "offers": offers,
                    "booking_data": booking_data
                }
                return response

        except Exception as e:
            print("Error getting location: " + str(e))
            sentry_sdk.capture_message("Error getting location: " + str(e), "error")


    # Determine the embedded query based on history presence
    start_time_emb = time.time()  # get current time
    # remove ',', '.', '?', '!' from the user query and convert to lowercase
    user_query_preprocessed = user_query.strip().strip('.').strip(',').strip('?').strip('!').lower()
    print("Embedded query final: " + user_query_preprocessed)
    embedded_query = await get_embeddings(user_query_preprocessed)
    if history:
        history, unique, call_redirect_condition  = await handle_results(embedded_query, update_system_prompt=True, property_name=property_name, history=history, user_query=user_query, language=language, offers=offers, guest_phone_number=booking_data.get("guest_phone_number"))
    else:
        history, unique, call_redirect_condition = await handle_results(embedded_query, property_name=property_name, history=history, user_query=user_query, language=language, offers=offers, guest_phone_number=booking_data.get("guest_phone_number"))
    
    end_time_emb = time.time()  # get current time after the API call
    print("Time taken for Embeddedings: " + str(end_time_emb - start_time_emb))

    # if both matched embeddins results have either "Switchboard" or "Telefonzentrale" in them, then redirect to service desk
    if call_redirect_condition:
        # redirect to employee
        assistant = get_text("service_hotline_open", language)
        offers = None
        booking_data = None
        response = {
            "gpt_response" : assistant,
            "history": history, 
            "property_name": property_name,
            "hangup": False ,
            "offers": offers,
            "booking_data": booking_data,
            "location_data": location_data
        }
        return response

    if unique and property_name is None: # the matched db results are unique and the location is not confirmed
        history.append({"role": "user", "content": user_query})
        history.append({"role": "onsai", "content": "location"})
        assistant = get_text("which_property_name", language) 

        response = {
            "gpt_response" : assistant,
            "history": history, 
            "property_name": None,
            "location_attempts": location_data["location_attempts"],
            "offers": offers,
            "booking_data": booking_data,
        
        }
        return response
        
    # Append user query to the history
    history.append({"role": "user", "content": user_query})

    print("History:")
    print(history)

    # Get the assistant response
    start_time = time.time()  # get current time
    try:
        # chat_completion = groq_client.chat.completions.create(
        #     messages=history,
        #     model="llama-3.3-70b-versatile",   #"llama-3.3-70b-versatile", 
        #     response_format={ "type": "json_object" },
        #     temperature=0,
        #     # timeout=6.0   
        # )
        chat_completion = azure_client.complete(
            messages=history,
            response_format="json_object",
            temperature=0, 
            max_tokens=4000,
        )
        print("Chat completion result:")
        print(chat_completion)
        try:
            json.loads(chat_completion.choices[0].message.content)
        except json.JSONDecodeError:
            print("Invalid JSON response from LLM")
            sentry_sdk.capture_message("Invalid JSON response from LLM", "warning")
            chat_completion = None
    
    except Exception as e:
        print("Error: " + str(e))
        bad_request_error = "LLM BadRequestError wit this message: " + str(e)
        sentry_sdk.capture_message(bad_request_error, "warning")
        chat_completion = None
        # Set assistant to 'Mitarbeiter' or 'Employee' depending on language
        assistant = get_text("service_hotline_open", language)
    
        # Build response to trigger call redirection
        response = {
            "gpt_response": assistant,
            "history": history,
            "phone_number": config["call"]["transfer"]["default_extension"],
            "property_name": property_name,
            "hangup": False,
            "offers": convert_floats_to_decimals(offers) if offers else None,
            "booking_data": convert_floats_to_decimals(booking_data) if booking_data else None
        }
        return response

    end_time = time.time()  # get current time after the API call
    follow_up_response = await follow_up(chat_completion, history, property_name, language, booking_data, offers, city)
    print("Time taken for LLM API call: " + str(end_time - start_time))
    return follow_up_response

async def follow_up(chat_completion, history, property_name, language, booking_data=None, offers=None, city=None):
    print("GPT Response:")
    print(chat_completion)
    hangup = False

    # Initialize booking_data if it's None
    if booking_data is None:
        booking_data = {}

    #Gettting the assistant response and appending it to the history
    #making sure the response is not None and has a length greater than 0
    assistant_json = None
    try:
        if chat_completion is not None and len(chat_completion.choices[0].message.content) > 1:
            try: 
                assistant_json = json.loads(chat_completion.choices[0].message.content)
                print("Assistant json:", assistant_json)
                if language == "de-DE":
                    # if no response from LLM, set assistant to "Telefonzentrale"
                    assistant = assistant_json.get("response", "Telefonzentrale")
                else:
                    assistant = assistant_json.get("response", "Switchboard")
                
                print("Assistant response:")
                print(json.dumps(assistant_json, ensure_ascii=False, indent=2)) # indent was 4
            except json.JSONDecodeError as e:
                print("Error parsing assistant JSON: " + str(e))
                assistant = chat_completion.choices[0].message.content
                assistant_json = None  # Ensure assistant_json is None if parsing fails
        else:
            print("No response from LLM")
            if language == "de-DE":
                assistant = "Telefonzentrale"
            else:
                assistant = "Switchboard"
            assistant_json = None
            hangup = False 
    except Exception as e:
        print("LLM Response Error: " + str(e))
        if language == "de-DE":
            assistant = "Telefonzentrale"
        else:
            assistant = "Switchboard"
        assistant_json = None
        hangup = False ###
        sentry_sdk.capture_message("LLM Response Error: " + str(e), "error")

    if assistant_json is not None:
        print("Assistant JSON not None")
        # Filter out 'none', 'null', or None values from the assistant JSON and update booking_data
        new_data = {k: v for k, v in assistant_json.items() if v not in ["none", "null", None] and k not in ["response", "follow_up", "mode"]}
        booking_data.update(new_data)
        
        # check if it's a reservation and if the property name (location) is not confirmed
        if assistant_json.get("booking") in ["true", True] and property_name == "":
            assistant = get_text("service_hotline_open", language)

            hangup = False
            response = {
                "gpt_response" : assistant,
                "history": history, 
                "phone_number": config["call"]["transfer"]["default_extension"],
                "property_name": property_name,
                "hangup": hangup,
                "offers": convert_floats_to_decimals(offers) if offers else None,
                "booking_data": convert_floats_to_decimals(booking_data) if booking_data else None
            }
            return response
            
        elif assistant_json.get("mode") == "booking" and assistant_json.get("booking") in ["true", True]:
            # do not allow reservations for the same day
            print("Start booking process")
            booking_data["property_name"] = property_name
            if "booking_confirmed" in assistant_json and assistant_json["booking_confirmed"] in ["true", True]:
                if offers:
                    print("BOOKING PART")
                    assistant = get_text("booking_confirmation", language)
                    try:
                        if LOCAL_DYNAMO_DB_URL:
                            booking_data = convert_decimals_to_floats(booking_data)
                            print("LOCAL DYNAMO DB. Starting background task")
                            # Start background task
                            asyncio.create_task(background_task(booking_data, offers))
                        else:
                            lambda_client = boto3.client('lambda')
                            response = lambda_client.invoke(
                                FunctionName=config["lambda_client"]["booking_function"]["name"],
                                InvocationType='Event',  # Asynchronous invocation
                            Payload=json.dumps({
                                'booking_data': convert_decimals_to_floats(booking_data),
                                'offers': convert_decimals_to_floats(offers)
                                })
                            )
                            print("lambda_client")
                            print(response)

                    except Exception as e:
                        print("Error starting background task: " + str(e))
                        sentry_sdk.capture_message("Error starting background task: " + str(e), "error")
                        assistant = get_text("booking_error", language)
                        if booking_data is not None:
                            booking_data['error_getting_offers'] = str(e)

                        error_details = {
                            "Error Message": str(e),
                            "Reservation Data": str(booking_data),
                            "Offers": str(offers),
                            "Timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
                            # Add more contextual information if available
                        }
                        send_teams_message(
                            webhook_url=config["microsoft_teams_channel"]["webhook_url"],
                            title=f"❌ {config["hotel_info"]["hotel_brand"]} ({property_name}) Reservation Failed",
                            message=config["microsoft_teams_channel"]["failure_message"],
                            details=error_details,
                            is_error=True
                        )
                        sentry_sdk.capture_message("Error starting background task: " + str(e), "error")
                else:   # no offers available, reset the booking process
                    print("Create reservation failed, no offers available")
                    assistant = get_text_with_variables("no_available_offers", language, arrival=booking_data.get("arrival_date"), departure=booking_data.get("departure_date"))
                # Reset variables
                booking_data = None
                offers = None
                assistant_json = None
            elif "booking_confirmed" in assistant_json and assistant_json["booking_confirmed"] in ["false", False]:
                print("Booking was NOT confirmed")
                assistant = get_text("booking_not_confirmed", language)
                history.append({"role": "assistant", "content": assistant})
                assistant_json = None
                response = {
                        "gpt_response": assistant,
                        "history": history,
                        "phone_number": None,
                        "property_name": property_name,
                        "hangup": False,
                        "offers": None,
                        "booking_data": None
                    }
                return response
            else:
                try:           
                    # check if all required data fields are present
                    validate_availability_check_data = BookingValidator.parse_obj(assistant_json)
                    booking_data.update(validate_availability_check_data.dict()) # update booking_data with validated data
                    try:

                        #pronounced_arrival_date, pronounced_departure_date = process_dates_pronunciation(booking_data.get("arrival"), booking_data.get("departure"), language)
                        print("CHECK PRIME AVAILABILITY in APALEO")
                        # correct the current date if it's in the past
                        booking_data["arrival_date"], booking_data["departure_date"] = correct_data_year(booking_data.get("arrival_date"), booking_data.get("departure_date"))
                        offers = check_apaleo_offers(language, property_name, booking_data.get("arrival_date"), booking_data.get("departure_date"), booking_data.get("number_of_adults"))
                        if offers:
                            print("Rooms available")
                            assistant = get_text_with_variables(
                                "available_offers",
                                language,
                                num_rooms=len(offers),
                                arrival=booking_data.get("arrival_date"),
                                departure=booking_data.get("departure_date")
                            )
                        
                            grouped_offers = defaultdict(list)
                            
                            for offer in offers:
                                print(json.dumps(offer, indent=4, ensure_ascii=False))
                                unit_name = offer['unitGroup']['name']
                                price = offer['totalGrossAmount']['amount']
                                currency = offer['totalGrossAmount']['currency']
                                cancelation_fee = offer['cancellationFee']['name']
                                cancelation_fee_description = offer['cancellationFee']['description']
                                grouped_offers[unit_name].append((price, currency, cancelation_fee, cancelation_fee_description))

                            unit_name, prices = next(iter(grouped_offers.items()))
                            price, currency, cancelation_fee, cancelation_fee_description = prices[0]
                            if language == "de-DE":
                                if cancelation_fee == "Flexible":
                                    assistant += f"\n{unit_name} für {price} {currency}. Die Stornierungsbedingungen sind {cancelation_fee} und erlauben eine kostenfreie Stornierung bis zum Check-In."
                                else:
                                    assistant += f"\n{unit_name} für {price} {currency}. {cancelation_fee_description}." 
                            else:
                                if cancelation_fee == "Flexible":
                                    assistant += f"\n{unit_name} for {price} {currency}. The cancellation policy is {cancelation_fee} and allows {cancelation_fee_description}."
                                else:
                                    assistant += f"\n{unit_name} for {price} {currency}. {cancelation_fee_description}."
                            assistant += get_text("offer_selection", language)
                            # Append the confirmation prompt to history and return the response, waiting for user confirmation.
                            history.append({"role": "assistant", "content": assistant})
                            response = {
                                "gpt_response": assistant,
                                "history": history,
                                "property_name": property_name,
                                "offers": convert_floats_to_decimals(offers) if offers else None,
                                "booking_data": convert_floats_to_decimals(booking_data) if booking_data else None,
                            }
                            return response
                        else:
                            # no available time slots
                            assistant = get_text_with_variables("no_available_offers", language, arrival=booking_data.get("arrival_date"), departure=booking_data.get("departure_date"))
                            assistant_json = None
                            offers = None

                    except Exception as e: # Error checking availability
                        print("Error checking availability: " + str(e))
                        sentry_sdk.capture_message("Error checking availability: " + str(e), "error")
                        assistant = get_text("booking_error", language)
                        # Reset variables to collect data again
                        assistant_json = None
                        offers = None
                        if booking_data is not None:
                            booking_data['error_getting_offers'] = str(e)
                        # Append assistant response to history and return
                        history.append({"role": "assistant", "content": assistant})
                        response = {
                            "gpt_response": assistant,
                            "history": history,
                            "phone_number": None,
                            "property_name": property_name,
                            "hangup": hangup,
                            "offers": None,
                            "booking_data": convert_floats_to_decimals(booking_data) if booking_data else None
                        }
                        return response
                    
                except ValidationError as e: # not all the required data slots are filled, gather data
                    missing_fields = e.errors()
                    print("Missing fields: " + str(missing_fields))

                    if missing_fields:
                        response = {
                        "gpt_response" : assistant,
                        "history": history, 
                        "property_name": property_name,
                        "offers": convert_floats_to_decimals(offers) if offers else None,
                        "booking_data": convert_floats_to_decimals(booking_data) if booking_data else None,
                        }
                        return response
        else:
            # Handle other cases
            if language == "de-DE":
                assistant = assistant_json.get("response", "Telefonzentrale")
            else:
                assistant = assistant_json.get("response", "Switchboard")


    else:
        # If assistant_json is None, use the assistant content directly as the response
        pass

    # Check if there's a follow-up question and append it
    follow_up = assistant_json.get("follow_up", " ") if assistant_json else " "
    if follow_up and assistant not in ["Telefonzentrale", "Switchboard"] or (assistant_json and assistant_json.get("mode") == "employee_handover"):
        assistant += " " + follow_up 

    history.append({"role": "assistant", "content": assistant})
           
    if  "Verabschiedung" in assistant or "verabschiedung" in assistant:
        assistant = assistant.replace("Verabschiedung", "") 
        assistant = assistant.replace("verabschiedung", "")
        hangup = True  
    elif "Goodbye" in assistant or "goodbye" in assistant:
        assistant = assistant.replace("goodbye", "") 
        assistant = assistant.replace("Goodbye", "")
        hangup = True  
    elif assistant_json and assistant_json.get("mode") == "farewell":
        hangup = True
        assistant = assistant_json.get("response")

    
    # Set the phone number to None
    phone_number = None        

    # Check if the assistant response contains the word "Mitarbeiter"
    print("ASSISTANT HERE: ", assistant)
    if "telefonzentrale" in assistant.lower() or "switchboard" in assistant.lower() or (assistant_json and assistant_json.get("mode") == "employee_handover"):
        print("TELEFONZENTRALE")
        assistant = get_text("service_hotline_open", language)
        phone_number = config["call"]["transfer"]["default_extension"]
        hangup = False


    print("Assistant response:", assistant)

    response = {
        "gpt_response" : assistant,
        "history": history, 
        "phone_number": phone_number,
        "property_name": property_name,
        "hangup": hangup,
        "city": city,
        "offers": convert_floats_to_decimals(offers) if offers else None,
        "booking_data": convert_floats_to_decimals(booking_data) if booking_data else None

    }   
    return response