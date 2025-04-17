import os
import pinecone
from dotenv import load_dotenv
import boto3
import json
import asyncio
import openai
import yaml
import random
from pathlib import Path

load_dotenv()

def load_config():
    config_path = Path("config.yaml")
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    # Replace environment variables
    # You might want to add more sophisticated environment variable handling
    if "${PINECONE_INDEX}" in config["pinecone"]["index_name"]:
        config["pinecone"]["index_name"] = os.getenv("PINECONE_INDEX")
    if "${LOCAL_DYNAMO_DB_URL}" in config["pinecone"]["environment"]:
        config["pinecone"]["environment"] = os.getenv("PINECONE_ENVIRONMENT")
    return config

# Load configuration at startup
config = load_config()
pinecone_api_key = os.getenv('PINECONE_API_KEY')
pinecone_environment = config["pinecone"]["environment"]
pinecone_index = config["pinecone"]["index_name"]

OPENAI_API_AZURE_KEY = os.getenv('OPENAI_API_AZURE_KEY')
OPENAI_AZURE_BASE_URL = os.getenv('OPENAI_AZURE_BASE_URL')
OPENAI_API_AZURE_EMBEDDING = os.getenv('OPENAI_API_AZURE_EMBEDDING')


# Load configuration from YAML
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

pinecone.init(      
	api_key=pinecone_api_key,      
	environment=pinecone_environment  
)      
index = pinecone.Index(pinecone_index)

client = openai.AzureOpenAI(
    api_key=OPENAI_API_AZURE_KEY, azure_endpoint=OPENAI_AZURE_BASE_URL, api_version = "2023-05-15"
)

def get_embeddings_sync(user_query):
    response = client.embeddings.create(input=user_query, model=OPENAI_API_AZURE_EMBEDDING)
    return response.data[0].embedding

async def get_embeddings(user_query):
    # Run the synchronous function in a thread
    return await asyncio.to_thread(get_embeddings_sync, user_query)

def search_results(query_result, property_name=None, language="de-DE"):
    print(f"query_result: {query_result}, property_name: {property_name}, language: {language}")
    """
    Search for the most similar results in the index.

    Args:
        query_result (list): List of embeddings from get_embeddings
        property_name (str): property_name location
    
    Returns:
        responses (list): List of responses from search_results with metadata, scores and ids
    """
    if property_name is not None:
        responses = index.query(queries=[query_result], top_k=2, include_metadata=True, filter={"location": property_name, "language":language})

    else:
        # 
        properties = config["hotel_info"]["properties"]
        random_property = random.choice(list(properties.keys()))
        responses = index.query(queries=[query_result], top_k=2, include_metadata=True, filter={"location": random_property, "language":language})

    print("Responses"*50)
    print(responses)

    return responses


def confidence_score_filter(responses):
    """
    Filter out results with confidence score < 0.5.

    Args:
        responses (list): List of responses from search_results with metadata, scores and ids
    
    Returns:
        responses (list): List of tuples with the text, location and unique 
        fallback (str): Fallback message if no results with confidence score > 0.5

    """
    # Filter out results with confidence score < 0.5

    for result in responses["results"]:
        # Matches to keep
        responses = [(match["metadata"]["text"], match["metadata"]["location"], match["metadata"]["uniqe"], match["score"]) for match in result["matches"] if match["score"] > 0.5] # 0.8 
        # If no results with confidence score > 0.5, return an empty Paragraph
        if len(responses) == 0:
            responses = [(' ', None, False)]
    return responses
