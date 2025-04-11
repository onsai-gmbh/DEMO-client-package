import boto3
import botocore
import json
import os
import time
from dotenv import load_dotenv
from datetime import datetime
import pandas as pd
import openpyxl
from openpyxl import Workbook



def exponential_backoff_scan(table):
    backoff_time = 5  # Initial backoff time in seconds
    max_backoff_time = 60  # Maximum backoff time in seconds
    items = []
    exclusive_start_key = None

    while True:
        try:
            print(f"Scanning with ExclusiveStartKey: {exclusive_start_key}")
            scan_kwargs = {}
            if exclusive_start_key:
                scan_kwargs['ExclusiveStartKey'] = exclusive_start_key

            response = table.scan(**scan_kwargs)
            items.extend(response.get('Items', []))

            exclusive_start_key = response.get('LastEvaluatedKey', None)
            if not exclusive_start_key:
                break  # No more items to retrieve, break the loop
            time.sleep(backoff_time)  # Wait before next scan


        except botocore.exceptions.ProvisionedThroughputExceededException:
            print(f"Waiting for {backoff_time} seconds before retrying...")
            time.sleep(backoff_time)
            backoff_time = min(backoff_time * 2, max_backoff_time)  # Increase backoff time

    return items


def fetch_conversations(table):
    # Fetch conversations from DynamoDB
    # response = table.scan()  # Get all items from the table
    # items = response.get('Items', [])  # Fetch the items
    items = exponential_backoff_scan(table)

    # Filter and sort items based on the start datetime if given

    filtered_sorted_items = sorted(
        items,
        key=lambda x: x['timestamp'],
        reverse=True
    )
    count_filtered_sorted_items = len(filtered_sorted_items) # Count filtered items

    return filtered_sorted_items, count_filtered_sorted_items


def count_user_messages(conversation):
    # Count user messages in a conversation
    user_message_count = 0
    if conversation['messages'] != "initialized":
        for message in conversation['messages']:
            if message['role'] == 'user':
                user_message_count += 1
            else:
                user_message_count += 0
    return user_message_count



def save_conversations_to_file(conversations, filename='conversations.txt', start_datetime=None):
    # Save conversations to a text file
    with open(filename, 'w') as file:
        total_count = len(conversations)
        file.write(f"Total Conversations found from {start_datetime}: {total_count}\n\n")
        for index, conversation in enumerate(conversations, start=1): 
            user_message_count = str(count_user_messages(conversation)) # Count user messages in a conversation
            # Write each conversation to the file
            conversation = json.dumps(conversation, indent=4, ensure_ascii=False)
            file.write(f"CONVERSATION {index} CONTAINS {user_message_count} USER MESSAGE(S):\n{conversation}\n\n")
    
    print(f"Saved {len(conversations)} conversations to {filename}")


def save_conversations_to_xlsx(conversations, filename='excel.xlsx', start_datetime=None):
    columns_name = ["Timestamp", "ID", "Caller", "Conversation", "User Messages", "Hotel", "Role", "Message", "Evaluation", "Conversation successfull/not successfull", "Weiterleitung/Abschluss", "To do", "Audio"]
    rows = []

    for index, conversation in enumerate(conversations, start=1):
        row = {
            "Timestamp": conversation.get("timestamp"),
            "ID": conversation.get('id'),
            "Caller": conversation.get('caller'),
            "Conversation": index,
            "User Messages": count_user_messages(conversation),
            "Hotel": conversation.get('hotel') if conversation.get('hotel') is not None else "null",
            
        }
        rows.append(row)

        if conversation.get('messages') != "initialized":
            try:
                system_history_iter = iter(conversation["system_history"])
            except KeyError:
                system_history_iter = iter([])
            for message in conversation['messages']:
                if message.get("role") == "user":
                    rows.append({
                        "Role": message.get("role"),
                        "Message": message.get("content")
                    })
                    # add the next system message (if any) immediately after the user message
                    # try:
                    #     next_system_msg = next(system_history_iter)
                    #     while next_system_msg.get("role") != "system":
                    #         next_system_msg = next(system_history_iter)
                    #     print("###################")
                    #     print(next_system_msg)
                    #     rows.append({
                    #         "Role": next_system_msg.get("role"),
                    #         "Message": next_system_msg.get("content")
                    #     })
                    # except StopIteration:
                    #     # no more system messages
                    #     pass
                elif message.get("role") not in ["embeddedings", "system"]:
                    rows.append({
                        "Role": message.get("role"),
                        "Message": message.get("content")
                    }) 
        
    df = pd.DataFrame(rows, columns=columns_name)
    df.to_excel(filename, index=False)
    
    
def main():
    # Load environment variables
    load_dotenv()
    LOCAL_DYNAMO_DB_URL = os.getenv('LOCAL_DYNAMO_DB_URL')
    DYNAMO_DB_TABLE = os.getenv('DYNAMO_DB_TABLE')
    DYNAMO_DB_TABLE = "McDreams-PhoneBot" #Production
    #DYNAMO_DB_TABLE = "McDream-Test" #Test
    print(f"Table: {DYNAMO_DB_TABLE}")

    # Connect to DynamoDB
    if LOCAL_DYNAMO_DB_URL:
        print("Using local DynamoDB ...")
        dynamodb = boto3.resource('dynamodb', endpoint_url=LOCAL_DYNAMO_DB_URL, region_name="localhost")
    else:
        print("Using remote DynamoDB ...")
        dynamodb = boto3.resource('dynamodb', region_name="eu-central-1")

    table = dynamodb.Table(DYNAMO_DB_TABLE)

    # Fetch conversations from the DB
    conversations, count_conversations = fetch_conversations(table)

    #print total count of conversations (before filtering)
    print(f"TOTAL CONVERSATIONS FOUND: {len(conversations)}")

    # Save conversations to a TXT file
    # save_conversations_to_file(conversations)

    # Save conversations to a XLSL file
    save_conversations_to_xlsx(conversations)



if __name__ == "__main__":
    main()