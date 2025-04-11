import requests
import os
from datetime import datetime, timedelta
import re
import json
import math
import uuid
import sentry_sdk
import yaml

# from dotenv import load_dotenv
# load_dotenv()

with open('config.yaml', 'r') as file:
    config = yaml.safe_load(file)

CLIENT_ID = os.getenv('APALEO_CLIENT_ID')
CLIENT_SECRET = os.getenv('APALEO_CLIENT_SECRET')


TOKEN_URL = 'https://identity.apaleo.com/connect/token'
API_URL = 'https://api.apaleo.com'

def get_oauth_token():
    data = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'client_credentials' 
    }

    response = requests.post(TOKEN_URL, data=data)
    if response.status_code == 200:
        return response.json().get('access_token')
    else:
        print(f"Failed to get token: {response.status_code}")
        print(response.text)
        #sentry_sdk.capture_message(f"Failed to get token: {response.status_code}")

def get_location_id(location_name):
    location_id = "BER"
    return location_id
    
def check_apaleo_offers(language, location: str, arrival_date: str, departure_date: str, adults_num: int, children_ages: list = []):
    access_token = get_oauth_token()
    print(f"Location: {location}")
    location_id = get_location_id(location)
    print(f"Location ID: {location_id}")
    lang = 'de' if language == 'de-DE' else 'en'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept-Language': lang,
    }
    params = {
        'propertyId': location_id,
        'arrival': arrival_date,
        'departure': departure_date,
        'adults': adults_num,
        'childrenAges': children_ages,
        'channelCode': 'Direct',
        #'promoCode': 'ONSAI'
    }

    response = requests.get(
        f'{API_URL}/booking/v1/offers', headers=headers, params=params
    )

    if response.status_code != 200:
        print(f"Request failed with status code: {response.status_code}")
        print(f"Response content: {response.content}")
        #sentry_sdk.capture_message(f"Request failed with status code: {response.status_code}")
        return None

    try:
        response_json = response.json()
        offers = response_json.get('offers', [])
        if not offers:
            print("No offers found.")
            return None
        
        
        #Filter offers based on rate plan
        #offers = [offer for offer in offers if offer['ratePlan']['code'] == 'ONSAI']

        # Step 1: Look for offers where maxPersons == adults_num
        offers_exact = [
            offer
            for offer in offers
            if offer["unitGroup"]["maxPersons"] == adults_num
        ]

        if offers_exact:
            # Sort these offers by price in descending order
            sorted_offers_exact = sorted(
                offers_exact,
                key=lambda x: x["totalGrossAmount"]["amount"],
                reverse=True,
            )
            # Return the most expensive offer(s)
            
            sorted_offers_exact = [sorted_offers_exact[0]]
            # print(f"Found {len(offers)} offers with exact number of persons.")
            # print(f"Selected offer: {sorted_offers_exact}")
            return sorted_offers_exact

        # Step 2: If no offers found, look for offers where maxPersons == adults_num + 1
        offers_plus_one = [
            offer
            for offer in offers
            if offer["unitGroup"]["maxPersons"] == adults_num + 1
        ]

        if offers_plus_one:
            # Sort these offers by price in descending order
            sorted_offers_plus_one = sorted(
                offers_plus_one,
                key=lambda x: x["totalGrossAmount"]["amount"],
                reverse=True,
            )
            # Return the most expensive offer(s)
            sorted_offers_plus_one = [sorted_offers_plus_one[0]]
            # print(f"Found {len(sorted_offers_plus_one)} offers with one extra person")
            # print(f"Selected offer: {sorted_offers_plus_one}")
            return sorted_offers_plus_one

        # Step 3: If still no offers found, return None
        print("No suitable offers found.")
        return None


    except Exception as e:
        print(f"Error parsing response JSON: {e}")
        sentry_sdk.capture_message(f"Error parsing response JSON for Apaleo offers: {e}")
        return None


def get_booking_data(first_name, last_name, telephone_number, offer, adults_num, children_ages=[]):
    time_slices = [
        {
            "ratePlanId": offer['ratePlan']['id'],
            "totalAmount": {
                "amount": time_slice['totalGrossAmount']['amount'],
                "currency": time_slice['totalGrossAmount']['currency']
            }
        }
        for time_slice in offer['timeSlices']
    ]

    data =  {
        "booker": {
            "firstName": first_name,
            "lastName": last_name,
            "phone": telephone_number,
        },
        "reservations": [
            {
                "arrival": offer['arrival'],
                "departure": offer['departure'],
                "adults": adults_num,
                "childrenAges": children_ages,
                "channelCode": "Direct",
                "primaryGuest": {
                    "firstName": first_name,
                    "lastName": last_name,
                    "phone": telephone_number,
                },
        "timeSlices": time_slices
            }
        ]
    }

    return data


def create_booking(booking_data):
    access_token = get_oauth_token()
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Idempotency-Key': str(uuid.uuid4())
    }
    endpoint = f'{API_URL}/booking/v1/bookings'

    response = requests.post(endpoint, headers=headers, json=booking_data)
    if response.status_code == 201:
        return response.json()
    else:
        print(f"Failed to create a booking: {response.status_code}")
        print(response.text) 
        sentry_sdk.capture_message(f"Failed to create a booking in Apaleo: {response.status_code}")

        return None

def get_folio_id_by_booking_id(booking_id):
    """
    Get the ID of the folio with a negative balance for a given booking ID.

    Parameters:
    - booking_id: The booking ID.

    Returns:
    - str: The ID of the folio with a negative balance, or None if no such folio exists.

    """
    access_token = get_oauth_token()
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    endpoint = f'{API_URL}/finance/v1/folios?bookingIds={booking_id}'
    response = requests.get(endpoint, headers=headers)
    if response.status_code == 200:
        folios = response.json().get('folios', [])
        negative_balance_folios = [folio for folio in folios if folio.get('balance', {}).get('amount') < 0]
        return negative_balance_folios[0].get('id') if negative_balance_folios else None
    print(f"Failed to get folio: {response.status_code}")
    sentry_sdk.capture_message(f"Failed to get folio ID in Apaleo: {response.status_code}")
    print(response.text)
    return None

def find_folio_by_id(folio_id: str):
    """
    Find a folio by its ID.

    Parameters:
    - folio_id: The ID of the folio.

    Returns:
    - dict: The detailed folio data, or None if the folio was not found. 

    """
    access_token = get_oauth_token()
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Idempotency-Key': str(uuid.uuid4())
    }

        # get folio 
    url = f"{API_URL}/finance/v1/folios/{folio_id}"
    try:
        response = requests.get(url, headers=headers)

        # Check if request was successful (status code 200)
        if response.status_code == 200:
            folio_data = response.json()
            print(f"Folio data: {folio_data}")
            return folio_data
        else:
            print(f"Failed to retrieve folio. Status code: {response.status_code}")
            print(f"Response content: {response.text}")

    except requests.exceptions.RequestException as e:
        print(f"Error fetching folio: {e}")
        sentry_sdk.capture_message(f"Error fetching folio in Apaleo: {e}")

def create_payment_link(folio, country_code: str, description: str):
    """
    Create a payment link for a given folio.

    Parameters:
    - folio: The folio data.
    - country_code: The country code for the payment link (e.g. 'de', 'en'). Depending on the country code, the payment methods and the language of the payment page will be set.
    - description: Payment description. It will be shown on the payment form of the link

    Returns:
    - dict: id of the created payment link as a string
    """
    access_token = get_oauth_token()
    folio_id = folio.get('id')
    open_balance = folio["balance"]["amount"]

    # Calculate total pending payments
    pending_payments = sum(payment["amount"]["amount"] for payment in folio.get("pendingPayments", []))
    # Calculate maximum allowed payment without exceeding the open balance and pending payments
    max_allowed_payment = open_balance - pending_payments
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Idempotency-Key': str(uuid.uuid4())
    }

    charges = [
        {
            "chargeId": charge.get('id'),
            "amount": abs(charge.get('amount').get('grossAmount'))
        }
        for charge in folio['charges']
    ]
    payment_link_data = {
        "expiresAt": (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "countryCode": country_code,
        "description": description,
        "amount": {
            "amount": abs(max_allowed_payment),
            "currency": folio.get('balance').get('currency'),
        },
        "paidCharges": charges
    }
    endpoints = f"{API_URL}/finance/v1/folios/{folio_id}/payments/by-link"
    response = requests.post(endpoints, headers=headers, json=payment_link_data)
    if response.status_code == 201:
        payment_info = response.json()
        return payment_info.get('id')
    else:
        print("Failed to create payment link:")
        print(f"Status code: {response.status_code}")
        print(f"Response content: {response.content}")
        print(response.text)
        return None

def get_payment_link_data(folio_data, payment_id):
    access_token = get_oauth_token()
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
    }
    folio_id = folio_data.get('id')
    endpoints = f"{API_URL}/finance/v1/folios/{folio_id}/payments/{payment_id}"
    response = requests.get(endpoints, headers=headers)
    if response.status_code == 200:
        payment_link_data = response.json()
        print("Payment Link Data:", payment_link_data)
        return payment_link_data
    else:
        print(response.text)
        return None




# if __name__ == "__main__":
#     CLIENT_ID=""
#     CLIENT_SECRET=""
#     language = "de-DE"
#     location = "BER"
#     arrival_date = "2025-04-10"
#     departure_date = "2025-04-11"
#     first_name = "Test"
#     adults_num =1
#     last_name = "Test"
#     telephone_number = None
#     # offers = check_apaleo_offers(language, location, arrival_date, departure_date, adults_num)
#     # if offers:
#     #     print(f"Offers found: {offers}")
#     #     print(f"Number of offers: {len(offers)}")
    
#     #     offer = offers[0]
#     #     print(f"Selected offer: {offer}")
#     #     booking_data = get_booking_data(first_name, last_name, telephone_number, offer, adults_num)
#     #     booking = create_booking(booking_data)
#     #     import time
#     #     time.sleep
#     #     print("Booking created:", booking)
#     #     if booking:
#     #         booking_id = booking.get('id')
#     #         folio_id = get_folio_id_by_booking_id(booking_id)
#     #         if folio_id:
#     #             folio_data = find_folio_by_id(folio_id)
#     #             print("Folio data:", folio_data)
#     #             # if folio_data:
#     #             #     payment_link_id = create_payment_link(folio_data, 'de', 'Payment for booking')
#     #             #     if payment_link_id:
#     #             #         payment_link_data = get_payment_link_data(folio_data, payment_link_id)
#     #             #         if payment_link_data:
#     #             #             print(f"Payment link created: {payment_link_data.get('url')}")
#     # else:
#     #     print("No offers found here too.")
# # payment_link_id = create_payment_link(folio_data, 'de', 'Payment for booking')
# # print(f"Payment link ID: {payment_link_id}")

